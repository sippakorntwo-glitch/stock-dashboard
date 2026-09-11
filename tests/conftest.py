"""Explicitly gated import stubs for offline testing; never enabled in CI."""
import os
import sys
import types
import pytest
from functools import lru_cache
if os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1':
    def cache(fn=None, **kwargs):
        def wrap(f):
            obj=lru_cache(maxsize=8)(f);obj.clear=obj.cache_clear;return obj
        return wrap(fn) if fn else wrap
    st=types.ModuleType('streamlit');st.cache_data=st.cache_resource=cache;st.secrets={}
    st.components=types.ModuleType('streamlit.components');st.components.v1=types.ModuleType('streamlit.components.v1')
    st.components.v1.html=lambda *args,**kwargs:None
    sys.modules.update({'streamlit':st,'streamlit.components':st.components,'streamlit.components.v1':st.components.v1})
    yf=types.ModuleType('yfinance')
    def no_network(*args,**kwargs):raise AssertionError('Unexpected provider request in offline test')
    yf.download=yf.Ticker=no_network;sys.modules['yfinance']=yf


@pytest.fixture(autouse=True)
def isolated_ranking_feed(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_ALLOW_MINUTE_QUOTES','false')
    import json
    from datetime import datetime, timezone
    fixture = {
        'schema': 1, 'model': 'existing-100-point-pullback-v1',
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'counts': {'total':4900, 'scanned':4900, 'evaluated':1, 'candidates':1},
        'items': [{'ticker':'MSFT', 'name':'UNIT TEST FIXTURE', 'score':85, 'coverage':100,
                   'qualified':False, 'ready_at_calculation':False, 'reasons':[], 'blockers':[]}]
    }
    path = tmp_path / 'ranking-unit-fixture.json'
    path.write_text(json.dumps(fixture))
    monkeypatch.setenv('DASHBOARD_RANKING_FILE', str(path))
