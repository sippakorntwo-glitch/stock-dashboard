from copy import deepcopy
from datetime import datetime,timezone
import math
import pytest
from financial_statements import parse_statements,derived_metrics,METHOD
from company_research import build_review,format_value
from company_metrics import METRICS,BY_KEY

NOW='2026-09-13T10:00:00+00:00'

def observation(value,start='2025-01-01',end='2025-12-31',accn='0000000001-26-000001',filed='2026-02-01',form='10-K'):
    x={'val':value,'end':end,'accn':accn,'filed':filed,'form':form}
    if start:x['start']=start
    return x

def doc(rows):return {'cik':1,'facts':{'us-gaap':{k:{'units':{'USD':v}} for k,v in rows.items()}}}

def base_period():
    return {'start':'2025-01-01','end':'2025-12-31','accession':'0000000001-26-000001','filed':'2026-02-01','currency':'USD','url':'https://www.sec.gov/Archives/edgar/data/1/test/',
            'values':{'revenue':1000.,'cost_of_revenue':600.,'operating_income':160.,'net_income':100.,'pretax_income':150.,'tax_expense':30.,'interest_expense':10.,'da':40.,'ocf':150.,'capex':50.,'assets':1000.,'equity':500.,'cash':100.,'liabilities':500.,'debt_current':20.,'debt_long':180.,'debt_short':0.,'current_assets':300.,'current_liabilities':150.,'inventory':50.,'receivables':70.,'short_investments':30.,'sbc':25.},
            'opening':{'assets':900.,'equity':400.,'cash':80.,'debt_current':20.,'debt_long':130.,'debt_short':0.,'inventory':30.},'tags':{}}

def test_all_required_metrics_defined_and_tooltips_are_substantive():
    assert len(METRICS)>=50 and len({s.key for s in METRICS})==len(METRICS)
    for key in ('de','roe','roic','ebit','ebitda','net_income','gross_profit','price_book','current_ratio','ocf','fcf'):
        assert key in BY_KEY and len(BY_KEY[key].definition)>50
    assert all(s.guide and s.group for s in METRICS)

def test_same_fiscal_year_formulas_use_average_denominators_and_no_assumed_debt():
    p=base_period();before=deepcopy(p);x=derived_metrics(p)
    assert p==before
    expected={'gross_profit':400,'gross_margin':40,'operating_margin':16,'net_margin':10,'ebit':160,'ebitda':200,'fcf':100,'roe':100/450*100,'roa':100/950*100,'de':.4,'current_ratio':2,'quick_ratio':200/150,'ocf_ni':1.5,'interest_coverage':16,'net_debt':100,'net_debt_ebitda':.5,'roic':128/535*100,'sbc_revenue':2.5}
    for k,v in expected.items():assert x[k]['value']==pytest.approx(v),k
    del p['values']['debt_short']
    x=derived_metrics(p)
    assert 'roic' not in x and 'de' not in x and 'net_debt' not in x

def test_prior_year_growth_requires_adjacent_dates_currency_and_positive_base():
    p=base_period();old={'end':'2024-12-31','currency':'USD','values':{'revenue':800,'net_income':-20}}
    x=derived_metrics(p,old)
    assert x['revenue_growth_fy']['value']==25 and 'net_income_growth_fy' not in x
    assert 'revenue_growth_fy' not in derived_metrics(p,{**old,'currency':'EUR'})
    assert 'revenue_growth_fy' not in derived_metrics(p,{**old,'end':'2023-12-31'})

@pytest.mark.parametrize('key,value',[('pretax_income',-1),('tax_expense',-1),('tax_expense',160)])
def test_roic_refuses_unusable_tax_rate(key,value):
    p=base_period();p['values'][key]=value
    assert 'roic' not in derived_metrics(p)

def test_negative_or_zero_equity_is_not_high_quality_roe_or_low_de():
    p=base_period();p['values']['equity']=-100;p['opening']['equity']=-50
    x=derived_metrics(p)
    assert 'roe' not in x and 'de' not in x
    r=build_review('TEST',{'sector':'Technology','bookValue':-1,'returnOnEquity':.5,'debtToEquity':-40,'priceToBook':-3},as_of=NOW)
    rows={v['key']:v for v in r['rows']}
    assert all(rows[k]['status']=='not_meaningful' for k in ('roe','de','price_book'))

def test_parser_keeps_filing_and_currency_coherent_and_does_not_use_quarter_as_fy():
    raw=doc({'Revenues':[observation(1000)],'NetIncomeLoss':[observation(100,accn='0000000001-26-000002')],
             'Assets':[observation(2000,start=None)],'OperatingIncomeLoss':[observation(40,start='2025-10-01')]})
    p=parse_statements(raw,1,'2026-09-13')['annual'][0]
    x=derived_metrics(p)
    assert 'net_margin' not in x and 'operating_margin' not in x
    with pytest.raises(ValueError):parse_statements(raw,99)

def test_parser_prefers_latest_filed_amendment_but_not_future_or_ambiguous_contexts():
    raw=doc({'Revenues':[observation(1000),observation(1100,accn='0000000001-26-000002',filed='2026-03-01',form='10-K/A'),observation(9999,filed='2027-01-01')]})
    assert parse_statements(raw,1,'2026-09-13')['annual'][0]['values']['revenue']==1100
    bad=doc({'Revenues':[observation(100),observation(110)]})
    result=parse_statements(bad,1,'2026-09-13')
    assert not result['annual'] and result['ambiguous_contexts_excluded']==1

def test_no_composite_from_different_currency_or_missing_opening_equity():
    raw=doc({'Revenues':[observation(1000)],'NetIncomeLoss':[observation(100)],'StockholdersEquity':[observation(500,start=None)]})
    raw['facts']['us-gaap']['Assets']={'units':{'EUR':[observation(300,start=None)]}}
    package=parse_statements(raw,1,'2026-09-13',currency='USD')
    x=derived_metrics(package['annual'][0])
    assert x['net_margin']['value']==10 and 'roe' not in x and 'roa' not in x

@pytest.mark.parametrize('raw',[True,float('nan'),float('inf'),'oops'])
def test_invalid_primary_value_never_gets_a_favorable_grade(raw):
    r=build_review('TEST',{'sector':'Technology','returnOnEquity':raw},as_of=NOW)
    row=next(x for x in r['rows'] if x['key']=='roe')
    assert row['value'] is None and row['grade']=='Not assessed'

def test_provider_scale_zero_loss_and_period_are_explicit():
    info={'sector':'Technology','debtToEquity':67.5,'returnOnEquity':.2,'totalDebt':0,'trailingEps':-2,'trailingPE':20,'financialCurrency':'EUR','currency':'USD'}
    old=deepcopy(info);r=build_review('TEST',info,as_of=NOW);x={v['key']:v for v in r['rows']}
    assert info==old and x['de']['value']==.675 and x['roe']['value']==20
    assert x['debt']['value']==0 and x['debt']['unit']=='EUR'
    assert x['trailing_pe']['status']=='not_meaningful'
    assert x['roic']['status']=='missing' and 'period' in x['roe']['basis']
    assert not r['complete']

def test_fund_has_no_corporate_rating_even_with_plausible_placeholders():
    r=build_review('AAAU',{'profitMargins':.3,'returnOnEquity':.4,'trailingPE':20},is_etf=True,as_of=NOW)
    assert all(x['status']=='not_applicable' for x in r['rows'])
    assert all(x['grade']=='Not assessed' for x in r['rows'])

def test_bank_liquidity_and_roic_guides_do_not_use_manufacturing_thresholds():
    info={'sector':'Financial Services','currentRatio':.7,'debtToEquity':600,'financialCurrency':'USD'}
    x={v['key']:v for v in build_review('BANK',info,as_of=NOW)['rows']}
    assert x['de']['grade']==x['current_ratio']['grade']=='Sector-specific review'

def test_fy_calculations_not_mixed_with_provider_estimates_or_claimed_ttm():
    reference={'financial_statements':{'method':METHOD,'annual':[base_period()]}}
    r=build_review('TEST',{'sector':'Technology','forwardPE':22,'totalRevenue':88888},reference,as_of=NOW)
    x={v['key']:v for v in r['rows']}
    assert x['revenue']['value']==1000 and x['revenue']['basis'].startswith('FY ')
    assert x['forward_pe']['value']==22 and 'estimate' in x['forward_pe']['basis']
    assert x['roic']['grade']=='Compare with WACC'
    r=build_review('TEST',{'sector':'Technology'},reference,as_of=NOW,wacc=10)
    assert next(v for v in r['rows'] if v['key']=='roic')['grade']=='Above WACC assumption'
    with pytest.raises(ValueError):build_review('TEST',{},wacc=101)

def test_currency_units_and_missing_format_do_not_invent_zero():
    assert format_value({'value':None,'status':'missing','unit':'USD'})=='Not reported'
    assert format_value({'value':1250000000,'status':'available','unit':'USD'})=='1.25B USD'
    assert format_value({'value':-10,'status':'available','unit':'%'})=='-10.00%'
