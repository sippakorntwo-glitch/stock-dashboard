from company_research import build_review
from financial_statements import parse_statements,METHOD
import pytest


def test_negative_de_without_book_value_is_not_favorable_low_leverage():
    r=build_review('TEST',{'sector':'Industrials','debtToEquity':-70},as_of='2026-09-13')
    row=next(x for x in r['rows'] if x['key']=='de')
    assert row['value'] is None and row['status']=='not_meaningful'
    assert row['grade']=='Not assessed'


def test_future_filing_does_not_enter_a_historical_asof_review():
    p={'start':'2025-01-01','end':'2025-12-31','filed':'2026-03-01','currency':'USD',
       'values':{'revenue':1000},'opening':{},'tags':{},'url':'https://www.sec.gov/example'}
    r=build_review('TEST',{'sector':'Technology'},{'financial_statements':{'method':METHOD,'annual':[p]}},as_of='2026-02-01')
    assert r['fiscal_period'] is None
    assert next(x for x in r['rows'] if x['key']=='revenue')['status']=='missing'


def test_reit_payout_is_not_declared_good_by_generic_earnings_coverage():
    r=build_review('TEST',{'sector':'Real Estate','industry':'REIT - Retail','payoutRatio':.5,'trailingEps':2},as_of='2026-09-13')
    row=next(x for x in r['rows'] if x['key']=='payout')
    assert row['value']==50 and row['grade']=='Sector-specific review'


def test_bool_document_cik_is_not_a_verified_numeric_identity():
    with pytest.raises(ValueError):parse_statements({'cik':True},1)
