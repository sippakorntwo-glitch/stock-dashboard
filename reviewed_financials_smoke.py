"""Read-only proof of the reviewed correction on a checked public AARD shard.

No SEC or issuer request is made. A changed provider tuple requires another
review and is never reported as a passing correction test.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from company_analysis_ui import statement_table, export_statements
from company_metrics import metric_observations
from data_sync import ObjectStore, read_manifest
from financial_statements import observations
from quality_smoke import REPO
from reviewed_financials import AARD_CORRECTION, ISSUER_SOURCE, apply_reviewed
from sec_financials_smoke import _shard_objects


def verify(bundle, profile):
    c = AARD_CORRECTION
    if (bundle.get('schema') != 1 or bundle.get('ticker') != c.ticker
            or bundle.get('currency') != c.currency or profile.get('financialCurrency') != c.currency):
        raise ValueError('Prepared AARD identity or reporting currency is invalid')
    original = deepcopy(bundle)
    corrected = apply_reviewed(bundle)
    assert bundle == original, 'Correction mutated provider observations'
    selected = [row for row in corrected.get('annual', {}).get('balance', []) if row.get('end') == c.end]
    if len(selected) != 1:
        return {'result': 'changed_source_requires_review', 'reason': 'Reviewed fiscal-year balance is absent or ambiguous'}
    row = selected[0]
    origin = row.get('field_provenance', {}).get('totalLiabilities', {})
    if (row['values'].get('totalLiabilities') != c.issuer_liabilities
            or row['values'].get('totalAssets') != c.total_assets
            or row['values'].get('stockholdersEquity') != c.stockholders_equity
            or origin.get('correction_id') != c.identifier or origin.get('source') != ISSUER_SOURCE
            or origin.get('url') != c.url
            or origin.get('original_observation', {}).get('value') != c.provider_liabilities):
        return {'result': 'changed_source_requires_review', 'reason': 'Provider tuple no longer matches this reviewed correction'}
    changed = []
    for period in ('annual', 'quarterly'):
        for kind in ('income', 'balance', 'cashflow'):
            before_rows = original.get(period, {}).get(kind, [])
            after_rows = corrected.get(period, {}).get(kind, [])
            assert len(before_rows) == len(after_rows), 'Correction changed statement periods'
            for before, after in zip(before_rows, after_rows):
                assert before['end'] == after['end']
                assert before['values'].keys() == after['values'].keys(), 'Correction invented a field'
                for field, amount in before['values'].items():
                    if after['values'][field] != amount:
                        assert (kind == 'balance' and before['end'] == c.end and field == 'totalLiabilities'
                                and amount == c.provider_liabilities and after['values'][field] == c.issuer_liabilities)
                        changed.append({'period': period, 'end': c.end, 'field': field,
                                        'previous_value': amount, 'value': after['values'][field]})
    # Keep each original statement date in the source audit above. This isolated
    # historical view only checks what canonical consumers calculate for FY2024.
    historical = deepcopy(original)
    for period in ('annual', 'quarterly'):
        historical[period] = {'balance': [r for r in original.get(period, {}).get('balance', []) if r['end'] == c.end]}
    for result in (observations(historical), metric_observations(c.ticker, profile, historical)):
        assert result['totalLiabilities']['value'] == c.issuer_liabilities
        assert result['totalLiabilities']['source'] == ISSUER_SOURCE
        assert result['liabilitiesToEquity']['state'] == 'not_meaningful', 'Negative equity must not become a normal leverage ratio'
    table = next(r for r in statement_table(original, 'balance') if r['_field'] == 'totalLiabilities')
    assert table[c.end] == '5.39M USD'
    exported = next(r for r in export_statements(original) if r['รอบบัญชี'] == 'annual'
                    and r['วันสิ้นงวด'] == c.end and r['รายการต้นทาง'] == 'totalLiabilities')
    assert exported['ค่าต้นทาง'] == c.issuer_liabilities and exported['แหล่งข้อมูล'] == ISSUER_SOURCE
    assert apply_reviewed(corrected) == corrected, 'Correction is not idempotent'
    return {'result': 'passed', 'correction_id': c.identifier, 'changed_cells': changed,
            'already_reviewed': not bool(changed), 'provenance': origin,
            'checks': {'source_bundle_unchanged': True, 'other_financial_fields_unchanged': True,
                       'canonical_history_export_agree': True, 'negative_equity_ratio_not_meaningful': True},
            'scope': 'Only the reviewed AARD FY2024 total-liabilities source definition; no claim that all issuer data is complete.'}


def run():
    report = {'ticker': 'AARD', 'read_only': True, 'provider_requests': 0,
              'source_sha': os.environ.get('GITHUB_SHA'), 'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        store = ObjectStore({'backend': 'github', 'DASHBOARD_DATA_REPO': REPO,
            'DASHBOARD_DATA_VISIBILITY': 'public', 'DASHBOARD_DATA_BRANCH': 'dashboard-data'})
        manifest = read_manifest(store)
        if not manifest:
            raise ValueError('Prepared manifest is unavailable')
        report['source_generation'] = manifest['generation']
        objects = _shard_objects(store, manifest, 'AARD')
        report.update(verify(objects.get('financials:AARD', ({}, {}))[0], objects.get('info:AARD', ({}, {}))[0]))
    except Exception as exc:
        report.update(result='failed' if isinstance(exc, AssertionError) else 'unavailable',
                      error=type(exc).__name__, reason=str(exc)[:250])
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='work/reviewed-financials-live-smoke.json')
    args = parser.parse_args()
    report = run()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['result'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
