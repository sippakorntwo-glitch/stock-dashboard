"""Exercise quote controls without changing source timestamps or inventing prices."""
from __future__ import annotations
from datetime import datetime,timezone
import math
import time
from playwright.sync_api import expect


def refresh_state(status):
    value=status.evaluate('(e)=>({...e.dataset})')
    assert value['state'] in {'disabled','paused','updating','rate_limited','budget','retry','scheduled'},value
    assert value['session'] in {'pre','regular','post','closed','unknown'},value
    assert value['busy'] in {'true','false'},value
    assert int(value['requestedSeconds']) in (30,60,120),value
    effective=float(value['effectiveSeconds']);due=float(value['nextDue'])
    assert math.isfinite(effective) and 0<effective<=1800 and math.isfinite(due) and due>=0,value
    if value['session'] in {'pre','regular','post'}:
        assert effective==int(value['requestedSeconds']),value
    return value


def verify_quote_refresh(page,app,chart,payload,ticker):
    from production_smoke import no_exception,wait_page_ready,chart_for_symbol
    panel=app.locator('.st-key-minute_quote_panel')
    minute=panel.locator('.minute-quote[data-ticker="'+ticker+'"]')
    status=panel.locator('.quote-refresh-status')
    expect(minute).to_be_visible(timeout=90000)
    expect(status).to_be_visible()
    auto=panel.get_by_role('checkbox',name='อัปเดตราคาอัตโนมัติ',exact=True)
    interval=panel.locator('[data-testid="stSelectbox"]').filter(
        has=app.get_by_text('รอบขอราคา',exact=True)).get_by_role('combobox')
    expect(auto).to_be_checked()
    expect(interval).to_have_value('30 วินาที')
    expect(status).to_have_attribute('data-requested-seconds','30')
    first=refresh_state(status)
    search=app.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True).input_value()
    generation=app.locator('.workspace-ready').last.get_attribute('data-generation')
    original=chart.locator('#payload').evaluate('e=>{const p=JSON.parse(e.textContent);return {ticker:p.ticker,period:p.period,periodReturn:p.periodReturn};}')
    assert original['ticker']==ticker and original['period']==payload['period'],original

    interval.click();app.get_by_role('option',name='60 วินาที',exact=True).click()
    expect(interval).to_have_value('60 วินาที')
    expect(status).to_have_attribute('data-requested-seconds','60')
    sixty=refresh_state(status)
    auto.uncheck()
    expect(auto).not_to_be_checked()
    expect(status).to_have_attribute('data-state','paused')
    expect(status).to_contain_text('พักการอัปเดตราคา')
    interval.click();app.get_by_role('option',name='30 วินาที',exact=True).click()
    expect(interval).to_have_value('30 วินาที')
    expect(status).to_have_attribute('data-requested-seconds','30')
    expect(status).to_have_attribute('data-state','paused')
    auto.check()
    expect(auto).to_be_checked()
    expect(status).not_to_have_attribute('data-state','paused')
    resumed=refresh_state(status)
    assert resumed['state']!='disabled',resumed

    fetched=minute.get_attribute('data-fetched-at')
    assert fetched
    # A new fetch can truthfully return the same bar and price. Require a second
    # observation only in an advertised active session with an available budget.
    active=resumed['session'] in {'pre','regular','post'}
    due=max(0,float(resumed['nextDue'])-datetime.now(timezone.utc).timestamp())
    automatic={'session':resumed['session'],'state':resumed['state'],
               'effective_seconds':float(resumed['effectiveSeconds']),'next_due':float(resumed['nextDue'])}
    if active and resumed['state'] in {'scheduled','updating'} and due<=60:
        deadline=time.monotonic()+max(60,due+45)
        while time.monotonic()<deadline and minute.get_attribute('data-fetched-at')==fetched:
            page.wait_for_timeout(2000);no_exception(app)
        assert minute.get_attribute('data-fetched-at')!=fetched,'No second quote observation within the advertised active-session cadence'
        automatic['second_observation']=True
    else:
        automatic['second_observation']=False
        automatic['reason']='provider session or request budget requires a conservative wait'
    quote=minute.evaluate('(e)=>({...e.dataset})')
    price=float(quote['price'])
    observed=datetime.fromisoformat(quote['barTime']);received=datetime.fromisoformat(quote['fetchedAt'])
    now=datetime.now(timezone.utc)
    assert math.isfinite(price) and price>0 and observed.tzinfo is not None and received.tzinfo is not None,quote
    assert observed<=now and received<=now,quote
    assert received>=datetime.fromisoformat(fetched),quote
    assert quote['state'] in {'recent','stale'},quote
    expect(minute).to_contain_text('อายุแท่ง')
    expect(minute).not_to_contain_text('นอกเวลาซื้อขาย')
    # Quote controls operate in their own fragment. They must preserve the
    # selected daily chart, its return calculation, and the active search.
    wait_page_ready(app,ticker,query=search)
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)).to_have_value(ticker)
    expect(app.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)).to_have_value(search)
    chart,current_payload=chart_for_symbol(page,app,ticker)
    current=chart.locator('#payload').evaluate('e=>{const p=JSON.parse(e.textContent);return {ticker:p.ticker,period:p.period,periodReturn:p.periodReturn};}')
    assert (current['ticker'],current['period'])==(original['ticker'],original['period']),(original,current)
    current_generation=app.locator('.workspace-ready').last.get_attribute('data-generation')
    if current_generation==generation:
        assert current==original,(original,current)
    else:
        # A newly published daily snapshot may update its own figures while
        # quote controls are exercised; independently check that new chart.
        from chart_commentary_smoke import verify_chart_commentary
        verify_chart_commentary(page,app,current_payload)
    expect(app.locator('.chart-reading')).to_have_count(1)
    expect(app.locator('.chart-reading')).to_have_attribute('data-ticker',ticker)
    no_exception(app)
    return {'auto_refresh_verified':automatic,'quote_controls':{'requested_seconds':[30,60,30],
        'initial':first,'sixty_seconds':sixty,'resumed':refresh_state(status),
        'pause_resume':True,'ticker_search_and_daily_chart_preserved':True,
        'generation_before':generation,'generation_after':current_generation},
        'minute_price':{'price':price,'bar_time':quote['barTime'],'fetched_at':quote['fetchedAt'],'state':quote['state']}}
