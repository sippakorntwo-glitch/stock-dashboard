"""Actual Streamlit table config and CSV, with isolated deterministic fixtures."""
import json
import os
import pytest


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit AppTest')
def test_eight_english_headers_and_numeric_selection_table(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from return_periods import RETURN_FIELDS,RETURN_LABELS
    import dashboard_runtime as a
    cache=a.DashboardCache(tmp_path/'ui.sqlite3')
    monkeypatch.setattr(a,'get_data_cache',lambda:cache)
    monkeypatch.setattr(a.yf,'Ticker',lambda *args,**kwargs:pytest.fail('No provider in UI fixture'))
    monkeypatch.setattr(a.yf,'download',lambda *args,**kwargs:pytest.fail('No provider in UI fixture'))
    script='''
import pandas as pd
import streamlit as st
from dashboard_views import overview
from return_periods import RETURN_FIELDS
row={'Ticker':'AAPL','Security_Name':'Fixture only','Industry':'Technology','Asset_Type':'Common Stock','Status':'PASS','Close':100,'RSI_14':50,'Price_AsOf':'2026-09-10','Data_Status':'fixture'}
row.update({field:1.25 for field in RETURN_FIELDS})
frame=pd.DataFrame([row])
overview(frame,selectable=True,prepared=frame)
'''
    at=AppTest.from_string(script,default_timeout=30).run()
    assert not at.exception,str(at.exception)
    data=at.dataframe[0]
    assert tuple(data.value.columns[7:15])==RETURN_FIELDS
    assert data.value.columns[6]=='Price_AsOf'
    config=json.loads(data.proto.columns)
    assert config['Price_AsOf']['label']=='Price As Of'
    for field,label in RETURN_LABELS.items():
        assert config[field]['label']==label
        assert config[field]['type_config']['format']=='%+.2f%%'
        assert 'cumulative adjusted return' in config[field]['help']
    assert any('Adjusted-close returns' in cap.value for cap in at.caption)
    assert len(at.get('download_button'))==1
