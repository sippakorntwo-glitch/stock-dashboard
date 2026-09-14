"""Historical research uses actual matched observations, never invented flows."""
from copy import deepcopy
from datetime import date
import json
import pandas as pd
import pytest

from financial_statements import collect
from financial_trends import build_financial_trends, export_trends


def fixture():
    return {'schema': 1, 'ticker': 'TEST', 'currency': 'USD',
            'fetched_at': '2026-09-14T00:00:00Z', 'annual': {
                'income': [
                    {'end': '2025-12-31', 'values': {'revenue': 100, 'grossProfit': 40,
                     'operatingIncome': 20, 'netIncome': 10, 'dilutedEPS': 2, 'dilutedAverageShares': 5}},
                    {'end': '2024-12-31', 'values': {'revenue': 80, 'netIncome': 8, 'dilutedAverageShares': 4}}],
                'cashflow': [{'end': '2025-12-31', 'values': {'operatingCashflow': 30,
                    'capitalExpenditure': -10, 'stockBasedCompensation': 3,
                    'repurchaseOfCapitalStock': -5, 'issuanceOfCapitalStock': 2}}],
                'balance': [
                    {'end': '2025-12-31', 'values': {'totalDebt': 20, 'cash': 10, 'ordinarySharesNumber': 4.5}},
                    {'end': '2024-12-31', 'values': {'totalDebt': 18, 'cash': 8, 'ordinarySharesNumber': 4}}]},
            'quarterly': {}}


def quarters(bundle):
    ends = ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30']
    bundle['quarterly'] = {
        'income': [{'end': end, 'values': {'revenue': 25, 'grossProfit': 10, 'netIncome': 5,
                                          'dilutedAverageShares': 5, 'dilutedEPS': 1}} for end in ends],
        'cashflow': [{'end': end, 'values': {'operatingCashflow': 10, 'capitalExpenditure': -2,
                    'repurchaseOfCapitalStock': -3, 'issuanceOfCapitalStock': 1}} for end in ends],
        'balance': [{'end': '2026-06-30', 'values': {'totalDebt': 30, 'cash': 20,
                                                               'ordinarySharesNumber': 6}}]}
    return bundle


def build(bundle):
    return build_financial_trends('TEST', {'financialCurrency': 'USD'}, bundle, today=date(2026, 9, 14))


def test_fy_formulas_actual_share_counts_and_exact_export_do_not_mutate_inputs():
    bundle = fixture()
    before = deepcopy(bundle)
    result = build(bundle)
    metrics = result['periods']['FY'][-1]['metrics']
    expected = {'revenueGrowth': .25, 'netIncomeGrowth': .25, 'grossMargins': .4,
                'profitMargins': .1, 'freeCashflow': 20, 'fcfMargin': .2, 'cashConversion': 3,
                'sbcToRevenue': .03, 'buybacks': 5, 'netBuybackCash': 3, 'netDebt': 10,
                'shareCountGrowth': .125, 'dilutedSharesGrowth': .25}
    for key, expected_value in expected.items():
        assert metrics[key]['state'] == 'available', key
        assert metrics[key]['value'] == pytest.approx(expected_value), key
    exported = [r for r in export_trends(result, 'FY') if r['วันสิ้นงวด'] == '2025-12-31']
    values = {r['รหัสรายการ']: r for r in exported}
    assert values['grossMargins']['ค่า'] == 40 and values['grossMargins']['หน่วย'] == '%'
    assert values['ordinarySharesNumber']['ค่า'] == 4.5 and values['ordinarySharesNumber']['หน่วย'] == 'หุ้น'
    assert values['shareCountGrowth']['วันสิ้นงวดเทียบปีก่อน'] == '2024-12-31'
    assert values['totalDebt']['ประเภทข้อมูล'] == 'Balance sheet'
    assert values['freeCashflow']['ดึงข้อมูลเมื่อ'] == bundle['fetched_at']
    assert bundle == before
    json.dumps(result, allow_nan=False)


def test_ttm_sums_only_complete_matched_flows_and_uses_point_balance():
    result = build(quarters(fixture()))
    assert len(result['periods']['TTM']) == 1
    metrics = result['periods']['TTM'][0]['metrics']
    for key, value in {'revenue': 100, 'freeCashflow': 32, 'cashConversion': 2,
                       'fcfMargin': .32, 'netBuybackCash': 8, 'ordinarySharesNumber': 6,
                       'totalDebt': 30, 'netDebt': 10}.items():
        assert metrics[key]['value'] == pytest.approx(value), key
    for key in ('dilutedEPS', 'dilutedAverageShares'):
        assert metrics[key]['value'] is None and metrics[key]['state'] == 'not_reported'
    assert len(metrics['revenue']['period_ends']) == 4
    assert metrics['totalDebt']['period_ends'] == ['2026-06-30']


@pytest.mark.parametrize('change', ['missing_quarter', 'gap', 'shifted_window', 'missing_value'])
def test_ttm_never_combines_incomplete_or_different_quarter_windows(change):
    bundle = quarters(fixture())
    records = bundle['quarterly']['cashflow']
    if change == 'missing_quarter':
        records.pop()
    elif change == 'gap':
        records[-1]['end'] = '2025-03-31'
    elif change == 'shifted_window':
        records[-1]['end'] = '2025-09-29'
    else:
        del records[1]['values']['operatingCashflow']
    metrics = build(bundle)['periods']['TTM'][-1]['metrics']
    assert metrics['revenue']['value'] == 100
    assert metrics['cashConversion']['value'] is None
    assert metrics['fcfMargin']['value'] is None
    if change == 'shifted_window':
        assert metrics['cashConversion']['state'] == 'period_mismatch'
        assert metrics['freeCashflow']['value'] == 32


def test_annual_dates_and_currencies_cannot_be_mixed():
    bundle = fixture()
    bundle['annual']['cashflow'][0]['end'] = '2025-09-30'
    result = build(bundle)
    assert all(row['metrics']['cashConversion']['value'] is None for row in result['periods']['FY'])
    bundle = fixture()
    bundle['annual']['cashflow'][0]['currency'] = 'EUR'
    metrics = build(bundle)['periods']['FY'][-1]['metrics']
    assert metrics['operatingCashflow']['state'] == 'currency_mismatch'
    assert metrics['cashConversion']['state'] == 'currency_mismatch'
    bundle['currency'] = 'EUR'
    assert build(bundle)['state'] == 'currency_mismatch'


def test_ytd_records_never_count_as_a_single_quarter():
    bundle = quarters(fixture())
    bundle['quarterly']['cashflow'][0]['basis'] = 'YTD'
    metrics = build(bundle)['periods']['TTM'][-1]['metrics']
    assert metrics['operatingCashflow']['state'] == 'period_mismatch'
    assert metrics['cashConversion']['value'] is None


@pytest.mark.parametrize('key,value', [('repurchaseOfCapitalStock', 5), ('capitalExpenditure', 10),
                                     ('issuanceOfCapitalStock', -2)])
def test_sign_reversals_are_withheld_instead_of_reinterpreted(key, value):
    bundle = fixture()
    bundle['annual']['cashflow'][0]['values'][key] = value
    metrics = build(bundle)['periods']['FY'][-1]['metrics']
    assert metrics[key]['state'] == 'invalid' and metrics[key]['value'] is None
    affected = 'freeCashflow' if key == 'capitalExpenditure' else 'netBuybackCash'
    assert metrics[affected]['state'] == 'invalid'


def test_missing_issuance_does_not_turn_gross_repurchases_into_net_buyback():
    bundle = fixture()
    del bundle['annual']['cashflow'][0]['values']['issuanceOfCapitalStock']
    metrics = build(bundle)['periods']['FY'][-1]['metrics']
    assert metrics['buybacks']['value'] == 5
    assert metrics['netBuybackCash']['value'] is None
    assert metrics['netBuybackCash']['state'] == 'missing_inputs'
    bundle['annual']['cashflow'][0]['values']['issuanceOfCapitalStock'] = 0
    assert build(bundle)['periods']['FY'][-1]['metrics']['netBuybackCash']['value'] == 5


def test_reported_fcf_errors_do_not_cancel_when_aggregated_to_ttm():
    bundle = quarters(fixture())
    for record, value in zip(bundle['quarterly']['cashflow'], (10, 6, 8, 8)):
        record['values']['freeCashflow'] = value
    metrics = build(bundle)['periods']['TTM'][-1]['metrics']
    assert metrics['freeCashflow']['state'] == 'invalid'
    assert metrics['freeCashflow']['value'] is None
    assert metrics['fcfMargin']['state'] == 'invalid'


def test_losses_are_not_positive_growth_or_cash_conversion_scores():
    bundle = fixture()
    bundle['annual']['income'][1]['values']['netIncome'] = -8
    bundle['annual']['income'][0]['values']['netIncome'] = -10
    metrics = build(bundle)['periods']['FY'][-1]['metrics']
    assert metrics['netIncomeGrowth']['state'] == 'not_meaningful'
    assert metrics['cashConversion']['state'] == 'not_meaningful'
    assert metrics['profitMargins']['value'] == -.1


def test_future_invalid_and_ambiguous_duplicate_periods_are_withheld():
    bundle = fixture()
    bundle['annual']['income'].append({'end': '2028-12-31', 'values': {'revenue': 1000}})
    bundle['annual']['income'].append({'end': '2025-12-31', 'values': {'revenue': 999}})
    result = build(bundle)
    assert len(result['issues']) == 2
    assert result['periods']['FY'][-1]['end'] == '2025-12-31'
    assert result['periods']['FY'][-1]['metrics']['revenue']['value'] is None
    assert result['periods']['FY'][-1]['metrics']['revenue']['state'] == 'invalid'
    bundle = fixture()
    bundle['annual']['income'][0]['values']['revenue'] = float('inf')
    result = build(bundle)
    assert result['periods']['FY'][-1]['metrics']['revenue']['state'] == 'invalid'
    json.dumps(result, allow_nan=False)


def test_percent_overflow_is_withheld_before_chart_or_csv_conversion():
    bundle = fixture()
    bundle['annual']['income'][0]['values']['revenue'] = 1e308
    bundle['annual']['income'][1]['values']['revenue'] = 1
    result = build(bundle)
    assert result['periods']['FY'][-1]['metrics']['revenueGrowth']['state'] == 'invalid'
    json.dumps(export_trends(result), allow_nan=False)


def test_conflicting_same_date_balances_not_selected_arbitrarily_for_ttm():
    bundle = quarters(fixture())
    bundle['annual']['balance'].append({'end': '2026-06-30', 'values': {'totalDebt': 999}})
    metrics = build(bundle)['periods']['TTM'][-1]['metrics']
    assert metrics['totalDebt']['state'] == 'invalid'
    assert metrics['netDebt']['value'] is None


def test_missing_data_and_fund_applicability_are_distinct():
    assert build_financial_trends('SPY', {'quoteType': 'ETF'}, None)['state'] == 'not_applicable'
    assert build(None)['state'] == 'missing_inputs'
    bundle = fixture()
    bundle['ticker'] = 'OTHER'
    assert build(bundle)['state'] == 'missing_inputs'
    bundle['ticker'] = 'TEST'
    bundle['currency'] = None
    assert build(bundle)['state'] == 'missing_inputs'


def test_collector_adds_explicit_share_and_issuance_observations_without_summing_them():
    class Provider:
        def get_income_stmt(self, **kwargs):
            return pd.DataFrame({'2025-12-31': [100, 5]}, index=['Total Revenue', 'Diluted Average Shares'])

        def get_balance_sheet(self, **kwargs):
            return pd.DataFrame({'2025-12-31': [4.5]}, index=['Ordinary Shares Number'])

        def get_cash_flow(self, **kwargs):
            return pd.DataFrame({'2025-12-31': [30, 2]}, index=['Operating Cash Flow', 'Issuance Of Capital Stock'])

    bundle = collect('TEST', {'financialCurrency': 'USD'}, Provider(), now='2026-09-14T00:00:00Z')
    assert bundle['annual']['income'][0]['values']['dilutedAverageShares'] == 5
    assert bundle['quarterly']['balance'][0]['values']['ordinarySharesNumber'] == 4.5
    assert bundle['annual']['cashflow'][0]['values']['issuanceOfCapitalStock'] == 2
    assert 'dilutedAverageShares' not in bundle['observations']
    assert 'ordinarySharesNumber' not in bundle['observations']


def test_charts_keep_missing_gaps_exact_percent_units_and_share_series_separate():
    from financial_trends_ui import trend_figure
    rows = build(fixture())['periods']['FY']
    fig = trend_figure(rows, ('grossMargins',), 'USD', percent=True)
    assert list(fig.data[0].y) == [None, 40]
    assert fig.data[0].connectgaps is False
    assert list(fig.data[0].x) == ['2024-12-31', '2025-12-31']
    assert 'ร้อยละ' in fig.layout.yaxis.title.text
    shares = trend_figure(rows, ('ordinarySharesNumber', 'dilutedAverageShares'), 'USD', shares=True)
    assert list(shares.data[0].y) == [4, 4.5]
    assert list(shares.data[1].y) == [4, 5]
