"""Accounting invariants and integration for the company's financial research.

All financial observations below are explicit test fixtures, never market data.
"""
from copy import deepcopy
from datetime import date
import json
import pandas as pd
import pytest
from financial_statements import observations, statement_records, FLOW_FIELDS, collect
from company_metrics import METRICS, BY_KEY, audit_profile, build_rows, metric_observations, evaluate


def bundle():
    return {'schema':1, 'ticker':'TEST', 'currency':'USD', 'fetched_at':'2026-09-13T00:00:00Z',
            'annual':{
                'income':[
                    {'end':'2025-12-31','values':{'revenue':100,'grossProfit':40,'operatingIncome':20,'ebit':21,'ebitda':25,'netIncome':10,'dilutedEPS':2,'pretaxIncome':12.5,'taxProvision':2.5,'interestExpense':2}},
                    {'end':'2024-12-31','values':{'revenue':80,'netIncome':8,'dilutedEPS':1.6}}],
                'balance':[
                    {'end':'2025-12-31','values':{'stockholdersEquity':80,'totalDebt':20,'cash':10,'totalAssets':140,'totalLiabilities':60,'currentAssets':60,'currentLiabilities':30,'receivables':20}},
                    {'end':'2024-12-31','values':{'stockholdersEquity':60,'totalDebt':20,'cash':10,'totalAssets':120}}],
                'cashflow':[{'end':'2025-12-31','values':{'operatingCashflow':30,'capitalExpenditure':-10,'repurchaseOfCapitalStock':-5,'cashDividendsPaid':-4}}]}, 'quarterly':{}}


def test_matched_fiscal_year_formulas_units_and_provenance():
    b=bundle();before=deepcopy(b);o=observations(b)
    expected={'debtToEquity':.25,'liabilitiesToEquity':.75,'currentRatio':2,'quickRatio':1,
              'cashRatio':1/3,'grossMargins':.4,'profitMargins':.1,'freeCashflow':20,'fcfMargin':.2,
              'cashConversion':3,'interestCoverage':10.5,'roic':.2,'returnOnEquity':10/70,
              'returnOnAssets':10/130,'revenueGrowthFY':.25,'netIncomeGrowthFY':.25,
              'epsGrowthFY':.25,'capex':10,'buybacks':5,'dividendsPaid':4,'netDebt':10,'workingCapital':30}
    for key,value in expected.items():
        assert o[key]['value']==pytest.approx(value),key
        assert o[key]['end']=='2025-12-31' and o[key]['currency']=='USD'
    assert 'average' in o['roic']['formula']
    assert o['operatingIncome']['value']!=o['ebit']['value']
    assert b==before
    json.dumps(o,allow_nan=False)


def test_info_debt_percentage_is_always_converted_without_magnitude_guessing():
    for raw,expected in [(150,1.5),(1,.01),(0,0)]:
        result=metric_observations('TEST',{'debtToEquity':raw})
        assert result['debtToEquity']['value']==expected
        assert 'percentage / 100' in result['debtToEquity']['formula']


def test_ttm_uses_four_consecutive_aligned_quarters_and_never_sums_eps():
    b=bundle();ends=['2026-06-30','2026-03-31','2025-12-31','2025-09-30']
    b['quarterly']={'income':[{'end':d,'values':{'revenue':25,'grossProfit':10,'netIncome':5,'dilutedEPS':1}} for d in ends],
                    'cashflow':[{'end':d,'values':{'operatingCashflow':10,'capitalExpenditure':-2}} for d in ends]}
    o=observations(b)
    assert o['revenue']['value']==100 and o['freeCashflow']['value']==32
    assert o['fcfMargin']['value']==.32
    assert o['revenue']['basis']=='TTM (4 reported quarters)'
    assert 'dilutedEPS' not in o
    assert 'roic' not in o, 'No balance sheet at the TTM date or tax inputs; do not mix annual inputs'
    # One missing quarter's value must not become a three-quarter total.
    del b['quarterly']['income'][2]['values']['grossProfit']
    assert 'grossProfit' not in observations(b)


@pytest.mark.parametrize('change',['three_quarters','gap','mismatched_cash_dates'])
def test_incomplete_or_misaligned_quarters_fall_back_to_labeled_fiscal_year(change):
    b=bundle();ends=['2026-06-30','2026-03-31','2025-12-31','2025-09-30']
    b['quarterly']={kind:[{'end':d,'values':{'revenue':1000,'operatingCashflow':1000}} for d in ends] for kind in ('income','cashflow')}
    if change=='three_quarters':b['quarterly']['income'].pop()
    elif change=='gap':b['quarterly']['income'][2]['end']='2024-12-31'
    else:b['quarterly']['cashflow'][1]['end']='2026-03-30'
    o=observations(b)
    assert o['revenue']['value']==100 and o['revenue']['basis']=='FY'


def test_different_annual_flow_dates_never_generate_cross_period_ratios():
    b=bundle();b['annual']['cashflow'][0]['end']='2023-12-31'
    o=observations(b)
    assert o['operatingCashflow']['end']=='2023-12-31'
    assert o['revenue']['end']=='2025-12-31'
    assert 'cashConversion' not in o and 'fcfMargin' not in o and 'roic' not in o


@pytest.mark.parametrize('field,value',[('stockholdersEquity',0),('stockholdersEquity',-20),('totalDebt',-1),('cash',-2)])
def test_invalid_capital_does_not_generate_a_strong_roic(field,value):
    b=bundle();b['annual']['balance'][0]['values'][field]=value
    o=observations(b)
    if field=='stockholdersEquity':
        assert o['returnOnEquity']['state']=='not_meaningful'
        assert o['debtToEquity']['state']=='not_meaningful'
    if field in ('totalDebt','cash'):
        assert o[field]['state']=='invalid'
    # ROIC can be defined with negative book equity only when net invested capital
    # is still positive; this fixture's zero/negative equity leaves nonpositive IC.
    if field!='stockholdersEquity' or value < 0:
        assert o['roic']['state']=='not_meaningful'


@pytest.mark.parametrize('tax,pretax',[(30,10),(-1,10),(1,0),(1,-5)])
def test_roic_never_invents_a_tax_rate(tax,pretax):
    b=bundle();b['annual']['income'][0]['values'].update(taxProvision=tax,pretaxIncome=pretax)
    result=observations(b)['roic']
    assert result['state']=='not_meaningful' and result['value'] is None


def test_zero_debt_and_cash_are_valid_and_missing_capex_is_not_zero():
    b=bundle();b['annual']['balance'][0]['values']['totalDebt']=0
    b['annual']['cashflow'][0]['values'].pop('capitalExpenditure')
    o=observations(b)
    assert o['debtToEquity']['value']==0
    assert o['netDebt']['value']==-10
    assert 'freeCashflow' not in o and 'capex' not in o
    b['annual']['income'][0]['values']['interestExpense']=0
    assert observations(b)['interestCoverage']['state']=='not_meaningful'


def test_losses_and_book_equity_are_not_cheap_valuation_or_positive_growth():
    states=audit_profile('TEST',{'forwardPE':10,'forwardEps':-1,'trailingPE':5,'trailingEps':0,'priceToBook':2,'bookValue':-1,'debtToEquity':10,'returnOnEquity':.3})
    for key in ('forwardPE','trailingPE','priceToBook','debtToEquity','returnOnEquity'):
        assert states[key]=='not_meaningful'
    b=bundle();b['annual']['income'][1]['values']['netIncome']=-10
    assert observations(b)['netIncomeGrowthFY']['state']=='not_meaningful'


def test_etfs_have_applicable_fund_metrics_but_no_corporate_ratio_scores():
    states=audit_profile('AAAU',{'trailingPE':10,'returnOnEquity':.2},bundle(),is_etf=True)
    assert set(states.values())=={'not_applicable'}


def test_specialized_financial_business_and_roic_do_not_get_generic_good_bad_scores():
    for sector in ('Financial Services','Financial'):
        assert evaluate(BY_KEY['debtToEquity'],3,{'sector':sector})[1]=='Specialized comparison'
        assert evaluate(BY_KEY['returnOnAssets'],.01,{'sector':sector})[1]=='Specialized comparison'
    result=evaluate(BY_KEY['roic'],.15,{'sector':'Technology'})
    assert result[1]=='WACC comparison needed' and 'not supplied' in result[0]


def test_symbols_currencies_and_invalid_values_are_never_silently_assumed():
    b=bundle();b['ticker']='OTHER'
    assert metric_observations('TEST',{},b)['grossProfit']['value'] is None
    b['ticker']='TEST';b['currency']=None
    assert metric_observations('TEST',{},b)['grossProfit']['value'] is None
    for value in (True,float('nan'),float('inf'),'bad'):
        assert metric_observations('TEST',{'debtToEquity':value})['debtToEquity']['state']=='invalid'


def test_future_statements_missing_values_and_duplicate_labels_are_rejected():
    frame=pd.DataFrame({'2025-12-31':[100,float('nan')],'2028-12-31':[500,200]},index=['Total Revenue','Gross Profit'])
    records=statement_records(frame,FLOW_FIELDS,today=date(2026,9,13))
    assert records==[{'end':'2025-12-31','values':{'revenue':100}}]
    duplicate=pd.DataFrame({'2025-12-31':[100,200]},index=['Total Revenue','Total Revenue'])
    assert statement_records(duplicate,FLOW_FIELDS)==[]


def test_collection_is_separate_and_partial_errors_preserve_available_statements():
    class Provider:
        def get_income_stmt(self,**kwargs):return pd.DataFrame({'2025-12-31':[100]},index=['Total Revenue'])
        def get_balance_sheet(self,**kwargs):raise ValueError('Unavailable')
        def get_cash_flow(self,**kwargs):return pd.DataFrame({'2025-12-31':[20]},index=['Operating Cash Flow'])
    result=collect('TEST',{'financialCurrency':'USD'},Provider(),now='2026-09-13T00:00:00Z')
    assert result['observations']['revenue']['value']==100
    assert len(result['errors'])==2
    class Limited(Provider):
        def get_income_stmt(self,**kwargs):raise RuntimeError('429 rate limited')
    with pytest.raises(RuntimeError,match='429'):
        collect('TEST',{},Limited())


def test_grouped_html_is_escaped_and_help_only_appears_on_metric_names():
    from bs4 import BeautifulSoup
    from company_analysis_ui import analysis_html
    rows=build_rows('TEST',{'financialCurrency':'USD','debtToEquity':150},bundle())
    rows[0]['Metric']='<script>alert(1)</script>'
    rows[0]['_help']='\"<img src=x onerror=alert(1)>'
    markup=analysis_html(rows,'TEST\" onmouseover=bad')
    soup=BeautifulSoup(markup,'html.parser')
    assert not soup.select('script, img, [onmouseover]')
    assert len(soup.select('section.company-analysis'))==9
    assert len(soup.select('tbody tr'))==len(METRICS)
    assert len(soup.select('tbody abbr[title][tabindex="0"]'))==len(METRICS)
    assert not soup.select('thead [title], td [title]')
    assert '1.50' not in soup.select_one('[data-metric="debtToEquity"]').get_text(), 'Matched statement D/E overrides profile percentage'
    assert '0.25×' in soup.select_one('[data-metric="debtToEquity"]').get_text()


def test_statement_objects_survive_checked_snapshot_and_whole_catalog_audit(tmp_path):
    import dashboard_runtime as a
    from data_sync import ObjectStore,SnapshotReader
    from update_data import publish_snapshot
    from data_quality import make_quality
    cache=a.DashboardCache(tmp_path/'source.sqlite3')
    cache.put('info:TEST',{'symbol':'TEST','financialCurrency':'USD'},{'fetched_at':'2026-09-13T00:00:00Z'})
    cache.put('financials:TEST',bundle(),{'fetched_at':'2026-09-13T00:00:00Z'})
    q=make_quality(cache,('TEST','AAAU'),etfs=('AAAU',))
    assert q['columns']['company.roic']=={'available':1,'not_applicable':1}
    assert q['counts']['financial_statements']==1
    store=ObjectStore({'backend':'local','DASHBOARD_SNAPSHOT_DIR':str(tmp_path/'snapshots')},writable=True)
    manifest=publish_snapshot(store,cache,('TEST','AAAU'),{},None)
    assert manifest['coverage']['financial_statements']==1
    target=a.DashboardCache(tmp_path/'target.sqlite3');reader=SnapshotReader(store,target)
    reader._sync();reader._details('TEST')
    assert target.get('financials:TEST',request_remote=False)[0]==bundle()
