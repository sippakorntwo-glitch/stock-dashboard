import html
import json
import os
import re
import pandas as pd
import pytest


def applied(at):
    markup=next(m.value for m in at.markdown if 'class="screener-ready"' in m.value)
    return json.loads(html.unescape(re.search(r'data-controls="([^"]*)"',markup).group(1)))


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit AppTest')
def test_combined_controls_report_only_the_completed_filter_state():
    from streamlit.testing.v1 import AppTest
    script='''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
f=pd.DataFrame([
 {'Ticker':'TESTA','Asset_Type':'Common Stock','Security_Name':'Fixture A','Industry':'Software','Status':'PASS','Close':100.,'Return_1M':5.},
 {'Ticker':'TESTB','Asset_Type':'ETF','Security_Name':'Fixture B','Industry':'Derivative Income','Status':'FAIL','Close':50.,'Return_1M':2.},
 {'Ticker':'TESTC','Asset_Type':'ETF','Security_Name':'Fixture C','Industry':'Derivative Income','Status':'FAIL','Close':40.,'Return_1M':-1.},
])
r=filter_universe(f)
if r is not None:st.dataframe(r)
'''
    at=AppTest.from_string(script,default_timeout=20).run()
    assert not at.exception,str(at.exception)
    assert len(at.dataframe[0].value)==3
    at.selectbox(key='screen_asset').set_value('ETF').run()
    at.multiselect(key='screen_cat_Industry').set_value(['Derivative Income']).run()
    assert not at.exception,str(at.exception)
    assert at.dataframe[0].value.Ticker.tolist()==['TESTB','TESTC']
    assert applied(at)['Asset Type']=='ETF'
    assert applied(at)['Industry / ETF Category']==['Derivative Income']
    at.multiselect(key='screen_periods').set_value(['Return_1M']).run()
    at.number_input(key='screen_min_Return_1M').set_value(0.0).run()
    assert at.dataframe[0].value.Ticker.tolist()==['TESTB']
    assert applied(at)['Minimum 1 Month (%)']==0
    at.button(key='reset_screener').click().run()
    assert not at.exception,str(at.exception)
    assert len(at.dataframe[0].value)==3
    assert applied(at)['Asset Type']=='All'
    assert applied(at)['Industry / ETF Category']==[]
    assert not any(k.startswith('Minimum ') for k in applied(at))


def test_old_metadata_is_not_starved_by_recent_partial_classification():
    from data_quality import metadata_jobs
    now=pd.Timestamp('2026-09-11T20:00:00Z').timestamp()
    meta={'info:RECENT':{'fetched_at':'2026-09-09T20:00:00Z','classification_available':False},
          'info:OLD':{'fetched_at':'2026-08-01T20:00:00Z','classification_available':True}}
    jobs=metadata_jobs(['RECENT','OLD','MISSING','SPY'],meta,['SPY'],now,mode='daily')
    stock_profiles=[t for k,t in jobs if k=='info' and t!='SPY']
    assert stock_profiles==['MISSING','OLD','RECENT']
    assert jobs[1]==('info','SPY')
    assert len(jobs)==len(set(jobs))==8


def test_failed_history_is_not_mislabeled_as_an_unattempted_metric(tmp_path):
    import dashboard_runtime as a
    from data_quality import make_quality
    cache=a.DashboardCache(tmp_path/'history-failure.sqlite3')
    cache.put('attempt:history:TEST',{'success':False},{'success':False,'fetched_at':'2026-09-11T20:00:00Z'})
    report=make_quality(cache,['TEST'])
    assert report['columns']['history']=={'failed':1}
    assert report['columns']['price.Close']=={'failed':1}
    assert report['symbols']['TEST']['missing_metrics']['Return_1D']=='failed'
