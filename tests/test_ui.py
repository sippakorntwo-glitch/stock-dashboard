"""Real Streamlit single-page integration; provider calls are prohibited here."""
import os
from unittest.mock import patch
import numpy as np
import pytest


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Real Streamlit AppTest is unavailable in the offline build container')
def test_single_page_selection_and_all_sections_without_provider_calls(tmp_path):
    from streamlit.testing.v1 import AppTest
    import dashboard_runtime as a
    from test_analytics import frame
    cache=a.DashboardCache(tmp_path/'ui.sqlite3')
    for ticker in ['AAPL','MSFT','SPY','QQQ']:
        cache.save_history(ticker,frame(np.linspace(100,200,800)),'2026-09-10T00:00:00Z')
        cache.put('info:'+ticker,{'shortName':ticker+' Test','industry':'Technology','quoteType':'ETF' if ticker in ('SPY','QQQ') else 'EQUITY','_Fetched_At_UTC':'2026-09-10T00:00:00Z'},{})
        cache.put('dividends:'+ticker,{'records':[],'error':None,'fetched_at':'2026-09-10T00:00:00Z','coverage_start':'2020-01-01','coverage_end':'2026-09-09'},{})
    class Reader:
        def refresh(self,force=False):pass
        def request(self,ticker):pass
        def status(self):return {'busy':False,'revision':0,'error':'','manifest':{'generation':'test','published_at':'2026-09-10T00:00:00Z'}}
    script='''
import streamlit as st
from dashboard_selection import apply_table_selection
command=st.session_state.pop('_test_selection',None)
if command:
    st.session_state['test_table']=command['event']
    apply_table_selection(st.session_state,'test_table',command['tickers'])
from dashboard_ui import main
main()
'''
    with patch.object(a,'get_data_cache',return_value=cache),patch.object(a.core,'get_data_cache',return_value=cache),patch.object(a,'get_remote_reader',return_value=(Reader(),'')),patch.object(a,'get_updater',return_value=a.ReadOnlyUpdater()),patch.object(a.yf,'download',side_effect=AssertionError('Unexpected provider call')),patch.object(a.yf,'Ticker',side_effect=AssertionError('Unexpected provider call')):
        at=AppTest.from_string(script,default_timeout=40).run()
        assert not at.exception,str(at.exception)
        assert at.metric[0].value=='4,900'
        assert len(at.sidebar.radio)==0
        for title in ['กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว']:
            assert title in [h.value for h in at.header]
        assert 'สถานะข้อมูลและระบบ' in [h.value for h in at.subheader]
        assert len(at.get('plotly_chart'))>=3
        at.radio(key='chart_period').set_value('3 ปี').run()
        at.session_state['_test_selection']={'tickers':['AAPL','MSFT'],'event':{'selection':{'rows':[],'cells':[(1,'Ticker')]}}}
        at.run()
        assert not at.exception,str(at.exception)
        assert at.sidebar.text_input(key='ticker_input').value=='MSFT'
        assert at.multiselect(key='comparison_symbols').value==['MSFT','SPY']
        assert at.radio(key='chart_period').value=='3 ปี'
        assert any(h.value.startswith('MSFT ·') for h in at.subheader)
        # Filtering must not silently change the selected stock.
        at.text_input(key='stock_search').set_value('NO-MATCH-IN-CATALOG').run()
        assert not at.exception,str(at.exception)
        assert at.session_state['selected_ticker']=='MSFT'
        assert at.dataframe[0].value.empty
        at.sidebar.text_input(key='ticker_input').set_value('spy').run()
        assert not at.exception,str(at.exception)
        assert at.multiselect(key='comparison_symbols').value==['SPY','QQQ']
        at.sidebar.text_input(key='ticker_input').set_value('!').run()
        assert not at.exception,str(at.exception)
        assert any('Ticker ให้ถูกต้อง' in w.value for w in at.warning)
        at.sidebar.text_input(key='ticker_input').set_value('UNKNOWN123').run()
        assert not at.exception,str(at.exception)
        assert any('ยังไม่มีประวัติ' in i.value for i in at.info)
