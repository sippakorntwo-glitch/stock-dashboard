"""Thai output keeps financial meaning, provenance and accessible metric help."""
from copy import deepcopy
import re

from bs4 import BeautifulSoup
from company_analysis_th import (METRIC_TEXT, METRIC_ALIASES, STATEMENT_ALIASES, GROUP_LABELS, TEXT, FORMULAS,
                                 build_rows_th, export_rows_th, profile_text_th)
from company_analysis_ui import analysis_html, statement_table, history_html
from company_metrics import METRICS, GROUPS, build_rows, evaluate, metric_observations


def has_thai(text):
    return bool(re.search('[ก-๙]', text))


def statement_fixture():
    return {'schema': 1, 'ticker': 'TEST', 'currency': 'USD', 'annual': {
        'income': [{'end': '2025-12-31', 'values': {
            'revenue': 100, 'grossProfit': 40, 'operatingIncome': 20, 'ebit': 21,
            'ebitda': 25, 'netIncome': 10, 'dilutedEPS': 2, 'pretaxIncome': 12.5,
            'taxProvision': 2.5, 'interestExpense': 2}},
            {'end': '2024-12-31', 'values': {'revenue': 80, 'netIncome': 8, 'dilutedEPS': 1.6}}],
        'balance': [{'end': '2025-12-31', 'values': {
            'stockholdersEquity': 80, 'totalDebt': 20, 'cash': 10, 'totalAssets': 140,
            'totalLiabilities': 60, 'currentAssets': 60, 'currentLiabilities': 30,
            'receivables': 20, 'inventory': 5}},
            {'end': '2024-12-31', 'values': {'stockholdersEquity': 60, 'totalDebt': 20,
                                          'cash': 10, 'totalAssets': 120}}],
        'cashflow': [{'end': '2025-12-31', 'values': {'operatingCashflow': 30,
            'capitalExpenditure': -10, 'repurchaseOfCapitalStock': -5, 'cashDividendsPaid': -4}}]},
        'quarterly': {}}


def test_all_metrics_and_policy_outcomes_have_complete_thai_translations():
    assert set(METRIC_TEXT) == {m.key for m in METRICS}
    assert set(METRIC_ALIASES) == set(METRIC_TEXT)
    assert METRIC_TEXT['grossMargins'][0] == 'อัตรากำไรขั้นต้น (GPM)'
    assert METRIC_TEXT['grossProfit'][0] == 'กำไรขั้นต้น (GP)'
    assert set(GROUP_LABELS) == set(GROUPS)
    # Exercise each band and the specialized-company policy, including loss bases.
    for info in ({}, {'sector': 'Financial Services'}, {'industry': 'REIT - Retail'}):
        for metric in METRICS:
            assert all(has_thai(s) for s in METRIC_TEXT[metric.key])
            label = METRIC_TEXT[metric.key][0]
            assert label.endswith('('+METRIC_ALIASES[metric.key]+')')
            assert label.count('(') == label.count(')') == 1, label
            for value in (-1, 0, .01, .03, .1, .5, .8, 1, 2, 3, 4, 10, 20, 30, 50):
                for message in evaluate(metric, value, info):
                    assert message in TEXT, (metric.key, message)
                    assert has_thai(TEXT[message])


def test_localized_rows_preserve_values_states_period_dates_and_complete_provenance():
    bundle = statement_fixture()
    info = {'financialCurrency': 'USD', 'currency': 'USD', 'trailingPE': 20,
            'forwardEps': 4.25, 'debtToEquity': 150}
    original = deepcopy(bundle)
    english, thai = build_rows('TEST', info, bundle), build_rows_th('TEST', info, bundle)
    observations = metric_observations('TEST', info, bundle)
    for before, after in zip(english, thai):
        assert (after['_key'], after['_state'], after['_value']) == (before['_key'], before['_state'], before['_value'])
        assert after['Group'] == before['Group']
        for key in ('Metric', 'Reference / Benchmark', 'Assessment', 'Interpretation', 'Period'):
            assert has_thai(after[key]), (after['_key'], key, after[key])
        if after['_state'] == 'available':
            assert after['Current Value'] == before['Current Value'].replace('/share', '/หุ้น')
        item = observations[after['_key']]
        if item.get('end'):
            assert item['end'] in after['Period']
        if item.get('formula'):
            assert item['formula'] in FORMULAS
            assert FORMULAS[item['formula']] in after['_help']
        assert all(has_thai(line) for line in after['_help'].splitlines())
    assert bundle == original


def test_missing_invalid_and_currency_mismatch_stay_distinct_in_thai_csv():
    bundle = statement_fixture()
    bundle['annual']['cashflow'][0]['values']['cashDividendsPaid'] = 4
    info = {'financialCurrency': 'USD', 'currency': 'JPY', 'priceToSalesTrailing12Months': 2,
            'enterpriseValue': 200, 'trailingEps': -1, 'trailingPE': -10}
    rows = build_rows_th('TEST', info, bundle)
    by_key = {r['_key']: r for r in rows}
    assert by_key['dividendsPaid']['_state'] == 'invalid'
    assert 'ผิดปกติ' in by_key['dividendsPaid']['Interpretation']
    assert by_key['trailingPE']['_state'] == 'not_meaningful'
    assert by_key['priceToSales']['_state'] == 'missing_inputs'
    assert 'สกุลเงิน' in by_key['priceToSales']['Interpretation']
    assert by_key['grossProfit']['Current Value'] == '40.00 USD'
    export = export_rows_th(rows)
    assert len(export) == len(METRICS)
    assert all(has_thai(key) for row in export for key in row)
    assert export[0]['หมวด'] == 'มูลค่าและความถูกแพง'
    assert all(has_thai(row['สถานะข้อมูล']) for row in export)
    pending = {r['_key']: r for r in build_rows_th('TEST', {})}
    assert pending['roic']['Current Value'] == 'รอเก็บงบการเงิน'
    fund = build_rows_th('SPY', {'quoteType': 'ETF'}, is_etf=True)
    assert all(r['_state'] == 'not_applicable' and 'N/A' in r['Current Value'] for r in fund)


def test_unreconciled_dividend_source_has_same_thai_reason_in_table_help_and_csv():
    from company_metrics import DIVIDEND_YIELD_SOURCE_DISAGREEMENT
    info = {'trailingAnnualDividendYield': 0., '_ProfileFetchedAt': '2026-09-11T20:00:00+00:00',
            '_DividendHistory': {'records': [{'Ex_Date': '2026-09-01', 'Dividend_Per_Share': .5}]}}
    original = deepcopy(info)
    row = next(row for row in build_rows_th('TEST', info) if row['_key'] == 'dividendYield')
    reason = TEXT[DIVIDEND_YIELD_SOURCE_DISAGREEMENT]
    assert row['_state'] == 'invalid' and row['_value'] is None
    assert row['Current Value'] != '0.00%'
    assert row['Interpretation'] == reason and reason in row['_help']
    assert 'องค์ประกอบของเงินจ่าย' in reason and 'นิยามอัตราผลตอบแทน' in reason
    exported = export_rows_th([row])[0]
    assert exported['ค่าปัจจุบัน'] == row['Current Value']
    assert exported['การตีความ'] == reason and reason in exported['คำอธิบายและวิธีคำนวณ']
    assert all(has_thai(line) for line in row['_help'].splitlines())
    assert info == original


def test_legacy_360_withholds_same_unreconciled_dividend_for_company_and_fund():
    from asset_semantics import adapt_analysis
    from company_analysis_th import localize_360_frame, LEGACY_360_LABELS
    from company_metrics import DIVIDEND_YIELD_SOURCE_DISAGREEMENT
    from dashboard_runtime import build_analysis
    for ticker, asset_type, quote_type in [('AAPL', 'Common Stock', 'EQUITY'), ('SPY', 'ETF', 'ETF')]:
        info = {'symbol': ticker, 'quoteType': quote_type, 'trailingAnnualDividendYield': 0.,
                'trailingAnnualDividendRate': 0., 'regularMarketPrice': 100.,
                '_ProfileFetchedAt': '2026-09-11T20:00:00+00:00',
                '_DividendHistory': {'records': [{'Ex_Date': '2026-09-01', 'Dividend_Per_Share': .5}]}}
        original = deepcopy(info)
        frame, _, extra = build_analysis({}, {'Ticker': ticker, 'Asset_Type': asset_type}, info)
        display = localize_360_frame(adapt_analysis(frame, ticker, info, asset_type == 'ETF'))
        row = display.loc[display['ปัจจัย'].eq(LEGACY_360_LABELS['Dividend Yield'])].iloc[0]
        assert row['ค่าล่าสุด'] == '— (ค่าต้นทางผิดปกติ)'
        assert row['การแปลผล'] == TEXT[DIVIDEND_YIELD_SOURCE_DISAGREEMENT]
        assert extra['dividend_pct'] is None and extra['dividend_yield_state'] == 'source_disagreement'
        assert extra['dividend_yield_conflict_date'] == '2026-09-01'
        if asset_type == 'Common Stock':
            assert frame['_company_metric'].isin(METRIC_TEXT).sum() == 15
        assert info == original


def test_thai_tables_keep_metric_only_help_and_include_all_annual_source_fields():
    bundle = statement_fixture()
    rows = build_rows_th('TEST', {'currency': 'USD', 'financialCurrency': 'USD'}, bundle)
    soup = BeautifulSoup(analysis_html(rows, 'TEST'), 'html.parser')
    assert len(soup.select('section[data-group][data-ticker="TEST"]')) == 9
    assert len(soup.select('tr[data-metric]')) == 54
    assert len(soup.select('tbody abbr[title][tabindex="0"]')) == 54
    assert all(has_thai(n.get_text()) for n in soup.select('h4, thead th, tbody th'))
    assert not soup.select('thead [title], td [title]')
    # The compact presentation retains all figures and periods, while detailed
    # interpretation remains available to mouse, keyboard and touch readers.
    for source, rendered in zip(rows, soup.select('tr[data-metric]')):
        assert [cell.get_text() for cell in rendered.select('td')] == [
            source['Current Value'], source['Period'], source['Assessment']]
        assert source['Reference / Benchmark'] in rendered.abbr['title']
        assert source['Interpretation'] in rendered.abbr['title']
        glossary = rendered.find_parent('section').select_one('details.company-glossary')
        assert source['_help'] in glossary.get_text()
        assert source['Reference / Benchmark'] in glossary.get_text()
        assert source['Interpretation'] in glossary.get_text()
    assert all([cell.get_text() for cell in header.select('th')] ==
               ['ตัวชี้วัด', 'ค่าปัจจุบัน', 'รอบข้อมูล', 'การประเมิน']
               for header in soup.select('thead'))
    restored = set()
    for kind in ('income', 'balance', 'cashflow'):
        annual = statement_table(bundle, kind)
        history = BeautifulSoup(history_html(annual, 'งบการเงิน', kind=kind), 'html.parser')
        assert history.select_one(f'section[data-statement="{kind}"]')
        assert all(has_thai(n.get_text()) and has_thai(n['title']) for n in history.select('tbody abbr'))
        for row in annual:
            alias = STATEMENT_ALIASES[{'capitalExpenditure': 'capex', 'repurchaseOfCapitalStock': 'buybacks', 'cashDividendsPaid': 'dividendsPaid'}.get(row['_field'], row['_field'])]
            assert row['Metric'].endswith('('+alias+')')
            assert row['Metric'].count('(') == row['Metric'].count(')') == 1
        assert not history.select('td [title], thead [title]')
        restored.update(n['data-statement-field'] for n in history.select('tr[data-statement-field]'))
    assert {'interestExpense', 'pretaxIncome', 'taxProvision', 'receivables', 'inventory'} <= restored
    bundle['annual']['balance'][0]['values']['inventory'] = -5
    bundle['annual']['cashflow'][0]['values']['cashDividendsPaid'] = 4
    assert next(r for r in statement_table(bundle, 'balance') if r['_field'] == 'inventory')['2025-12-31'] == 'ค่าต้นทางผิดปกติ'
    assert next(r for r in statement_table(bundle, 'cashflow') if r['_field'] == 'cashDividendsPaid')['2025-12-31'] == 'ค่าต้นทางผิดปกติ'


def test_profile_values_are_translated_without_guessing_unknown_classifications():
    result = profile_text_th({'sector': 'Technology', 'industry': 'Semiconductors', 'country': 'United States'})
    assert result == 'กลุ่มธุรกิจ: เทคโนโลยี · อุตสาหกรรม: เซมิคอนดักเตอร์ · ประเทศ/เขตที่ตั้ง: สหรัฐอเมริกา'
    assert profile_text_th({'industry': 'New source category'}) == 'อุตสาหกรรม: ตามข้อมูลต้นทาง (New source category)'


def test_profile_eps_never_borrows_reporting_currency_when_quote_currency_missing():
    rows = {r['_key']: r for r in build_rows_th('TEST', {'financialCurrency': 'JPY', 'trailingEps': 1.5, 'forwardEps': 2})}
    assert rows['dilutedEPS']['Current Value'] == '1.50 ไม่ระบุสกุลเงิน/หุ้น'
    assert rows['forwardEps']['Current Value'] == '2.00 ไม่ระบุสกุลเงิน/หุ้น'
    usd = {r['_key']: r for r in build_rows_th('TEST', {'financialCurrency': 'JPY', 'currency': 'USD', 'forwardEps': 2})}
    assert usd['forwardEps']['Current Value'] == '2.00 USD/หุ้น'
