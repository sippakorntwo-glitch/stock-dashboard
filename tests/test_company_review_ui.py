from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import ast
import json
import os
from pathlib import Path
import pytest
from company_research import build_review
from company_research_ui import review_html,export_frame
from company_metrics import METRICS,GROUPS


class AuditHTML(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.abbr=[];self.groups=[];self.headers=[];self.tag=None
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=='tr' and 'data-observation' in data:self.rows.append(json.loads(data['data-observation']))
        if tag=='abbr':self.abbr.append(data)
        if tag=='section':self.groups.append(data.get('data-financial-group'))
        self.tag=tag
    def handle_data(self,data):
        if self.tag=='th':self.headers.append(data)


def test_full_html_has_every_metric_and_only_name_tooltips():
    review=build_review('AAPL',{'sector':'Technology','returnOnEquity':.2,'debtToEquity':67.5},as_of='2026-09-13')
    before=deepcopy(review);html=review_html(review);parser=AuditHTML();parser.feed(html)
    assert review==before
    assert len(parser.rows)==len(parser.abbr)==len(METRICS)
    assert parser.groups==list(GROUPS)
    assert all(len(t['title'])>100 and t['tabindex']=='0' for t in parser.abbr)
    assert set(parser.headers)=={'Metric','Current Value','Reference / Screening Guide','Assessment / Interpretation','Period / Basis'}
    assert all('แหล่งข้อมูล'!=h and 'สถานะข้อมูล'!=h for h in parser.headers)
    assert 'data-tooltip-column="0"' in html
    assert 'Metric definitions, formulas and evidence' in html


def test_export_keeps_raw_numbers_units_and_missing_not_zero():
    review=build_review('TEST',{'sector':'Technology','returnOnEquity':.2,'totalDebt':0,'currency':'USD','financialCurrency':'USD'},as_of='2026-09-13')
    frame=export_frame(review).set_index('Metric')
    assert len(frame)==len(METRICS)
    assert frame.loc['ROE','Value']==20 and frame.loc['ROE','Unit']=='%'
    assert frame.loc['Interest-bearing Debt','Value']==0
    assert frame.loc['ROIC','Availability']=='missing'
    assert 'Definition' in frame and frame['Definition'].str.len().min()>20


def test_html_source_and_user_strings_are_escaped_not_executable():
    review=build_review('X<script>alert(1)</script>',{'sector':'Technology','returnOnEquity':.2},as_of='2026-09-13')
    review['rows'][0]['source']='<img src=x onerror=alert(1)>'
    html=review_html(review)
    assert '<script>' not in html and '<img ' not in html
    assert '&lt;script&gt;' in html and '&lt;img ' in html


def test_company_review_does_not_request_prices_or_modify_scoring():
    text=Path('company_research_ui.py').read_text();tree=ast.parse(text)
    imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert not any(getattr(n,'module','') in ('requests','yfinance','ranking_policy') for n in imports)
    views=Path('dashboard_views.py').read_text()
    assert 'render_company_review(ticker,info,a.get_data_cache())' in views
    assert views.count('render_company_review(ticker,info,a.get_data_cache())')==1
    assert "analysis.loc[~analysis['หมวด'].eq('พื้นฐาน')]" in views
    assert 'criteria_score(ctx,info,is_etf)' in views


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Needs real Streamlit')
def test_real_company_review_renders_without_live_calls_and_accepts_optional_wacc():
    from streamlit.testing.v1 import AppTest
    script='''
from company_research_ui import render_company_review
class Cache:
    def get(self,key,request_remote=False):
        assert request_remote is False
        return ({},{'fetched_at':'2026-09-13T10:00:00Z'})
render_company_review('TEST',{'sector':'Technology','returnOnEquity':.2,'debtToEquity':67.5},Cache())
'''
    at=AppTest.from_string(script,default_timeout=15).run()
    assert not at.exception,str(at.exception)
    assert any(e.value=='Company Financial Review' for e in at.subheader)
    assert at.number_input(key='company_wacc_TEST').value is None
    at.number_input(key='company_wacc_TEST').set_value(10.).run()
    assert not at.exception,str(at.exception)
