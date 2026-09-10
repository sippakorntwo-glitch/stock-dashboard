"""Start the real Streamlit HTTP server and test the initial UI (no write token)."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright


def main():
    folder = Path('work'); folder.mkdir(exist_ok=True)
    log = folder / 'server-smoke.log'
    env = os.environ.copy()
    env['DASHBOARD_CACHE_FILE'] = str(folder / 'server-smoke.sqlite3')
    env['DASHBOARD_ALLOW_LIVE_UPDATES'] = 'false'
    env.pop('DASHBOARD_GITHUB_TOKEN', None)
    with log.open('w') as output:
        process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'app.py',
            '--server.headless=true', '--server.address=127.0.0.1', '--server.port=8501'],
            stdout=output, stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.monotonic() + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Streamlit server exited before readiness')
                try:
                    response = requests.get('http://127.0.0.1:8501/_stcore/health', timeout=3)
                    if response.status_code == 200:
                        break
                except requests.RequestException:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Streamlit health endpoint never became ready')
                time.sleep(1)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                try:
                    page.goto('http://127.0.0.1:8501/', wait_until='domcontentloaded')
                    page.get_by_role('heading', name='Stock Research Workspace', exact=True).wait_for(timeout=90000)
                    page.wait_for_timeout(5000)
                    error = page.locator('[data-testid="stException"]')
                    if error.count():
                        raise RuntimeError(error.first.inner_text())
                    page.locator('[data-testid="stDataFrame"]').first.wait_for(timeout=30000)
                    print('ACTUAL_SERVER_STARTUP_PASSED:', sys.version, flush=True)
                    print('PUBLIC_UI_TEXT:', page.locator('body').inner_text()[:3500], flush=True)
                finally:
                    print('LAST_BROWSER_TEXT:', page.locator('body').inner_text()[:7000], flush=True)
                    browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
    print('SERVER_LOG:', log.read_text()[-15000:], flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log = Path('work/server-smoke.log')
        if log.exists():
            print('FAILED_SERVER_LOG:', log.read_text()[-15000:], flush=True)
        raise
