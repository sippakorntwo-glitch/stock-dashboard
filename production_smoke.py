"""Public browser verification. No login, tokens, trading, or fabricated prices."""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

URL = 'https://my-stock-terminal.streamlit.app/'
VIEWS = ['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว','สถานะข้อมูล']


def no_exception(page):
    errors = page.locator('[data-testid="stException"]')
    if errors.count():
        raise RuntimeError('Streamlit exception: ' + errors.first.inner_text()[:1600])


def choose(page, name):
    page.locator('[data-testid="stSidebar"]').get_by_text(name, exact=True).click()
    page.wait_for_timeout(2500)
    no_exception(page)


def run():
    version = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)", Path('dashboard_runtime.py').read_text()).group(1)
    report = {'url': URL, 'expected_version': version, 'views': [], 'chart': False}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        deadline = time.monotonic() + 600
        while True:
            try:
                page.goto(URL, wait_until='domcontentloaded', timeout=45000)
                wake = page.get_by_role('button', name=re.compile('Yes, get this app back up', re.I))
                if wake.count():
                    wake.click()
                page.get_by_role('heading', name='Stock Research Workspace', exact=True).wait_for(timeout=45000)
                no_exception(page)
                choose(page, VIEWS[-1])
                page.get_by_text(version, exact=False).first.wait_for(timeout=15000)
                break
            except BrowserTimeout:
                print('Waiting for the deployed workspace...', page.url, flush=True)
                if time.monotonic() >= deadline:
                    print('PUBLIC_PAGE_TEXT:', page.locator('body').inner_text()[:1800], flush=True)
                    raise RuntimeError('Production did not show the expected version within 10 minutes')
                time.sleep(15)
        if 'generations/' not in page.locator('body').inner_text():
            page.locator('[data-testid="stSidebar"]').get_by_role('button', name='ตรวจชุดข้อมูลใหม่').click()
            page.get_by_text(re.compile(r'generations/')).first.wait_for(timeout=120000)
        report['deployed_version'] = version
        for view in VIEWS:
            choose(page, view)
            if view == VIEWS[0]:
                page.locator('[data-testid="stDataFrame"]').first.wait_for(timeout=30000)
            elif view == VIEWS[1]:
                chart_frame = None
                for _ in range(60):
                    no_exception(page)
                    for frame in page.frames:
                        try:
                            if frame.locator('#payload').count() and frame.locator('#chart canvas').count():
                                chart_frame = frame
                                break
                        except Exception:
                            continue
                    if chart_frame:
                        break
                    page.wait_for_timeout(2000)
                if chart_frame is None:
                    raise RuntimeError('No real candlestick chart rendered for AAPL')
                payload = chart_frame.eval_on_selector('#payload', '(el) => JSON.parse(el.textContent)')
                if payload.get('ticker') != 'AAPL' or payload.get('demo') or len(payload.get('records', [])) < 60:
                    raise RuntimeError('Chart has no sufficient real AAPL history')
                chart_frame.locator('#rsi').click()
                chart_frame.locator('#macd').click()
                page.wait_for_timeout(1000)
                if chart_frame.locator('#error').is_visible():
                    raise RuntimeError('JavaScript chart error: ' + chart_frame.locator('#error').inner_text())
                report.update(chart=True, chart_bars=len(payload['records']), chart_last_bar=payload.get('lastBar'))
            elif view == VIEWS[2]:
                page.get_by_role('heading', name=re.compile('ประวัติปันผล')).wait_for(timeout=60000)
                page.locator('[data-testid="stDataFrame"]').first.wait_for(timeout=30000)
            elif view == VIEWS[3]:
                page.locator('[data-testid="stPlotlyChart"]').first.wait_for(timeout=60000)
            elif view == VIEWS[4]:
                page.locator('[data-testid="stPlotlyChart"]').first.wait_for(timeout=120000)
                page.get_by_role('heading', name='Correlation ของผลตอบแทนรายวัน').wait_for(timeout=30000)
            no_exception(page)
            report['views'].append(view)
            print('VERIFIED_VIEW:', view, flush=True)
        report['result'] = 'passed'
        print('PRODUCTION_SMOKE_REPORT:', json.dumps(report, ensure_ascii=False), flush=True)
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                f.write('### Production browser verification\n\n```json\n' + json.dumps(report, ensure_ascii=False, indent=2) + '\n```\n')
        browser.close()


if __name__ == '__main__':
    run()
