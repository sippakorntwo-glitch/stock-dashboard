"""Read-only SEC smoke against authentic, checksum-verified AARD statements.

No fabricated financial fixtures, modified provider data, trading, publication,
or browser state injection. At most three SEC JSON requests. Older snapshots
require a checked checkpoint to read the durable provider cooldown; newer ones
publish that guard in their manifest and need only one prepared statement shard.
A provider denial is an unavailable result, never a passing test.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import zlib

from data_sync import ObjectStore, read_manifest, read_checked, restore_checkpoint, shard_number, stamp_seconds
from financial_statements import SCHEMA, number
from quality_smoke import REPO
from sec_financials import historical_facts, merge_missing
from sec_reference import SecClient, INDEX_URL, identity, normalized, ticker_index


def _shard_objects(store, manifest, ticker):
    slot = str(shard_number(ticker))
    item = manifest.get('details', {}).get(slot)
    if not item or item.get('key') != manifest['generation']+f'/details/{slot}.jsonl.gz':
        raise ValueError('Prepared statement shard is unavailable or invalid')
    raw = read_checked(store, item)
    if len(raw) > 20_000_000:
        raise ValueError('Prepared shard exceeds bounded size')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(40_000_001)
    if len(decoded) > 40_000_000:
        raise ValueError('Decoded prepared shard exceeds bounded size')
    result = {}
    for line in decoded.splitlines():
        symbol, key, value, metadata = json.loads(line)
        if symbol == ticker:
            if key in result:
                raise ValueError('Duplicate prepared record')
            result[key] = (value, metadata)
    return result


def _published_guard(manifest, checkpoint=None, *, store=None):
    """Require a same-generation durable SEC guard before any provider access."""
    guards = manifest.get('provider_circuits')
    if isinstance(guards, dict) and 'sec' in guards:
        guard = guards['sec'] or {}
        return guard.get('next_attempt_after'), 'same-generation published SEC circuit'
    if checkpoint:
        checkpoint = Path(checkpoint)
        digest = hashlib.sha256()
        with checkpoint.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != manifest['checkpoint']['sha256']:
            raise ValueError('Checkpoint does not match prepared generation')
        with closing(sqlite3.connect(checkpoint.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            row = db.execute('SELECT body FROM objects WHERE key=?', ('external:sec-circuit',)).fetchone()
        guard = json.loads(zlib.decompress(row[0])) if row else {}
        return guard.get('next_attempt_after'), 'same-generation checked local checkpoint'
    # Older manifests omit this global object from their public shards. The
    # expense of a one-time checked database download is preferable to bypassing
    # an unpublished or stale-report provider guard.
    if store is None:
        raise ValueError('Cannot verify the durable SEC provider circuit')
    with tempfile.TemporaryDirectory(prefix='sec-smoke-guard-') as folder:
        target = Path(folder)/'checkpoint.sqlite3'
        restore_checkpoint(store, manifest, target)
        return _published_guard(manifest, target)


def run(*, checkpoint=None):
    ticker = 'AARD'
    report = {'ticker': ticker, 'read_only': True, 'result': 'unavailable',
              'source_sha': __import__('os').environ.get('GITHUB_SHA'),
              'started_at': datetime.now(timezone.utc).isoformat()}
    client = SecClient(max_requests=3)
    try:
        store = ObjectStore({'backend': 'github', 'DASHBOARD_DATA_REPO': REPO,
            'DASHBOARD_DATA_VISIBILITY': 'public', 'DASHBOARD_DATA_BRANCH': 'dashboard-data'})
        manifest = read_manifest(store)
        if not manifest:
            raise ValueError('Prepared manifest is unavailable')
        report['source_generation'] = manifest['generation']
        until, checked = _published_guard(manifest, checkpoint, store=store)
        report['circuit_check'] = checked
        if stamp_seconds(until) > datetime.now(timezone.utc).timestamp():
            report.update(reason='Persisted SEC provider cooldown', cooldown_until=until)
            return report
        from sec_financials_job import release_access_pause
        incident=release_access_pause()
        if incident:
            report.update(reason='Observed SEC denial; dated release pause',
                          cooldown_until=incident['next_attempt_after'],denial_evidence=incident['evidence_url'])
            return report
        objects = _shard_objects(store, manifest, ticker)
        bundle = objects.get('financials:'+ticker, ({}, {}))[0]
        profile = objects.get('info:'+ticker, ({}, {}))[0]
        reference = objects.get('reference:'+ticker, ({}, {}))[0]
        if (bundle.get('schema') != SCHEMA or bundle.get('ticker') != ticker
                or not bundle.get('currency') or bundle['currency'] != profile.get('financialCurrency')):
            raise ValueError('AARD prepared identity or reported financial currency is missing')
        cik = reference.get('cik')
        if isinstance(cik, bool) or not isinstance(cik, int) or not 0 < cik < 10**10:
            mapped = ticker_index(client.get(INDEX_URL)).get(normalized(ticker))
            if not mapped:
                raise ValueError('SEC did not map this ticker uniquely')
            cik = mapped['cik']
        submission = client.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        verified = identity(submission, ticker, cik)
        payload = client.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
        original = deepcopy(bundle)
        merged, reconciliation = merge_missing(bundle, payload, submission, cik=cik)
        candidates = historical_facts(payload, cik, bundle['currency'])
        if not candidates:
            raise ValueError('SEC returned no usable compatible historical facts')
        assert bundle == original, 'Recovery mutated original provider observations'
        for period in ('annual', 'quarterly'):
            for kind in ('income', 'balance', 'cashflow'):
                old = bundle.get(period, {}).get(kind, [])
                new = merged.get(period, {}).get(kind, [])
                assert [r['end'] for r in old] == [r['end'] for r in new], 'Recovery invented a statement period'
                for before, after in zip(old, new):
                    for field, value in before.get('values', {}).items():
                        if number(value) is not None and after['values'][field] != value:
                            assert before.get('field_provenance', {}).get(field, {}).get('source')=='SEC EDGAR', 'Recovery overwrote a provider value'
                            assert any(r['field']==field and r['end']==before['end']
                                       and r['period']==period and r['statement']==kind
                                       and r['previous_value']==value and r['sec_value']==after['values'][field]
                                       for r in reconciliation.get('revised', [])), 'SEC revision lacks its previous-value audit'
        assert merged['currency'] == bundle['currency'], 'Recovery changed reporting currency'
        assert reconciliation['filled_count'] == len(reconciliation['filled'])
        report.update(result='passed', identity=verified, currency=bundle['currency'],
            compatible_sec_candidates=len(candidates), filled_count=reconciliation['filled_count'],
            conflict_count=reconciliation['conflict_count'], filled=reconciliation['filled'][:100],
            revised_count=reconciliation.get('revised_count', 0), revised=reconciliation.get('revised', [])[:100],
            conflicts=reconciliation['conflicts'][:100],
            rejected_alignment=reconciliation['rejected_alignment'][:100],
            ambiguous=reconciliation['ambiguous'][:100],
            checks={'provider_cells_preserved': True, 'sec_revisions_audited': True, 'no_new_periods': True,
                    'identity_verified': True, 'reported_currency_preserved': True},
            scope='Authentic AARD source reconciliation and safety checks. Filled count is actual; no claim that every absent field is reported.')
        gaap = payload.get('facts', {}).get('us-gaap', {})
        report['reported_preferred_tags'] = [tag for tag in gaap if 'preferred' in tag.lower() or 'temporaryequity' in tag.lower()][:40]
    except Exception as exc:
        report.update(result='unavailable' if not isinstance(exc, AssertionError) else 'failed',
                      error=type(exc).__name__, reason=str(exc)[:250])
    finally:
        report.update(provider_requests=client.calls, blocked=client.blocked,
                      http_evidence=client.evidence, finished_at=datetime.now(timezone.utc).isoformat())
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', help='Optional already-downloaded checkpoint; checksum must match current manifest')
    parser.add_argument('--output', default='work/sec-financials-live-smoke.json')
    args = parser.parse_args()
    report = run(checkpoint=args.checkpoint)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('filled', 'conflicts', 'ambiguous', 'rejected_alignment', 'http_evidence')}, ensure_ascii=False))
    return 0 if report['result'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
