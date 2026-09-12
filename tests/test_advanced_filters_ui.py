"""Real UI controls with deterministic test-only prices; providers forbidden."""
import os
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit')


def test_filter_widgets_apply_and_reset_without_changing_selected_stock(monkeypatch):
    import dashboard_runtime as a
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(a.yf,'download',lambda *args,**kwargs:pytest.fail('Unexpected network'))
    monkeypatch.setattr(a.yf,'Ticker',lambda *args,**kwargs:pytest.fail('Unexpected network'))
    script='''
import streamlit as st
import pandas as pd
from filters_ui import filter_universe
st.session_state.setdefault('selected_ticker','AAPL')
f=pd.DataFrame([
 {'Ticker':'AAPL','Security_Name':'Apple fixture','Industry':'Consumer Electronics','Asset_Type':'Common Stock','Status':'PASS','Close':100.,'RSI_14':55.,'Return_1D':1.,'Price_AsOf':'2026-09-10'},
 {'Ticker':'QQQI','Security_Name':'Fund fixture','Industry':'Derivative Income','Asset_Type':'ETF','Status':'PASS','Close':50.,'RSI_14':50.,'Return_1D':0.,'Price_AsOf':'2026-09-10'},
 {'Ticker':'SPY','Security_Name':'Index fixture','Industry':'Large Blend','Asset_Type':'ETF','Status':'FAIL','Close':500.,'RSI_14':45.,'Return_1D':-1.,'Price_AsOf':'2026-09-10'}])
w=filter_universe(f)
if w is not None: st.dataframe(w,hide_index=True)
st.write('Selected stock remains '+st.session_state['selected_ticker'])
'''
    at=AppTest.from_string(script,default_timeout=30).run()
    assert not at.exception,str(at.exception)
    assert len(at.dataframe[0].value)==3
    at.selectbox(key='screen_asset').select('ETF').run()
    assert len(at.dataframe[0].value)==2
    at.multiselect(key='screen_cat_Industry').set_value(['Derivative Income']).run()
    assert at.dataframe[0].value.Ticker.tolist()==['QQQI']
    at.multiselect(key='screen_periods').set_value(['Return_1D']).run()
    at.number_input(key='screen_min_Return_1D').set_value(0.).run()
    assert at.dataframe[0].value.Ticker.tolist()==['QQQI']
    at.number_input(key='screen_min_Return_1D').set_value(2.).run()
    assert len(at.dataframe[0].value)==0
    at.button(key='reset_screener').click().run()
    assert len(at.dataframe[0].value)==3 and at.session_state['selected_ticker']=='AAPL'
    assert not at.exception,str(at.exception)
