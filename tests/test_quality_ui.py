"""Real UI coverage with tiny, clearly isolated fixtures and no provider calls."""
import json
import os
import pytest


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1', reason='Requires real Streamlit AppTest')
def test_populated_quality_reports_and_short_history_explanations(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import dashboard_runtime as a
    monkeypatch.setattr(a.yf,'Ticker',lambda *args,**kwargs:pytest.fail('Unexpected provider call'))
    monkeypatch.setattr(a.yf,'download',lambda *args,**kwargs:pytest.fail('Unexpected provider call'))
    script='''
import pandas as pd
import numpy as np
import dashboard_runtime as a
from data_quality import make_quality
from quality_views import render_family_counts, render_symbol_quality, render_quality_report
cache=a.DashboardCache(PATH)
end=pd.Timestamp.now(tz='America/New_York').date()-pd.Timedelta(days=1)
prices=np.linspace(10,12,40)
history=pd.DataFrame({'Open':prices,'High':prices+1,'Low':prices-1,'Close':prices,'Volume':10000},index=pd.bdate_range(end=end,periods=40))
cache.save_history('AAPL',history,'2026-09-11T00:00:00Z')
info={'industry':'Consumer Electronics','currency':'USD','earningsGrowth':0}
cache.put('info:AAPL',info,{'fetched_at':'2026-09-11T00:00:00Z'})
cache.put('dividends:AAPL',{'records':[],'error':None,'coverage_start':'2025-01-01','coverage_end':'2026-09-10'},{'fetched_at':'2026-09-11T00:00:00Z'})
quality=make_quality(cache,['AAPL','SPY'],etfs=['SPY'])
cache.put('remote:quality',quality,{})
render_family_counts(cache)
render_symbol_quality('AAPL',cache,history,info)
render_quality_report(cache,pd.DataFrame())
'''.replace('PATH',json.dumps(str(tmp_path/'quality-ui.sqlite3')))
    at=AppTest.from_string(script,default_timeout=30).run()
    assert not at.exception,str(at.exception)
    assert any('พื้นฐาน 1/2' in x.value and 'ตรวจปันผลแล้ว 1/2' in x.value for x in at.caption)
    assert any(x.value=='รายงานความครบของข้อมูลทุกส่วน' for x in at.subheader)
    assert len(at.get('download_button'))==2
    diagnostic=at.dataframe[0].value
    assert diagnostic.loc[diagnostic['ส่วน'].eq('SMA200'),'สถานะ'].iloc[0]=='ประวัติไม่ยาวพอ'
    matrix=at.dataframe[1].value.set_index('ข้อมูล / ฟิลด์')
    assert matrix.loc['dividends','ตรวจแล้ว ไม่พบรายการในช่วงข้อมูล']==1
    assert matrix.loc['dividends','รอโหลดข้อมูล']==1
    assert matrix.loc['stock.earningsGrowth','มีข้อมูล']==1
    assert matrix.loc['stock.forwardPE','แหล่งข้อมูลไม่รายงาน']==1
