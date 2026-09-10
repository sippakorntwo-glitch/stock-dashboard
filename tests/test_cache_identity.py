"""Real Streamlit cache-key regression: attaching a reader must affect UI reads."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1',
    reason='Requires real Streamlit resource caching rather than import stubs',
)


def test_default_positional_keyword_cache_share_identity(tmp_path, monkeypatch):
    import dashboard_runtime as a
    monkeypatch.setenv('DASHBOARD_CACHE_FILE', str(tmp_path / 'identity.sqlite3'))
    a.get_data_cache.clear()
    try:
        default = a.get_data_cache()
        assert default is a.get_data_cache(a.APP_VERSION)
        assert default is a.get_data_cache(version=a.APP_VERSION)
    finally:
        a.get_data_cache.clear()


def test_remote_attachment_is_used_by_default_ui_reads(tmp_path, monkeypatch):
    import dashboard_runtime as a
    monkeypatch.setenv('DASHBOARD_CACHE_FILE', str(tmp_path / 'reader.sqlite3'))
    a.get_data_cache.clear()
    a.get_remote_reader.clear()
    requests = []
    class Reader:
        def __init__(self, store, cache):
            self.cache = cache
        def request(self, ticker):
            requests.append(ticker)
    monkeypatch.setattr(a, 'settings', lambda: {'backend': 'test'})
    monkeypatch.setattr(a, 'ObjectStore', lambda config: object())
    monkeypatch.setattr(a, 'SnapshotReader', Reader)
    try:
        reader, error = a.get_remote_reader()
        assert error == ''
        ui_cache = a.get_data_cache()
        assert reader.cache is ui_cache
        assert ui_cache.remote is reader
        history, _ = ui_cache.history('AAPL')
        assert history is None
        ui_cache.get('info:SPY')
        assert requests == ['AAPL', 'SPY']
    finally:
        a.get_remote_reader.clear()
        a.get_data_cache.clear()
