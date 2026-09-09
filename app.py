from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

PERIODS = ["1 วัน", "5 วัน", "7 วัน", "1 เดือน", "3 เดือน", "6 เดือน", "1 ปี", "2 ปี", "3 ปี"]
CDN = "https://unpkg.com/lightweight-charts@5.0.9/dist/lightweight-charts.standalone.production.js"


@st.cache_data(ttl=300, show_spinner=False)
def load_chart_history(ticker: str, interval: str = "1d") -> tuple[pd.DataFrame, str]:
    """Load warm-up history; missing or invalid data is reported to the caller."""
    period = "5y" if interval == "1d" else "1mo"
    obj = yf.Ticker(ticker)
    frame = obj.history(period=period, interval=interval, auto_adjust=True,
                        actions=False, prepost=False, timeout=20)
    if frame is None or frame.empty:
        raise ValueError("แหล่งข้อมูลไม่ส่งราคากลับมา ลองตรวจชื่อหุ้นหรือกดโหลดใหม่ภายหลัง")
    return normalize_history(frame), datetime.now(timezone.utc).isoformat()


def normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate chronological, unique, finite OHLC; preserve missing volume."""
    f = frame.copy()
    if isinstance(f.columns, pd.MultiIndex):
        # This entry point intentionally accepts only one ticker.
        if len(f.columns.get_level_values(-1).unique()) != 1:
            raise ValueError("ต้องส่งข้อมูลหุ้นทีละตัวให้กราฟ")
        f.columns = f.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close"]
    if not set(required).issubset(f.columns):
        raise ValueError("ข้อมูลราคาไม่ครบ Open / High / Low / Close")
    f.index = pd.DatetimeIndex(pd.to_datetime(f.index))
    f = f.loc[~f.index.isna()].sort_index()
    f = f.loc[~f.index.duplicated(keep="last")]
    for col in required + ["Volume"]:
        if col not in f:
            f[col] = np.nan
        f[col] = pd.to_numeric(f[col], errors="coerce")
    valid = np.isfinite(f[required]).all(axis=1)
    valid &= f["High"] >= f[["Open", "Close", "Low"]].max(axis=1)
    valid &= f["Low"] <= f[["Open", "Close", "High"]].min(axis=1)
    f = f.loc[valid].copy()
    f.loc[(f.Volume < 0) | ~np.isfinite(f.Volume), "Volume"] = np.nan
    if f.empty:
        raise ValueError("ไม่พบแท่งราคาที่สมบูรณ์")
    return f


def wilder_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI with SMA seed; insufficient history remains missing."""
    out = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) <= length:
        return out
    delta = close.diff()
    gain = delta.clip(lower=0).to_numpy()
    loss = (-delta.clip(upper=0)).to_numpy()
    avg_gain = float(np.mean(gain[1:length + 1]))
    avg_loss = float(np.mean(loss[1:length + 1]))
    for i in range(length, len(close)):
        if i > length:
            avg_gain = (avg_gain * (length - 1) + gain[i]) / length
            avg_loss = (avg_loss * (length - 1) + loss[i]) / length
        out.iloc[i] = (50.0 if avg_gain == avg_loss == 0 else
                       100.0 if avg_loss == 0 else
                       100 - 100 / (1 + avg_gain / avg_loss))
    return out


def build_payload(frame: pd.DataFrame, ticker: str, period: str,
                  interval: str, fetched_at: str = "") -> dict:
    f = normalize_history(frame)
    close = f.Close
    f["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    f["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    f["sma200"] = close.rolling(200, min_periods=200).mean()
    f["macd"] = (close.ewm(span=12, adjust=False, min_periods=12).mean()
                 - close.ewm(span=26, adjust=False, min_periods=26).mean())
    f["signal"] = f.macd.ewm(span=9, adjust=False, min_periods=9).mean()
    f["hist"] = f.macd - f.signal
    f["rsi"] = wilder_rsi(close)
    tz = str(f.index.tz) if f.index.tz is not None else "UTC"
    intraday = interval != "1d"
    if intraday and f.index.tz is None:
        raise ValueError("ข้อมูลระหว่างวันไม่มีเขตเวลา จึงยังแสดงเวลาตลาดอย่างถูกต้องไม่ได้")
    if period in ["1 วัน", "5 วัน", "7 วัน"]:
        count = int(period.split()[0])
        sessions = f.index.normalize().unique()
        begin = sessions[max(0, len(sessions) - count)]
    else:
        number, unit = period.split()
        offset = pd.DateOffset(months=int(number)) if unit == "เดือน" else pd.DateOffset(years=int(number))
        begin = f.index[-1] - offset
    visible_start = int(f.index.searchsorted(begin))
    # Retain earlier observations so dragging left reveals historical candles.
    records = []
    for stamp, row in f.iterrows():
        entry = {"time": int(stamp.timestamp()) if intraday else stamp.strftime("%Y-%m-%d")}
        for col in ["Open", "High", "Low", "Close", "Volume", "ema20", "ema50", "sma200", "macd", "signal", "hist", "rsi"]:
            value = row[col]
            entry[col.lower()] = float(value) if pd.notna(value) and math.isfinite(value) else None
        records.append(entry)
    precision = 2 if close.iloc[-1] >= 1 else 4 if close.iloc[-1] >= .01 else 6
    return {"ticker": ticker, "period": period, "interval": interval, "timezone": tz,
            "intraday": intraday, "precision": precision, "records": records,
            "visibleStart": visible_start, "fetchedAt": fetched_at,
            "lastBar": f.index[-1].strftime("%Y-%m-%d %H:%M %Z" if intraday else "%Y-%m-%d"),
            "positive": bool((f.Low > 0).all()), "demo": False}


def build_chart_html(payload: dict) -> str:
    # JSON is used only as data. Escape HTML/script terminators supplied in labels.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return HTML.replace("__PAYLOAD__", encoded).replace("__CDN__", CDN)


def render_trading_chart(ticker: str, *, key: str = "trading_chart") -> None:
    """Render inside an existing full-width Streamlit container or tab."""
    ticker = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}", ticker):
        st.warning("กรุณาระบุสัญลักษณ์หุ้นที่ถูกต้อง เช่น AAPL หรือ PTT.BK")
        return
    left, right = st.columns([5, 1])
    with left:
        period = st.radio("ช่วงเวลาที่แสดง", PERIODS, index=3, horizontal=True, key=f"{key}_period")
    with right:
        refresh = st.button("โหลดข้อมูลใหม่", key=f"{key}_refresh")
    interval = "5m" if period == "1 วัน" else "15m" if period in ["5 วัน", "7 วัน"] else "1d"
    if refresh:
        load_chart_history.clear(ticker, interval)
    try:
        with st.spinner(f"กำลังโหลดกราฟ {ticker}…"):
            history, fetched_at = load_chart_history(ticker, interval)
            payload = build_payload(history, ticker, period, interval, fetched_at)
    except Exception as exc:
        st.error(f"ยังโหลดกราฟ {ticker} ไม่ได้: {exc}")
        return
    html = build_chart_html(payload)
    if hasattr(st, "iframe"):
        st.iframe(html, height=900)
    else:
        components.html(html, height=900, scrolling=False)


HTML = r'''<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;background:#10141d;color:#dde3ef;font:14px system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif}
button{font:inherit;cursor:pointer;color:#aab7cd;background:transparent;border:1px solid #2a3343;border-radius:6px;padding:7px 12px;white-space:nowrap}
button:hover{background:#252d3e;color:#fff}button[aria-pressed=true]{background:#253c65;border-color:#446faf;color:#c4d8ff}
button:focus-visible,a:focus-visible{outline:2px solid #78a6ff;outline-offset:2px}button:disabled{opacity:.4;cursor:not-allowed}
#shell{border:1px solid #293143;border-radius:12px;overflow:hidden;height:888px;display:flex;flex-direction:column}
.header{display:flex;align-items:center;gap:18px;padding:18px 20px 12px;flex-wrap:wrap}.symbol{font-size:24px;font-weight:700;letter-spacing:.4px}
.meta{font-size:12px;color:#94a3bb;margin-top:4px}.quote{font-size:25px;font-weight:650;font-variant-numeric:tabular-nums}.change{font-size:13px;margin-top:4px}
.tag{margin-left:auto;font-size:12px;color:#9bacc4;padding:6px 10px;border:1px solid #303b4d;border-radius:5px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 20px 13px;border-bottom:1px solid #293143}.spacer{flex:1}
.ohlc{display:flex;gap:14px;padding:12px 20px 4px;flex-wrap:wrap;min-height:38px;font-variant-numeric:tabular-nums;font-size:13px;color:#9caec7}.ohlc b{font-weight:550;color:#dce5f4;margin-left:4px}
#chartwrap{position:relative;flex:1;min-height:200px}#chart{width:100%;height:100%}.panel-label{position:absolute;left:14px;color:#aebbd0;font-size:12px;pointer-events:none;padding:4px 8px;background:#10141de8;z-index:2;border-radius:4px}
.footer{border-top:1px solid #293143;padding:11px 18px;color:#8d9eb8;font-size:11px;display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap}.footer a{color:#a9bddb;text-decoration:none}.footer a:hover{text-decoration:underline}
#error{padding:30px;color:#f2b6b9;display:none}#info{color:#8c9db6;font-size:11px;padding:4px 20px 8px}
@media(max-width:620px){.header{gap:12px;padding:14px}.symbol{font-size:20px}.quote{font-size:21px}.tag{margin-left:0}.controls{padding:8px 12px;gap:6px}button{font-size:12px;padding:7px 9px}.ohlc{padding-left:14px;gap:9px}.footer{font-size:10px}}
</style></head><body>
<div id="shell">
 <div class="header"><div><div class="symbol" id="symbol"></div><div class="meta" id="meta"></div></div>
 <div><div class="quote" id="price"></div><div class="change" id="change"></div></div><div class="tag" id="status"></div></div>
 <div class="controls">
  <button id="ema20" aria-pressed="true" title="เส้นค่าเฉลี่ย EMA 20 แท่ง">EMA 20</button>
  <button id="ema50" aria-pressed="false" title="เส้นค่าเฉลี่ย EMA 50 แท่ง">EMA 50</button>
  <button id="sma200" aria-pressed="false" title="เส้นค่าเฉลี่ย SMA 200 แท่ง">SMA 200</button>
  <button id="volume" aria-pressed="true" title="ปริมาณซื้อขาย">Volume</button>
  <button id="rsi" aria-pressed="false" title="เปิด RSI 14 ในแผงด้านล่าง">RSI</button>
  <button id="macd" aria-pressed="false" title="เปิด MACD 12,26,9 ในแผงด้านล่าง">MACD</button>
  <span class="spacer"></span><button id="log" aria-pressed="false" title="สเกลลอการิทึมช่วยดูช่วงที่ราคาต่างกันมาก">Log</button>
  <button id="reset" title="กลับสู่ช่วงเวลาที่เลือกและปรับแกนราคาอัตโนมัติ">คืนมุมมอง</button>
 </div>
 <div class="ohlc"><span id="bar-time"></span><span>O<b id="o"></b></span><span>H<b id="h"></b></span><span>L<b id="l"></b></span><span>C<b id="c"></b></span><span>Vol<b id="v"></b></span><span id="indicator-value"></span></div>
 <div id="info"></div><div id="chartwrap"><div id="chart"></div><div id="labels"></div><div id="error" role="alert"></div></div>
 <div class="footer"><span>ลากเพื่อเลื่อน · หมุนล้อเมาส์เพื่อซูม · ดับเบิลคลิกแกนราคาเพื่อ Auto</span>
 <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" title="TradingView Lightweight Charts™. Copyright (c) 2025 TradingView, Inc.">TradingView Lightweight Charts™</a></div>
</div>
<script type="application/json" id="payload">__PAYLOAD__</script>
<script src="__CDN__"></script>
<script>
(()=>{'use strict';
const p=JSON.parse(document.getElementById('payload').textContent), rows=p.records;
const el=id=>document.getElementById(id), text=(id,value)=>el(id).textContent=value;
const green='#26a69a',red='#ef5350';
function failure(message){el('error').style.display='block';el('error').textContent=message;el('chart').style.display='none';}
if(!window.LightweightCharts){failure('โหลดตัวกราฟไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ unpkg.com แล้วเปิดหน้าใหม่');return;}
if(!rows.length){failure('ไม่พบข้อมูลราคา');return;}
const L=window.LightweightCharts,last=rows.at(-1),prev=rows.at(-2);
const fmt=x=>Number.isFinite(x)?x.toLocaleString('en-US',{minimumFractionDigits:p.precision,maximumFractionDigits:p.precision}):'—';
const volFmt=x=>Number.isFinite(x)?Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(x):'—';
function dateFmt(t,short=false){
 if(typeof t==='string')return t;
 if(typeof t==='object')return `${t.year}-${String(t.month).padStart(2,'0')}-${String(t.day).padStart(2,'0')}`;
 const opt=short?{hour:'2-digit',minute:'2-digit',hour12:false}:{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false};
 try{return new Intl.DateTimeFormat('en-GB',{...opt,timeZone:p.timezone}).format(new Date(t*1000));}
 catch{return new Date(t*1000).toISOString().slice(0,16).replace('T',' ')+' UTC';}
}
text('symbol',p.ticker);text('meta',`${p.period} · แท่ง ${p.interval==='1d'?'1 วัน':p.interval==='5m'?'5 นาที':'15 นาที'} · ${p.timezone}`);
text('price',fmt(last.close));text('status',p.demo?'ข้อมูลจำลองสำหรับดูหน้าตา':'Yahoo Finance · ราคาปรับแล้ว');
if(prev && prev.close!==0){const d=last.close-prev.close;const pct=d/prev.close*100;text('change',`${d>=0?'+':''}${fmt(d)} (${pct>=0?'+':''}${pct.toFixed(2)}%) จากแท่งก่อน`);el('change').style.color=d>=0?green:red;}
text('info',`แท่งล่าสุด: ${p.lastBar} · ${p.intraday?'นับวันซื้อขายที่มีข้อมูล · ':''}ข้อมูลตามแหล่งราคา ไม่ใช่ราคาสตรีมสด`);
const opts={ema20:true,ema50:false,sma200:false,volume:true,rsi:false,macd:false,log:false};
// UI preferences persist across the parent app's five-minute refresh where storage is available.
try{Object.assign(opts,JSON.parse(sessionStorage.getItem('chart-prefs-v1')||'{}'));}catch{}
if(!p.positive){opts.log=false;el('log').disabled=true;el('log').title='Log ใช้ได้เมื่อราคามากกว่า 0';}
let chart,candles,series={},currentRange=null;
const byTime=new Map(rows.map(r=>[String(r.time),r]));
const points=field=>rows.filter(r=>Number.isFinite(r[field])).map(r=>({time:r.time,value:r[field]}));
function readout(r){
 text('bar-time',dateFmt(r.time));for(const k of ['o','h','l','c'])text(k,fmt(r[{o:'open',h:'high',l:'low',c:'close'}[k]]));
 text('v',volFmt(r.volume));el('c').style.color=r.close>=r.open?green:red;
 const parts=[];if(opts.ema20)parts.push('EMA20 '+fmt(r.ema20));if(opts.rsi)parts.push('RSI '+(Number.isFinite(r.rsi)?r.rsi.toFixed(1):'—'));if(opts.macd)parts.push('MACD '+fmt(r.macd));text('indicator-value',parts.join(' · '));
}
function paneLabels(){
 el('labels').replaceChildren();if(!chart)return;let top=0;
 const names=['ราคา',...(opts.volume?['Volume']:[]),...(opts.rsi?['RSI 14']:[]),...(opts.macd?['MACD 12,26,9']:[])];
 chart.panes().forEach((pane,i)=>{if(i){const e=document.createElement('div');e.className='panel-label';e.style.top=(top+5)+'px';e.textContent=names[i];el('labels').appendChild(e);}top+=pane.getHeight()+1;});
}
function reset(){chart.priceScale('right').applyOptions({autoScale:true,mode:opts.log?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal});chart.timeScale().setVisibleLogicalRange({from:p.visibleStart-.8,to:rows.length+3});}
function create(){
 if(chart){currentRange=chart.timeScale().getVisibleLogicalRange();chart.remove();}
 el('chart').replaceChildren();series={};
 const height=Math.max(350,el('chartwrap').clientHeight);
 chart=L.createChart(el('chart'),{width:el('chart').clientWidth,height,
  layout:{background:{type:'solid',color:'#10141d'},textColor:'#a3b2c9',fontSize:13,fontFamily:'Segoe UI, Tahoma, sans-serif',attributionLogo:true,panes:{separatorColor:'#2a3343',separatorHoverColor:'#42618e',enableResize:true}},
  grid:{vertLines:{color:'#1b2332'},horzLines:{color:'#1e2838'}},
  crosshair:{mode:L.CrosshairMode.Normal,vertLine:{color:'#75849a',labelBackgroundColor:'#354259'},horzLine:{color:'#75849a',labelBackgroundColor:'#354259'}},
  rightPriceScale:{borderColor:'#2a3343',autoScale:true,mode:opts.log?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal,scaleMargins:{top:.1,bottom:.1},minimumWidth:76},leftPriceScale:{visible:false},
  timeScale:{borderColor:'#2a3343',rightOffset:4,barSpacing:12,minBarSpacing:2,timeVisible:p.intraday,secondsVisible:false,allowShiftVisibleRangeOnWhitespaceReplacement:false},
  localization:{locale:'en-US',timeFormatter:t=>dateFmt(t)},
  handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true,axisDoubleClickReset:true}
 });
 if(p.intraday)chart.timeScale().applyOptions({tickMarkFormatter:(time,type)=>dateFmt(time,type===L.TickMarkType.Time||type===L.TickMarkType.TimeWithSeconds)});
 const priceFormat={type:'price',precision:p.precision,minMove:10**(-p.precision)};
 candles=chart.addSeries(L.CandlestickSeries,{upColor:green,downColor:red,wickUpColor:green,wickDownColor:red,borderVisible:false,priceFormat,priceLineVisible:true,lastValueVisible:true});
 candles.setData(rows.map(r=>({time:r.time,open:r.open,high:r.high,low:r.low,close:r.close})));
 for(const [field,color] of [['ema20','#f3b34c'],['ema50','#5b9cf6'],['sma200','#b39ddb']]){
  // Only the candle range sets the price scale. Distant averages cannot flatten price.
  series[field]=chart.addSeries(L.LineSeries,{color,lineWidth:2,visible:opts[field],priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,priceFormat,autoscaleInfoProvider:()=>null});
  series[field].setData(points(field));
 }
 let pane=1;
 if(opts.volume){const s=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false},pane++);s.setData(rows.filter(r=>r.volume!==null).map(r=>({time:r.time,value:r.volume,color:r.close>=r.open?'#26a69a99':'#ef535099'})));s.priceScale().applyOptions({scaleMargins:{top:.28,bottom:0}});}
 if(opts.rsi){const s=chart.addSeries(L.LineSeries,{color:'#b39ddb',lineWidth:2,priceLineVisible:false,lastValueVisible:true,priceFormat:{type:'price',precision:1,minMove:.1},autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:100}})},pane++);s.setData(points('rsi'));for(const v of [30,70])s.createPriceLine({price:v,color:'#596578',lineWidth:1,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true});}
 if(opts.macd){const idx=pane++;const hist=chart.addSeries(L.HistogramSeries,{priceLineVisible:false,lastValueVisible:false},idx);hist.setData(rows.filter(r=>r.hist!==null).map(r=>({time:r.time,value:r.hist,color:r.hist>=0?'#26a69ab3':'#ef5350b3'})));for(const [f,color] of [['macd','#5b9cf6'],['signal','#f3b34c']]){const s=chart.addSeries(L.LineSeries,{color,lineWidth:2,priceLineVisible:false,lastValueVisible:false},idx);s.setData(points(f));}}
 const panes=chart.panes();let index=1;
 if(opts.volume)panes[index++].setHeight(100);
 if(opts.rsi)panes[index++].setHeight(135);
 if(opts.macd)panes[index++].setHeight(135);
 if(currentRange)chart.timeScale().setVisibleLogicalRange(currentRange);else reset();
 chart.subscribeCrosshairMove(param=>{const v=param.seriesData.get(candles);const r=v&&byTime.get(String(v.time));readout(r||last);});
 for(const name of Object.keys(opts))el(name).setAttribute('aria-pressed',String(opts[name]));
 paneLabels();readout(last);
}
try{create();}catch(e){failure('แสดงกราฟไม่สำเร็จ: '+e.message);return;}
for(const name of Object.keys(opts))el(name).onclick=()=>{
 opts[name]=!opts[name];el(name).setAttribute('aria-pressed',String(opts[name]));
 try{sessionStorage.setItem('chart-prefs-v1',JSON.stringify(opts));}catch{}
 if(['ema20','ema50','sma200'].includes(name)){series[name].applyOptions({visible:opts[name]});readout(last);}
 else if(name==='log'){chart.priceScale('right').applyOptions({mode:opts.log?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal,autoScale:true});}
 else create();
};
el('reset').onclick=reset;
new ResizeObserver(()=>{if(chart){chart.resize(el('chart').clientWidth,Math.max(350,el('chartwrap').clientHeight));paneLabels();}}).observe(el('chartwrap'));
document.addEventListener('pointerup',()=>setTimeout(paneLabels,30));
})();
</script></body></html>'''


if __name__ == "__main__":
    st.set_page_config(page_title="Stock Chart", layout="wide")
    st.title("กราฟหุ้น")
    symbol = st.text_input("Ticker", "AAPL").strip().upper()
    if symbol:
        render_trading_chart(symbol)
