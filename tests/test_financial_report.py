"""Public audit size regression with full, dated source evidence kept on disk."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from financial_report import MAX_PUBLIC_BYTES, SAMPLE_ITEMS, public_summary


REPOSITORY = 'sippakorntwo-glitch/stock-dashboard'
GENERATION = 'generations/20260921T000000Z-1234abcd'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')


def full_report():
    # 14 example companies, 7 metrics and 12 dated inputs per derived ratio.
    # This reproduces the real report shape without using live financial data.
    origins = [{
        'source': 'SEC EDGAR' if index % 2 else 'Yahoo Finance financial statements',
        'field': field, 'value': index + 1., 'end': end, 'currency': 'USD',
        'fetched_at': '2026-09-20T00:00:00Z', 'filed': '2026-08-01',
        'form': '10-Q', 'accession': '0001234567-26-000123',
        'tag': 'us-gaap:OperatingIncomeLoss',
        'url': 'https://www.sec.gov/Archives/edgar/data/1234567/000123456726000123/filing.htm',
    } for index, (end, field) in enumerate(
        (end, field) for end in ('2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30')
        for field in ('operatingIncome', 'taxProvision', 'pretaxIncome'))]
    observation = {
        'value': .15, 'state': 'available', 'basis': 'TTM (4 reported quarters)',
        'end': '2026-06-30', 'currency': 'USD',
        'source': 'SEC EDGAR + Yahoo Finance financial statements',
        'formula': 'NOPAT / average invested capital', 'reason': '',
        'period_ends': ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30'],
        'provenance': origins,
    }
    metrics = ('debtToEquity', 'returnOnEquity', 'roic', 'grossProfit', 'ebit',
               'netIncome', 'freeCashflow')
    examples = {f'FIXTURE{index:02d}': {key: deepcopy(observation) for key in metrics}
                for index in range(14)}
    examples['FIXTURE00']['roic'].update(
        value=None, state='invalid',
        reason='The retained SEC amount conflicts with an unresolved filing context',
        source_disagreements=[{'field': 'operatingIncome', 'end': '2026-06-30',
                               'provider_value': 1., 'sec_value': 2.,
                               'existing_provenance': deepcopy(origins[0])}])
    audit = {
        'counts': {'securities': 9876, 'companies': 4200, 'funds': 5676,
                   'companies_with_source_disagreements': 1,
                   'with_invalid_source_metrics': 1, 'with_missing_applicable_metrics': 2300},
        'field_counts': {key: {'available': 3000, 'not_reported': 1200,
                               'not_applicable': 5676} for key in metrics},
        'collection_revision': 2,
        'recheck_pending_symbols': [f'FIXTURE{index}' for index in range(4200)],
        'missing_currency_symbols': [f'NOCCY{index}' for index in range(200)],
        'examples': examples, 'data_complete': False,
    }
    return {
        'started_at': '2026-09-21T00:00:00Z', 'finished_at': '2026-09-21T00:01:00Z',
        'source_generation': GENERATION, 'generation': GENERATION,
        'scope': 'Every catalog member; source validation and formula audit.',
        'before': deepcopy(audit), 'after': deepcopy(audit),
        'collection': {'due_before': 2300, 'attempted': 400, 'updated': 19,
                       'failed': 0, 'remaining_due': 1900, 'only_missing': False,
                       'errors': [], 'symbols_updated': ['FIXTURE00']},
        'result': 'audit_completed', 'data_complete': False,
        'coverage': {'total': 9876, 'financial_statements': 1900},
        'recovery': {'restored': 0, 'reason': 'No compatible financial recovery artifact'},
    }


def configure_actions(monkeypatch, *, sec=False):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_REPOSITORY', REPOSITORY)
    monkeypatch.setenv('GITHUB_RUN_ID', '12345')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('DASHBOARD_GITHUB_TOKEN', 'fixture-token')
    prefix = 'sec' if sec else 'company'
    monkeypatch.setenv('FINANCIAL_AUDIT_ARTIFACT_NAME', f'{prefix}-financials-audit-2')


def capture_publication(monkeypatch):
    """Exercise the real publisher's size/envelope check with no network."""
    import verification_report
    sent = []

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            assert self.status_code == 200

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            return Response(404)

        def put(self, url, **kwargs):
            raw = base64.b64decode(kwargs['json']['content'])
            assert len(raw) <= 300_000
            sent.append((url, json.loads(raw)))
            return Response(200)

    monkeypatch.setattr(verification_report.requests, 'Session', Session)
    return sent


def test_oversized_provenance_report_has_truthful_bounded_public_projection(tmp_path, monkeypatch):
    configure_actions(monkeypatch)
    report = full_report()
    original = deepcopy(report)
    raw = encoded(report)
    assert len(raw) > 300_000  # Fails the actual pre-fix publication guard.
    path = tmp_path / 'company-financials-report.json'
    path.write_bytes(raw)
    summary = public_summary(report, path)
    assert len(encoded(summary)) <= MAX_PUBLIC_BYTES
    assert report == original and path.read_bytes() == raw
    assert summary['data_complete'] is False and summary['result'] == report['result']
    assert summary['coverage'] == report['coverage']
    for phase in ('before', 'after'):
        for key in ('counts', 'field_counts', 'collection_revision', 'data_complete'):
            assert summary[phase][key] == report[phase][key]
        projected = summary[phase]['examples']['FIXTURE00']['roic']
        for key in ('value', 'state', 'source', 'reason', 'formula', 'end', 'period_ends'):
            assert projected[key] == report[phase]['examples']['FIXTURE00']['roic'][key]
        assert projected['details_omitted'] == {'provenance': 12, 'source_disagreements': 1}
        assert summary[phase]['examples_summary']['metrics_with_source_disagreements'] == 1
        assert summary[phase]['examples_summary']['all_example_states']['invalid'] == 1
    artifact = summary['full_artifacts']
    assert artifact['report_bytes'] == len(raw)
    assert artifact['report_sha256'] == hashlib.sha256(raw).hexdigest()
    assert artifact['artifact_name'] == 'company-financials-audit-2'
    assert artifact['run_url'] == f'https://github.com/{REPOSITORY}/actions/runs/12345'


def test_large_lists_and_oversized_example_keep_exact_counts_and_source_issue_totals(tmp_path):
    report = full_report()
    report['collection'].update(
        provider='SEC EDGAR', provider_requests=51, only_missing=True,
        cooldown_until='2026-09-22T00:00:00Z', guard_updated=True,
        errors=[{'ticker': f'FIXTURE{i}', 'error': 'HTTPError'} for i in range(1000)])
    report['after']['recheck_pending_symbols'] = [f'FIXTURE{i}' for i in range(50_000)]
    # A long multibyte source label may be omitted as a whole example. It must
    # not lose the exact audit or example source-disagreement totals.
    report['after']['examples']['FIXTURE00']['roic']['source'] = 'หลักฐาน' * 20_000
    path = tmp_path / 'company-financials-report.json'
    path.write_bytes(encoded(report))
    summary = public_summary(report, path, sec=True)
    assert len(encoded(summary)) <= MAX_PUBLIC_BYTES
    collection = summary['collection']
    for key, value in report['collection'].items():
        if not isinstance(value, list):
            assert collection[key] == value
    assert collection['errors_summary'] == {
        'total': 1000, 'included': SAMPLE_ITEMS, 'omitted': 1000 - SAMPLE_ITEMS, 'selection': 'prefix'}
    after = summary['after']
    assert after['recheck_pending_symbols_summary']['omitted'] == 50_000 - SAMPLE_ITEMS
    assert 'FIXTURE00' not in after['examples']
    assert after['examples_summary']['symbols_omitted'] >= 1
    assert after['examples_summary']['all_example_states']['invalid'] == 1
    assert after['examples_summary']['source_disagreement_records'] == 1
    assert after['data_complete'] is False


@pytest.mark.parametrize('sec', [False, True], ids=['yahoo', 'sec'])
@pytest.mark.parametrize('attempted', [0, 1], ids=['cooldown-no-op', 'updated-snapshot'])
def test_both_collectors_publish_summary_and_preserve_full_artifacts(
        tmp_path, monkeypatch, sec, attempted):
    import company_financials_job as job
    import data_quality
    import data_sync
    import financial_recovery
    import sec_financials_job
    import update_data
    import verification_report

    configure_actions(monkeypatch, sec=sec)
    monkeypatch.chdir(tmp_path)
    report = full_report()
    collection = {
        'attempted': attempted, 'updated': attempted, 'failed': 0,
        'due_before': 2300, 'remaining_due': 2300 - attempted, 'only_missing': True,
        'provider': 'SEC EDGAR' if sec else 'Yahoo Finance', 'provider_requests': attempted,
        'cooldown_until': '2026-09-22T00:00:00Z' if not attempted else None,
        'errors': [], 'symbols_updated': ['FIXTURE00'] if attempted else [],
    }
    previous = {'generation': GENERATION, 'summary': {}, 'coverage': report['coverage']}
    monkeypatch.setattr(data_sync, 'config_from', lambda: {
        'backend': 'github', 'DASHBOARD_DATA_REPO': REPOSITORY,
        'DASHBOARD_DATA_VISIBILITY': 'public'})
    monkeypatch.setattr(data_sync, 'ObjectStore', lambda *args, **kwargs: object())
    monkeypatch.setattr(data_sync, 'read_manifest', lambda store: deepcopy(previous))
    monkeypatch.setattr(data_sync, 'read_checked', lambda *args: gzip.compress(b'{}'))
    monkeypatch.setattr(data_sync, 'restore_checkpoint', lambda *args: None)
    monkeypatch.setattr(data_quality, 'checked_universe', lambda summary: ('FIXTURE00',))
    monkeypatch.setattr(financial_recovery, 'recover_recent_failure', lambda *args, **kwargs: {'restored': 0})
    monkeypatch.setattr(job, 'audit_all', lambda *args: (deepcopy(report['after']), [
        {'Ticker': 'FIXTURE00', 'Source Disagreements': 'Full fixture evidence',
         'Missing Applicable Metrics': 'roic'}]))
    monkeypatch.setattr(job, 'collect_batch', lambda *args, **kwargs: deepcopy(collection))
    monkeypatch.setattr(sec_financials_job, 'collect_batch', lambda *args, **kwargs: deepcopy(collection))
    published_snapshots = []

    def publish_snapshot(*args, **kwargs):
        published_snapshots.append(True)
        return {**previous, 'generation': 'generations/20260921T000100Z-abcd1234'}

    monkeypatch.setattr(update_data, 'publish_snapshot', publish_snapshot)
    sent = capture_publication(monkeypatch)
    # The original report still fails the general bound; do not weaken it.
    with pytest.raises(ValueError, match='bounded audit size'):
        verification_report.publish_report('size-guard-regression', report)
    assert not sent
    job.main(['--publish', '--backfill', *(['--sec'] if sec else [])])
    assert len(sent) == 1 and len(published_snapshots) == attempted
    url, public = sent[0]
    assert url.endswith('/sec-financials-reconciliation.json' if sec else '/company-fundamentals-v28.json')
    full_path = Path('work/company-financials-report.json')
    raw = full_path.read_bytes()
    full = json.loads(raw)
    assert len(raw) > 300_000
    assert full['after']['examples'] == report['after']['examples']
    assert full['after']['recheck_pending_symbols'] == report['after']['recheck_pending_symbols']
    assert 'report_format' not in full
    assert public['collection']['remaining_due'] == collection['remaining_due']
    assert public['collection']['cooldown_until'] == collection['cooldown_until']
    assert public['collection']['only_missing'] is True
    assert public['after']['counts'] == report['after']['counts']
    assert public['data_complete'] is False
    assert public['source_sha'] == 'a' * 40 and public['run_id'] == '12345'
    assert public['full_artifacts']['report_sha256'] == hashlib.sha256(raw).hexdigest()
    assert bool(public.get('snapshot_unchanged')) is (attempted == 0)
    assert 'Full fixture evidence' in Path('work/company-financials-all-securities.csv').read_text()
    assert Path('work/company-financials-all-metrics.csv').exists()
    recovery = Path('work/company-financials-recovery.json.gz').read_bytes()
    recovery_manifest = json.loads(Path('work/company-financials-recovery.manifest.json').read_text())
    assert hashlib.sha256(recovery).hexdigest() == recovery_manifest['sha256']
