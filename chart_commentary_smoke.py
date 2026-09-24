"""Independent browser checks of the visible explanation, without extra data calls."""
from __future__ import annotations
import json
import math
from pathlib import Path
from playwright.sync_api import expect


def close_enough(left,right):
    if right is None:
        assert left is None,(left,right)
    else:
        assert left is not None and math.isclose(left,right,rel_tol=1e-9,abs_tol=1e-9),(left,right)


def verify_mobile_chart_layout(frame):
    """Measure actual canvas bounds and reach controls inside the narrow iframe."""
    shell=frame.locator('#shell')
    old_scroll=shell.evaluate('e=>e.scrollTop')
    before_payload=frame.locator('#payload').text_content()
    before_controls=frame.locator('.controls button[aria-pressed]').evaluate_all('es=>es.map(e=>[e.id,e.getAttribute("aria-pressed")])')
    try:
        dimensions=frame.evaluate("""()=>{
          const shell=document.getElementById('shell'),wrap=document.getElementById('chartwrap'),chart=document.getElementById('chart');
          const w=wrap.getBoundingClientRect(),c=chart.getBoundingClientRect();
          return {width:shell.clientWidth,scrollWidth:shell.scrollWidth,height:shell.clientHeight,scrollHeight:shell.scrollHeight,
            wrapHeight:w.height,chartHeight:c.height,overflowY:getComputedStyle(shell).overflowY,
            canvases:[...chart.querySelectorAll('canvas')].map(e=>{const r=e.getBoundingClientRect();return {left:r.left-w.left,right:r.right-w.right,top:r.top-w.top,bottom:r.bottom-w.bottom}})};
        }""")
        assert dimensions['scrollWidth']<=dimensions['width']+2,dimensions
        assert dimensions['wrapHeight']>=349,dimensions
        assert dimensions['chartHeight']<=dimensions['wrapHeight']+2,dimensions
        assert dimensions['canvases'],dimensions
        for canvas in dimensions['canvases']:
            assert canvas['left']>=-2 and canvas['right']<=2 and canvas['top']>=-2 and canvas['bottom']<=2,dimensions
        if dimensions['scrollHeight']>dimensions['height']+2:
            assert dimensions['overflowY'] in ('auto','scroll'),dimensions
        reachable=[]
        for control in frame.locator('.controls button:visible').all():
            control.scroll_into_view_if_needed()
            expect(control).to_be_in_viewport(ratio=.9)
            if control.is_enabled():control.click(trial=True)
            reachable.append(control.get_attribute('id'))
        for selector in ('.header','#chart-levels','#chartwrap','.footer'):
            item=frame.locator(selector)
            item.scroll_into_view_if_needed()
            expect(item).to_be_in_viewport(ratio=.9)
        frame.locator('#chartwrap').scroll_into_view_if_needed()
        frame.locator('#shell').screenshot(path='work/v39-chart-mobile.png')
        assert frame.locator('#payload').text_content()==before_payload
        assert frame.locator('.controls button[aria-pressed]').evaluate_all('es=>es.map(e=>[e.id,e.getAttribute("aria-pressed")])')==before_controls
        return {**dimensions,'reachable_controls':reachable,'screenshot':'work/v39-chart-mobile.png'}
    finally:
        shell.evaluate('(e,y)=>e.scrollTop=y',old_scroll)


def verify_reference_lines(page, payload, card, *, screenshot=False):
    """Read prices back from actual Lightweight Charts price-line objects."""
    frame = None
    for candidate in page.frames:
        try:
            if not candidate.locator('#reference-levels-data').count():
                continue
            actual = candidate.eval_on_selector('#payload', 'e=>JSON.parse(e.textContent)')
            if (actual.get('ticker'),actual.get('period'),actual['records'][-1]['time']) == (payload['ticker'],payload['period'],payload['records'][-1]['time']):
                frame = candidate
                break
        except Exception:
            continue
    assert frame is not None, 'No reference levels on the selected chart'
    receipt = frame.locator('#chart-levels')
    expect(receipt).to_have_attribute('data-ticker', payload['ticker'])
    expect(receipt).to_have_attribute('data-period', payload['period'])
    expect(frame.locator('#chart canvas').first).to_be_visible()
    expected = json.loads(card.get_attribute('data-report'))['levels']
    line_data = lambda: json.loads(receipt.get_attribute('data-rendered-lines'))
    frame.wait_for_function("document.querySelector('#chart-levels').dataset.renderedLines !== undefined")
    button = frame.locator('#levels-toggle')
    original_report = card.get_attribute('data-report')
    original_payload = frame.locator('#payload').text_content()
    original_range = frame.locator('#chart').evaluate('e=>[e.dataset.rangeFrom,e.dataset.rangeTo]')
    original_controls = frame.locator('#ema20,#ema50,#sma200,#volume,#volumeSplit,#rsi,#macd,#log,#inspect-toggle').evaluate_all('els=>els.map(e=>[e.id,e.getAttribute("aria-pressed")])')
    initial_visible = button.get_attribute('aria-pressed') == 'true'
    assert len(line_data()) == 2
    for line in line_data():
        close_enough(line['price'], expected[line['key']])
        assert line['visible'] == line['axisLabelVisible'] == initial_visible
        assert f'{line["price"]:,.{payload["precision"]}f}' in receipt.inner_text()
    # Genuine clicks update only line visibility. The source snapshot, selected
    # range, indicator preferences and hover-independent commentary stay fixed.
    for visible in (not initial_visible, initial_visible):
        button.click()
        expect(button).to_have_attribute('aria-pressed', str(visible).lower())
        for line in line_data():
            assert line['visible'] == line['axisLabelVisible'] == visible
            close_enough(line['price'], expected[line['key']])
        assert frame.locator('#chart').evaluate('e=>[e.dataset.rangeFrom,e.dataset.rangeTo]') == original_range
        assert card.get_attribute('data-report') == original_report
        assert frame.locator('#payload').text_content() == original_payload
    assert frame.locator('#ema20,#ema50,#sma200,#volume,#volumeSplit,#rsi,#macd,#log,#inspect-toggle').evaluate_all('els=>els.map(e=>[e.id,e.getAttribute("aria-pressed")])') == original_controls
    result = {'actual_price_lines': line_data(), 'toggle_preserves_range_and_snapshot': True,
              'shares_commentary_calculation': True}
    if screenshot:
        if not initial_visible:
            button.click()
        page.wait_for_timeout(150)
        Path('work').mkdir(exist_ok=True)
        frame.locator('#shell').screenshot(path='work/v39-support-resistance.png')
        result['screenshot'] = 'work/v39-support-resistance.png'
        if not initial_visible:
            button.click()
    return result


def verify_chart_commentary(page,app,payload,*,screenshot=False):
    assert not payload.get('demo')
    rows=payload['records'];last=rows[-1];start=payload['visibleStart']
    app.wait_for_function("""([ticker,period,time]) => {
      const nodes=[...document.querySelectorAll('.chart-reading')];
      const node=nodes.at(-1);
      if(!node||node.closest('[data-stale="true"]'))return false;
      const report=JSON.parse(node.dataset.report);
      return report.available && report.ticker===ticker && report.period===period && report.latest_time===time;
    }""",arg=[payload['ticker'],payload['period'],last['time']],timeout=30000)
    card=app.locator('.chart-reading')
    expect(card).to_have_count(1)
    expect(card.get_by_role('heading',name='สรุปแนวโน้มและวิเคราะห์กราฟ · '+payload['ticker'],exact=True)).to_be_visible()
    data=json.loads(card.get_attribute('data-report'))
    assert data['interval']==payload['interval']
    assert data['visible_bars']==len(rows)-start
    close_enough(data['close'],last['close'])
    for key in ('ema20','ema50','sma200','rsi','macd','signal','hist'):
        close_enough(data['metrics'][key],last[key])
    expected=(last['close']/rows[start]['close']-1)*100
    close_enough(data['return_window']['percent'],expected)
    assert data['return_window']['start_time']==rows[start]['time']
    assert data['return_window']['end_time']==last['time']
    prev=rows[max(start,len(rows)-21):-1]
    assert len(prev)>=5
    close_enough(data['levels']['support'],min(r['low'] for r in prev))
    close_enough(data['levels']['resistance'],max(r['high'] for r in prev))
    assert data['levels']['bars']==len(prev)
    vols=[r['volume'] for r in rows[-21:-1]]
    if len(vols)==20 and all(v is not None and v>=0 for v in vols) and sum(vols)>0:
        close_enough(data['volume_ratio'],last['volume']/(sum(vols)/20))
    # Independently classify the ordered/slope-concordant trend; no import of
    # the application summary function in this verification.
    ema20,ema50=last['ema20'],last['ema50']
    if ema20 is None or ema50 is None:
        trend='insufficient'
    elif last['close']>ema20>ema50 and all(last[k]>rows[-6][k] for k in ('ema20','ema50')):
        trend='uptrend'
    elif last['close']<ema20<ema50 and all(last[k]<rows[-6][k] for k in ('ema20','ema50')):
        trend='downtrend'
    else:trend='mixed'
    assert data['trend']==trend
    text=card.inner_text()
    label={'uptrend':'ขาขึ้นตาม EMA','downtrend':'ขาลงตาม EMA','mixed':'สัญญาณผสม / ทิศทางยังไม่ชัด','insufficient':'ข้อมูลแนวโน้มยังไม่พอ'}[trend]
    assert label in text
    for heading in ('แนวโน้มและเส้นค่าเฉลี่ย','โมเมนตัม · RSI / MACD','แนวรับ–แนวต้านอ้างอิง','Volume และความผันผวน','เงื่อนไขที่ควรติดตามจากกราฟ'):
        assert heading in text
    assert f'{last["close"]:,.{payload["precision"]}f}' in text
    assert ('แท่ง 5 นาที' if payload['interval']=='5m' else 'แท่ง 1 วัน') in text
    assert card.evaluate('''e=>{
        const frame=document.querySelector('.st-key-research_technical iframe');
        return !!frame && !!(frame.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING);
    }'''),'Explanation is not below the chart'
    assert card.locator('table,script').count()==0
    result={'ticker':payload['ticker'],'period':payload['period'],'interval':payload['interval'],
            'trend':trend,'bar_time':last['time'],'return_percent':expected,'levels':data['levels'],
            'volume_ratio':data['volume_ratio'],'metrics':data['metrics'],'atr_pct':data['atr_pct'],
            'below_chart':True,'source_values_checked':True,'warnings':data['warnings']}
    result['chart_reference_lines']=verify_reference_lines(page,payload,card,screenshot=screenshot)
    if screenshot:
        Path('work').mkdir(exist_ok=True)
        card.screenshot(path='work/v26-chart-commentary.png')
        result['screenshot']='work/v26-chart-commentary.png'
        old=page.viewport_size
        try:
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(800)
            expect(card).to_be_visible()
            dimensions=card.evaluate('e=>({width:e.clientWidth,scroll:e.scrollWidth})')
            assert dimensions['scroll']<=dimensions['width']+4,dimensions
            card.screenshot(path='work/v26-chart-commentary-mobile.png')
            result['mobile_dimensions']=dimensions
            for frame in page.frames:
                if frame.locator('#chart-levels').count() and frame.locator('#chart-levels').get_attribute('data-ticker')==payload['ticker']:
                    result['mobile_chart_layout']=verify_mobile_chart_layout(frame)
                    break
            else:
                raise AssertionError('Mobile chart frame not found')
        finally:
            page.set_viewport_size(old or {'width':1440,'height':1000})
    return result
