"""A contradicted reported zero is neither a measured zero nor ordinary missing data."""
from copy import deepcopy
import os
import pandas as pd
import pytest
from screening import dividend_yield_observation, profile_rows, enrich_frame, filter_frame


def history(date='2026-08-19',cash=.652):
    return {'records':[{'Ex_Date':date,'Dividend_Per_Share':cash}],
            'coverage_start':'2026-08-01','coverage_end':'2026-09-11','error':''}


def test_zero_yield_conflict_uses_actual_profile_year_without_replacement_or_mutation():
    info={'trailingAnnualDividendYield':0.,'dividendYield':.15}
    events=history()
    before=deepcopy((info,events))
    result=dividend_yield_observation(info,'2026-09-11T20:27:08+00:00',events)
    assert result=={'value':None,'state':'source_disagreement','conflict_date':'2026-08-19'}
    assert (info,events)==before
    # Partial-year cash history establishes an unreconciled definition without
    # classifying cash components or supporting a replacement yield calculation.
    assert events['coverage_start']=='2026-08-01'
    assert dividend_yield_observation({'trailingAnnualDividendYield':.025},
        '2026-09-11T20:27:08+00:00',events)['value']==2.5


def test_future_old_boundary_undated_and_invalid_cash_cannot_disprove_zero():
    info={'trailingAnnualDividendYield':0.}
    for date in ('2026-09-12','2025-09-11','2025-08-01',None,'bad-date'):
        result=dividend_yield_observation(info,'2026-09-11T20:00:00+00:00',history(date))
        assert result['state']=='available' and result['value']==0.,date
    for timestamp in (None,'','not-a-date','2026-09-11'):
        assert dividend_yield_observation(info,timestamp,history())['state']=='available'
    for cash in (None,0.,-.2,float('inf'),True,'invalid'):
        assert dividend_yield_observation(info,'2026-09-11T20:00:00+00:00',history(cash=cash))['state']=='available'
    # September 12 UTC is still September 11 at the US exchange: September 12
    # events are future observations relative to this profile.
    assert dividend_yield_observation(info,'2026-09-12T00:10:00+00:00',history('2026-09-12'))['state']=='available'
    error=history();error['error']='Unavailable'
    assert dividend_yield_observation(info,'2026-09-11T20:00:00+00:00',error)['state']=='available'


def test_missing_yield_is_distinct_from_malformed_or_negative_source():
    for raw in (None,'','N/A'):
        assert dividend_yield_observation({'trailingAnnualDividendYield':raw},None)['state']=='not_reported'
    for raw in (-.1,float('inf'),float('nan'),True,'bad'):
        result=dividend_yield_observation({'trailingAnnualDividendYield':raw},None)
        assert result['state']=='invalid_source' and result['value'] is None


def test_profile_projection_keeps_conflict_state_and_never_admits_it_as_missing(tmp_path):
    import dashboard_runtime as a
    cache=a.DashboardCache(tmp_path/'yield-source.sqlite3')
    tickers=['FUND','COMPANY','MISSING','ZERO','INVALID']
    for ticker in tickers:
        raw=None if ticker=='MISSING' else -.1 if ticker=='INVALID' else 0.
        cache.put('info:'+ticker,{'quoteType':'ETF' if ticker=='FUND' else 'EQUITY',
            'trailingAnnualDividendYield':raw},{'fetched_at':'2026-09-11T20:00:00+00:00'})
        if ticker in ('FUND','COMPANY'):cache.put('dividends:'+ticker,history(),{})
    profiles=profile_rows(cache,tickers)
    for ticker in ('FUND','COMPANY'):
        assert profiles[ticker]['Dividend_Yield'] is None
        assert profiles[ticker]['Dividend_Yield_State']=='source_disagreement'
        assert cache.get('info:'+ticker,request_remote=False)[0]['trailingAnnualDividendYield']==0.
    frame=enrich_frame(pd.DataFrame({'Ticker':tickers,'Asset_Type':['ETF',*['Common Stock']*4]}),profiles)
    assert filter_frame(frame,bounds={'Dividend_Yield':(0.,None)}).Ticker.tolist()==['ZERO']
    assert filter_frame(frame,bounds={'Dividend_Yield':(0.,None)},include_missing=True).Ticker.tolist()==['MISSING','ZERO']
    assert filter_frame(frame,bounds={'Dividend_Yield':(None,None)},include_missing=True).Ticker.tolist()==tickers
    # The explicit state also protects against a stale retained numeric value.
    frame.loc[frame.Ticker.eq('FUND'),'Dividend_Yield']=0.
    assert 'FUND' not in filter_frame(frame,bounds={'Dividend_Yield':(0.,None)},include_missing=True).Ticker.tolist()


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit')
def test_yield_controls_explain_source_disagreement_and_usable_count():
    from streamlit.testing.v1 import AppTest
    script='''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
f=pd.DataFrame([
 {'Ticker':'CONFLICT','Asset_Type':'ETF','Dividend_Yield':None,'Dividend_Yield_State':'source_disagreement'},
 {'Ticker':'MISSING','Asset_Type':'Common Stock','Dividend_Yield':None,'Dividend_Yield_State':'not_reported'},
 {'Ticker':'ZERO','Asset_Type':'Common Stock','Dividend_Yield':0.,'Dividend_Yield_State':'available'}])
w=filter_universe(f)
if w is not None:st.dataframe(w)
'''
    at=AppTest.from_string(script,default_timeout=20).run()
    at.multiselect(key='screen_metrics_price').set_value(['Dividend_Yield']).run()
    assert any('ยังยืนยันนิยามให้ตรงกันไม่ได้' in item.value for item in at.warning)
    assert any('มีค่าที่ใช้กรองได้ 1 / 3' in item.value for item in at.caption)
    at.number_input(key='screen_min_Dividend_Yield').set_value(0.).run()
    at.checkbox(key='screen_missing').check().run()
    assert not at.exception,str(at.exception)
    assert at.dataframe[0].value.Ticker.tolist()==['MISSING','ZERO']
    assert any('อัตราปันผลที่แหล่งข้อมูลขัดแย้ง / ไม่ถูกต้อง: ไม่ผ่านเสมอ' in item.value for item in at.markdown)


def test_published_quality_and_financial_audits_share_display_withholding(tmp_path):
    from dashboard_runtime import DashboardCache
    from data_quality import make_quality
    from company_financials_job import audit_all
    cache=DashboardCache(tmp_path/'yield-audit.sqlite3')
    info={'quoteType':'EQUITY','financialCurrency':'USD','trailingAnnualDividendYield':0.}
    stamp='2026-09-11T20:27:08Z'
    cache.put('info:TEST',info,{'fetched_at':stamp})
    cache.put('dividends:TEST',history(),{'fetched_at':stamp})
    quality=make_quality(cache,('TEST',),etfs=set())
    audit,rows=audit_all(cache,('TEST',),set())
    assert quality['columns']['company.dividendYield']=={'invalid':1}
    assert audit['field_counts']['dividendYield']=={'invalid':1}
    assert 'dividendYield' in rows[0]['Invalid Source Metrics']
    assert cache.get('info:TEST',request_remote=False)[0]==info
