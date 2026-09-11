"""Additional real-browser checks: no state injection or generated prices."""
import time
import re
from playwright.sync_api import expect


def wait_range(page,app,period,seconds=90):
    deadline=time.monotonic()+seconds;last=None
    while time.monotonic()<deadline:
        if app.locator('[data-testid="stException"]').count():raise RuntimeError(app.locator('[data-testid="stException"]').first.inner_text())
        for frame in page.frames:
            try:
                if not frame.locator('#payload').count():continue
                p=frame.eval_on_selector('#payload','e=>JSON.parse(e.textContent)')
                if p.get('ticker')!='SPY' or p.get('period')!=period:continue
                last=p
                if not p.get('full_window'):continue
                if p.get('demo') or not p.get('records'):raise RuntimeError('No real data')
                expect(frame.locator('#chart canvas').first).to_be_visible()
                return frame,p
            except Exception as e:
                if 'No real data' in str(e):raise
        page.wait_for_timeout(1000)
    raise RuntimeError(f'No complete real chart for {period}; last coverage={last and last.get("full_window")}')


def verify_enhancements(page,app):
    report={'page_size':500,'tooltips':False,'ranges':[]}
    query=app.get_by_role('textbox',name='ค้นหา Ticker / บริษัท / อุตสาหกรรม',exact=True)
    query.fill('');query.press('Enter')
    expect(app.get_by_text(re.compile(r'แสดง 500 ตัวในหน้านี้'))).to_be_visible(timeout=30000)
    item=app.locator('.st-key-research_technical .workspace-help-table abbr').filter(has_text='ราคา > EMA20 > EMA50').first
    expect(item).to_be_visible()
    assert 'รายวัน' in item.get_attribute('title')
    item.hover()
    assert app.locator('.workspace-glossary summary').count()>=4
    assert app.locator('.st-key-research_fundamentals abbr[title]').count()>=5
    report['tooltips']=True
    for period in ['1 วัน','3 วัน','5 ปี','10 ปี']:
        app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text(period,exact=True).click()
        frame,payload=wait_range(page,app,period);page.wait_for_timeout(500)
        if period.endswith('วัน'):assert payload['interval']=='5m' and payload['intraday']
        else:assert payload['interval']=='1d' and not payload['intraday']
        data=frame.locator('#chart').evaluate('(e)=>({...e.dataset})')
        assert abs(float(data['rangeFrom'])-(payload['visibleStart']-.8))<6,data
        assert abs(float(data['rangeTo'])-(len(payload['records'])+3))<6,data
        report['ranges'].append({'period':period,'interval':payload['interval'],'bars':len(payload['records']),'visible_bars':len(payload['records'])-payload['visibleStart'],'first':payload['range_first'],'last':payload['range_last']})
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
    from performance_smoke import verify_growth_and_plain_cells
    report['growth_and_plain_cells']=verify_growth_and_plain_cells(page,app)
    return report
