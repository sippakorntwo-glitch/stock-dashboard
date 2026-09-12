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
        finally:
            page.set_viewport_size(old or {'width':1440,'height':1000})
    return result
