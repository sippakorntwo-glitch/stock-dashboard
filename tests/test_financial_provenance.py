"""SEC fallback cells remain auditable through refresh, derivation and display."""
from copy import deepcopy
import json

from bs4 import BeautifulSoup
import pytest

from financial_statements import SOURCE, observations
from financial_completeness import preserve_refresh
from financial_trends import build_financial_trends, export_trends
from company_analysis_ui import statement_table, history_html, export_statements, reconciliation_html
from company_analysis_th import build_rows_th


def sec(row, field, *, start=None):
    row.setdefault('field_provenance', {})[field] = {
        'source': 'SEC EDGAR', 'tag': 'us-gaap:Fixture',
        'accession': '0001234567-26-000001', 'filed': '2026-02-15',
        'start': start, 'end': row['end'], 'currency': 'USD',
        'url': 'https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/report.htm',
        'fetched_at': '2026-08-01T00:00:00Z', 'form': '10-K'}


def bundle():
    return {'schema': 1, 'ticker': 'TEST', 'currency': 'USD', 'source': SOURCE,
        'fetched_at': '2026-09-14T00:00:00Z', 'errors': [], 'quarterly': {},
        'annual': {'income': [
            {'end': '2025-12-31', 'values': {'revenue': 100, 'grossProfit': 40,
                'netIncome': 10, 'operatingIncome': 20, 'pretaxIncome': 12.5, 'taxProvision': 2.5}},
            {'end': '2024-12-31', 'values': {'revenue': 80, 'netIncome': 8}}],
            'balance': [
                {'end': '2025-12-31', 'values': {'stockholdersEquity': 80, 'totalAssets': 140, 'totalDebt': 20, 'cash': 10}},
                {'end': '2024-12-31', 'values': {'stockholdersEquity': 60, 'totalAssets': 120, 'totalDebt': 20, 'cash': 10}}],
            'cashflow': [{'end': '2025-12-31', 'values': {'operatingCashflow': 30, 'capitalExpenditure': -10}}]}}


def test_raw_fy_balance_and_calculations_preserve_actual_cells_including_prior_capital():
    value = bundle()
    sec(value['annual']['income'][0], 'grossProfit', start='2025-01-01')
    sec(value['annual']['income'][1], 'revenue', start='2024-01-01')
    sec(value['annual']['balance'][1], 'stockholdersEquity')
    sec(value['annual']['balance'][0], 'totalAssets')
    sec(value['annual']['cashflow'][0], 'capitalExpenditure', start='2025-01-01')
    before = deepcopy(value)
    result = observations(value)
    assert result['grossProfit']['value'] == 40
    assert result['grossProfit']['source'] == 'SEC EDGAR'
    assert result['totalAssets']['source'] == 'SEC EDGAR'
    assert result['revenue']['source'] == SOURCE
    for key in ('grossMargins', 'returnOnEquity', 'returnOnAssets', 'roic', 'freeCashflow', 'revenueGrowthFY'):
        assert set(p['source'] for p in result[key]['provenance']) == {SOURCE, 'SEC EDGAR'}, key
        assert 'SEC EDGAR' in result[key]['source'] and SOURCE in result[key]['source']
    assert result['returnOnEquity']['value'] == pytest.approx(10 / 70)
    assert {(p['field'], p['end']) for p in result['returnOnEquity']['provenance']} == {
        ('netIncome', '2025-12-31'), ('stockholdersEquity', '2024-12-31'), ('stockholdersEquity', '2025-12-31')}
    assert value == before
    json.dumps(result, allow_nan=False)


def test_overlapping_balance_copy_retains_only_the_source_of_the_selected_value():
    value = bundle()
    sec(value['annual']['balance'][0], 'totalAssets')
    value['quarterly']['balance'] = [{'end': '2025-12-31', 'values': {'cash': 12}}]
    assert observations(value)['totalAssets']['source'] == 'SEC EDGAR'
    value['quarterly']['balance'][0]['values']['totalAssets'] = 141
    result = observations(value)['totalAssets']
    assert result['value'] == 141 and result['source'] == SOURCE
    assert all('accession' not in p for p in result['provenance'])


@pytest.mark.parametrize('partial', [False, True])
def test_refresh_retains_sec_source_only_for_retained_cells(partial):
    previous = bundle()
    sec(previous['annual']['income'][0], 'grossProfit', start='2025-01-01')
    incoming = bundle()
    incoming['errors'] = [{'error': 'TimeoutError'}] if partial else []
    incoming['annual']['income'][0]['values'].pop('grossProfit')
    original = deepcopy(previous)
    retained = preserve_refresh(previous, incoming)
    row = retained['annual']['income'][0]
    assert row['field_provenance']['grossProfit'] == previous['annual']['income'][0]['field_provenance']['grossProfit']
    assert row['field_fetched_at']['grossProfit'] == '2026-08-01T00:00:00Z'
    assert retained['observations']['grossProfit']['source'] == 'SEC EDGAR'
    incoming['annual']['income'][0]['values']['grossProfit'] = 41
    replaced = preserve_refresh(retained, incoming)
    item = replaced['observations']['grossProfit']
    assert item['value'] == (40 if partial else 41)
    assert item['source'] == ('SEC EDGAR' if partial else SOURCE)
    assert ('grossProfit' in replaced['annual']['income'][0].get('field_provenance', {})) is partial
    assert previous == original


def test_ttm_trends_growth_and_export_include_each_actual_source_and_original_fetch_date():
    value = bundle()
    ends = ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30']
    value['quarterly'] = {
        'income': [{'end': end, 'values': {'revenue': 25, 'grossProfit': 10, 'netIncome': 5}} for end in ends],
        'cashflow': [{'end': end, 'values': {'operatingCashflow': 10, 'capitalExpenditure': -2}} for end in ends]}
    sec(value['quarterly']['income'][0], 'grossProfit', start='2026-04-01')
    sec(value['quarterly']['cashflow'][0], 'capitalExpenditure', start='2026-04-01')
    sec(value['annual']['income'][1], 'revenue', start='2024-01-01')
    canonical = observations(value)
    assert canonical['grossProfit']['value'] == 40
    assert len(canonical['grossProfit']['provenance']) == 4
    assert len(canonical['grossMargins']['provenance']) == 8
    result = build_financial_trends('TEST', {'financialCurrency': 'USD'}, value, today='2026-09-14')
    ttm = result['periods']['TTM'][-1]['metrics']
    for key in ('grossProfit', 'grossMargins', 'freeCashflow'):
        assert {p['source'] for p in ttm[key]['provenance']} == {SOURCE, 'SEC EDGAR'}
    assert ttm['freeCashflow']['value'] == 32 and len(ttm['freeCashflow']['provenance']) == 8
    assert 'SEC EDGAR' in result['periods']['FY'][-1]['metrics']['revenueGrowth']['source']
    assert 'SEC EDGAR' in result['source']
    exported = next(r for r in export_trends(result, 'Q') if r['วันสิ้นงวด'] == '2026-06-30' and r['รหัสรายการ'] == 'grossProfit')
    assert exported['แหล่งข้อมูล'] == 'SEC EDGAR'
    assert exported['ดึงข้อมูลเมื่อ'] == '2026-08-01T00:00:00Z'
    assert json.loads(exported['ที่มารายการที่ใช้คำนวณ'])[0]['accession'] == '0001234567-26-000001'


def test_explicit_conflicting_starts_do_not_create_same_end_ratios():
    value = bundle()
    sec(value['annual']['income'][0], 'grossProfit', start='2025-01-01')
    sec(value['annual']['income'][0], 'revenue', start='2025-02-01')
    assert 'grossMargins' not in observations(value)
    result = build_financial_trends('TEST', {}, value, today='2026-09-14')
    item = result['periods']['FY'][-1]['metrics']['grossMargins']
    assert item['state'] == 'period_mismatch' and item['value'] is None
    assert {p['start'] for p in item['provenance']} == {'2025-01-01', '2025-02-01'}


def test_history_badge_and_raw_export_expose_filing_without_changing_financial_values():
    value = bundle()
    sec(value['annual']['cashflow'][0], 'capitalExpenditure', start='2025-01-01')
    original = deepcopy(value)
    rows = statement_table(value, 'cashflow')
    row = next(r for r in rows if r['_field'] == 'capitalExpenditure')
    assert row['2025-12-31'] == '10.00 USD'
    soup = BeautifulSoup(history_html(rows, 'งบกระแสเงินสด', kind='cashflow'), 'html.parser')
    cell = soup.select_one('[data-statement-field="capitalExpenditure"] td')
    assert cell.get_text() == '10.00 USD SEC'
    assert cell.a['href'] == value['annual']['cashflow'][0]['field_provenance']['capitalExpenditure']['url']
    exported = next(r for r in export_statements(value) if r['รายการต้นทาง'] == 'capitalExpenditure')
    assert exported['ค่าต้นทาง'] == -10
    assert json.loads(exported['ที่มารายรายการ'])[0]['start'] == '2025-01-01'
    assert value == original


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://www.sec.gov.evil.test/Archives/edgar/data/a',
                                'https://evil@www.sec.gov/Archives/edgar/data/a',
                                'https://www.sec.gov/Archives/edgar/data/a?next=javascript:alert(1)'])
def test_history_untrusted_provenance_cannot_inject_html_or_active_links(url):
    value = bundle()
    row = value['annual']['income'][0]
    sec(row, 'grossProfit')
    row['field_provenance']['grossProfit'].update(url=url, tag='"><script>alert(1)</script>')
    markup = history_html(statement_table(value, 'income'), 'งบกำไรขาดทุน', kind='income')
    soup = BeautifulSoup(markup, 'html.parser')
    cell = soup.select_one('[data-statement-field="grossProfit"] td')
    assert not soup.select('script, a')
    assert cell.abbr.get_text() == 'SEC'
    assert '"><script>alert(1)</script>' in cell.abbr['title']


def test_aard_shaped_liabilities_conflict_preserves_raw_amount_but_blocks_ratio():
    value = bundle()
    balance = value['annual']['balance'][0]
    balance['values']['totalLiabilities'] = 132_150_000
    value['sec_reconciliation'] = {'conflicts': [{
        'period': 'annual', 'statement': 'balance', 'end': balance['end'],
        'field': 'totalLiabilities', 'provider_value': 132_150_000, 'sec_value': 5_394_000,
        'currency': 'USD', 'tag': 'us-gaap:Liabilities', 'filed': '2026-02-15',
        'accession': '0001234567-26-000001',
        'url': 'https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/',
        'preferred_equity_reconciliation': {'value': 126_756_000}}]}
    original = deepcopy(value)
    result = observations(value)
    assert result['totalLiabilities']['state'] == 'invalid'
    assert result['totalLiabilities']['value'] is None
    assert 'liabilitiesToEquity' not in result
    assert result['totalDebt']['value'] == 20
    rows = statement_table(value, 'balance')
    soup = BeautifulSoup(history_html(rows, 'งบฐานะการเงิน', kind='balance'), 'html.parser')
    cell = soup.select_one('[data-statement-field="totalLiabilities"] td')
    assert '132.15M USD' in cell.get_text() and 'แหล่งข้อมูลต่างกัน' in cell.get_text()
    assert '5394000' in cell.abbr['title']
    comparison = BeautifulSoup(reconciliation_html(value), 'html.parser')
    assert '132,150,000.0 USD' in comparison.get_text()
    assert '5,394,000.0 USD' in comparison.get_text()
    assert '126,756,000.0 USD' in comparison.get_text()
    assert comparison.a['href'].startswith('https://www.sec.gov/Archives/edgar/data/')
    thai = next(r for r in build_rows_th('TEST', {}, value) if r['_key'] == 'totalLiabilities')
    assert 'พักใช้' in thai['Interpretation'] and 'SEC' in thai['Interpretation']
    assert value == original
    # A comparison for an old provider amount cannot quarantine a revised value.
    incoming=deepcopy(value)
    incoming.pop('sec_reconciliation')
    retained=preserve_refresh(value,incoming)
    assert retained['observations']['totalLiabilities']['state']=='invalid'
    assert retained['sec_reconciliation']==value['sec_reconciliation']
    balance['values']['totalLiabilities'] = 5_394_000
    revised = observations(value)
    assert revised['totalLiabilities']['state'] == 'available'
    assert revised['liabilitiesToEquity']['value'] == 5_394_000 / 80
    assert not reconciliation_html(value)


@pytest.mark.parametrize('ambiguous',[False,True])
def test_unresolved_sec_owned_cell_is_withheld_from_canonical_trends_and_ratios(ambiguous):
    value=bundle()
    row=value['annual']['income'][0]
    sec(row,'grossProfit',start='2025-01-01')
    value['sec_reconciliation']={'conflicts':[{
        'period':'annual','statement':'income','field':'grossProfit','end':row['end'],
        'currency':'USD','provider_value':40,'sec_value':None if ambiguous else 41,
        'existing_source':'SEC EDGAR','existing_provenance':deepcopy(row['field_provenance']['grossProfit']),
        'ambiguous':ambiguous}]}
    result=observations(value)
    assert result['grossProfit']['state']=='invalid' and result['grossProfit']['value'] is None
    assert result['grossMargins']['state']=='invalid' and result['grossMargins']['value'] is None
    trends=build_financial_trends('TEST',{},value,today='2026-09-14')
    latest=trends['periods']['FY'][-1]['metrics']
    assert latest['grossProfit']['state']==latest['grossMargins']['state']=='invalid'
    assert row['values']['grossProfit']==40
    markup=reconciliation_html(value)
    assert '40.0 USD' in markup
    if ambiguous:assert 'ข้อมูล SEC หลายรายการขัดแย้งกัน' in markup
    # Metadata from a subsequently accepted filing is a different source version.
    row['field_provenance']['grossProfit']['filed']='2026-08-01'
    assert observations(value)['grossProfit']['state']=='available'


@pytest.mark.parametrize('kind,field,affected', [
    ('income', 'grossProfit', ('grossMargins',)),
    ('income', 'netIncome', ('profitMargins', 'returnOnEquity', 'returnOnAssets', 'cashConversion', 'netIncomeGrowthFY')),
    ('income', 'operatingIncome', ('operatingMargins', 'roic')),
    ('balance', 'stockholdersEquity', ('debtToEquity', 'returnOnEquity', 'roic')),
    ('balance', 'totalAssets', ('returnOnAssets',)),
    ('balance', 'currentLiabilities', ('currentRatio', 'cashRatio', 'quickRatio')),
    ('cashflow', 'operatingCashflow', ('freeCashflow', 'fcfMargin', 'cashConversion')),
    ('cashflow', 'capitalExpenditure', ('capex', 'freeCashflow', 'fcfMargin')),
])
@pytest.mark.parametrize('ambiguous', [False, True])
def test_profile_fallback_cannot_restore_ratios_with_quarantined_sec_inputs(kind, field, affected, ambiguous):
    from company_metrics import metric_observations
    value=bundle()
    value['annual']['balance'][0]['values'].update(currentLiabilities=10, currentAssets=30, receivables=5)
    row=value['annual'][kind][0]
    sec(row,field,start=None if kind=='balance' else '2025-01-01')
    amount=row['values'][field]
    value['sec_reconciliation']={'conflicts':[{
        'period':'annual','statement':kind,'field':field,'end':row['end'],'currency':'USD',
        'provider_value':amount,'sec_value':None if ambiguous else amount+1,
        'existing_source':'SEC EDGAR','existing_provenance':deepcopy(row['field_provenance'][field]),
        'ambiguous':ambiguous}]}
    info={'financialCurrency':'USD','totalRevenue':100,
          'grossMargins':.4,'operatingMargins':.2,'profitMargins':.1,
          'returnOnEquity':.15,'returnOnAssets':.1,'debtToEquity':25,
          'currentRatio':3,'freeCashflow':20}
    result=metric_observations('TEST',info,value)
    for key in affected:
        assert result[key]['state']=='invalid', key
        assert result[key]['value'] is None, key
        assert result[key]['source']!='Yahoo Finance profile', key
        assert any(p['field']==field and p['value']==amount for p in result[key]['provenance']), key
    # Unrelated reported data remains usable while these specific inputs await review.
    assert result['revenue']['state']=='available' and result['revenue']['value']==100


def test_ordinary_missing_inputs_still_allow_distinct_profile_observations():
    from company_metrics import metric_observations
    value=bundle()
    for row in value['annual']['income']:
        row['values'].pop('grossProfit', None)
        row['values'].pop('netIncome', None)
    info={'financialCurrency':'USD','totalRevenue':100,'grossMargins':.4,
          'returnOnEquity':.15,'returnOnAssets':.1}
    result=metric_observations('TEST',info,value)
    for key in ('grossMargins','returnOnEquity','returnOnAssets'):
        assert result[key]['state']=='available' and result[key]['value']==info[key]
        assert result[key]['source']=='Yahoo Finance profile'
