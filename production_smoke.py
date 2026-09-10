"""Browser checks against actual data; report URL distinguishes CI/production."""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

URL='https://my-stock-terminal.streamlit.app/'
VIEWS=['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว','สถานะข้อมูล']


def no_exception(app):
    errors=app.locator('[data-testid="stException"]')
    if errors.count(): raise RuntimeError('Streamlit exception: '+errors.first.inner_text()[:1600])


def choose(app,name):
    app.locator('[data-testid="stSidebar"]').get_by_text(name,exact=True).click()
    app.page.wait_for_timeout(2500)
    no_exception(app)


def diagnose(page):
    for frame in page.frames:
        try:
            u=urlsplit(frame.url)
            print('BROWSER_FRAME:',json.dumps({'url':u.scheme+'://'+u.netloc+u.path,'payload_count':frame.locator('#payload').count(),'canvas_count':frame.locator('canvas').count(),'text':frame.locator('body').inner_text()[:9000]},ensure_ascii=False),flush=True)
        except Exception as exc: print('FRAME_DIAGNOSTIC_ERROR:',type(exc).__name__,flush=True)


def app_frame(page):
    for frame in page.frames:
        try:
            if frame.get_by_role('heading',name='Stock Research Workspace',exact=True).count(): return frame
        except Exception: pass
    return None


def wait_for_release(page,version):
    deadline=time.monotonic()+420
    while time.monotonic()<deadline:
        page.goto(URL,wait_until='domcontentloaded',timeout=60000)
        app=None
        for _ in range(20):
            app=app_frame(page)
            if app: break
            wake=page.get_by_role('button',name=re.compile('Yes, get this app back up',re.I))
            if wake.count(): wake.click()
            page.wait_for_timeout(1000)
        if app:
            choose(app,VIEWS[-1])
            try:
                app.get_by_text(version,exact=False).first.wait_for(timeout=10000)
                return app
            except BrowserTimeout:
                print('Waiting for hosting to load release',version,flush=True)
        page.wait_for_timeout(10000)
    diagnose(page)
    raise RuntimeError('Production did not load the expected release')


def run():
    version=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
    report={'url':URL,'expected_version':version,'views':[],'chart':False}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:print('JAVASCRIPT_ERROR:',str(e)[:1000],flush=True))
        try:
            app=wait_for_release(page,version)
            app.get_by_text(re.compile(r'generations/')).first.wait_for(timeout=120000)
            # Require the new native status poll, not an old cached UI with the same title.
            app.get_by_text(re.compile('พร้อมใช้งาน · ตรวจชุดข้อมูลใหม่|กำลังอ่านข้อมูลที่เลือก')).first.wait_for(timeout=30000)
            report['deployed_version']=version
            for view in VIEWS:
                choose(app,view)
                if view==VIEWS[0]:
                    app.locator('[data-testid="stDataFrame"]').first.wait_for(timeout=30000)
                elif view==VIEWS[1]:
                    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
                    chart_frame=None
                    for _ in range(90):
                        no_exception(app)
                        for frame in page.frames:
                            try:
                                if frame.locator('#payload').count() and frame.locator('#chart canvas').count(): chart_frame=frame;break
                            except Exception: pass
                        if chart_frame: break
                        page.wait_for_timeout(2000)
                    if chart_frame is None: raise RuntimeError('No real candlestick chart rendered for AAPL')
                    payload=chart_frame.eval_on_selector('#payload','(el)=>JSON.parse(el.textContent)')
                    if payload.get('ticker')!='AAPL' or payload.get('demo') or len(payload.get('records',[]))<60:
                        raise RuntimeError('Insufficient real AAPL history in chart')
                    chart_frame.locator('#rsi').click();chart_frame.locator('#macd').click()
                    page.wait_for_timeout(1000)
                    if chart_frame.locator('#error').is_visible(): raise RuntimeError('JavaScript chart error: '+chart_frame.locator('#error').inner_text())
                    report.update(chart=True,chart_bars=len(payload['records']),chart_last_bar=payload.get('lastBar'))
                elif view==VIEWS[2]:
                    app.get_by_role('heading',name=re.compile('ประวัติปันผล')).wait_for(timeout=60000)
                    app.locator('[data-testid="stDataFrame"]').first.wait_for(timeout=30000)
                elif view==VIEWS[3]:
                    app.locator('[data-testid="stPlotlyChart"]').first.wait_for(timeout=60000)
                elif view==VIEWS[4]:
                    app.locator('[data-testid="stPlotlyChart"]').first.wait_for(timeout=120000)
                    app.get_by_role('heading',name='Correlation ของผลตอบแทนรายวัน').wait_for(timeout=30000)
                no_exception(app)
                report['views'].append(view)
                print('VERIFIED_VIEW:',view,flush=True)
            report['result']='passed'
            print('BROWSER_SMOKE_REPORT:',json.dumps(report,ensure_ascii=False),flush=True)
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as f:
                    f.write('### Browser verification — see target URL\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')
        except Exception:
            diagnose(page)
            raise
        finally:
            browser.close()


if __name__=='__main__': run()
