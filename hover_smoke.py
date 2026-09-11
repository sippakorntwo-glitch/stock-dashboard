"""Mouse-driven inspection checks on actual chart records, local or public URL.

No crosshair/state injection. DOM geometry is only read to position real mouse
input; every numeric value is checked independently against original candles.
"""
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import expect

FIELDS = ['open','high','low','close','ema20','ema50','sma200','volume','rsi','macd','signal','hist']


def _enabled(frame, key, value=True):
    control = frame.locator('#'+key)
    if control.get_attribute('aria-pressed') != str(value).lower():
        control.click()
    expect(control).to_have_attribute('aria-pressed', str(value).lower())


def _verify_values(frame, payload):
    tip = frame.locator('#chart-inspector')
    expect(tip).to_be_visible()
    stamp = tip.get_attribute('data-time')
    index = next(i for i,r in enumerate(payload['records']) if str(r['time']) == stamp)
    record = payload['records'][index]
    displayed = tip.locator('.inspector-row').evaluate_all("es=>Object.fromEntries(es.map(e=>[e.dataset.field,{raw:e.querySelector('b').dataset.value,text:e.querySelector('b').textContent}]))")
    for field in FIELDS:
        if field not in displayed:
            continue
        expected = record.get(field)
        if expected is None:
            assert displayed[field]['text'] == '—', (field, displayed[field])
        else:
            assert math.isclose(float(displayed[field]['raw']), expected, rel_tol=1e-10, abs_tol=1e-10), field
    before = payload['records'][index-1]['close'] if index else None
    expected = (record['close']/before-1)*100 if before and before>0 else None
    if expected is None:
        assert displayed['barChange']['text'] == '—'
    else:
        assert math.isclose(float(displayed['barChange']['raw']), expected, abs_tol=1e-9)
    label = tip.locator('.inspector-time').inner_text()
    if payload['intraday']:
        expected_date = datetime.fromtimestamp(record['time'], ZoneInfo(payload['timezone'])).strftime('%Y-%m-%d %H:%M')
        assert expected_date in label and payload['timezone'] in label
    else:
        assert record['time'] in label
    bounds = tip.evaluate("e=>{const a=e.getBoundingClientRect(),b=document.getElementById('chartwrap').getBoundingClientRect();return {left:a.left-b.left,top:a.top-b.top,right:a.right-b.right,bottom:a.bottom-b.bottom}}")
    assert bounds['left'] >= -1 and bounds['top'] >= -1 and bounds['right'] <= 1 and bounds['bottom'] <= 1, bounds
    return stamp, displayed


def _move(page, frame, fraction=.45, y=100):
    frame.locator('#chart').scroll_into_view_if_needed()
    box = frame.locator('#chartwrap').bounding_box()
    page.mouse.move(box['x'] + (box['width']-80)*fraction, box['y']+y, steps=5)
    expect(frame.locator('#chart-inspector')).to_be_visible()
    return box


def verify_hover(page, app):
    from production_smoke import chart_for_symbol, no_exception
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    # Verify the symbol shown in the owner's example rather than only a demo.
    manual=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    manual.fill('ORCL');manual.press('Enter')
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
    frame,payload=chart_for_symbol(page,app,'ORCL')
    for key in ['ema20','ema50','sma200','volume','rsi','macd','inspect-toggle']:
        _enabled(frame,key)
    before_price=frame.locator('#price').inner_text()
    before_growth=frame.locator('#range-return-value').get_attribute('data-value')
    _move(page,frame)
    first,values=_verify_values(frame,payload)
    assert set(FIELDS).issubset(values), values
    targets=json.loads(frame.locator('#chart-inspector').get_attribute('data-targets'))
    visited=[]
    for field in ['ema20','ema50','sma200','volume','rsi','macd','signal','hist']:
        target=next(t for t in targets if t['field']==field)
        assert target['y'] is not None, field
        box=frame.locator('#chartwrap').bounding_box()
        if not 0 <= target['top']+target['y'] < box['height']-26:
            raise AssertionError('Test point outside chart: '+field)
        page.mouse.move(box['x']+target['x'],box['y']+target['top']+target['y'],steps=4)
        expect(frame.locator('#chart-inspector')).to_have_attribute('data-pane',str(target['pane']))
        _verify_values(frame,payload)
        focus=frame.locator('#chart-inspector').get_attribute('data-focus')
        assert focus, 'No highlighted series at '+field
        visited.append({'series':field,'pane':target['pane'],'highlight':focus})
    # Historical readout must change with the bar, never with the last-price header.
    box=_move(page,frame,.28)
    pinned,_=_verify_values(frame,payload)
    page.mouse.click(box['x']+(box['width']-80)*.28,box['y']+100)
    expect(frame.locator('#chart-inspector')).to_have_attribute('data-pinned','true')
    page.mouse.move(box['x']+(box['width']-80)*.73,box['y']+80,steps=5)
    expect(frame.locator('#chart-inspector')).to_have_attribute('data-time',pinned)
    page.keyboard.press('Escape')
    _move(page,frame,.74)
    after,_=_verify_values(frame,payload)
    assert after!=pinned
    assert frame.locator('#price').inner_text()==before_price
    assert frame.locator('#range-return-value').get_attribute('data-value')==before_growth
    # Hidden overlays must not remain in either floating or fixed readouts.
    _enabled(frame,'ema50',False);_move(page,frame)
    assert not frame.locator('#chart-inspector [data-field="ema50"]').count()
    assert 'EMA 50' not in frame.locator('#indicator-value').inner_text()
    _enabled(frame,'ema50',True)
    _enabled(frame,'inspect-toggle',False)
    box=frame.locator('#chartwrap').bounding_box()
    page.mouse.move(box['x']+150,box['y']+100)
    expect(frame.locator('#chart-inspector')).to_be_hidden()
    # Pan and reset remain functional with the optional overlay off.
    original=float(frame.locator('#chart').get_attribute('data-range-from'))
    page.mouse.move(box['x']+300,box['y']+80);page.mouse.down()
    page.mouse.move(box['x']+430,box['y']+80,steps=10);page.mouse.up()
    page.wait_for_timeout(200)
    moved=float(frame.locator('#chart').get_attribute('data-range-from'))
    assert abs(moved-original)>1,(moved,original)
    frame.locator('#reset').click()
    _enabled(frame,'inspect-toggle',True)
    _move(page,frame,.96);_verify_values(frame,payload)
    frame.locator('#symbol').hover()
    expect(frame.locator('#chart-inspector')).to_be_hidden()
    frame.locator('#chartwrap').focus();page.keyboard.press('ArrowLeft')
    expect(frame.locator('#chart-inspector')).to_have_attribute('data-pinned','true')
    _verify_values(frame,payload)
    frame.locator('#inspect-clear').click()
    report={'ticker':'ORCL','daily_values_checked':FIELDS,'panes':visited,
            'pin_and_escape':True,'keyboard':True,'optional_toggle':True,
            'pan_reset':True,'edge_bounds':True,'latest_price_and_period_return_unchanged':True}
    # Verify intraday epoch timestamps and exchange timezone with real SPY data.
    manual.fill('SPY');manual.press('Enter')
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 วัน',exact=True).click()
    from enhanced_smoke import wait_range
    frame,payload=wait_range(page,app,'1 วัน')
    _enabled(frame,'inspect-toggle',True)
    _move(page,frame,.4);stamp,_=_verify_values(frame,payload)
    report['intraday']={'ticker':'SPY','interval':payload['interval'],'time':stamp,'timezone':payload['timezone']}
    no_exception(app)
    assert not frame.locator('#error').is_visible()
    assert not errors,errors
    return report
