"""Reference support/resistance from the exact selected chart window.

Historical extrema are observations, not predicted turning points. The latest
bar and indicator warm-up history never contribute to the levels.
"""
from __future__ import annotations
from collections.abc import Mapping
from html import escape
import json
import math

BASIS = 'prior-selected-window-high-low-max20-min5'


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def reference_levels(payload: Mapping) -> dict:
    result = dict(support=None, resistance=None, bars=0, state='unknown',
                  support_distance_pct=None, resistance_distance_pct=None,
                  start_time=None, end_time=None, latest_time=None, close=None,
                  basis=BASIS, reason='ต้องมี High/Low ที่ใช้ได้อย่างน้อย 5 แท่งก่อนหน้าในช่วงที่เลือก')
    rows, start = payload.get('records'), payload.get('visibleStart')
    if (payload.get('demo') or payload.get('interval') not in ('1d', '5m')
            or not isinstance(rows, (list, tuple)) or not rows
            or isinstance(start, bool) or not isinstance(start, int)
            or not 0 <= start < len(rows) or not all(isinstance(r, Mapping) for r in rows)):
        return result
    times = [r.get('time') for r in rows]
    try:
        if any(t is None or isinstance(t, bool) for t in times) or any(a >= b for a, b in zip(times, times[1:])):
            return result
    except TypeError:
        return result
    prior = rows[max(start, len(rows) - 21):-1]
    result['bars'] = len(prior)
    close = _positive(rows[-1].get('close'))
    if len(prior) < 5 or close is None:
        return result
    lows = [_positive(r.get('low')) for r in prior]
    highs = [_positive(r.get('high')) for r in prior]
    if any(v is None for v in lows + highs) or any(lo > hi for lo, hi in zip(lows, highs)):
        result['reason'] = 'High/Low ในกรอบอ้างอิงไม่สมบูรณ์ จึงยังไม่แสดงเส้นแนวรับ–แนวต้าน'
        return result
    support, resistance = min(lows), max(highs)
    support_distance, resistance_distance = (support / close - 1) * 100, (resistance / close - 1) * 100
    if not all(math.isfinite(v) for v in (support_distance, resistance_distance)):
        return result
    result.update(support=support, resistance=resistance, close=close,
                  state='breakout' if close > resistance else 'breakdown' if close < support else 'inside',
                  support_distance_pct=support_distance, resistance_distance_pct=resistance_distance,
                  start_time=prior[0]['time'], end_time=prior[-1]['time'], latest_time=rows[-1]['time'], reason='')
    return result


def level_names(levels):
    return ('แนวรับเดิม (หลุดแล้ว)' if levels['state'] == 'breakdown' else 'แนวรับอ้างอิง',
            'แนวต้านเดิม (ทะลุแล้ว)' if levels['state'] == 'breakout' else 'แนวต้านอ้างอิง')


def _precision(payload):
    value = payload.get('precision', 2)
    return max(2, min(8, value)) if isinstance(value, int) and not isinstance(value, bool) else 2


def level_caption(levels, precision=2):
    if levels['support'] is None:
        return levels['reason']
    support_name, resistance_name = level_names(levels)
    return (f'{support_name} {levels["support"]:,.{precision}f} ({levels["support_distance_pct"]:+.2f}%) · '
            f'{resistance_name} {levels["resistance"]:,.{precision}f} ({levels["resistance_distance_pct"]:+.2f}%) '
            '· ระยะจาก Close ล่าสุด')


_STYLE = '''
#chart-levels{padding:3px 20px 8px;font-size:12px;line-height:1.6;color:#c6d4e8;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
#chart-levels[data-visible=false]{color:#9aa9bd}#levels-toggle[aria-pressed=true]{border-color:#62bfa9}
@media(max-width:620px){#chart-levels{padding-left:14px;padding-right:14px;font-size:11px}}
'''
_BUTTON = '<button id="levels-toggle" aria-pressed="true" title="แสดง/ซ่อน High/Low สูงสุด 20 แท่งก่อนหน้าในช่วงที่เลือก ไม่รวมแท่งล่าสุด">แนวรับ / แนวต้าน</button>\n  '
_SCRIPT = r'''
// The source is the same immutable calculation as the commentary below this chart.
const referenceLevels=JSON.parse(el('reference-levels-data').textContent);
let referenceLevelLines=[],referenceLevelsVisible=true;
try{referenceLevelsVisible=sessionStorage.getItem('chart-reference-levels-v1')!=='off';}catch{}
function updateReferenceLevelReceipt(){
 const receipt=el('chart-levels'),button=el('levels-toggle');
 const rendered=referenceLevelLines.map(({key,line})=>({key,price:line.options().price,visible:line.options().lineVisible,axisLabelVisible:line.options().axisLabelVisible}));
 receipt.dataset.renderedLines=JSON.stringify(rendered);
 receipt.dataset.visible=String(referenceLevelsVisible&&rendered.length>0);
 button.disabled=referenceLevels.support===null;
 button.setAttribute('aria-pressed',receipt.dataset.visible);
}
function attachReferenceLevels(){
 referenceLevelLines=[];
 if(referenceLevels.support!==null){
  const names={support:referenceLevels.state==='breakdown'?'รับเดิม (หลุด)':'รับอ้างอิง',resistance:referenceLevels.state==='breakout'?'ต้านเดิม (ทะลุ)':'ต้านอ้างอิง'};
  for(const key of ['support','resistance']){
   const line=candles.createPriceLine({price:referenceLevels[key],color:key==='support'?'#57d5b5':'#ffbd69',lineWidth:2,lineStyle:L.LineStyle.Dashed,title:names[key],lineVisible:referenceLevelsVisible,axisLabelVisible:referenceLevelsVisible});
   referenceLevelLines.push({key,line});
  }
 }
 updateReferenceLevelReceipt();
}
el('levels-toggle').onclick=()=>{
 referenceLevelsVisible=!referenceLevelsVisible;
 try{sessionStorage.setItem('chart-reference-levels-v1',referenceLevelsVisible?'on':'off');}catch{}
 for(const {line} of referenceLevelLines)line.applyOptions({lineVisible:referenceLevelsVisible,axisLabelVisible:referenceLevelsVisible});
 updateReferenceLevelReceipt();
};
'''


def with_levels(html: str, payload: Mapping) -> str:
    """Add independent, togglable price lines without rebuilding the chart.

    Compatible with the original template and with performance/inspector hooks.
    No provider calls, new price-series data or scoring changes.
    """
    if 'id="reference-levels-data"' in html:
        raise ValueError('Chart reference levels already installed')
    levels = reference_levels(payload)
    encoded = json.dumps(levels, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    receipt = (f'<div id="chart-levels" role="note" data-ticker="{escape(str(payload.get("ticker", "")), quote=True)}" '
               f'data-period="{escape(str(payload.get("period", "")), quote=True)}" '
               f'data-state="{levels["state"]}">{escape(level_caption(levels, _precision(payload)))}</div>\n '
               f'<script type="application/json" id="reference-levels-data">{encoded}</script>\n ')
    candle_anchor = 'candles.setData(rows.map(r=>({time:r.time,open:r.open,high:r.high,low:r.low,close:r.close})));'
    changes = [
        ('</style>', _STYLE + '</style>'),
        ('<span class="spacer"></span><button id="log"', _BUTTON + '<span class="spacer"></span><button id="log"'),
        ('<div id="info"></div>', '<div id="info"></div>\n ' + receipt),
        (candle_anchor, candle_anchor + '\n attachReferenceLevels();'),
        ('try{create();}catch(e){', _SCRIPT + '\ntry{create();}catch(e){'),
    ]
    for old, new in changes:
        if html.count(old) != 1:
            raise ValueError('Chart reference-level anchor changed: ' + old[:70])
        html = html.replace(old, new, 1)
    return html
