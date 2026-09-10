"""Release boot guards; stale-import recovery runs in an isolated interpreter."""
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
import pytest
import workspace_boot as boot


def test_refresh_decision_requires_version_and_native_poll():
    expected='2026-09-11.13'
    good=SimpleNamespace(APP_VERSION=expected)
    native=SimpleNamespace(_poll_data=lambda:None)
    assert not boot.needs_refresh(good,native,expected)
    assert boot.needs_refresh(SimpleNamespace(APP_VERSION='old'),native,expected)
    assert boot.needs_refresh(good,SimpleNamespace(),expected)


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit imports')
def test_stale_modules_recover_without_mutating_old_references(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code='''
import dashboard_runtime as old_runtime
import dashboard_ui as old_ui
import workspace_boot
old_runtime.APP_VERSION = 'previous-release'
old_ui._poll_data = None
runtime, ui = workspace_boot.ensure_release('2026-09-11.13')
assert runtime.APP_VERSION == '2026-09-11.13'
assert callable(ui._poll_data)
assert runtime is not old_runtime and ui is not old_ui
assert old_runtime.APP_VERSION == 'previous-release'
assert old_ui._poll_data is None
again_runtime, again_ui = workspace_boot.ensure_release('2026-09-11.13')
assert again_runtime is runtime and again_ui is ui
assert runtime.core.DashboardCache is runtime.DashboardCache
assert runtime.core.scan_snapshot_row is runtime.scan_snapshot_row
print('STALE_IMPORT_RECOVERY_OK')
'''
    env={**os.environ,'DASHBOARD_ALLOW_LIVE_UPDATES':'false','DASHBOARD_CACHE_FILE':str(tmp_path/'boot.sqlite3')}
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'STALE_IMPORT_RECOVERY_OK' in result.stdout
