from copy import deepcopy
from company_research import build_review
from financial_statements import METHOD
from financial_review_validation import validate_review,expected_value


def test_reported_values_and_unit_conversion_reconcile_independently():
    r=build_review('TEST',{'sector':'Technology','returnOnEquity':.2,'debtToEquity':150,'trailingPE':20,'trailingEps':2,'totalDebt':0,'financialCurrency':'USD'},as_of='2026-09-13')
    result=validate_review(r)
    assert result['checked_values']>=5 and not result['errors']
    bad=deepcopy(r)
    next(v for v in bad['rows'] if v['key']=='de')['value']=150
    assert validate_review(bad)['errors'][0]['metric']=='de'


def test_derived_fiscal_values_are_independently_reconciled():
    p={'start':'2025-01-01','end':'2025-12-31','currency':'USD','filed':'2026-02-01','url':'https://www.sec.gov/filing','tags':{},
       'values':{'revenue':1000,'cost_of_revenue':600,'net_income':100,'equity':500,'assets':1000,'pretax_income':120,'interest_expense':20,'operating_income':150,'tax_expense':24,'ocf':160,'capex':40,'da':30,'debt_current':10,'debt_long':90,'debt_short':0,'cash':50},
       'opening':{'equity':400,'assets':900,'cash':40,'debt_current':10,'debt_long':80,'debt_short':0}}
    r=build_review('TEST',{'sector':'Technology'},{'financial_statements':{'method':METHOD,'annual':[p]}},as_of='2026-09-13')
    result=validate_review(r)
    assert result['checked_values']>=20 and not result['errors']


def test_missing_value_is_never_replaced_by_zero_to_pass_audit():
    r=build_review('TEST',{},as_of='2026-09-13')
    assert not validate_review(r)['errors']
    r['rows'][0]['value']=0
    assert validate_review(r)['errors']
