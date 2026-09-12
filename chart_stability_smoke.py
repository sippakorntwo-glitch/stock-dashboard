"""Public browser regression for the duplicated-period card found in production."""
from __future__ import annotations
import re
from pathlib import Path
from playwright.sync_api import expect


def verify_chart_stability(page,app):
    from production_smoke import wait_page_ready,chart_for_symbol,wait_for_release,no_exception
    from enhanced_smoke import wait_range
    from chart_commentary_smoke import verify_chart_commentary
    field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    current=field.input_value();wait_page_ready(app,current)
    field.fill('SPY');field.press('Enter')
    wait_page_ready(app,'SPY')
    report={'period_switches':[],'reloads':[],'timer_seconds':65}
    for period in ('1 วัน','3 วัน','1 วัน','3 วัน','5 ปี','1 ปี'):
        control=app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ')
        control.get_by_text(period,exact=True).click()
        frame,payload=wait_range(page,app,period)
        result=verify_chart_commentary(page,app,payload)
        expect(app.locator('.chart-reading')).to_have_count(1)
        assert result['period']==period
        report['period_switches'].append({'period':period,'summary_count':1,'values_match':True})
    for _ in range(13):
        page.wait_for_timeout(5000)
        no_exception(app)
        expect(field).to_have_value('SPY')
        expect(app.locator('.chart-reading')).to_have_count(1)
        expect(app.locator('.chart-reading')).to_have_attribute('data-period','1 ปี')
    version=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
    for iteration in range(2):
        page.reload(wait_until='domcontentloaded',timeout=60000)
        app=wait_for_release(page,version)
        # A fresh Streamlit session initializes AAPL. The heading can render
        # before React hydrates the input; capturing its temporary empty value
        # and waiting for that ticker would falsely reject an already-ready app.
        ticker='AAPL'
        wait_page_ready(app,ticker)
        field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
        expect(field).to_have_value(ticker,timeout=30000)
        frame,payload=chart_for_symbol(page,app,ticker)
        verify_chart_commentary(page,app,payload)
        no_exception(app)
        expect(app.locator('.chart-reading')).to_have_count(1)
        report['reloads'].append({'iteration':iteration+1,'ticker':ticker,'summary_count':1,'page_ready':True})
    report['result']='passed'
    return report
