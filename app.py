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
def _cached_chart_history(ticker: str, interval: str = "1d"):
    # Cache failures too: a provider outage must not trigger the same request
    # independently in every tab. The refresh buttons explicitly clear this.
    try:
        period = "5y" if interval == "1d" else "1mo"
        frame = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True,
                                         actions=False, prepost=False, timeout=20)
        if frame is None or frame.empty:
            raise ValueError("แหล่งข้อมูลไม่ส่งราคากลับมา ลองตรวจชื่อหุ้นหรือกดโหลดใหม่ภายหลัง")
        return normalize_history(frame), datetime.now(timezone.utc).isoformat(), None
    except Exception as exc:
        return None, "", str(exc)


def load_chart_history(ticker: str, interval: str = "1d") -> tuple[pd.DataFrame, str]:
    frame, fetched_at, error = _cached_chart_history(ticker, interval)
    if error is not None:
        raise ValueError(error)
    return frame, fetched_at


load_chart_history.clear = _cached_chart_history.clear


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
 const panes=chart.panes();
 const weights=[Math.max(320,height-30-(opts.volume?95:0)-(opts.rsi?140:0)-(opts.macd?140:0)),...(opts.volume?[95]:[]),...(opts.rsi?[140]:[]),...(opts.macd?[140]:[])];
 panes.forEach((pane,i)=>pane.setStretchFactor(weights[i]));
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


# ---------------------------------------------------------------------------
# Full dashboard: watchlist, filters, fundamentals, analysis, risk and comparisons.
# The scanner and its CSV remain independent of the display application.
# ---------------------------------------------------------------------------
from io import BytesIO
import inspect
from pathlib import Path
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

WATCHLIST_FILE = Path(__file__).resolve().parent / "daily_watchlist.csv"
NUMERIC_COLUMNS = ["Close", "Historical_Return", "Vol_Ratio", "RSI_14", "MACD",
                   "MACD_Signal", "ATR", "Suggested_Stop", "EMA20", "EMA50", "SMA200"]


def width_options(element):
    """Use the modern width API when present, retain older Streamlit support."""
    parameter = inspect.signature(element).parameters.get("width")
    return {"width": "stretch"} if parameter is not None and parameter.default == "stretch" else {"use_container_width": True}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def show_number(value, suffix="", digits=2):
    n = number(value)
    return f"{n:,.{digits}f}{suffix}" if n is not None else "ไม่มีข้อมูล"


def compact_number(value):
    n = number(value)
    if n is None:
        return "ไม่มีข้อมูล"
    for scale, label in [(1e12, "T"), (1e9, "B"), (1e6, "M")]:
        if abs(n) >= scale:
            return f"{n / scale:,.2f}{label}"
    return f"{n:,.0f}"


def parse_watchlist(data: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(data), encoding="utf-8-sig")
    frame.columns = frame.columns.astype(str).str.strip()
    if "Ticker" not in frame and "Symbol" in frame:
        frame = frame.rename(columns={"Symbol": "Ticker"})
    if "Ticker" not in frame:
        raise ValueError("ไฟล์ต้องมีคอลัมน์ Ticker หรือ Symbol")
    frame = frame.loc[frame.Ticker.notna()].copy()
    frame["Ticker"] = frame.Ticker.astype(str).str.strip().str.upper()
    frame = frame.loc[frame.Ticker.ne("")].drop_duplicates("Ticker", keep="last")
    if "Asset_Type" not in frame:
        frame["Asset_Type"] = "ไม่ระบุ"
    frame["Asset_Type"] = frame.Asset_Type.fillna("ไม่ระบุ").astype(str)
    if "Status" not in frame:
        frame["Status"] = "ไม่มีข้อมูล"
    frame["Status"] = frame.Status.fillna("ไม่มีข้อมูล").astype(str).str.strip().str.upper()
    for col in NUMERIC_COLUMNS:
        if col not in frame:
            frame[col] = np.nan
        elif not pd.api.types.is_numeric_dtype(frame[col]):
            frame[col] = pd.to_numeric(
                frame[col].astype(str).str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False).str.replace("%", "", regex=False), errors="coerce")
        frame[col] = frame[col].replace([np.inf, -np.inf], np.nan)
    return frame.reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def read_watchlist(path: str, modified_ns: int, file_size: int) -> pd.DataFrame:
    # modified_ns and file_size invalidate the cache after the scanner writes.
    return parse_watchlist(Path(path).read_bytes())


def filter_watchlist(frame, asset_type, pass_only, query, low, high, rsi_range,
                     min_return, keep_missing):
    result = frame.copy()
    if asset_type != "ทั้งหมด":
        result = result.loc[result.Asset_Type.eq(asset_type)]
    if pass_only:
        result = result.loc[result.Status.eq("PASS")]
    if query:
        result = result.loc[result.Ticker.str.contains(query.strip().upper(), regex=False, na=False)]
    for col, mask in [("Close", result.Close.between(low, high)),
                      ("RSI_14", result.RSI_14.between(*rsi_range)),
                      ("Historical_Return", result.Historical_Return.ge(min_return))]:
        if keep_missing:
            mask = mask | result[col].isna()
        result = result.loc[mask.reindex(result.index, fill_value=False)]
    return result


@st.cache_data(ttl=900, show_spinner=False)
def load_fundamentals(ticker):
    result = yf.Ticker(ticker).get_info()
    if not isinstance(result, dict):
        raise ValueError("แหล่งข้อมูลไม่ได้ส่งข้อมูลพื้นฐานกลับมา")
    return result


def daily_snapshot(history):
    if history is None or history.empty:
        return {}
    payload = build_payload(history, "", "1 เดือน", "1d")
    row = payload["records"][-1]
    f = normalize_history(history)
    previous = f.Close.shift(1)
    true_range = pd.concat([f.High-f.Low, (f.High-previous).abs(), (f.Low-previous).abs()], axis=1).max(axis=1)
    atr = None
    if len(true_range) >= 14:
        atr = float(true_range.iloc[:14].mean())
        for value in true_range.iloc[14:]:
            atr = (atr * 13 + float(value)) / 14
    average_vol = number(f.Volume.iloc[-21:-1].mean()) if len(f) >= 21 else None
    volume = number(f.Volume.iloc[-1])
    ratio = volume / average_vol if average_vol and volume is not None else None
    return {"Close": row["close"], "EMA20": row["ema20"], "EMA50": row["ema50"],
            "SMA200": row["sma200"], "RSI_14": row["rsi"], "MACD": row["macd"],
            "MACD_Signal": row["signal"], "ATR": atr, "Vol_Ratio": ratio,
            "Bar_Date": f.index[-1].strftime("%Y-%m-%d")}


def build_analysis(snapshot, selected_row, info):
    metrics, sources = {}, {}
    for col in NUMERIC_COLUMNS:
        fresh = number(snapshot.get(col))
        old = number(selected_row.get(col))
        metrics[col] = fresh if fresh is not None else old
        sources[col] = "กราฟรายวัน" if fresh is not None else "CSV" if old is not None else "—"
    # Use a quote from the fundamentals response for target-price comparison.
    quote = number(info.get("regularMarketPrice"))
    if quote is None:
        quote = number(info.get("currentPrice"))
    price = quote if quote is not None else metrics["Close"]
    metrics["Quote"] = price
    pe = number(info.get("forwardPE"))
    trailing_pe = number(info.get("trailingPE"))
    target = number(info.get("targetMeanPrice"))
    upside = (target / price - 1) * 100 if target is not None and price and price > 0 else None
    # Explicitly use the trailing annual rate/yield; do not guess dividendYield units.
    dividend_rate = number(info.get("trailingAnnualDividendRate"))
    raw_yield = number(info.get("trailingAnnualDividendYield"))
    dividend_pct = dividend_rate / price * 100 if dividend_rate is not None and price and price > 0 else (
        raw_yield * 100 if raw_yield is not None else None)
    beta = number(info.get("beta"))
    current, ema20, ema50 = metrics["Close"], metrics["EMA20"], metrics["EMA50"]
    trend = None if any(x is None for x in (current, ema20, ema50)) else current > ema20 > ema50
    rsi, macd, signal, volume_ratio, atr = (metrics[k] for k in ["RSI_14", "MACD", "MACD_Signal", "Vol_Ratio", "ATR"])
    status = str(selected_row.get("Status", "ไม่มีข้อมูล"))
    rows = []

    def add(group, metric, value, meaning, source):
        rows.append({"หมวด": group, "ปัจจัย": metric, "ค่าล่าสุด": value,
                     "การแปลผล": meaning, "แหล่งข้อมูล": source})

    pe_text = "ไม่มีประมาณการกำไร" if pe is None else "กำไรประมาณการไม่เป็นบวก" if pe <= 0 else "ต่ำกว่าเกณฑ์ 15 เท่า" if pe < 15 else "อยู่ระหว่าง 15–30 เท่า" if pe <= 30 else "มากกว่า 30 เท่า"
    add("พื้นฐาน", "Forward P/E", show_number(pe, "x"), pe_text+"; ควรเทียบธุรกิจกลุ่มเดียวกัน", "Yahoo Finance")
    add("พื้นฐาน", "Trailing P/E", show_number(trailing_pe, "x"), "ราคาเทียบกำไรย้อนหลัง", "Yahoo Finance")
    add("พื้นฐาน", "Target Price", show_number(target), "ไม่มีราคาเป้าหมาย" if upside is None else f"ต่างจากราคาอ้างอิง {upside:+.2f}%", "นักวิเคราะห์ผ่าน Yahoo")
    add("พื้นฐาน", "Dividend Yield", show_number(dividend_pct, "%"), "อัตราปันผลย้อนหลังเทียบราคาอ้างอิง" if dividend_pct is not None else "ไม่มีข้อมูลปันผล", "Yahoo Finance")
    add("เทคนิค", "Trend / Screener", status, "สถานะจากไฟล์สแกนเดิม", "CSV" if selected_row else "—")
    add("เทคนิค", "EMA 20 / EMA 50", f"{show_number(ema20)} / {show_number(ema50)}", "ข้อมูลไม่พอ" if trend is None else "ราคา > EMA20 > EMA50" if trend else "ยังไม่เรียงตัวตามเงื่อนไข ราคา > EMA20 > EMA50", sources["EMA20"])
    add("เทคนิค", "SMA 200", show_number(metrics["SMA200"]), "ค่าเฉลี่ย 200 แท่งรายวัน", sources["SMA200"])
    add("เทคนิค", "MACD / Signal", f"{show_number(macd, digits=4)} / {show_number(signal, digits=4)}", "ข้อมูลไม่พอ" if macd is None or signal is None else "MACD อยู่เหนือ Signal" if macd > signal else "MACD อยู่ต่ำกว่าหรือเท่ากับ Signal", sources["MACD"])
    add("เทคนิค", "RSI (14)", show_number(rsi), "ข้อมูลไม่พอ" if rsi is None else "สูงกว่า 70" if rsi > 70 else "ต่ำกว่า 30" if rsi < 30 else "อยู่ในช่วง 30–70", sources["RSI_14"])
    add("สภาพคล่อง", "Volume Ratio", show_number(volume_ratio, "x"), "ปริมาณล่าสุดเทียบค่าเฉลี่ย 20 แท่งก่อนหน้า" if sources["Vol_Ratio"] == "กราฟรายวัน" else "อัตราวอลุ่มจากไฟล์สแกน", sources["Vol_Ratio"])
    add("ความเสี่ยง", "Beta", show_number(beta), "ไม่มีข้อมูล" if beta is None else "Beta มากกว่า 1" if beta > 1 else "Beta ต่ำกว่าหรือเท่ากับ 1", "Yahoo Finance")
    add("ความเสี่ยง", "ATR (14)", show_number(atr), "ขนาด True Range เฉลี่ยรายวัน ในหน่วยราคา", sources["ATR"])
    add("ความเสี่ยง", "Suggested Stop", show_number(selected_row.get("Suggested_Stop")), "จุด Stop จากไฟล์สแกนเดิม", "CSV" if number(selected_row.get("Suggested_Stop")) is not None else "—")
    checks = [
        ("Screener = PASS", None if status not in ("PASS", "FAIL") else status == "PASS", 2),
        ("Forward P/E มากกว่า 0 และต่ำกว่า 25", None if pe is None else 0 < pe < 25, 1),
        ("Upside มากกว่า 5%", None if upside is None else upside > 5, 1),
        ("MACD > Signal", None if macd is None or signal is None else macd > signal, 1),
        ("RSI อยู่ระหว่าง 30–65", None if rsi is None else 30 <= rsi <= 65, 1),
        ("Volume Ratio มากกว่า 1.1", None if volume_ratio is None else volume_ratio > 1.1, 1)]
    return pd.DataFrame(rows), metrics, {"pe": pe, "target": target, "upside": upside,
                                        "dividend_pct": dividend_pct, "beta": beta, "checks": checks}


def position_size(capital, risk_pct, entry, stop):
    values = [number(v) for v in (capital, risk_pct, entry, stop)]
    if any(v is None for v in values):
        raise ValueError("กรุณากรอกตัวเลขให้ครบ")
    if capital <= 0 or not 0 < risk_pct <= 100 or entry <= 0 or stop < 0 or stop >= entry:
        raise ValueError("ราคาเข้าต้องมากกว่า Stop Loss และเงินลงทุนต้องมากกว่า 0")
    budget = capital * risk_pct / 100
    per_share = entry - stop
    by_risk = math.floor(budget / per_share)
    by_cash = math.floor(capital / entry)
    shares = min(by_risk, by_cash)
    return {"shares": shares, "capital_used": shares * entry, "planned_loss": shares * per_share,
            "risk_budget": budget, "cash_limited": by_cash < by_risk}


def render_position_sizer(ticker, selected_row, metrics, currency):
    st.subheader("วางแผนการซื้อ — Position Sizer")
    st.caption(f"กรอกพอร์ตและราคาเป็นสกุลเดียวกัน ({currency})")
    current = number(metrics.get("Quote"))
    csv_stop = number(selected_row.get("Suggested_Stop"))
    if current is not None and current > 0:
        entry_default = current
    else:
        entry_default = 0.0
    stop_default = max(0.0, csv_stop) if csv_stop is not None else 0.0
    if csv_stop is not None:
        st.caption(f"Stop จาก CSV: {csv_stop:,.4f} — แก้ไขได้ตามแผนของคุณ")
    else:
        st.caption("ไม่มี Suggested_Stop ใน CSV กรุณากรอกจุด Stop ของคุณ")
    a, b = st.columns(2)
    capital = a.number_input(f"เงินลงทุน ({currency})", min_value=0.0, value=10000.0, step=1000.0, key="port_size")
    risk = b.slider("ความเสี่ยงต่อไม้ (% ของพอร์ต)", .5, 5.0, 1.0, .5, key="risk_pct")
    a, b = st.columns(2)
    entry = a.number_input("ราคาเข้าซื้อ", min_value=0.0, value=float(entry_default), step=.01, format="%.4f", key=f"entry_{ticker}")
    stop = b.number_input("Stop Loss", min_value=0.0, value=float(stop_default), step=.01, format="%.4f", key=f"stop_{ticker}")
    if stop == 0:
        st.info("กรอก Stop Loss มากกว่า 0 เพื่อคำนวณจำนวนหุ้น")
        return
    try:
        plan = position_size(capital, risk, entry, stop)
    except ValueError as exc:
        st.warning(str(exc))
        return
    a, b, c = st.columns(3)
    a.metric("จำนวนหุ้น", f"{plan['shares']:,}")
    b.metric(f"เงินที่ใช้ ({currency})", f"{plan['capital_used']:,.2f}")
    c.metric(f"ขาดทุนตามแผน ({currency})", f"{plan['planned_loss']:,.2f}")
    if plan["cash_limited"]:
        st.caption("จำนวนหุ้นถูกจำกัดด้วยเงินลงทุนที่กรอก")
    st.caption("คำนวณที่ราคา Stop ที่ระบุ ยังไม่รวมค่าธรรมเนียมและส่วนต่างราคาซื้อขายจริง")


def align_comparison(histories: dict, period: str):
    series = []
    for ticker, frame in histories.items():
        f = normalize_history(frame)
        s = f.Close.copy()
        s.index = s.index.tz_localize(None).normalize() if s.index.tz is not None else s.index.normalize()
        s = s.loc[~s.index.duplicated(keep="last")]
        series.append(s.rename(ticker))
    common = pd.concat(series, axis=1, join="inner").dropna()
    if common.empty:
        raise ValueError("หุ้นที่เลือกไม่มีวันที่มีข้อมูลตรงกัน")
    n, unit = period.split()
    begin = common.index[-1] - (pd.DateOffset(months=int(n)) if unit == "เดือน" else pd.DateOffset(years=int(n)))
    common = common.loc[common.index >= begin]
    if len(common) < 2 or (common.iloc[0] <= 0).any():
        raise ValueError("ข้อมูลร่วมกันไม่พอสำหรับเปรียบเทียบ")
    return (common / common.iloc[0] - 1) * 100


def render_comparison(first, second, period, key):
    first, second = first.strip().upper(), second.strip().upper()
    if not all(re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}", t) for t in (first, second)):
        st.info("กรุณาระบุ Ticker ให้ครบสองตัว")
        return
    if first == second:
        st.info("เลือกหุ้นคนละตัวเพื่อเปรียบเทียบ")
        return
    try:
        histories = {t: load_chart_history(t, "1d")[0] for t in (first, second)}
        performance = align_comparison(histories, period)
    except Exception as exc:
        st.warning(f"ยังเปรียบเทียบไม่ได้: {exc}")
        return
    fig = go.Figure()
    for ticker, color in zip((first, second), ("#5b9cf6", "#f3b34c")):
        fig.add_trace(go.Scatter(x=performance.index, y=performance[ticker], mode="lines", name=ticker,
                                line=dict(color=color, width=2.5), hovertemplate="%{y:+.2f}%<extra>%{fullData.name}</extra>"))
    fig.add_hline(y=0, line_color="#526075", line_dash="dot")
    fig.update_layout(height=480, template="plotly_dark", paper_bgcolor="#10141d", plot_bgcolor="#10141d",
                      font=dict(size=14), margin=dict(l=15,r=15,t=35,b=15), hovermode="x unified", dragmode="pan",
                      yaxis=dict(title="ผลตอบแทน (%)", side="right", fixedrange=False),
                      xaxis=dict(title=None, rangeslider_visible=False), legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, **width_options(st.plotly_chart), key=key, config={"scrollZoom": True, "displaylogo": False})
    a,b,c = st.columns(3)
    end = performance.iloc[-1]
    a.metric(first, f"{end[first]:+.2f}%")
    b.metric(second, f"{end[second]:+.2f}%")
    c.metric("ส่วนต่างผลตอบแทน", f"{end[first]-end[second]:+.2f} จุดเปอร์เซ็นต์")
    st.caption(f"เริ่มทั้งคู่ที่ 0% บนวันที่มีข้อมูลร่วมกัน: {performance.index[0]:%d/%m/%Y} – {performance.index[-1]:%d/%m/%Y} · ใช้ราคาปรับแล้วในสกุลของแต่ละสินทรัพย์")


def render_filters(frame):
    st.subheader("ตัวกรองข้อมูล — Data Filters")
    a,b,c = st.columns([1,1,1.4])
    asset = a.selectbox("ประเภทสินทรัพย์", ["ทั้งหมด"]+sorted(frame.Asset_Type.unique().tolist()), key="asset_filter")
    status = b.radio("สถานะจาก Screener", ["ทั้งหมด", "PASS เท่านั้น"], horizontal=True, key="status_filter")
    query = c.text_input("ค้นหา Ticker ในตาราง", key="search_ticker", help="พิมพ์ชื่อหุ้นบางส่วนได้")
    with st.expander("ตัวกรองขั้นสูง", expanded=False):
        a,b,c = st.columns(3)
        low = a.number_input("ราคาต่ำสุด", min_value=0.0, value=0.0, step=1.0, key="min_price")
        # Start with a bound that retains every finite price in the user's CSV.
        max_seen = number(frame.Close.max())
        high_default = max(5000.0, max_seen or 0.0)
        high = a.number_input("ราคาสูงสุด", min_value=0.0, value=high_default, step=10.0, key="max_price")
        rsi = b.slider("ช่วง RSI (14)", 0, 100, (0,100), key="rsi_filter")
        ret = c.number_input("ผลตอบแทน 1 ปีขั้นต่ำ (%)", value=-100.0, step=10.0, key="return_filter")
        keep = st.checkbox("แสดงแถวที่บางคอลัมน์ยังไม่มีข้อมูลด้วย", value=True, key="keep_missing")
    if high < low:
        st.warning("ราคาสูงสุดต้องไม่น้อยกว่าราคาต่ำสุด")
        return frame.iloc[0:0]
    return filter_watchlist(frame, asset, status == "PASS เท่านั้น", query, low, high, rsi, ret, keep)


def render_watchlist_table(frame):
    columns = ["Ticker", "Asset_Type", "Status", "Close", "Historical_Return", "Vol_Ratio", "RSI_14", "MACD"]
    table = frame[columns].copy()
    def rsi_style(value):
        n = number(value)
        return "" if n is None else "color: #ef5350" if n > 70 else "color: #26a69a" if n < 30 else ""
    styled = table.style.format({"Close":"{:,.2f}", "Historical_Return":"{:+.2f}%", "Vol_Ratio":"{:.2f}x", "RSI_14":"{:.2f}", "MACD":"{:.4f}"}, na_rep="—")
    styled = styled.map(rsi_style, subset=["RSI_14"]) if hasattr(styled,"map") else styled.applymap(rsi_style, subset=["RSI_14"])
    st.dataframe(styled, height=500, **width_options(st.dataframe), hide_index=True, column_config={
        "Ticker":st.column_config.TextColumn("Ticker",help="สัญลักษณ์หุ้นหรือกองทุน"),
        "Asset_Type":st.column_config.TextColumn("ประเภท",help="ประเภทสินทรัพย์จากไฟล์สแกน"),
        "Status":st.column_config.TextColumn("Status",help="PASS/FAIL ตามเงื่อนไขของ screener.py เดิม"),
        "Close":st.column_config.NumberColumn("ราคาใน CSV",help="ราคาที่บันทึกตอนสแกน อาจต่างจากกราฟที่ดึงใหม่"),
        "Historical_Return":st.column_config.NumberColumn("1Y Return (%)",help="ผลตอบแทน 1 ปีจาก CSV หน่วยเปอร์เซ็นต์"),
        "Vol_Ratio":st.column_config.NumberColumn("Vol Ratio",help="ปริมาณซื้อขายเทียบค่าเฉลี่ย ตามสูตรใน screener"),
        "RSI_14":st.column_config.NumberColumn("RSI (14)",help="ค่าจากไฟล์สแกน: ต่ำกว่า 30 / มากกว่า 70 เป็นระดับที่มักใช้สังเกตโมเมนตัม"),
        "MACD":st.column_config.NumberColumn("MACD",help="ค่า MACD จากไฟล์สแกน ดูเทียบ Signal ในตารางวิเคราะห์")})
    st.download_button("ดาวน์โหลดรายการที่กรองแล้ว", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="filtered_watchlist.csv", mime="text/csv", key="download_watchlist")


def main():
    st.set_page_config(page_title="Ultimate Trend Trading Terminal", page_icon="📈", layout="wide")
    st.markdown("""<style>
    .block-container {padding-top:2rem;padding-bottom:3rem;max-width:1800px}
    [data-testid="stMetricValue"]{font-size:1.65rem}
    [data-testid="stDataFrame"]{border:1px solid #334155;border-radius:7px}
    </style>""", unsafe_allow_html=True)
    head, settings = st.columns([4,1])
    head.title("Ultimate Trend Trading Terminal")
    head.caption("คัดกรองหุ้น · วิเคราะห์พื้นฐานและเทคนิค · วางแผนความเสี่ยง · เปรียบเทียบผลตอบแทน")
    auto = settings.checkbox("รีเฟรชหน้าทุก 5 นาที", value=True, key="auto_refresh")
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=300_000, key="dashboard_refresh_5m")
        except ImportError:
            settings.caption("ใช้ปุ่มโหลดข้อมูลใหม่เพื่อรีเฟรช")
    if settings.button("โหลดข้อมูลใหม่ทั้งหมด", key="refresh_all"):
        load_chart_history.clear()
        load_fundamentals.clear()
        read_watchlist.clear()
    with st.expander("แหล่งข้อมูล Watchlist / อัปโหลด CSV", expanded=not WATCHLIST_FILE.exists()):
        upload = st.file_uploader("เลือก daily_watchlist.csv เดิม", type=["csv"], key="watchlist_upload")
        st.caption("อ่านไฟล์ในโฟลเดอร์แอปอัตโนมัติ หรือเลือกอัปโหลดเพื่อใช้ในรอบนี้")
    frame = pd.DataFrame(columns=["Ticker","Asset_Type","Status"]+NUMERIC_COLUMNS)
    source_label = "ยังไม่มีไฟล์ Watchlist"
    try:
        if upload is not None:
            frame = parse_watchlist(upload.getvalue())
            source_label = f"ไฟล์ที่อัปโหลด: {upload.name}"
        elif WATCHLIST_FILE.exists():
            stat = WATCHLIST_FILE.stat()
            frame = read_watchlist(str(WATCHLIST_FILE), stat.st_mtime_ns, stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).astimezone(ZoneInfo("Asia/Bangkok"))
            source_label = f"CSV แก้ไขล่าสุด {modified:%d/%m/%Y %H:%M} เวลาไทย"
        else:
            st.info("ยังไม่พบ daily_watchlist.csv ให้วางไฟล์เดิมไว้ข้าง app.py หรืออัปโหลดด้านบน เพื่อแสดงรายชื่อหุ้นทั้งหมด")
    except Exception as exc:
        st.error(f"อ่าน Watchlist ไม่สำเร็จ: {exc}")
    st.caption(source_label+" · เวลาไฟล์ไม่ใช่เวลาของราคาสตรีมสด")
    c1,c2,c3 = st.columns(3)
    c1.metric("สินทรัพย์ใน Watchlist", f"{len(frame):,}")
    c2.metric("ผ่าน Screener (PASS)", f"{int(frame.Status.eq('PASS').sum()):,}")
    c3.metric("ประเภทสินทรัพย์", f"{frame.Asset_Type.nunique():,}")
    filtered = render_filters(frame)
    st.divider()
    a,b = st.columns([1,1])
    with a:
        st.subheader(f"รายการสินทรัพย์ ({len(filtered):,} ตัว)")
        render_watchlist_table(filtered)
        if filtered.empty and not frame.empty:
            st.info("ไม่พบหุ้นตามตัวกรอง ลองปรับเงื่อนไขหรือค้นชื่อหุ้นด้านขวา")
    with b:
        st.subheader("เลือกหุ้นเพื่อวิเคราะห์")
        options = filtered.Ticker.tolist()
        if options:
            if st.session_state.get("selected_watchlist") not in options:
                st.session_state["selected_watchlist"] = options[0]
            chosen = st.selectbox("Ticker จากรายการที่กรอง", options, key="selected_watchlist")
            manual = st.text_input("หรือพิมพ์ Ticker อื่น", value="", key="manual_ticker")
            ticker = manual.strip().upper() or chosen
        else:
            ticker = st.text_input("Ticker สำหรับวิเคราะห์", value="AAPL", key="manual_fallback").strip().upper()
        valid_ticker = bool(re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}",ticker))
        matches = frame.loc[frame.Ticker.eq(ticker)]
        selected_row = matches.iloc[0].to_dict() if not matches.empty else {}
        info, history, snapshot = {}, None, {}
        if valid_ticker:
            try:
                info = load_fundamentals(ticker)
            except Exception as exc:
                st.warning(f"ข้อมูลพื้นฐานยังโหลดไม่ได้: {exc}")
            try:
                history, _ = load_chart_history(ticker,"1d")
                snapshot = daily_snapshot(history)
            except Exception as exc:
                st.warning(f"ราคาย้อนหลังยังโหลดไม่ได้ ใช้ค่าที่มีใน CSV: {exc}")
        else:
            st.info("กรุณาระบุ Ticker ให้ถูกต้อง")
        analysis, metrics, facts = build_analysis(snapshot, selected_row, info)
        currency = str(info.get("currency") or selected_row.get("Currency") or "สกุลราคาหุ้น")
        st.markdown(f"**{ticker or '—'} — {info.get('shortName') or info.get('longName') or ''}**")
        st.caption(f"Sector: {info.get('sector') or 'ไม่มีข้อมูล'} · Industry: {info.get('industry') or 'ไม่มีข้อมูล'}")
        c1,c2,c3 = st.columns(3)
        c1.metric(f"ราคาอ้างอิง ({currency})",show_number(metrics["Quote"]))
        c2.metric("Target Price",show_number(facts["target"]),
                  delta=f"{facts['upside']:+.2f}%" if facts["upside"] is not None else None)
        c3.metric("Market Cap",compact_number(info.get("marketCap")))
        c1,c2,c3 = st.columns(3)
        c1.metric("Forward P/E",show_number(facts["pe"],"x"),help="ราคาเทียบประมาณการกำไรต่อหุ้น")
        c2.metric("Dividend Yield",show_number(facts["dividend_pct"],"%"),help="ปันผลย้อนหลังหนึ่งปีเทียบราคาอ้างอิง")
        c3.metric("Beta",show_number(facts["beta"]),help="ค่าความสัมพันธ์ของความเคลื่อนไหวกับตลาดจากผู้ให้ข้อมูล")
        if snapshot:
            st.caption(f"อินดิเคเตอร์คำนวณจากแท่งรายวันล่าสุด {snapshot['Bar_Date']} · ค่าในตารางหุ้นยังอ้าง CSV เดิม")
    st.divider()
    st.subheader("ตารางวิเคราะห์ 360° — พื้นฐาน เทคนิค และความเสี่ยง")
    st.dataframe(analysis, **width_options(st.dataframe), hide_index=True, height=500,
                 column_config={"การแปลผล":st.column_config.TextColumn(width="large"),
                                "แหล่งข้อมูล":st.column_config.TextColumn(help="ค่าแต่ละส่วนอาจอัปเดตคนละเวลา")})
    verdict, risk_col = st.columns([1,1.25])
    with verdict:
        st.subheader("สรุปเงื่อนไข — Trading Verdict")
        checks = facts["checks"]
        score = sum(weight for _,passed,weight in checks if passed is True)
        available = sum(weight for _,passed,weight in checks if passed is not None)
        if available:
            st.metric("คะแนนตามเงื่อนไขเดิม", f"{score} / 7")
            if available == 7:
                label = "ผ่านหลายเงื่อนไข" if score >= 5 else "เข้า Watchlist เพื่อพิจารณา" if score >= 3 else "ผ่านเงื่อนไขน้อย"
                st.info(label)
            else:
                st.info(f"ยังประเมินไม่ครบ: มีข้อมูลสำหรับ {available} จาก 7 คะแนน")
        else:
            st.info("ยังไม่มีข้อมูลพอสำหรับให้คะแนน")
        st.dataframe(pd.DataFrame([{"เงื่อนไข":name,"ผล":"ไม่มีข้อมูล" if passed is None else "ผ่าน" if passed else "ไม่ผ่าน","คะแนนเต็ม":weight} for name,passed,weight in checks]),
                     hide_index=True,**width_options(st.dataframe))
        st.caption("คะแนนจากกติกาที่แสดง ไม่ใช่ผลทำนายราคา")
    with risk_col:
        render_position_sizer(ticker or "UNKNOWN", selected_row, metrics, currency)
    st.divider()
    tab1,tab2,tab3 = st.tabs(["กราฟเทคนิค", "Relative Strength เทียบ SPY", "เปรียบเทียบหุ้น 2 ตัว"])
    with tab1:
        st.subheader(f"กราฟเทคนิค — {ticker or 'เลือกหุ้น'}")
        if valid_ticker:
            render_trading_chart(ticker)
    with tab2:
        st.subheader("ผลตอบแทนเทียบตลาด — SPY")
        rs_period = st.radio("ช่วงเวลาเทียบตลาด",["1 เดือน","3 เดือน","6 เดือน","1 ปี","2 ปี","3 ปี"],index=3,horizontal=True,key="rs_period")
        if valid_ticker:
            render_comparison(ticker,"SPY",rs_period,"rs_chart")
    with tab3:
        st.subheader("เปรียบเทียบผลตอบแทนหุ้น 2 ตัว")
        c1,c2 = st.columns(2)
        c1.text_input("หุ้นตัวที่ 1 (หุ้นที่เลือก)",value=ticker,disabled=True,key=f"comp_first_{ticker}")
        second = c2.text_input("หุ้นตัวที่ 2",value="MSFT" if ticker == "AAPL" else "AAPL",key="comp_second").strip().upper()
        comp_period = st.radio("ช่วงเวลาเปรียบเทียบ",["1 เดือน","3 เดือน","6 เดือน","1 ปี","2 ปี","3 ปี"],index=3,horizontal=True,key="comp_period")
        if valid_ticker:
            render_comparison(ticker,second,comp_period,"comparison_chart")


if __name__ == "__main__":
    main()
