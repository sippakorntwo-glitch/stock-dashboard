"""Display bases must not invent dates or replace financial observations."""
from copy import deepcopy

from company_analysis_th import build_rows_th, export_rows_th, period_label_th
from company_metrics import build_rows, metric_observations


def profile_fixture():
    return {
        'symbol': 'TEST', 'currency': 'USD', 'financialCurrency': 'USD',
        'marketCap': 4.92e12, 'enterpriseValue': 4.94e12,
        'trailingPE': 38.17, 'forwardPE': 35.15, 'priceToBook': 45.79,
        'priceToSalesTrailing12Months': 10.54,
        'enterpriseToRevenue': 10.58, 'enterpriseToEbitda': 29.41,
        'trailingEps': 8.7, 'forwardEps': 9.3, 'totalRevenue': 466e9,
        'ebitda': 168e9, 'trailingAnnualDividendYield': .003,
        '_Fetched_At_UTC': '2026-09-21T07:00:00Z',
        '_ProfileFetchedAt': '2026-09-20T08:00:00Z',
        'mostRecentQuarter': 1782777600,
        'lastFiscalYearEnd': 1767139200,
    }


def test_valuation_display_distinguishes_economic_bases_without_invented_dates():
    info = profile_fixture()
    before = deepcopy(info)
    observations = metric_observations('TEST', info)
    english = {r['_key']: r for r in build_rows('TEST', info)}
    rows = {r['_key']: r for r in build_rows_th('TEST', info)}
    periods = {key: rows[key]['Period'] for key in (
        'marketCap', 'enterpriseValue', 'trailingPE', 'forwardPE',
        'priceToBook', 'priceToSales', 'evRevenue', 'evEbitda')}
    assert len(set(periods.values())) == len(periods)
    assert 'มูลค่าตลาด ณ จุดเวลา' in periods['marketCap']
    assert 'วันที่องค์ประกอบ' in periods['enterpriseValue']
    assert 'กำไรย้อนหลัง 12 เดือน (TTM)' in periods['trailingPE']
    assert 'คาดการณ์' in periods['forwardPE'] and 'ไม่ระบุงวดประมาณการ' in periods['forwardPE']
    assert 'มูลค่าทางบัญชี' in periods['priceToBook'] and 'ไม่ระบุวันที่งบ' in periods['priceToBook']
    assert 'ยอดขายย้อนหลัง 12 เดือน (TTM)' in periods['priceToSales']
    for key in ('evRevenue', 'evEbitda'):
        assert 'ไม่ระบุงวด' in periods[key]
        assert 'TTM' not in periods[key]
    for row in rows.values():
        assert '2026-09-21' not in row['Period']
        assert '2026-09-20' not in row['Period']
        assert '2026-06-30' not in row['Period']
        assert '2025-12-31' not in row['Period']
        original = english[row['_key']]
        assert (row['_value'], row['_state']) == (original['_value'], original['_state'])
        if row['_state'] == 'available':
            assert row['Current Value'] == original['Current Value'].replace('/share', '/หุ้น')
    for key in periods:
        assert 'ไม่ระบุ' in periods[key]
        assert observations[key]['basis'] == 'Provider period'
        assert observations[key]['end'] is None
        assert 'แหล่งข้อมูล: ข้อมูลสรุปบริษัทจาก Yahoo Finance' in rows[key]['_help']
        assert periods[key] in rows[key]['_help']
    exported = export_rows_th([rows['priceToSales'], rows['forwardPE']])
    assert exported[0]['ค่าปัจจุบัน'] == '10.54×'
    assert exported[0]['รอบข้อมูล'] == periods['priceToSales']
    assert exported[1]['รอบข้อมูล'] == periods['forwardPE']
    assert 'Yahoo Finance' in exported[0]['คำอธิบายและวิธีคำนวณ']
    assert info == before


def test_canonical_reported_periods_and_provenance_take_precedence_over_profile_hints():
    info = profile_fixture()
    ends = ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30']
    bundle = {
        'schema': 1, 'ticker': 'TEST', 'currency': 'USD',
        'fetched_at': '2026-09-19T00:00:00Z', 'source': 'SEC EDGAR',
        'annual': {'income': [{'end': '2025-12-31', 'values': {'dilutedEPS': 2}}]},
        'quarterly': {
            'income': [{'end': end, 'values': {'revenue': 25, 'netIncome': 5}} for end in ends],
            'balance': [{'end': ends[0], 'values': {'totalAssets': 140, 'totalDebt': 20}}],
        },
    }
    before = deepcopy(bundle)
    rows = {row['_key']: row for row in build_rows_th('TEST', info, bundle)}
    assert rows['revenue']['Period'] == 'ย้อนหลัง 12 เดือน (TTM: 4 ไตรมาสที่รายงาน) · 2026-06-30'
    assert rows['profitMargins']['Period'] == rows['revenue']['Period']
    assert rows['dilutedEPS']['Period'] == 'ปีบัญชี (FY) · 2025-12-31'
    assert rows['totalAssets']['Period'] == 'งบฐานะการเงิน ณ วันที่ · 2026-06-30'
    assert rows['totalDebt']['Period'] == rows['totalAssets']['Period']
    assert rows['revenue']['_value'] == 100
    assert rows['dilutedEPS']['_value'] == 2
    assert 'แหล่งข้อมูล: SEC EDGAR' in rows['revenue']['_help']
    assert 'ไม่ระบุวันสิ้นงวด' in rows['priceToSales']['Period']
    assert rows['priceToSales']['Current Value'] == '10.54×'
    assert all('2026-09-19' not in row['Period'] for row in rows.values())
    assert bundle == before


def test_unknown_profile_basis_and_fund_applicability_are_explicit():
    rows = {row['_key']: row for row in build_rows_th('TEST', profile_fixture())}
    assert rows['revenue']['Period'] == 'ผู้ให้ข้อมูลไม่ระบุรอบบัญชี'
    assert 'กำไรต่อหุ้นย้อนหลัง 12 เดือน' in rows['dilutedEPS']['Period']
    assert 'คาดการณ์' in rows['forwardEps']['Period']
    fund = build_rows_th('FUND', {'quoteType': 'ETF', **profile_fixture()}, is_etf=True)
    assert all(row['_state'] == 'not_applicable' for row in fund)
    assert all(row['Period'] == 'ไม่ใช้กับหลักทรัพย์ประเภทนี้' for row in fund)
    # An explicitly dated observation is kept, even if a provider supplies it later.
    dated = {'source': 'Yahoo Finance profile', 'basis': 'Provider period', 'end': '2026-06-30'}
    assert period_label_th('priceToBook', dated) == 'รอบข้อมูลตามผู้ให้ข้อมูล · 2026-06-30'
