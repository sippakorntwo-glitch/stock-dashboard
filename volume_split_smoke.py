"""Real-browser checks for the explicitly estimated, stacked volume display.

Only normal pointer/button input changes the chart. Read-only DOM geometry and
canvas pixels establish that both colors render in one bar, rather than merely
checking a toggle or trusting the series configuration.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal, localcontext
from pathlib import Path


SPLIT_FIELDS = ('buy_volume_est', 'sell_volume_est', 'unclassified_volume')


def verify_volume_payload(payload):
    assert payload.get('volumeSplitMethod') == 'ohlc-close-position-estimate'
    counts = {'bars': 0, 'mixed_bars': 0, 'flat_bars': 0, 'missing_volume': 0}
    for record in payload['records']:
        counts['bars'] += 1
        assert all(key in record for key in SPLIT_FIELDS), record['time']
        volume = record['volume']
        parts = [record[key] for key in SPLIT_FIELDS]
        if volume is None:
            assert parts == [None, None, None], record
            counts['missing_volume'] += 1
            continue
        if volume == 0:
            assert parts == [0, 0, 0], record
            continue
        if record['high'] == record['low']:
            assert parts == [None, None, volume], record
            counts['flat_bars'] += 1
            continue
        # Evaluate independently at higher precision. Left-associated binary
        # V*(C-L)/(H-L) can overshoot V by one ULP even when C == H, creating
        # a negative expected sell amount for a correctly rendered zero.
        with localcontext() as context:
            context.prec = 80
            v, high, low, close = (Decimal.from_float(float(value))
                                   for value in (volume,record['high'],record['low'],record['close']))
            fraction = (close-low)/(high-low)
            buy, sell = float(v*fraction), float(v*(1-fraction))
        tolerance = 4*math.ulp(float(volume))
        assert math.isclose(parts[0], buy, rel_tol=0, abs_tol=tolerance), record
        assert math.isclose(parts[1], sell, rel_tol=0, abs_tol=tolerance), record
        assert parts[2] == 0 and 0 <= parts[0] <= volume and 0 <= parts[1] <= volume, record
        assert math.isclose(sum(parts), volume, rel_tol=0, abs_tol=tolerance), record
        counts['mixed_bars'] += int(0 < buy < volume)
    return counts


def _range(frame):
    raw = frame.locator('#chart').evaluate('(e)=>({...e.dataset})')
    return float(raw['rangeFrom']), float(raw['rangeTo'])


def _same_range(frame, expected):
    observed = _range(frame)
    assert all(abs(a-b) < .025 for a, b in zip(observed, expected)), (observed, expected)


def _inspect_parts(frame, payload):
    from hover_smoke import _verify_values
    stamp, displayed = _verify_values(frame, payload)
    record = next(r for r in payload['records'] if str(r['time']) == stamp)
    assert set(SPLIT_FIELDS).issubset(displayed), displayed
    for key in SPLIT_FIELDS:
        if record[key] is None:
            assert displayed[key]['text'] == '—', (key, displayed[key])
        else:
            assert math.isclose(float(displayed[key]['raw']), record[key], rel_tol=1e-10, abs_tol=1e-8), key
    assert 'ประมาณ' in frame.locator('#chart-inspector').inner_text()
    return stamp, record


def _stack_pixels(frame):
    targets = json.loads(frame.locator('#chart-inspector').get_attribute('data-targets'))
    volume = next(t for t in targets if t['field'] == 'volume')
    following = min(t['top'] for t in targets if t['pane'] > volume['pane'])
    # Read the rendered volume pane's base canvas, excluding the other panes
    # and axes. A transparent crosshair overlay must not hide the bar evidence.
    return frame.evaluate("""({volume, following}) => {
        const wrap=document.getElementById('chartwrap').getBoundingClientRect();
        const samples=[];
        for(const canvas of document.querySelectorAll('#chart canvas')) {
            const rect=canvas.getBoundingClientRect();
            if(rect.width<100 || Math.abs(rect.top-wrap.top-volume.top)>3)continue;
            const sx=canvas.width/rect.width,sy=canvas.height/rect.height;
            const center=(wrap.left+volume.x-rect.left)*sx;
            const y0=Math.max(0,Math.ceil((wrap.top+volume.top+1-rect.top)*sy));
            const y1=Math.min(canvas.height,Math.floor((wrap.top+following-1-rect.top)*sy));
            if(y1<=y0)continue;
            const context=canvas.getContext('2d');if(!context)continue;
            for(const shift of [-1,0,1]) {
                const x=Math.round(center+shift*sx);if(x<0||x>=canvas.width)continue;
                const pixels=context.getImageData(x,y0,1,y1-y0).data;
                const green=[],red=[];
                for(let y=0;y<y1-y0;y++) {
                    const c=pixels.slice(y*4,y*4+4);
                    if(c[3]<250)continue;
                    if(Math.abs(c[0]-38)<=2&&Math.abs(c[1]-166)<=2&&Math.abs(c[2]-154)<=2)green.push(y);
                    if(Math.abs(c[0]-239)<=2&&Math.abs(c[1]-83)<=2&&Math.abs(c[2]-80)<=2)red.push(y);
                }
                samples.push({green:green.length,red:red.length,
                    redAboveGreen:green.length>0&&red.length>0&&Math.max(...red)<Math.min(...green)});
            }
        }
        return samples.sort((a,b)=>(b.green+b.red)-(a.green+a.red))[0]||null;
    }""", {'volume': volume, 'following': following})


def verify_volume_split(page, frame, payload):
    from playwright.sync_api import expect
    from hover_smoke import _enabled
    report = verify_volume_payload(payload)
    expect(frame.locator('#volumeSplit')).to_have_attribute('aria-pressed', 'true')
    expect(frame.locator('#volume-note')).to_be_visible()
    assert 'ประมาณ' in frame.locator('#volume-note summary').inner_text()
    assert 'ไม่ใช่ข้อมูลผู้เริ่มซื้อขายจริง' in frame.locator('#volume-note summary').inner_text()
    original = {key: frame.locator('#'+key).get_attribute('aria-pressed') == 'true'
                for key in ('ema20','ema50','sma200','volume','rsi','macd','log','inspect-toggle')}
    _enabled(frame, 'volume'); _enabled(frame, 'rsi'); _enabled(frame, 'macd')
    _enabled(frame, 'inspect-toggle')
    frame.locator('#chart').scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    view = _range(frame)
    width = max(frame.locator('#chart canvas').evaluate_all('xs=>xs.map(x=>x.getBoundingClientRect().width)'))
    candidates = sorted(((i,r) for i,r in enumerate(payload['records'])
                         if view[0]+3 < i < view[1]-3 and r.get('volume')
                         and r.get('buy_volume_est') is not None
                         and .15 < r['buy_volume_est']/r['volume'] < .85),
                        key=lambda item: min(item[1]['buy_volume_est'], item[1]['sell_volume_est']), reverse=True)
    assert candidates, 'No real mixed-volume bar available for the rendering check'
    rendered = []
    visited = set()
    for index, _ in candidates[:16]:
        box = frame.locator('#chartwrap').bounding_box()
        x = width*(index-view[0])/(view[1]-view[0])
        page.mouse.move(box['x']+x, box['y']+65, steps=3)
        expect(frame.locator('#chart-inspector')).to_be_visible()
        stamp, record = _inspect_parts(frame, payload)
        if stamp in visited:
            continue
        visited.add(stamp)
        if not record['volume'] or record.get('buy_volume_est') is None:
            continue
        ratio = record['buy_volume_est']/record['volume']
        if not .15 < ratio < .85:
            continue
        pixels = _stack_pixels(frame)
        if not pixels or pixels['green']+pixels['red'] < 8:
            continue
        assert pixels['redAboveGreen'], (stamp, pixels)
        observed_ratio = pixels['green']/(pixels['green']+pixels['red'])
        assert abs(observed_ratio-ratio) <= max(.04, 3/(pixels['green']+pixels['red'])), (stamp, ratio, pixels)
        rendered.append({'time':stamp, 'pixels':pixels, 'estimated_buy_fraction':ratio})
        break
    assert rendered, 'No visible stacked red/green volume bar was verified'
    report['rendered_stacks'] = rendered
    box = frame.locator('#chartwrap').bounding_box()
    targets = json.loads(frame.locator('#chart-inspector').get_attribute('data-targets'))
    x = next(t['x'] for t in targets if t['field'] == 'volume')
    page.mouse.click(box['x']+x, box['y']+65)
    expect(frame.locator('#chart-inspector')).to_have_attribute('data-pinned', 'true')
    pinned, _ = _inspect_parts(frame, payload)
    page.mouse.move(box['x']+width*.15, box['y']+80, steps=3)
    expect(frame.locator('#chart-inspector')).to_have_attribute('data-time', pinned)
    _inspect_parts(frame, payload)
    expect(frame.locator('#volume-split-readout')).to_be_visible()
    Path('work').mkdir(exist_ok=True)
    frame.locator('#shell').screenshot(path='work/volume-split-real-bars.png')
    page.keyboard.press('Escape')
    page.mouse.move(box['x']+width*.6, box['y']+70)
    page.mouse.wheel(0,-280)
    page.wait_for_timeout(350)
    zoomed = _range(frame)
    assert zoomed[1]-zoomed[0] < view[1]-view[0]-1, (zoomed, view)
    controls = {key:frame.locator('#'+key).get_attribute('aria-pressed')
                for key in ('ema20','ema50','sma200','volume','rsi','macd','log')}
    for enabled in (False, True):
        _enabled(frame,'volumeSplit',enabled)
        page.wait_for_timeout(250)
        _same_range(frame,zoomed)
        for key,value in controls.items():
            expect(frame.locator('#'+key)).to_have_attribute('aria-pressed',value)
        if enabled:
            expect(frame.locator('#volume-split-readout')).to_be_visible()
            expect(frame.locator('#volume-note')).to_be_visible()
        else:
            expect(frame.locator('#volume-split-readout')).to_be_hidden()
            expect(frame.locator('#volume-note')).to_be_hidden()
            box = frame.locator('#chartwrap').bounding_box()
            page.mouse.move(box['x']+width*.45,box['y']+65,steps=3)
            expect(frame.locator('#chart-inspector')).to_be_visible()
            for field in SPLIT_FIELDS:
                expect(frame.locator('#chart-inspector [data-field="'+field+'"]')).to_have_count(0)
    _enabled(frame,'volume',False)
    expect(frame.locator('#volumeSplit')).to_be_disabled()
    expect(frame.locator('#volume-split-readout')).to_be_hidden()
    _same_range(frame,zoomed)
    _enabled(frame,'volume',True)
    expect(frame.locator('#volumeSplit')).to_be_enabled()
    expect(frame.locator('#volumeSplit')).to_have_attribute('aria-pressed','true')
    _same_range(frame,zoomed)
    viewport=page.viewport_size
    try:
        page.set_viewport_size({'width':390,'height':844})
        frame.locator('#chart').scroll_into_view_if_needed()
        page.wait_for_timeout(350)
        expect(frame.locator('#volume-note summary')).to_be_visible()
        expect(frame.locator('#volume-split-readout')).to_be_visible()
        narrow=frame.evaluate("""() => ({
            width:document.documentElement.clientWidth,
            scroll:document.documentElement.scrollWidth,
            chartHeight:document.getElementById('chartwrap').getBoundingClientRect().height,
            content:['volume-note','volume-split-readout'].map(id=>{
                const element=document.getElementById(id),rect=element.getBoundingClientRect();
                return {id,left:rect.left,right:rect.right,width:element.clientWidth,scroll:element.scrollWidth};
            })
        })""")
        assert narrow['width']<620 and narrow['scroll']<=narrow['width']+1, narrow
        assert narrow['chartHeight']>=200, narrow
        assert all(x['left']>=0 and x['right']<=narrow['width']+1
                   and x['scroll']<=x['width']+1 for x in narrow['content']), narrow
        frame.locator('#shell').screenshot(path='work/volume-split-mobile.png')
        report['mobile_layout']=narrow
    finally:
        page.set_viewport_size(viewport)
        page.wait_for_timeout(250)
    for key,value in original.items():
        _enabled(frame,key,value)
    frame.locator('#reset').click()
    report.update(hover_values=True,pin_values=True,approximation_visible=True,
                  toggle_preserves_zoom_and_indicators=True,volume_visibility=True)
    return report
