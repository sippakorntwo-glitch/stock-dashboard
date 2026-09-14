"""Reviewed source fixtures are confined to tests; public smoke uses actual data."""
from copy import deepcopy
import json

from bs4 import BeautifulSoup
import pytest

from company_analysis_ui import statement_table, history_html, export_statements, _issuer_badge
from company_metrics import metric_observations
from financial_completeness import preserve_refresh
from financial_statements import observations, collect
from financial_trends import build_financial_trends
from reviewed_financials import apply_reviewed, AARD_CORRECTION, ISSUER_SOURCE, PROVIDER_SOURCE
from reviewed_financials_smoke import verify


def bundle():
    return {'schema': 1, 'ticker': 'AARD', 'currency': 'USD', 'source': PROVIDER_SOURCE,
            'fetched_at': '2026-09-13T12:00:00Z', 'errors': [],
            'annual': {'balance': [{'end': '2024-12-31', 'values': {
                'totalAssets': 77_507_000, 'stockholdersEquity': -54_643_000,
                'totalLiabilities': 132_150_000, 'totalDebt': 779_000, 'cash': 73_663_000}}],
                'income': [{'end': '2024-12-31', 'values': {'revenue': 0, 'dilutedEPS': -0.99}}]},
            'quarterly': {},
            'observations': {'totalLiabilities': {'value': 132_150_000, 'source': PROVIDER_SOURCE}}}


def test_exact_review_retains_provider_and_issuer_evidence_without_mutation_or_stale_calculations():
    value = bundle(); original = deepcopy(value)
    corrected = apply_reviewed(value)
    assert value == original and 'observations' not in corrected
    row = corrected['annual']['balance'][0]
    assert row['values']['totalLiabilities'] == 5_394_000
    p = row['field_provenance']['totalLiabilities']
    assert p['original_observation'] == {'source': PROVIDER_SOURCE, 'value': 132_150_000,
                                          'fetched_at': original['fetched_at']}
    assert p['convertible_preferred_stock'] == 126_756_000
    assert p['url'] == AARD_CORRECTION.url and p['source'] == ISSUER_SOURCE
    assert p['published'] == '2026-03-23' and p['fetched_at'] == p['reviewed_on'] == '2026-09-14'
    assert row['values']['totalLiabilities'] + p['convertible_preferred_stock'] + row['values']['stockholdersEquity'] == row['values']['totalAssets']
    assert apply_reviewed(corrected) is corrected
    assert corrected['annual']['income'] == original['annual']['income']
    assert 'grossProfit' not in corrected['annual']['income'][0]['values']


@pytest.mark.parametrize('path,replacement', [
    (('ticker',), 'OTHER'), (('currency',), 'CAD'), (('schema',), 2), (('schema',), True),
    (('source',), 'SEC EDGAR'), (('annual', 'balance', 0, 'end'), '2025-12-31'),
    (('annual', 'balance', 0, 'currency'), 'CAD'),
    (('annual', 'balance', 0, 'values', 'totalAssets'), 77_507_001),
    (('annual', 'balance', 0, 'values', 'stockholdersEquity'), -54_643_001),
    (('annual', 'balance', 0, 'values', 'totalLiabilities'), 132_150_001),
    (('annual', 'balance', 0, 'values', 'totalLiabilities'), None),
    (('annual', 'balance', 0, 'values', 'totalLiabilities'), '132150000'),
    (('annual', 'balance', 0, 'field_provenance'), {'totalLiabilities': {'source': 'SEC EDGAR'}}),
])
def test_unreviewed_context_or_revised_tuple_is_never_overridden(path, replacement):
    value = bundle(); part = value
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = replacement
    original = deepcopy(value)
    assert apply_reviewed(value) is value and value == original


def test_all_consumers_use_reviewed_history_and_preserve_negative_equity_semantics():
    value = bundle()
    for result in (observations(value), metric_observations('AARD', {'financialCurrency': 'USD'}, value)):
        assert result['totalLiabilities']['value'] == 5_394_000
        assert result['totalLiabilities']['source'] == ISSUER_SOURCE
        assert result['liabilitiesToEquity']['state'] == 'not_meaningful'
    rows = statement_table(value, 'balance')
    soup = BeautifulSoup(history_html(rows, 'งบฐานะการเงิน'), 'html.parser')
    cell = soup.select_one('[data-statement-field="totalLiabilities"] td')
    assert cell.get_text() == '5.39M USD รายงานบริษัท'
    assert cell.a['href'] == AARD_CORRECTION.url
    assert '132150000' in cell.a['aria-label'] and '126756000' in cell.a['title']
    exported = next(r for r in export_statements(value) if r['รายการต้นทาง'] == 'totalLiabilities')
    assert exported['ค่าต้นทาง'] == 5_394_000 and exported['แหล่งข้อมูล'] == ISSUER_SOURCE
    assert json.loads(exported['ที่มารายรายการ'])[0]['original_observation']['value'] == 132_150_000
    assert build_financial_trends('AARD', {}, value, today='2026-09-14') == build_financial_trends('AARD', {}, apply_reviewed(value), today='2026-09-14')
    assert verify(value, {'financialCurrency': 'USD'})['result'] == 'passed'


def test_same_date_quarterly_balance_is_corrected_without_touching_another_date():
    value = bundle()
    value['quarterly']['balance'] = deepcopy(value['annual']['balance'])
    later = deepcopy(value['annual']['balance'][0]); later['end'] = '2025-03-31'
    value['quarterly']['balance'].insert(0, later)
    corrected = apply_reviewed(value)
    assert corrected['quarterly']['balance'][0] == later
    assert corrected['quarterly']['balance'][1]['values']['totalLiabilities'] == 5_394_000
    assert observations(corrected)['totalLiabilities']['value'] == 132_150_000


def test_successful_yahoo_refresh_reapplies_review_but_accepts_a_revised_tuple():
    first = preserve_refresh(None, bundle())
    assert first['observations']['totalLiabilities']['value'] == 5_394_000
    incoming = bundle(); incoming['fetched_at'] = '2026-09-15T12:00:00Z'
    refreshed = preserve_refresh(first, incoming)
    assert refreshed['observations']['totalLiabilities']['value'] == 5_394_000
    assert refreshed['annual']['balance'][0]['field_provenance']['totalLiabilities']['original_observation']['fetched_at'] == incoming['fetched_at']
    incoming['annual']['balance'][0]['values']['totalLiabilities'] = 5_400_000
    revised = preserve_refresh(refreshed, incoming)
    assert revised['observations']['totalLiabilities']['value'] == 5_400_000
    assert revised['observations']['totalLiabilities']['source'] == PROVIDER_SOURCE
    assert 'totalLiabilities' not in revised['annual']['balance'][0].get('field_provenance', {})


def test_issuer_badge_allows_only_reviewed_url_and_escapes_untrusted_details():
    origin = apply_reviewed(bundle())['annual']['balance'][0]['field_provenance']['totalLiabilities']
    origin.update(url=AARD_CORRECTION.url+'?redirect=evil', published='"><script>alert(1)</script>')
    soup = BeautifulSoup(_issuer_badge([origin]), 'html.parser')
    assert not soup.select('a, script')
    assert soup.abbr.get_text() == 'รายงานบริษัท'
    assert '"><script>alert(1)</script>' in soup.abbr['title']


def test_changed_authentic_source_probe_requires_review_not_pass():
    value = bundle()
    value['annual']['balance'][0]['values']['totalAssets'] += 1
    assert verify(value, {'financialCurrency': 'USD'})['result'] == 'changed_source_requires_review'
    value = apply_reviewed(bundle())
    value['annual']['balance'][0]['values']['totalAssets'] += 1
    assert verify(value, {'financialCurrency': 'USD'})['result'] == 'changed_source_requires_review'


def test_collector_persists_correction_and_original_source_amount():
    import pandas as pd
    class Provider:
        def get_balance_sheet(self, **_):
            return pd.DataFrame({'2024-12-31': {'Total Assets': 77_507_000,
                'Stockholders Equity': -54_643_000, 'Total Liabilities Net Minority Interest': 132_150_000}})
        def get_income_stmt(self, **_): return pd.DataFrame()
        def get_cash_flow(self, **_): return pd.DataFrame()
    result = collect('AARD', {'financialCurrency': 'USD'}, Provider(), now='2026-09-14T12:00:00Z')
    assert result['annual']['balance'][0]['values']['totalLiabilities'] == 5_394_000
    assert result['observations']['totalLiabilities']['source'] == ISSUER_SOURCE
