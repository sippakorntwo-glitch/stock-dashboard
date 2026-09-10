"""Cached resources must consistently include the release and data source."""
import os
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires actual Streamlit resource hashing')


def test_reader_identity_and_release_isolation(tmp_path,monkeypatch):
    import dashboard_runtime as a
    monkeypatch.setenv('DASHBOARD_CACHE_FILE',str(tmp_path/'versions.sqlite3'))
    monkeypatch.setattr(a,'settings',lambda:{'backend':'test'})
    monkeypatch.setattr(a,'ObjectStore',lambda config:object())
    class Reader:
        def __init__(self,store,cache): self.cache=cache
        def request(self,ticker): pass
    monkeypatch.setattr(a,'SnapshotReader',Reader)
    a.get_remote_reader.clear();a.get_data_cache.clear()
    try:
        default,error=a.get_remote_reader()
        assert error==''
        assert default is a.get_remote_reader(a.APP_VERSION)[0]
        assert default is a.get_remote_reader(version=a.APP_VERSION)[0]
        previous,error=a.get_remote_reader(version='older-build')
        assert error=='' and previous is not default
        assert previous.cache is a.get_data_cache('older-build')
        assert default.cache is a.get_data_cache()
        assert a.get_data_cache().remote is default
    finally:
        a.get_remote_reader.clear();a.get_data_cache.clear()


def test_updater_arguments_have_one_identity(tmp_path,monkeypatch):
    import dashboard_runtime as a
    monkeypatch.setenv('DASHBOARD_CACHE_FILE',str(tmp_path/'worker.sqlite3'))
    monkeypatch.setattr(a,'live_enabled',lambda:False)
    a.get_updater.clear()
    try:
        worker=a.get_updater()
        assert worker is a.get_updater(a.APP_VERSION)
        assert worker is a.get_updater(version=a.APP_VERSION)
        assert worker is not a.get_updater(version='older-build')
    finally: a.get_updater.clear()
