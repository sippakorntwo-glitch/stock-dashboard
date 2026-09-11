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
