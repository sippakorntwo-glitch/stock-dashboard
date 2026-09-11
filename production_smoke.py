"""Exercise the real single-page app, actual canvas selection, and real charts.

The report always names its target URL; localhost success is not production success.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

URL='https://my-stock-terminal.streamlit.app/'
VIEWS=['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว','สถานะข้อมูล']


def no_exception(app):
    errors=app.locator('[data-testid="stException"]')
    if errors.count(): raise RuntimeError('Streamlit exception: '+errors.first.inner_text()[:1600])


def diagnose(page):
    for frame in page.frames:
        try:
            u=urlsplit(frame.url)
            print('BROWSER_FRAME:',json.dumps({'url':u.scheme+'://'+u.netloc+u.path,'payload_count':frame.locator('#payload').count(),'canvas_count':frame.locator('canvas').count(),'text':frame.locator('body').inner_text()[:12000]},ensure_ascii=False),flush=True)
        except Exception as exc: print('FRAME_DIAGNOSTIC_ERROR:',type(exc).__name__,flush=True)


def app_frame(page):
    for frame in page.frames:
        try:
            if frame.get_by_role('heading',name='Stock Research Workspace',exact=True).count(): return frame
        except Exception: pass
    return None


def wait_for_release(page,version):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        page.goto(URL,wait_until='domcontentloaded',timeout=60000)
        for _ in range(20):
            app=app_frame(page)
            if app:
                if app.get_by_text(re.compile(re.escape(version))).count() and app.locator('.st-key-research_overview').count():
                    return app
            wake=page.get_by_role('button',name=re.compile('Yes, get this app back up',re.I))
            if wake.count(): wake.click()
            page.wait_for_timeout(1000)
        print('Waiting for single-page hosting release',version,flush=True)
        page.wait_for_timeout(5000)
    raise RuntimeError('Production did not load the expected single-page release')


def chart_for_symbol(page,app,ticker):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        no_exception(app)
        for frame in page.frames:
            try:
                if frame.locator('#payload').count() and frame.locator('#chart canvas').count():
                    payload=frame.eval_on_selector('#payload','(el)=>JSON.parse(el.textContent)')
                    if payload.get('ticker')==ticker and not payload.get('demo') and len(payload.get('records',[]))>=60:
                        return frame,payload
            except Exception: pass
        page.wait_for_timeout(1000)
    raise RuntimeError('No real candlestick history rendered for '+ticker)


def verify_sections(app):
    no_exception(app)
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('radiogroup')).to_have_count(0)
    for section,title in [('research_technical','กราฟและแผนซื้อ'),('research_fundamentals','พื้นฐานและปันผล'),('research_risk','ความเสี่ยง'),('research_comparison','เปรียบเทียบหลายตัว')]:
        expect(app.locator('.st-key-'+section).get_by_role('heading',name=title,exact=True)).to_be_visible(timeout=60000)
    expect(app.locator('.st-key-research_fundamentals').get_by_role('heading',name=re.compile('ประวัติปันผล'))).to_be_visible(timeout=60000)
    expect(app.locator('.st-key-research_fundamentals [data-testid="stDataFrame"]').first).to_be_visible()
    expect(app.locator('.st-key-research_risk [data-testid="stPlotlyChart"]')).to_have_count(2,timeout=60000)
    expect(app.locator('.st-key-research_comparison [data-testid="stPlotlyChart"]')).to_have_count(1,timeout=120000)
    expect(app.locator('.st-key-research_comparison').get_by_role('heading',name='Correlation ของผลตอบแทนรายวัน')).to_be_visible(timeout=30000)
    expect(app.locator('.st-key-research_health').get_by_role('heading',name='สถานะข้อมูลและระบบ')).to_be_visible()
    no_exception(app)


def click_filtered_stock(page,app,ticker,*,row_selector=False):
    query=app.get_by_role('textbox',name='ค้นหา Ticker / บริษัท / อุตสาหกรรม',exact=True)
    query.fill(ticker);query.press('Enter')
    expect(app.get_by_text('หุ้นในผลค้นหา: '+ticker,exact=True)).to_be_visible(timeout=30000)
    page.wait_for_timeout(1000)
    canvas=app.locator('.st-key-stock_picker_table canvas').first
    canvas.scroll_into_view_if_needed()
    # Actual mouse input on the first displayed row: company cell or row selector.
    # The app sets row_height=36. This does not inject state or call a JS callback.
    canvas.click(position={'x':16 if row_selector else 180,'y':54})
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)).to_have_value(ticker,timeout=30000)
    expect(app.get_by_role('heading',name=re.compile('^'+re.escape(ticker)+r' ·'))).to_be_visible(timeout=30000)
    return chart_for_symbol(page,app,ticker)


def run():
    version=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
    report={'url':URL,'expected_version':version,'layout':'single-page','views':[],'chart':False,'selections':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:print('JAVASCRIPT_ERROR:',str(e)[:1000],flush=True))
        try:
            app=wait_for_release(page,version)
            app.get_by_text(re.compile(r'generations/')).first.wait_for(timeout=120000)
            app.get_by_text(re.compile('พร้อมใช้งาน · ตรวจชุดข้อมูลใหม่|กำลังอ่านข้อมูลที่เลือก')).first.wait_for(timeout=30000)
            chart,payload=chart_for_symbol(page,app,'AAPL')
            chart.locator('#rsi').click();chart.locator('#macd').click()
            page.wait_for_timeout(1000)
            if chart.locator('#error').is_visible(): raise RuntimeError('Candlestick JavaScript error')
            verify_sections(app)
            report.update(chart=True,chart_bars=len(payload['records']),chart_last_bar=payload.get('lastBar'),deployed_version=version,views=list(VIEWS))
            for ticker,row_selector in [('MSFT',False),('AAPL',True)]:
                chart,payload=click_filtered_stock(page,app,ticker,row_selector=row_selector)
                verify_sections(app)
                report['selections'].append({'ticker':ticker,'via':'row' if row_selector else 'cell','bars':len(payload['records'])})
                print('VERIFIED_STOCK_SELECTION:',ticker,flush=True)
            # Manual input is still available; SPY defaults to comparing against QQQ.
            field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
            field.fill('SPY');field.press('Enter')
            chart,payload=chart_for_symbol(page,app,'SPY')
            verify_sections(app)
            expect(app.locator('.st-key-research_comparison').get_by_text('QQQ',exact=True).first).to_be_visible()
            report['selections'].append({'ticker':'SPY','via':'manual','bars':len(payload['records'])})
            report['result']='passed'
            print('BROWSER_SMOKE_REPORT:',json.dumps(report,ensure_ascii=False),flush=True)
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as f:
                    f.write('### Single-page browser verification — see target URL\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')
        except Exception:
            diagnose(page)
            raise
        finally:
            browser.close()


if __name__=='__main__': run()
