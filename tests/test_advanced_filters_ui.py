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


def test_presets_editable_ranges_applicability_receipt_and_reset_preserve_workspace():
    from streamlit.testing.v1 import AppTest
    from test_applied_filters import applied
    script='''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
st.session_state.setdefault('selected_ticker','QQQI')
st.session_state.setdefault('chart_range','5 Years')
st.session_state.setdefault('favourites',['QQQI'])
f=pd.DataFrame([
 {'Ticker':'A','Asset_Type':'Common Stock','Status':'PASS','Industry':'Software','Close':100.,'Revenue_Growth':5.,'Profit_Margin':20.,'ROE':15.},
 {'Ticker':'B','Asset_Type':'Common Stock','Status':'FAIL','Industry':'Software','Close':20.,'Revenue_Growth':None,'Profit_Margin':None,'ROE':None},
 {'Ticker':'QQQI','Asset_Type':'ETF','Status':'PASS','Industry':'Derivative Income','Close':50.,'Revenue_Growth':None,'Profit_Margin':None,'ROE':None}])
w=filter_universe(f)
if w is not None:st.dataframe(w)
'''
    at=AppTest.from_string(script,default_timeout=20).run()
    at.selectbox(key='screen_preset').set_value('profit').run()
    at.button(key='apply_screener_preset').click().run()
    assert not at.exception,str(at.exception)
    assert at.dataframe[0].value.Ticker.tolist()==['A']
    assert at.number_input(key='screen_min_Profit_Margin').value==10.
    assert applied(at)['Company Filters Active'] is True
    at.selectbox(key='screen_asset').set_value('All').run()
    at.checkbox(key='screen_missing').check().run()
    assert at.dataframe[0].value.Ticker.tolist()==['A','B']
    assert applied(at)['Include Missing Values'] is True
    assert 'รวมไว้โดยยังไม่ยืนยันเกณฑ์นั้น' in next(m.value for m in at.markdown if 'screener-summary' in m.value)
    at.number_input(key='screen_min_Profit_Margin').set_value(30.).run()
    assert at.dataframe[0].value.Ticker.tolist()==['B']
    at.number_input(key='screen_max_Profit_Margin').set_value(10.).run()
    assert len(at.dataframe)==0
    assert any('ค่าต่ำสุดต้องไม่มากกว่า' in warning.value for warning in at.warning)
    assert not any(any(button.key=='reset_screener' for button in exp.button) for exp in at.expander)
    at.button(key='reset_screener').click().run()
    assert len(at.dataframe[0].value)==3
    assert at.session_state['selected_ticker']=='QQQI' and at.session_state['chart_range']=='5 Years'
    assert at.session_state['favourites']==['QQQI']
    assert applied(at)['Company Filters Active'] is False
    assert not applied(at)['Include Missing Values']
    assert at.selectbox(key='screen_return_mode').value=='Cumulative (Adjusted Close)'


def test_complete_summary_reports_quality_and_technical_conditions():
    from streamlit.testing.v1 import AppTest
    from test_applied_filters import applied
    script='''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
f=pd.DataFrame([{'Ticker':'A','Asset_Type':'Common Stock','Industry':'Software','Status':'PASS',
 'Close':100.,'SMA200':80.,'Price_AsOf':pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d'),
 'Profile_AsOf':pd.Timestamp.now(tz='UTC').isoformat(),'Historical_Return':10.}])
w=filter_universe(f)
if w is not None:st.dataframe(w)
'''
    at=AppTest.from_string(script,default_timeout=20).run()
    at.checkbox(key='screen_fresh').check().run()
    at.checkbox(key='screen_profile_fresh').check().run()
    at.checkbox(key='screen_above_sma').check().run()
    at.multiselect(key='screen_required').set_value(['Historical_Return']).run()
    receipt=applied(at)
    assert receipt['Maximum Price Age']==4 and receipt['Maximum Profile Age']==14
    assert receipt['Price Above SMA200'] is True
    assert receipt['Require Available Return Periods']==['1 Year (%)']
    summary=next(m.value for m in at.markdown if 'screener-summary' in m.value)
    assert 'อายุข้อมูลราคา ≤ 4 วัน' in summary and 'SMA200' in summary
    assert 'ต้องมีผลตอบแทน: 1 Year (%)' in summary
    at.button(key='reset_screener').click().run()
    receipt=applied(at)
    assert 'Maximum Price Age' not in receipt and 'Maximum Profile Age' not in receipt
    assert receipt['Require Available Return Periods']==[] and receipt['Price Above SMA200'] is False
