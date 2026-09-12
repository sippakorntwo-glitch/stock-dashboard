"""Regress the requested UI projection without deleting provenance or backend quality."""
from html.parser import HTMLParser
from pathlib import Path
import os
import pandas as pd
import pytest
from dashboard_help import table_html, PRESENTATION_ONLY_HIDDEN_COLUMNS
from ui_stability import page_receipt

class Cells(HTMLParser):
    def __init__(self):
        super().__init__();self.tag=None;self.headers=[];self.values=[];self.text=''
    def handle_starttag(self,tag,attrs):
        if tag in ('th','td'):self.tag=tag;self.text=''
    def handle_data(self,value):
        if self.tag:self.text+=value
    def handle_endtag(self,tag):
        if tag==self.tag:
            (self.headers if tag=='th' else self.values).append(self.text.strip());self.tag=None


def test_display_hides_only_diagnostic_columns_and_keeps_original_data():
    frame=pd.DataFrame([{'หมวด':'พื้นฐาน','เกณฑ์':'Forward P/E','ค่าปัจจุบัน':18.5,
                         'ได้':10,'เต็ม':10,'ผล':'เต็ม','ข้อมูลอ้างอิง':'Daily bars',
                         'แหล่งข้อมูล':'Yahoo Finance','ฟิลด์ต้นทาง':'forwardPE','สถานะข้อมูล':'มีข้อมูล'}])
    original=frame.copy(deep=True)
    parsed=Cells();output=table_html(frame);parsed.feed(output)
    assert parsed.headers==['หมวด','เกณฑ์','ค่าปัจจุบัน','ได้','เต็ม','ผล']
    assert {'18.5','10','เต็ม'}.issubset(parsed.values)
    assert not set(parsed.headers)&PRESENTATION_ONLY_HIDDEN_COLUMNS
    pd.testing.assert_frame_equal(frame,original)
    assert 'กำไรต่อหุ้นคาดการณ์' in output, 'Metric-name definitions must survive'


def test_profile_tooltip_uses_hidden_provider_key_and_missing_is_not_zero():
    frame=pd.DataFrame([{'มิติ':'Revenue growth','ค่า':None,'หน่วย':'%',
                         'สถานะข้อมูล':'แหล่งข้อมูลไม่รายงาน','ฟิลด์ต้นทาง':'revenueGrowth'}])
    html=table_html(frame);parsed=Cells();parsed.feed(html)
    assert parsed.headers==['มิติ','ค่า','หน่วย']
    assert '—' in parsed.values and '0' not in parsed.values
    assert 'การเติบโตของรายได้' in html
    assert frame.loc[0,'ฟิลด์ต้นทาง']=='revenueGrowth'


def test_removed_metadata_never_reappears_as_visible_column_or_injected_html():
    frame=pd.DataFrame({'เกณฑ์':['<script>name</script>'],'ค่า':['<img src=x onerror=alert(1)>'],
                        'แหล่งข้อมูล':['<script>provider</script>']})
    html=table_html(frame);parsed=Cells();parsed.feed(html)
    assert parsed.headers==['เกณฑ์','ค่า']
    assert '<script>' not in html and '<img ' not in html
    assert '&lt;img ' in html and '&lt;script&gt;name' in html


def test_receipt_supports_backend_readiness_without_a_visible_status_panel():
    markup=page_receipt('v24','QQQI','',1.2,generation='generations/abc" onmouseover="bad')
    assert 'data-generation="generations/abc&quot;' in markup
    assert '">bad' not in markup
    assert markup.endswith('></span>')


def test_public_entrypoint_keeps_refresh_and_errors_but_no_diagnostic_render_calls():
    source=Path('dashboard_ui.py').read_text()
    for text in ('health(reader,frame,cache)','render_family_counts(cache)',
                 'render_symbol_quality(ticker,cache,history,info)',"key='research_health'"):
        assert text not in source
    assert '_poll_data(reader,revision,worker_revision,chart_revision)' in source
    assert 'if cache.error: st.warning(' in source
    assert 'def render_quality_report(' in Path('quality_views.py').read_text()
    assert 'def make_quality(' in Path('data_quality.py').read_text()


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit AppTest')
def test_top_industry_multiselect_combines_with_search_and_clears_without_losing_selection():
    from streamlit.testing.v1 import AppTest
    script='''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
st.session_state.setdefault('selected_ticker','AAPL')
f=pd.DataFrame([
 {'Ticker':'AAPL','Security_Name':'Apple fixture','Asset_Type':'Common Stock','Status':'PASS','Industry':'Consumer Electronics','Close':100.},
 {'Ticker':'QQQI','Security_Name':'Income fixture','Asset_Type':'ETF','Status':'PASS','Industry':'Derivative Income','Close':50.},
 {'Ticker':'SPY','Security_Name':'Index fixture','Asset_Type':'ETF','Status':'FAIL','Industry':'Large Blend','Close':500.},
 {'Ticker':'NEW','Security_Name':'Missing fixture','Asset_Type':'ETF','Status':'FAIL','Industry':None,'Close':None}])
w=filter_universe(f)
if w is not None:st.dataframe(w)
'''
    at=AppTest.from_string(script,default_timeout=20).run()
    assert not at.exception,str(at.exception)
    dropdown=at.multiselect(key='screen_cat_Industry')
    assert dropdown.label=='Industry / ETF Category' and dropdown.value==[]
    assert 'None' not in dropdown.options
    assert all(not any(w.key=='screen_cat_Industry' for w in exp.multiselect) for exp in at.expander)
    at.multiselect(key='screen_cat_Industry').set_value(['Derivative Income','Large Blend']).run()
    assert at.dataframe[0].value.Ticker.tolist()==['QQQI','SPY']
    at.selectbox(key='screen_asset').set_value('ETF').run()
    at.text_input(key='stock_search').set_value('QQQI').run()
    assert at.dataframe[0].value.Ticker.tolist()==['QQQI']
    at.text_input(key='stock_search').set_value('AAPL').run()
    assert at.dataframe[0].value.empty
    assert at.session_state['selected_ticker']=='AAPL'
    at.button(key='reset_screener').click().run()
    assert not at.exception,str(at.exception)
    assert len(at.dataframe[0].value)==4
    assert at.multiselect(key='screen_cat_Industry').value==[]
    assert at.text_input(key='stock_search').label=='Search Ticker / Company'
    assert at.session_state['selected_ticker']=='AAPL'
