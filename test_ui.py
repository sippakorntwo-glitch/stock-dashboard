"""Requires real Streamlit; offline import-stub builds skip this test explicitly."""
import os
from unittest.mock import patch
import numpy as np
import pytest

@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Real Streamlit AppTest is unavailable in the offline build container')
def test_six_views_without_provider_calls(tmp_path):
    from streamlit.testing.v1 import AppTest
    import dashboard_runtime as a
    import dashboard_ui as ui
    from test_analytics import frame
    cache=a.DashboardCache(tmp_path/'ui.sqlite3')
    for ticker in ['AAPL','SPY']:
        cache.save_history(ticker,frame(np.linspace(100,200,800)),'2026-09-10T00:00:00Z')
        cache.put('info:'+ticker,{'industry':'Technology','_Fetched_At_UTC':'2026-09-10T00:00:00Z'},{})
        cache.put('dividends:'+ticker,{'records':[],'error':None,'fetched_at':'2026-09-10T00:00:00Z','coverage_start':'2020-01-01','coverage_end':'2026-09-09'},{})
    class Reader:
        def refresh(self,force=False):pass
        def request(self,ticker):pass
        def status(self):return {'busy':False,'revision':0,'error':'','manifest':{'generation':'test','published_at':'2026-09-10T00:00:00Z'}}
    with patch.object(a,'get_data_cache',return_value=cache),patch.object(a.core,'get_data_cache',return_value=cache),patch.object(a,'get_remote_reader',return_value=(Reader(),'')),patch.object(a,'get_updater',return_value=a.ReadOnlyUpdater()),patch.object(a.yf,'download',side_effect=AssertionError('Unexpected provider call')),patch.object(a.yf,'Ticker',side_effect=AssertionError('Unexpected provider call')):
        at=AppTest.from_string('from dashboard_ui import main\nmain()',default_timeout=30).run()
        assert not at.exception,str(at.exception)
        assert at.metric[0].value=='4,900'
        for view in ui.VIEWS:
            at.sidebar.radio[0].set_value(view).run()
            assert not at.exception,f'{view}: {at.exception}'
