"""Client-only inspection of existing chart candles; no fetches or scoring changes.

Uses Lightweight Charts 5.0's crosshair/click events and per-pane coordinates.
Transforms the known template with guarded anchors, preserving its price payload.
"""
from __future__ import annotations

_STYLE = r'''
#chart-inspector{position:absolute;z-index:10;width:274px;max-width:calc(100% - 16px);padding:11px 12px;border:1px solid #49627c;border-radius:10px;background:rgba(13,23,37,.97);box-shadow:0 5px 22px #0006;font-size:12px;line-height:1.45;pointer-events:none;overflow:auto;overscroll-behavior:contain}
#chart-inspector[hidden],#inspector-guide[hidden]{display:none!important}
#chart-inspector[data-pinned=true]{pointer-events:auto;border-color:#d6b36b}
.inspector-title{font-size:13px;font-weight:700;color:#e7eefb}.inspector-time{color:#b5c8de;margin:3px 0 5px;overflow-wrap:anywhere}.inspector-focus{color:#8fdccf;margin-bottom:5px}
.inspector-row{display:flex;justify-content:space-between;gap:14px;padding:2px 5px;border-radius:3px;font-variant-numeric:tabular-nums}.inspector-row b{font-weight:600;color:#e7eefb}.inspector-row.focus{background:#2b3e55;outline:1px solid #486383}
.inspector-hint{font-size:10px;color:#a3b4cb;border-top:1px solid #334359;margin-top:6px;padding-top:5px}
#inspector-guide{position:absolute;top:0;bottom:26px;border-left:1px dashed #d6b36b;z-index:3;pointer-events:none}
#inspect-clear[hidden]{display:none}#chartwrap:focus-visible{outline:2px solid #78a6ff;outline-offset:-2px}
@media(max-width:620px){#chart-inspector{width:250px;font-size:11px;padding:8px}.inspector-row{padding:1px 4px}}
'''

_BUTTONS = '''<button id="inspect-toggle" aria-pressed="true" title="ชี้เพื่อดูข้อมูล ณ เวลาเดียวกันของทุกเส้นที่เปิด คลิกเพื่อตรึง">ข้อมูลตามเมาส์</button>
  <button id="inspect-clear" hidden title="ยกเลิกการตรึงข้อมูล หรือกด Escape">เลิกตรึง</button>
  '''

_SCRIPT = r'''
// One isolated controller per chart iframe. Never interpolate or reuse another bar.
const inspection={enabled:true,pinned:null,hover:null};
try{inspection.enabled=sessionStorage.getItem('chart-inspector-v1')!=='off';}catch{}
const tooltip=document.createElement('div');tooltip.id='chart-inspector';tooltip.hidden=true;
tooltip.setAttribute('role','region');tooltip.setAttribute('aria-label','ข้อมูลกราฟ ณ จุดที่เลือก');
const pinGuide=document.createElement('div');pinGuide.id='inspector-guide';pinGuide.hidden=true;
el('chartwrap').append(tooltip,pinGuide);
el('chartwrap').tabIndex=0;el('chartwrap').setAttribute('aria-label','กราฟราคา ชี้เพื่ออ่าน คลิกเพื่อตรึง ลูกศรซ้ายขวาเลือกแท่ง Escape เลิกตรึง');
const inspectionNames={open:'Open · เปิด',high:'High · สูงสุด',low:'Low · ต่ำสุด',close:'Close · ปิด',volume:'Volume · ปริมาณ',ema20:'EMA 20',ema50:'EMA 50',sma200:'SMA 200',rsi:'RSI 14',macd:'MACD',signal:'Signal',hist:'MACD Histogram',rsi30:'RSI ระดับ 30',rsi70:'RSI ระดับ 70',barChange:'เปลี่ยนจากแท่งก่อน (%)'};
const inspectionIndex=new Map(rows.map((r,i)=>[String(r.time),i]));
function inspectionKey(t){return t&&typeof t==='object'?`${t.year}-${String(t.month).padStart(2,'0')}-${String(t.day).padStart(2,'0')}`:String(t);}
function inspectionTime(t){
 if(typeof t!=='number')return inspectionKey(t)+' · แท่งรายวัน';
 try{return new Intl.DateTimeFormat('sv-SE',{timeZone:p.timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(t*1000))+' · '+p.timezone;}
 catch{return new Date(t*1000).toISOString().slice(0,16).replace('T',' ')+' UTC';}
}
function inspectionFormat(k,v){
 if(!Number.isFinite(v))return '—';
 const digits=k==='volume'?0:k==='rsi'||k==='barChange'?2:['macd','signal','hist'].includes(k)?Math.max(4,p.precision):p.precision;
 const value=v.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
 return k==='barChange'?(v>0?'+':'')+value+'%':value;
}
function inspectionFields(r){
 const list=['open','high','low','close'];
 for(const k of ['ema20','ema50','sma200','volume','rsi'])if(opts[k])list.push(k);
 if(opts.macd)list.push('macd','signal','hist');
 const values=list.map(k=>[k,r[k]]),i=inspectionIndex.get(String(r.time));
 const before=i>0?rows[i-1].close:null;
 const change=Number.isFinite(before)&&before>0&&Number.isFinite(r.close)?(r.close/before-1)*100:null;
 values.push(['barChange',change]);return values;
}
function inspectionSeries(){
 const result=[['close',candles,0]];
 for(const k of ['ema20','ema50','sma200'])if(opts[k])result.push([k,series[k],0]);
 let pane=1;
 if(opts.volume)result.push(['volume',series.volume,pane++]);
 if(opts.rsi){result.push(['rsi',series.rsi,pane],['rsi30',series.rsi,pane],['rsi70',series.rsi,pane]);pane++;}
 if(opts.macd)for(const k of ['macd','signal','hist'])result.push([k,series[k],pane]);
 return result.filter(x=>x[1]);
}
function inspectionCoordinate(k,s,r){
 const v=k==='rsi30'?30:k==='rsi70'?70:r[k];
 return Number.isFinite(v)?s.priceToCoordinate(v):null;
}
function inspectionPaneTop(index){
 const pane=chart.panes()[index],node=pane&&pane.getHTMLElement();
 return node?node.getBoundingClientRect().top-el('chartwrap').getBoundingClientRect().top:0;
}
function inspectionEvent(param){
 if(!param||param.time===undefined||!param.point)return null;
 const pane=Number.isInteger(param.paneIndex)?param.paneIndex:0;
 const currentPane=chart.panes()[pane];
 if(!currentPane||param.point.x<0||param.point.x>chart.timeScale().width()||param.point.y<0||param.point.y>currentPane.getHeight())return null;
 const r=byTime.get(inspectionKey(param.time));if(!r)return null;
 let focus='',nearest=12;
 const present=inspectionSeries().filter(x=>x[2]===pane);
 for(const [k,s] of present){
  const y=inspectionCoordinate(k,s,r);if(y===null)continue;
  const distance=Math.abs(param.point.y-y);
  if(distance<nearest){focus=k;nearest=distance;}
 }
 // Candle/volume bodies can be hovered away from their closing/top coordinate.
 if(!focus&&param.hoveredSeries)focus=(present.find(x=>x[1]===param.hoveredSeries)||[])[0]||'';
 return {r,pane,focus,x:param.point.x,y:inspectionPaneTop(pane)+param.point.y};
}
function inspectionNode(tag,className,value){const n=document.createElement(tag);n.className=className;n.textContent=value;return n;}
function inspectionHide(){tooltip.hidden=true;pinGuide.hidden=true;}
function inspectionDraw(point){
 if(!inspection.enabled||!point){inspectionHide();return;}
 const r=point.r,pinned=!!inspection.pinned;
 readout(r);tooltip.replaceChildren();tooltip.hidden=false;
 tooltip.dataset.time=String(r.time);tooltip.dataset.pane=String(point.pane);tooltip.dataset.pinned=String(pinned);tooltip.dataset.focus=point.focus;
 tooltip.append(inspectionNode('div','inspector-title',p.ticker+(pinned?' · ตรึงข้อมูล':' · ข้อมูลตามเมาส์')),
                inspectionNode('div','inspector-time',inspectionTime(r.time)),
                inspectionNode('div','inspector-focus',point.focus?(inspectionNames[point.focus]+' ณ แท่งที่เลือก'):'ข้อมูล ณ แท่งที่เลือก'));
 const values=inspectionFields(r);
 if(point.focus==='rsi30'||point.focus==='rsi70')values.push([point.focus,point.focus==='rsi30'?30:70]);
 for(const [k,v] of values){
  const row=inspectionNode('div','inspector-row'+(k===point.focus?' focus':''),'');row.dataset.field=k;
  row.append(inspectionNode('span','',inspectionNames[k]),inspectionNode('b','',inspectionFormat(k,v)));
  row.lastChild.dataset.value=Number.isFinite(v)?String(v):'';tooltip.append(row);
 }
 tooltip.append(inspectionNode('div','inspector-hint',pinned?'ตรึงเฉพาะข้อมูล ไม่ใช่ราคาสด · คลิกแท่งอื่นเพื่อเปลี่ยน · Escape / เลิกตรึง':'ราคาปรับแล้ว · — = ข้อมูลไม่พอ · คลิก/แตะเพื่อตรึง'));
 const wrap=el('chartwrap'),width=wrap.clientWidth,height=wrap.clientHeight;
 tooltip.style.maxHeight=Math.max(100,height-16)+'px';
 const tw=tooltip.offsetWidth,th=tooltip.offsetHeight;
 const x=point.x+18+tw<width?point.x+18:point.x-tw-18;
 const y=point.y+14+th<height?point.y+14:point.y-th-14;
 tooltip.style.left=Math.max(8,Math.min(width-tw-8,x))+'px';
 tooltip.style.top=Math.max(8,Math.min(height-th-8,y))+'px';
 const coordinate=chart.timeScale().timeToCoordinate(r.time);
 pinGuide.hidden=!pinned||coordinate===null||coordinate<0||coordinate>chart.timeScale().width();
 if(!pinGuide.hidden)pinGuide.style.left=coordinate+'px';
 // Read-only geometry for browser regression checks; does not move the crosshair.
 tooltip.dataset.targets=JSON.stringify(inspectionSeries().map(([k,s,i])=>({field:k,pane:i,x:coordinate,y:inspectionCoordinate(k,s,r),top:inspectionPaneTop(i)})));
}
function refreshInspector(){
 el('inspect-toggle').setAttribute('aria-pressed',String(inspection.enabled));el('inspect-clear').hidden=!inspection.pinned;
 const point=inspection.pinned||inspection.hover;
 if(point){if(point.focus&&!inspectionSeries().some(x=>x[0]===point.focus))point.focus='';inspectionDraw(point);}
 else{inspectionHide();readout(last);}
}
function inspectionClear(){inspection.pinned=null;inspection.hover=null;refreshInspector();}
function attachInspector(){
 chart.subscribeCrosshairMove(param=>{
  if(inspection.pinned)return;
  inspection.hover=inspectionEvent(param);
  if(!inspection.enabled){readout(inspection.hover?inspection.hover.r:last);return;}
  refreshInspector();
 });
 chart.subscribeClick(param=>{
  if(!inspection.enabled)return;
  const point=inspectionEvent(param);if(!point)return;
  if(inspection.pinned&&inspection.pinned.r.time===point.r.time){inspection.pinned=null;inspection.hover=point;}
  else{inspection.pinned=point;inspection.hover=point;}
  refreshInspector();
 });
 chart.timeScale().subscribeVisibleLogicalRangeChange(()=>{
  if(inspection.pinned)inspectionDraw(inspection.pinned);else{inspection.hover=null;inspectionHide();readout(last);}
 });
}
el('inspect-toggle').onclick=()=>{inspection.enabled=!inspection.enabled;inspection.pinned=null;try{sessionStorage.setItem('chart-inspector-v1',inspection.enabled?'on':'off');}catch{}refreshInspector();};
el('inspect-clear').onclick=inspectionClear;
el('chartwrap').addEventListener('mouseleave',()=>{if(!inspection.pinned){inspection.hover=null;refreshInspector();}});
document.addEventListener('keydown',e=>{if(e.key==='Escape')inspectionClear();});
el('chartwrap').addEventListener('keydown',e=>{
 if(!inspection.enabled||!['ArrowLeft','ArrowRight','Enter',' '].includes(e.key))return;
 e.preventDefault();const current=inspection.pinned||inspection.hover;
 if(e.key==='Enter'||e.key===' '){inspection.pinned=inspection.pinned?null:current;refreshInspector();return;}
 const currentIndex=current?inspectionIndex.get(String(current.r.time)):rows.length-1;
 const i=Math.max(0,Math.min(rows.length-1,currentIndex+(e.key==='ArrowLeft'?-1:1)));
 const r=rows[i],x=chart.timeScale().timeToCoordinate(r.time);
 inspection.pinned={r,pane:0,focus:'close',x:x===null?20:x,y:20};refreshInspector();
});
new ResizeObserver(()=>{if(inspection.pinned)requestAnimationFrame(refreshInspector);}).observe(el('chartwrap'));
'''

_OLD_READOUT = " const parts=[];if(opts.ema20)parts.push('EMA20 '+fmt(r.ema20));if(opts.rsi)parts.push('RSI '+(Number.isFinite(r.rsi)?r.rsi.toFixed(1):'—'));if(opts.macd)parts.push('MACD '+fmt(r.macd));text('indicator-value',parts.join(' · '));"
_NEW_READOUT = " const parts=[];for(const k of ['ema20','ema50','sma200','rsi'])if(opts[k])parts.push(inspectionNames[k]+' '+inspectionFormat(k,r[k]));if(opts.macd)for(const k of ['macd','signal','hist'])parts.push(inspectionNames[k]+' '+inspectionFormat(k,r[k]));text('indicator-value',parts.join(' · '));"
_OLD_HOOK = 'chart.subscribeCrosshairMove(param=>{const v=param.seriesData.get(candles);const r=v&&byTime.get(String(v.time));readout(r||last);});'


def with_inspector(html: str) -> str:
    """Insert client-only behavior; fail explicitly if the chart template changes."""
    changes = [
        ('</style>', _STYLE + '</style>'),
        ('<span class="spacer"></span><button id="log"', _BUTTONS + '<span class="spacer"></span><button id="log"'),
        (_OLD_READOUT, _NEW_READOUT),
        ('crosshairMarkerVisible:false,priceFormat', 'crosshairMarkerVisible:true,priceFormat'),
        ("s.priceScale().applyOptions({scaleMargins:{top:.28,bottom:0}});}", "s.priceScale().applyOptions({scaleMargins:{top:.28,bottom:0}});series.volume=s;}"),
        ("s.setData(points('rsi'));", "s.setData(points('rsi'));series.rsi=s;"),
        ("hist.setData(rows.filter", "series.hist=hist;hist.setData(rows.filter"),
        ("s.setData(points(f));", "s.setData(points(f));series[f]=s;"),
        (_OLD_HOOK, 'attachInspector();'),
        ('paneLabels();readout(last);', 'paneLabels();refreshInspector();'),
        ('try{create();}catch(e){', _SCRIPT + '\ntry{create();}catch(e){'),
        ("series[name].applyOptions({visible:opts[name]});readout(last);", "series[name].applyOptions({visible:opts[name]});refreshInspector();"),
        ("el('reset').onclick=reset;", "el('reset').onclick=()=>{inspectionClear();reset();};"),
        ('ลากเพื่อเลื่อน · หมุนล้อเมาส์เพื่อซูม · ดับเบิลคลิกแกนราคาเพื่อ Auto', 'ชี้เพื่ออ่าน · คลิก/แตะเพื่อตรึง · Escape เลิกตรึง · ลากเลื่อน / ล้อเมาส์ซูม'),
    ]
    for old, new in changes:
        if html.count(old) != 1:
            raise ValueError('Chart inspection anchor changed: ' + old[:70])
        html = html.replace(old, new, 1)
    return html
