"""No live market requests; exercise rendering and immutable slot allocation."""
import ast
import json
import os
from pathlib import Path
import pytest


def test_chart_slots_are_allocated_before_dynamic_work():
    tree=ast.parse(Path('chart_ranges.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_chart')
    slots={}
    for i,node in enumerate(function.body):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call):
            if isinstance(node.value.func,ast.Attribute) and node.value.func.attr in ('container','empty'):
                slots[node.targets[0].id]=(i,node.value.func.attr)
    assert {k:v[1] for k,v in slots.items()}=={'controls':'container','notices':'container','chart_slot':'empty','commentary_slot':'empty'}
    protected=next(n for n in function.body if isinstance(n,ast.Try))
    assert all(i<function.body.index(protected) for i,_ in slots.values())
    markdown=[n for n in ast.walk(protected) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='markdown']
    assert len(markdown)==1 and isinstance(markdown[0].func.value,ast.Name) and markdown[0].func.value.id=='commentary_slot'
    assert all(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='empty'
                   and isinstance(n.func.value,ast.Name) and n.func.value.id==slot for n in ast.walk(protected.handlers[0]))
               for slot in ('chart_slot','commentary_slot'))


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires actual Streamlit')
def test_period_changes_replace_summary_even_when_loading_notice_changes(monkeypatch):
    import numpy as np
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    import chart_ranges as charts
    from html import unescape
    import re
    def frame(index):
        close=np.linspace(100.,130.,len(index))
        return pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1000.},index=index)
    daily=frame(pd.bdate_range(end='2026-09-11',periods=400))
    intraday=frame(pd.DatetimeIndex([t for day in ('2026-09-09','2026-09-10','2026-09-11')
                                  for t in pd.date_range(day+' 09:30',periods=78,freq='5min',tz='America/New_York')]))
    meta={'fetched_at':'2026-09-12T10:00:00+00:00'}
    class Cache:
        missing=False
        def history(self,ticker,interval='1d'):
            return (None,{}) if self.missing else (intraday if interval=='5m' else daily,meta)
    cache=Cache()
    class Service:
        calls=0
        def read(self,*args):return (None,{}) if cache.missing else (intraday,meta)
        def request(self,*args):
            self.calls+=1
            return 'กำลังโหลดประวัติกราฟที่เลือก' if self.calls%2 else ''
    service=Service()
    monkeypatch.setattr(charts,'get_chart_service',lambda:service)
    monkeypatch.setattr(charts.a,'get_data_cache',lambda:cache)
    monkeypatch.setattr(charts,'chart_requests_enabled',lambda:True)
    at=AppTest.from_string("import streamlit as st\nfrom chart_ranges import render_chart\nst.session_state['selected_ticker']='SPY'\nrender_chart('SPY',None)",default_timeout=20).run()
    for period in ('1 วัน','3 วัน','1 วัน','3 วัน','1 ปี'):
        at.radio(key='chart_period').set_value(period).run()
        assert not at.exception,str(at.exception)
        cards=[m.value for m in at.markdown if '<section class="chart-reading"' in m.value]
        assert len(cards)==1
        report=json.loads(unescape(re.search(r'data-report="([^"]+)"',cards[0]).group(1)))
        assert report['ticker']=='SPY' and report['period']==period
    cache.missing=True
    at.run()
    assert not at.exception,str(at.exception)
    assert not any('<section class="chart-reading"' in m.value for m in at.markdown)
