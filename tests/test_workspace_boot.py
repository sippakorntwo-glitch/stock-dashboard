"""Release boot guards; stale-import recovery runs in an isolated interpreter."""
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
import pytest
import workspace_boot as boot


def test_refresh_decision_requires_version_and_native_poll():
    expected='test-release'
    good=SimpleNamespace(APP_VERSION=expected)
    native=SimpleNamespace(_poll_data=lambda:None)
    assert not boot.needs_refresh(good,native,expected)
    assert boot.needs_refresh(SimpleNamespace(APP_VERSION='old'),native,expected)
    assert boot.needs_refresh(good,SimpleNamespace(),expected)


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit imports')
def test_stale_modules_require_restart_without_deleting_live_references(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code='''
import dashboard_runtime as old_runtime
import dashboard_ui as old_ui
import workspace_boot
expected = old_runtime.APP_VERSION
old_runtime.APP_VERSION = 'previous-release'
old_ui._poll_data = None
try:
    workspace_boot.ensure_release(expected)
except RuntimeError as exc:
    assert 'restart' in str(exc)
else:
    raise AssertionError('A stale release must not replace live modules')
import sys
assert sys.modules['dashboard_runtime'] is old_runtime
assert sys.modules['dashboard_ui'] is old_ui
assert old_runtime.APP_VERSION == 'previous-release'
assert old_ui._poll_data is None
print('STALE_RELEASE_GUARD_OK')
'''
    env={**os.environ,'DASHBOARD_ALLOW_LIVE_UPDATES':'false','DASHBOARD_CACHE_FILE':str(tmp_path/'boot.sqlite3')}
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'STALE_RELEASE_GUARD_OK' in result.stdout


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit imports')
def test_concurrent_sessions_keep_one_module_graph(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code=r"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import streamlit as st
from workspace_boot import ensure_release
expected=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
assert expected in Path('requirements.txt').read_text().splitlines()[0]
assert st.get_option('server.fileWatcherType') == 'none'
assert st.get_option('runner.fastReruns') is False
with ThreadPoolExecutor(max_workers=12) as pool:
    loaded=list(pool.map(lambda _: ensure_release(expected), range(60)))
runtime, ui=loaded[0]
assert all(r is runtime and u is ui for r,u in loaded)
assert runtime.core.DashboardCache is runtime.DashboardCache
assert callable(ui._poll_data)
print('CONCURRENT_BOOT_OK')
"""
    env={**os.environ,'DASHBOARD_ALLOW_LIVE_UPDATES':'false','DASHBOARD_CACHE_FILE':str(tmp_path/'parallel.sqlite3')}
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'CONCURRENT_BOOT_OK' in result.stdout
