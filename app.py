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


def load_chart_history(ticker: str, interval: str = "1d") -> tuple[pd.DataFrame, str]:
    """Read immediately. Network updates are explicit background jobs."""
    frame, meta = get_data_cache().history(ticker, interval)
    if frame is None:
        raise ValueError("ยังไม่มีประวัติที่บันทึกไว้ กดโหลด/อัปเดตหุ้นที่เลือก หรือโหลดข้อมูลกราฟ")
    return frame, meta.get("fetched_at", "")


load_chart_history.clear = lambda *args: None


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
        refresh = st.button("โหลดข้อมูลกราฟ", key=f"{key}_refresh")
    interval = "5m" if period == "1 วัน" else "15m" if period in ["5 วัน", "7 วัน"] else "1d"
    if refresh:
        if get_updater().request(ticker, "history", interval):
            st.info("ส่งคำขอโหลดกราฟแล้ว แสดงข้อมูลที่มีระหว่างรอ")
        else:
            st.warning("แหล่งข้อมูลกำลังพัก ลองใหม่ตามเวลาพักที่แสดงด้านบน")
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
NUMERIC_COLUMNS = ["Close", "Historical_Return", "Return_2Y", "Return_3Y", "Vol_Ratio", "RSI_14", "MACD",
                   "MACD_Signal", "ATR", "Suggested_Stop", "EMA20", "EMA50", "SMA200"]
WATCHLIST_NUMERIC_COLUMNS = NUMERIC_COLUMNS + ["Return_Calc_Version", "History_Years_Loaded"]
# === UNIVERSE SETTINGS — จำนวนรายชื่อและขนาดการโหลด ===
COMMON_STOCK_LIMIT = 4200
ETF_LIMIT = 700
HISTORY_YEARS = 5  # Three full calendar years plus warm-up / non-trading dates.
RETURN_CALC_VERSION = 2
SCAN_BATCH_SIZE = 25
SCAN_INTERVAL_SECONDS = 1
SCAN_COOLDOWN_SECONDS = 300
DOWNLOAD_THREADS = 4
DOWNLOAD_TIMEOUT_SECONDS = 10
CATALOG_AS_OF = "2026-09-09"
CATALOG_SOURCE = "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs"
# Common / ordinary / capital shares, excluding ETFs, preferreds, ADRs,
# warrants, rights, units and named funds. Class separators mapped to Yahoo '-'.
# V (Visa Inc.) is a named common-share exception; source investor.visa.com.
# Order: core symbols then alphabet buckets / ETF issuer buckets. Not an AUM ranking.
STOCK_CATALOG_TSV = """AAPL	Apple Inc. - Common Stock
MSFT	Microsoft Corporation - Common Stock
NVDA	NVIDIA Corporation - Common Stock
AMZN	Amazon.com, Inc. - Common Stock
GOOGL	Alphabet Inc. - Class A Common Stock
GOOG	Alphabet Inc. - Class C Capital Stock
META	Meta Platforms, Inc. - Class A Common Stock
TSLA	Tesla, Inc.  - Common Stock
BRK-B	Berkshire Hathaway Inc. New Common Stock
JPM	JP Morgan Chase & Co. Common Stock
V	Visa Inc.
UNH	UnitedHealth Group Incorporated Common Stock (DE)
XOM	ExxonMobil Holdings Corporation Common Stock
MA	Mastercard Incorporated Common Stock
COST	Costco Wholesale Corporation - Common Stock
HD	Home Depot, Inc. (The) Common Stock
WMT	Walmart Inc. - Common Stock
PG	Procter & Gamble Company (The) Common Stock
JNJ	Johnson & Johnson Common Stock
ABBV	AbbVie Inc. Common Stock
BAC	Bank of America Corporation Common Stock
KO	Coca-Cola Company (The) Common Stock
PEP	PepsiCo, Inc. - Common Stock
NFLX	Netflix, Inc. - Common Stock
AVGO	Broadcom Inc. - Common Stock
AMD	Advanced Micro Devices, Inc. - Common Stock
ORCL	Oracle Corporation Common Stock
CRM	Salesforce, Inc. Common Stock
ADBE	Adobe Inc. - Common Stock
DIS	Walt Disney Company (The) Common Stock
NKE	Nike, Inc. Common Stock
GE	GE Aerospace Common Stock
CAT	Caterpillar, Inc. Common Stock
LLY	Eli Lilly and Company Common Stock
MRK	Merck & Company, Inc. Common Stock (new)
CSCO	Cisco Systems, Inc. - Common Stock
INTC	Intel Corporation - Common Stock
QCOM	QUALCOMM Incorporated - Common Stock
TMO	Thermo Fisher Scientific Inc Common Stock
ABT	Abbott Laboratories Common Stock
DHR	Danaher Corporation Common Stock
TXN	Texas Instruments Incorporated - Common Stock
NEE	NextEra Energy, Inc. Common Stock
PM	Philip Morris International Inc Common Stock
RTX	RTX Corporation Common Stock
LOW	Lowe's Companies, Inc. Common Stock
UBER	Uber Technologies, Inc. Common Stock
PLTR	Palantir Technologies Inc. - Class A Common Stock
CRWD	CrowdStrike Holdings, Inc. - Class A Common Stock
A	Agilent Technologies, Inc. Common Stock
B	Barrick Mining Corporation Common Shares
C	Citigroup, Inc. Common Stock
D	Dominion Energy, Inc. Common Stock
E	ENI S.p.A. Common Stock
F	Ford Motor Company Common Stock
G	Genpact Limited Common Stock
H	Hyatt Hotels Corporation Class A Common Stock
IA	Innovative Solutions and Support, Inc. - Common Stock
J	Jacobs Solutions Inc. Common Stock
KAI	Kadant Inc Common Stock
L	Loews Corporation Common Stock
M	Macy's Inc Common Stock
NABL	N-able, Inc. Common Stock
O	Realty Income Corporation Common Stock
P	Everpure, Inc. Class A common stock
Q	Qnity Electronics, Inc. Common Stock
R	Ryder System, Inc. Common Stock
S	SentinelOne, Inc. Class A Common Stock
TAC	TransAlta Corporation Ordinary Shares
U	Unity Software Inc. Common Stock
W	Wayfair Inc. Class A Common Stock
XAIR	Beyond Air, Inc. - Common Stock
YAAS	Youxin Technology Ltd - Class A Ordinary shares
Z	Zillow Group, Inc. - Class C Capital Stock
AA	Alcoa Corporation Common Stock 
BA	Boeing Company (The) Common Stock
CAAP	Corporacion America Airports SA Common Shares
DAAQ	Digital Asset Acquisition Corp. - Class A Ordinary shares
EAF	GrafTech International Ltd. Common Stock
FA	First Advantage Corporation - Common Stock
GAB	Gabelli Equity Trust, Inc. (The) Common Stock
HACQ	HCM IV Acquisition Corp. - Class A Ordinary Share
IACO	Idea Acquisition Corp. - Class A Ordinary Shares
JACK	Jack In The Box Inc. - Common Stock
KALA	KALA BIO, Inc. - Common Stock
LAB	Standard BioTools Inc. - Common Stock
NAGE	Niagen Bioscience, Inc. - Common Stock
OABI	OmniAb, Inc. - Common Stock
PAAC	Proem Acquisition Corp I - Ordinary Shares
QADR	QDRO Acquisition Corp. - Class A Ordinary Shares
RAC	Rithm Acquisition Corp. Class A Ordinary Shares
SA	Seabridge Gold, Inc. Common Shares New
TACH	Titan Acquisition Corp. - Class A Ordinary Shares
UA	Under Armour, Inc. Class C Common Stock
VABK	Virginia National Bankshares Corporation - Common Stock
WAB	Westinghouse Air Brake Technologies Corporation Common Stock
XBIO	Xenetic Biosciences, Inc. - Common Stock
YARW	Yarrow Bioscience, Inc. - Common Stock
ZBAO	Zhibao Technology Inc. - Class A Ordinary Shares
AAC	Ares Acquisition Corporation III Class A Ordinary Shares
CAAS	China Automotive Systems, Inc. - Ordinary Share
DAC	Danaos Corporation Common Stock
EARN	Ellington Credit Company Common Shares of Beneficial Interest
FABC	Fabric.AI, Inc. - Common Stock
GABC	German American Bancorp, Inc. - Common Stock
HAE	Haemonetics Corporation Common Stock
IACQ	Irenic Acquisition Corp. - Class A Ordinary Shares
JACS	Jackson Acquisition Company II Class A Ordinary Shares
KALU	Kaiser Aluminum Corporation - Common Stock
LABT	Lakewood-Amedex Biotherapeutics Inc. - Common Stock
MAA	Mid-America Apartment Communities, Inc. Common Stock
NAII	Natural Alternatives International, Inc. - Common Stock
OACC	Oaktree Acquisition Corp. III Life Sciences - Class A Ordinary Share
PAAI	Paradium.AI, Inc. Common Stock
QBTS	D-Wave Quantum Inc. - Common Stock
RACC	Research Alliance Corporation III - Class A Ordinary Shares
SAAQ	Space Asset Acquisition Corp. - Class A Ordinary Shares
TACO	Berto Acquisition Corp. - Ordinary Shares
UAA	Under Armour, Inc. Class A Common Stock
VAC	Marriott Vacations Worldwide Corporation Common Stock
WABC	Westamerica Bancorporation - Common Stock
XBIT	XBiotech Inc. - Common Stock
YCBD	cbdMD, Inc. Common Stock
ZBH	Zimmer Biomet Holdings, Inc. Common Stock
AACI	Armada Acquisition Corp. III - Class A Ordinary Share
BACC	Blue Acquisition Corp. - Class A Ordinary Shares
CABA	Cabaletta Bio, Inc. - Common Stock
DAIC	CID HoldCo, Inc. - Common Stock
EAT	Brinker International, Inc. Common Stock
FAC	Factorial Energy Inc. - Class A Common Stock
GAIA	Gaia, Inc. - Class A Common Stock
HAFC	Hanmi Financial Corporation - Common Stock
IAG	Iamgold Corporation Ordinary Shares
JAGU	Jaguar Uranium Corp. Class A Common Shares
KAPA	Kairos Pharma, Ltd. Common Stock
LAC	Lithium Americas Corp. Common Shares
MAAS	Maase Inc. - Class A Ordinary Shares
NAK	Northern Dynasty Minerals, Ltd. Common Stock
OBA	Oxley Bridge Acquisition Limited - Class A Ordinary Shares
PAAS	Pan American Silver Corp. Common Stock
QCLS	Q/C Technologies, Inc. - Common Stock
RACD	Research Alliance Corporation IV - Class A Ordinary Shares
SABR	Sabre Corporation - Common Stock
TACT	TransAct Technologies Incorporated - Common Stock
UAC	United Acquisition Corp. I Class A Ordinary Shares
VACI	Viking Acquisition Corp. I Class A Ordinary Shares
WAFD	WaFd, Inc. - Common Stock
XBP	XBP Global Holdings, Inc. - Common Stock
YCY	AA Mission Acquisition Corp. II Class A Ordinary Shares
ZBIO	Zenas BioPharma, Inc. - Common Stock
AACO	Abony Acquisition Corp. I - Class A Ordinary Share
BAER	Bridger Aerospace Group Holdings, Inc. - Common Stock
CABO	Cable One, Inc. Common Stock
DAIO	Data I/O Corporation - Common Stock
EBAY	eBay Inc. - Common Stock
FACT	FACT II Acquisition Corp. - Class A Ordinary Shares
GALT	Galectin Therapeutics Inc. - Common Stock
HAFN	Hafnia Limited Common Shares
IART	Integra LifeSciences Holdings Corporation - Common Stock
JAGX	Jaguar Health, Inc. - Common Stock
KARD	Kardigan, Inc. - Common Stock
LAD	Lithia Motors, Inc. Common Stock
MAC	Macerich Company (The) Common Stock
NAKA	Nakamoto Inc. - Common Stock
OBAI	Our Bond, Inc. - Common Stock
PACB	Pacific Biosciences of California, Inc. - Common Stock
RACE	Ferrari N.V. Common Shares
SABS	SAB Biotherapeutics, Inc. - Common Stock
TALO	Talos Energy, Inc. Common Stock
UAL	United Airlines Holdings, Inc. - Common Stock
VAI	Valor Energy Incorporated - Common Stock
WAFU	Wah Fu Education Group Limited - Ordinary Shares
XCBE	X3 Acquisition Corp. Ltd. - Class A Ordinary Shares
YDDL	One and One Green Technologies. INC - Class A Ordinary Shares
ZBRA	Zebra Technologies Corporation - Class A Common Stock
AACP	Apogee Acquisition Corp - Class A Ordinary Shares
BAFN	BayFirst Financial Corp. - Common Stock
CABR	Caring Brands, Inc. - Common Stock
DAKT	Daktronics, Inc. - Common Stock
EBC	Eastern Bankshares, Inc. - Common Stock
FAF	First American Corporation (New) Common Stock
GAM	General American Investors, Inc. Common Stock
HAIN	The Hain Celestial Group, Inc. - Common Stock
IAUX	i-80 Gold Corp. Common Shares
JAKK	JAKKS Pacific, Inc. - Common Stock
KARO	Karooooo Ltd. - Ordinary shares
LADR	Ladder Capital Corp Class A Common Stock
MACI	Melar Acquisition Corp. I - Class A Ordinary Shares
NAMM	Namib Minerals - Ordinary Shares
OBDC	Blue Owl Capital Corporation Common Stock
PACH	Pioneer Acquisition I Corp - Class A Ordinary Shares
QCRH	QCR Holdings, Inc. - Common Stock
RAIL	Freightcar America, Inc. - Common Stock
SAC	Safeguard Acquisition Corp. Class A Ordinary Shares
TANH	Tantech Holdings Ltd. - Class A Common Shares
UAMY	United States Antimony Corporation Common Stock
VAL	Valaris Limited Common Shares
WAL	Western Alliance Bancorporation Common Stock (DE)
XCUR	Exicure, Inc. - Common Stock
YDES	YD Bio Limited - Ordinary Shares
ZCMD	Zhongchao Inc. - Class A Ordinary Shares
AADX	Applied Aerospace & Defense, Inc. Common Stock
BAH	Booz Allen Hamilton Holding Corporation Common Stock
CAC	Camden National Corporation - Common Stock
DAL	Delta Air Lines, Inc. Common Stock
EBF	Ennis, Inc. Common Stock
FAMI	Farmmi, Inc. - Class A Ordinary Shares
GAME	GameSquare Holdings, Inc. - Common stock
HAL	Halliburton Company Common Stock
IBAC	IB Acquisition Corp. - Common Stock
JAN	Janus Living, Inc. Class A-1 Common Stock
KAZR	Skyline Builders Group Holding Limited - Class A Ordinary Shares
LAES	SEALSQ Corp - Ordinary Shares
MAGH	Magnitude International Ltd - Ordinary Shares
NAMS	NewAmsterdam Pharma Company N.V. - Ordinary Shares
OBE	Obsidian Energy Ltd. Common Shares
PACK	Ranpak Holdings Corp Class A Common Stock
QDEL	QuidelOrtho Corporation - Common Stock
RAIN	Rain Enhancement Technologies Holdco, Inc. - Class A Common Stock
SACH	Sachem Capital Corp. Common Shares
TAOP	Taoping Inc. - Ordinary Shares
UAVS	AgEagle Aerial Systems, Inc. Common Stock
VALU	Value Line, Inc. - Common Stock
WALD	Waldencast plc - Class A Ordinary Share
XE	X-Energy, Inc. - Class A Common Stock
YDKG	Yueda Digital Holding - Class A Ordinary Share
ZD	Ziff Davis, Inc. - Common Stock
AAL	American Airlines Group, Inc. - Common Stock
BALL	Ball Corporation Common Stock
CACC	Credit Acceptance Corporation - Common Stock
DAN	Dana Incorporated Common Stock 
EBMT	Eagle Bancorp Montana, Inc. - Common Stock
FANG	Diamondback Energy, Inc. - Common Stock
GANX	Gain Therapeutics, Inc. - Common Stock
HALO	Halozyme Therapeutics, Inc. - Common Stock
IBCP	Independent Bank Corporation - Common Stock
JANX	Janux Therapeutics, Inc. - Common Stock
KBDC	Kayne Anderson BDC, Inc. Common Stock
LAFA	LaFayette Acquisition Corp. - Ordinary Share
MAGN	Magnera Corporation Common Stock
NAT	Nordic American Tankers Limited Common Stock
OBIO	Orchestra BioMed Holdings, Inc. - Ordinary Shares
PACS	PACS Group, Inc. Common Stock
QETA	Quetta Acquisition Corporation - Common Stock
RAL	Ralliant Corporation Common Stock
SAFE	Safehold Inc. New Common Stock 
TAOX	Tao Synergies Inc. - Common Stock
UBCP	United Bancorp, Inc. - Common Stock
VANI	Vivani Medical, Inc.  - Common Stock
WASH	Washington Trust Bancorp, Inc. - Common Stock
XEL	Xcel Energy Inc. - Common Stock
YELP	Yelp Inc. Common Stock
ZDAI	DirectBooking Technology Co., Ltd. - Class A Ordinary Shares
AAME	Atlantic American Corporation - Common Stock
BALY	Bally's Corporation Common Stock
CACI	CACI International, Inc. Class A Common Stock
DAR	Darling Ingredients Inc. Common Stock
EBON	Ebang International Holdings Inc. - Class A Ordinary Shares
FAST	Fastenal Company - Common Stock
GAP	Gap, Inc. (The) Common Stock
HAPN	Happen, Inc. - Common Stock
IBEX	IBEX Limited - Common Share
JATT	JATT II Acquisition Corp - Ordinary Shares
KBH	KB Home Common Stock
LAKE	Lakeland Industries, Inc. - Common Stock
MAIA	MAIA Biotechnology, Inc. Common Stock
NATH	Nathan's Famous, Inc. - Common Stock
OBK	Origin Bancorp, Inc. Common Stock
PAG	Penske Automotive Group, Inc. Common Stock
QGEN	Qiagen N.V. Common Shares
RAMP	LiveRamp Holdings, Inc. Common Stock
SAFT	Safety Insurance Group, Inc. - Common Stock
TAP	Molson Coors Beverage Company Class B Common Stock
VATE	INNOVATE Corp. Common Stock
WAT	Waters Corporation Common Stock
XELB	Xcel Brands, Inc - Common Stock
YETI	YETI Holdings, Inc. Common Stock
ZDGE	Zedge, Inc. Class B Common Stock 
AAMI	Acadian Asset Management Inc. Common Stock
BANC	Banc of California, Inc. Common Stock
CADL	Candel Therapeutics, Inc. - Common Stock
DARE	Dare Bioscience, Inc. - Common Stock
EBS	Emergent BioSolutions Inc. Common Stock
FATE	Fate Therapeutics, Inc. - Common Stock
GASS	StealthGas, Inc. - common stock
HAS	Hasbro, Inc. - Common Stock
IBG	Innovation Beverage Group Limited - Ordinary Shares
JAZZ	Jazz Pharmaceuticals plc - Ordinary Shares
KBON	Karbon Capital Partners Corp. - Class A Ordinary Shares
LAMR	Lamar Advertising Company - Class A Common Stock
MAIN	Main Street Capital Corporation Common Stock
NATL	NCR Atleos Corporation Common Stock
OBT	Orange County Bancorp, Inc. - Common Stock
PAGS	PagSeguro Digital Ltd. Class A Common Shares
QH	Quhuo Limited - Class A Ordinary Shares
RANG	Range Capital Acquisition Corp. - Ordinary Shares
SAFX	XCF Global, Inc. - Class A Common Stock
TAP-A	Molson Coors Beverage Company Class A Common Stock
UBS	UBS Group AG Registered Ordinary Shares
VBIO	Valion Bio, Inc. - Common stock
WATR	Air Water Ventures Limited - Ordinary Shares
XENE	Xenon Pharmaceuticals Inc. - Common Shares
YEXT	Yext, Inc. Common Stock
ZENA	ZenaTech, Inc. - Common Stock
AAOI	Applied Optoelectronics, Inc. - Common Stock
BAND	Bandwidth Inc. - Class A Common Stock
CAE	CAE Inc - Common Shares
DASH	DoorDash, Inc. - Common Stock
ECAT	BlackRock ESG Capital Allocation Term Trust Common Shares of Beneficial Interest
FATN	FatPipe, Inc. - common stock
GATX	GATX Corporation Common Stock
HASI	HA Sustainable Infrastructure Capital, Inc. Common Stock
IBIO	iBio, Inc. - Common Stock
JBDI	JBDI Holdings Limited - Ordinary Shares
KBR	KBR, Inc. Common Stock
LAND	Gladstone Land Corporation - Common Stock
MAIR	Madison Air Solutions Corporation Class A Common Stock
NATR	Nature's Sunshine Products, Inc. - Common Stock
OBX	Obsidian Therapeutics, Inc. - Common Stock
PAHC	Phibro Animal Health Corporation - Class A Common Stock
QLEP	Quantum Leap Acquisition Corp Class A Ordinary Shares
RANI	Rani Therapeutics Holdings, Inc. - Class A Common Stock
SAGT	SAGTEC GLOBAL LIMITED - Class A Ordinary shares
TARA	Protara Therapeutics, Inc.  - Common Stock
UBSI	United Bankshares, Inc. - Common Stock
VBNK	VersaBank - Common Shares
WATT	Energous Corporation - Common Stock
XERS	Xeris Biopharma Holdings, Inc. - Common Stock
YFOR	YYForce Inc. - Class A Ordinary Shares
ZEO	Zeo Energy Corporation - Class A Common Stock
AAON	AAON, Inc. - Common Stock
BANF	BancFirst Corporation - Common Stock
CAES	Cantor Equity Partners VII, Inc. - Class A Ordinary Shares
DAVE	Dave Inc.  - Class A Common Stock
ECBK	ECB Bancorp, Inc. - Common Stock
FBDT	First Breach Inc. - Common Stock
GAUZ	Gauzy Ltd. - Ordinary Shares
HAVA	Harvard Ave Acquisition Corporation - Class A Ordinary Share
IBKR	Interactive Brokers Group, Inc. - Class A Common Stock
JBGS	JBG SMITH Properties Common Shares 
KBSX	FST Corp. - Ordinary Shares
LANV	Lanvin Group Holdings Limited Ordinary Shares
MAKO	Mako Mining Corp - Common Stock
NAUT	Nautilus Biotechnology, Inc. - Common Stock
OC	Owens Corning Inc Common Stock New
PAII	Pyrophyte Acquisition Corp. II Class A Ordinary Shares
QLYS	Qualys, Inc. - Common Stock
RAPP	Rapport Therapeutics, Inc. - Common Stock
SAGU	Shreya Acquisition Group Class A Ordinary Shares
TARS	Tarsus Pharmaceuticals, Inc. - Common Stock
UCAR	U Power Limited - Class A Ordinary Shares
VC	Visteon Corporation - Common Stock
WAY	Waystar Holding Corp. - Common Stock
XFLH	XFLH Capital Corporation Ordinary Shares
YHC	LQR House Inc. - Common Stock
ZETA	Zeta Global Holdings Corp. Class A Common Stock
BANL	CBL International Limited - Class B Ordinary Shares
CAG	ConAgra Brands, Inc. Common Stock
DB	Deutsche Bank AG Common Stock
ECC	Eagle Point Credit Company Common Share of Beneficial Interest
FBGL	FBS Global Limited - Ordinary Shares
GBAB	Guggenheim Taxable Municipal Bond & Investment Grade Debt Trust Common Shares of Beneficial Interest
HAWK	HawkEye 360, Inc. Common Stock
IBM	International Business Machines Corporation Common Stock
JBHT	J.B. Hunt Transport Services, Inc. - Common Stock
KCHV	Kochav Defense Acquisition Corp. - Class A Ordinary Shares
LAR	Lithium Argentina AG Common Shares
MAMA	Mama's Creations, Inc. - Common Stock
NAVI	Navient Corporation - Common Stock
OCAC	Ocean Capital Acquisition Corporation Ordinary Shares
PAL	Proficient Auto Logistics, Inc. - Common Stock
QMCO	Quantum Corporation - Common Stock
RARE	Ultragenyx Pharmaceutical Inc. - Common Stock
SAH	Sonic Automotive, Inc. Common Stock
TASK	TaskUs, Inc. - Class A Common Stock
UCB	United Community Banks, Inc. Common Stock
VCEL	Vericel Corporation - Common Stock
WBD	Warner Bros. Discovery, Inc. - Series A Common Stock
XFLT	XAI Floating Rate & Alternative Income Trust Common Shares of Beneficial Interest
YHGJ	Yunhong Green CTI Ltd. - Common Stock
ZG	Zillow Group, Inc. - Class A Common Stock
AARD	Aardvark Therapeutics, Inc. - Common Stock
BANR	Banner Corporation - Common Stock
CAH	Cardinal Health, Inc. Common Stock
DBCA	D. Boral Acquisition I Corp. - Class A Ordinary Shares
ECG	Everus Construction Group, Inc. Common Stock
FBIN	Fortune Brands Innovations, Inc. Common Stock
GBCI	Glacier Bancorp, Inc. Common Stock
HAYW	Hayward Holdings, Inc. Common Stock
IBN	ICICI Bank Limited Common Stock
JBI	Janus International Group, Inc. Common Stock
KD	Kyndryl Holdings, Inc. Common Stock
LARK	Landmark Bancorp Inc. - Common Stock
MAMK	MaxsMaking Inc. - Class A Ordinary Shares
NAVN	Navan, Inc. - Class A Common Stock
OCC	Optical Cable Corporation - Common Stock
PALI	Palisade Bio, Inc. - Common Stock
QMLS	QumulusAI, Inc. - Common Stock
RAVE	Rave Restaurant Group, Inc. - Common Stock
SAIA	Saia, Inc. - Common Stock
TATT	TAT Technologies Ltd. - Ordinary Shares
UCFI	CN Healthy Food Tech Group Corp. - Common Stock
VCIG	VCI Global Limited - Ordinary Share
WBTN	WEBTOON Entertainment Inc. - Common stock
XFOR	X4 Pharmaceuticals, Inc. - Common Stock
YHNA	YHN Acquisition I Limited - Ordinary Shares
ZGN	Ermenegildo Zegna N.V. Ordinary Shares
AAT	American Assets Trust, Inc. Common Stock
BAOS	Baosheng Media Group Holdings Limited - Ordinary shares
CAI	Caris Life Sciences, Inc. - Common Stock
DBD	Diebold Nixdorf Incorporated Common stock
ECHO	EchoStar Corporation - Common stock
FBIO	Fortress Biotech, Inc. - Common Stock
GBFH	GBank Financial Holdings Inc. - Common Stock
HBAN	Huntington Bancshares Incorporated - Common Stock
IBO	Impact BioMedical, Inc. Common Stock
JBIO	Jade Biosciences, Inc. - Common Stock
KDK	Kodiak AI, Inc. - Common Stock
LASE	Laser Photonics Corporation - Common Stock
MAMO	Massimo Group - Common Stock
NB	NioCorp Developments Ltd. - Common Stock
OCFC	OceanFirst Financial Corp. - Common Stock
PALO	Paloma Acquisition Corp I - Class A Ordinary Shares
QNBC	QNB Corp. - Common Stock
RAY	Raytech Holding Limited - Ordinary Shares
SAIC	Science Applications International Corporation - Common Stock
TAVI	Tavia Acquisition Corp. - Ordinary Shares
UCTT	Ultra Clean Holdings, Inc. - Common Stock
VCTR	Victory Capital Holdings, Inc. - Common Stock
WBUY	WEBUY GLOBAL LTD. - Class A Ordinary Shares
XGN	Exagen Inc. - Common Stock
YIBO	Planet Image International Limited - Class A Ordinary Shares
ZIM	ZIM Integrated Shipping Services Ltd. Ordinary Shares
AAUC	Allied Gold Corporation Common Shares
BAP	Credicorp Ltd. Common Stock
CAII	Collective Acquisition Corp. II - Class A Ordinary Shares
DBGI	Digital Brands Group, Inc. - Common Stock
ECL	Ecolab Inc. Common Stock
FBIZ	First Business Financial Services, Inc. - Common Stock
GBLI	Global Indemnity Group, LLC - Class A Common Shares
HBB	Hamilton Beach Brands Holding Company Class A Common Stock 
IBOC	International Bancshares Corporation - Common Stock
JBL	Jabil Inc. Common Stock
KDP	Keurig Dr Pepper Inc. - Common Stock
LASR	nLIGHT, Inc. - Common Stock
MAN	ManpowerGroup Common Stock
NBBK	NB Bancorp, Inc. - Common Stock
OCG	Oriental Culture Holding LTD - Ordinary Shares
PAMT	PAMT CORP - Common Stock
QNC	Quantum eMotion Corp. Common Shares
RAYA	Erayak Power Solution Group Inc. - Class A Ordinary Shares
SAIH	SAIHEAT Limited - Class A Ordinary Shares
TAYD	Taylor Devices, Inc. - Common Stock
UDR	UDR, Inc. Common Stock
VCV	Invesco California Value Municipal Income Trust Common Stock
WBX	Wallbox N.V. Class A Ordinary Shares
XHLD	TEN Holdings, Inc. - Common Stock
YICC	Yorkville International Capital Corp. - Class A Ordinary Shares
ZION	Zions Bancorporation N.A. - Common Stock
ABAT	American Battery Technology Company - Common Stock
BARK	BARK, Inc. Class A Common Stock
CAKE	The Cheesecake Factory Incorporated - Common Stock
DBI	Designer Brands Inc. Class A Common Stock
ECO	Okeanis Eco Tankers Corp. Common Stock
FBK	FB Financial Corporation Common Stock
GBR	New Concept Energy, Inc Common Stock
HBCP	Home Bancorp, Inc. - Common Stock
IBP	Installed Building Products, Inc. Common Stock
JBLU	JetBlue Airways Corporation - Common Stock
KE	Kimball Electronics, Inc. - Common Stock
LATA	Galata Acquisition Corp. II - Class A Ordinary Shares
MANE	Veradermics, Incorporated Common Stock
NBHC	National Bank Holdings Corporation Common Stock
OCGN	Ocugen, Inc. - Common Stock
PANL	Pangaea Logistics Solutions Ltd. - Common Stock
QNCX	Quince Therapeutics, Inc. - Common Stock
RBA	RB Global, Inc. Common Stock
SAIL	SailPoint, Inc. - Common Stock
TBBB	BBB Foods Inc. Class A Common Shares
UE	Urban Edge Properties Common Shares of Beneficial Interest
VCYT	Veracyte, Inc. - Common Stock
WCC	WESCO International, Inc. Common Stock
XHR	Xenia Hotels & Resorts, Inc. Common Stock
YMAT	J-Star Holding Co., Ltd. - Class A Ordinary Shares
ZIP	ZipRecruiter, Inc. Class A Common Stock
BATL	Battalion Oil Corporation Common Stock
CAL	Caleres, Inc. Common Stock
DBX	Dropbox, Inc. - Class A Common Stock
ECOR	electroCore, Inc. - Common Stock
FBLA	FB Bancorp, Inc. - Common Stock
GBTG	Global Business Travel Group, Inc. Class A Common Stock
HBIO	Harvard Bioscience, Inc. - Common Stock
IBRX	ImmunityBio, Inc. - Common Stock
JBS	JBS N.V. Class A Common Shares
KEEL	Keel Infrastructure Corp. - Common Stock
LAUR	Laureate Education, Inc. - Common Stock
MANH	Manhattan Associates, Inc. - Common Stock
NBIS	Nebius Group N.V. - Class A Ordinary Shares
OCS	Oculis Holding AG - Ordinary shares
PANW	Palo Alto Networks, Inc. - Common Stock
QNME	Quanome Technologies, Inc. - Common Stock
RBB	RBB Bancorp - Common Stock
SAM	Boston Beer Company, Inc. (The) Common Stock
TBBK	The Bancorp, Inc. - Common Stock
UEC	Uranium Energy Corp. Common Stock
VECA	Vernal Capital Acquisition Corp. Ordinary Shares
WCN	Waste Connections, Inc. Common Shares
XLAB	Exascale Labs Holdings Inc. - Class A Common Stock
YORW	The York Water Company - Common Stock
ZJK	ZJK Industrial Co., Ltd. - Class A Ordinary Shares
ABCB	Ameris Bancorp Common Stock
BATRA	Atlanta Braves Holdings, Inc. - Series A Common Stock
CALC	CalciMedica, Inc. - Common Stock
DC	Dakota Gold Corp. Common Stock
ECPG	Encore Capital Group Inc - Common Stock
FBLG	FibroBiologics, Inc. - Common Stock
GBX	Greenbrier Companies, Inc. (The) Common Stock
HBM	Hudbay Minerals Inc. Ordinary Shares (Canada)
IBTA	Ibotta, Inc. Class A Common Stock
JBSS	John B. Sanfilippo & Son, Inc. - Common Stock
KELYA	Kelly Services, Inc. - Class A Common Stock
LAW	CS Disco, Inc. Common Stock
MANU	Manchester United Ltd. Class A Ordinary Shares
NBIX	Neurocrine Biosciences, Inc. - Common Stock
OCTV	Octave Intelligence plc - Class B Ordinary Shares
PAPL	Pineapple Financial Inc. Common Stock
QNST	QuinStreet, Inc. - Common Stock
RBBN	Ribbon Communications Inc.  - Common Stock
SAMG	Silvercrest Asset Management Group Inc. - Common Stock
TBCH	Turtle Beach Corporation - Common Stock
UEIC	Universal Electronics Inc. - Common Stock
VECO	Veeco Instruments Inc. - Common Stock
WCT	Wellchange Holdings Company Limited - Class A Ordinary shares
XLO	Xilio Therapeutics, Inc. - Common Stock
YOU	Clear Secure, Inc. Class A Common Stock
ZJYL	JIN MEDICAL INTERNATIONAL LTD. - Class A Ordinary Shares
ABCL	AbCellera Biologics Inc. - Common Shares
BATRK	Atlanta Braves Holdings, Inc. - Series C Common Stock
CALM	Cal-Maine Foods, Inc. - Common Stock
DCBO	Docebo Inc. - Common Shares
ECVT	Ecovyst Inc. Common Stock
FBNC	First Bancorp - Common Stock
GCBC	Greene County Bancorp, Inc. - Common Stock
HBNB	Hotel101 Global Holdings Corp. - Class A Ordinary Shares
ICCC	ImmuCell Corporation - Common Stock
JBTM	JBT Marel Corporation Common Stock
KELYB	Kelly Services, Inc. - Class B Common Stock
LAZ	Lazard, Inc. Common Stock
MAR	Marriott International - Class A Common Stock
NBN	Northeast Bank - Common Stock
OCUL	Ocular Therapeutix, Inc. - Common Stock
PAR	PAR Technology Corporation Common Stock
QNT	Quantinuum Inc. - Class A Common Stock
RBC	RBC Bearings Incorporated Common Stock
SAMO	Samos Energy Acquisition Corporation Class A Ordinary Shares
TBI	TrueBlue, Inc. Common Stock
UFCS	United Fire Group, Inc - Common Stock
VEEA	Veea Inc. - Common Stock
WD	Walker & Dunlop, Inc Common Stock
XMAX	XMAX, Inc. - Common Stock
YSS	York Space Systems Inc. Common Stock
ZKIN	ZK International Group Co., Ltd - Ordinary Share
ABEO	Abeona Therapeutics Inc. - Common Stock
BAX	Baxter International Inc. Common Stock
CALX	Calix, Inc Common Stock
DCGO	DocGo Inc. - Common Stock
ECX	ECARX Holdings Inc. - Class A Ordinary shares
FBP	First BanCorp. New Common Stock
GCDT	Green Circle Decarbonize Technology Limited Class A Ordinary Shares
HBNC	Horizon Bancorp, Inc. - Common Stock
ICCM	IceCure Medical Ltd. - Ordinary Shares
JCAP	Jefferson Capital, Inc. - Common Stock
KEN	Kenon Holdings Ltd. Ordinary Shares
LBGJ	Li Bang International Corporation Inc. - Class A Ordinary Shares
MARA	MARA Holdings, Inc. - Common Stock
NBRG	Newbridge Acquisition Limited - Class A Ordinary Share
ODC	Oil-Dri Corporation Of America Common Stock
PARA	Banzai International, Inc. - Class A Common Stock
QRED	QuasarEdge Acquisition Corporation Ordinary Shares
RBCAA	Republic Bancorp, Inc. - Class A Common Stock
SANA	Sana Biotechnology, Inc. - Common Stock
TBLA	Taboola.com Ltd. - Ordinary Shares
UFG	Uni-Fuels Holdings Limited - Class A Ordinary Shares
VEEE	Twin Vee PowerCats Co. - Common Stock
WDAY	Workday, Inc. - Class A Common Stock
XMTR	Xometry, Inc. - Class A Common Stock
YSWY	Yesway, Inc. - Class A Common Stock
ZKP	Lafayette Digital Acquisition Corp. I - Class A Ordinary Shares
ABG	Asbury Automotive Group Inc Common Stock
BB	BlackBerry Limited Common Stock
CALY	Callaway Golf Company Common Stock
DCH	Dauch Corporation Common Stock
ED	Consolidated Edison, Inc. Common Stock
FBRT	Franklin BSP Realty Trust, Inc. Common Stock
GCGR	General Catalyst Global Resilience Merger Corp. - Class A Ordinary Shares
HBT	HBT Financial, Inc. - Common Stock
ICE	Intercontinental Exchange Inc. Common Stock
JCI	Johnson Controls International plc Ordinary Share
KEP	Korea Electric Power Corporation Common Stock
LBRT	Liberty Energy Inc. Class A common stock
MAS	Masco Corporation Common Stock
NBTB	NBT Bancorp Inc. - Common Stock
ODD	ODDITY Tech Ltd. - Class A Ordinary Shares
PARK	Park Dental Partners, Inc. - Common Stock
QRHC	Quest Resource Holding Corporation - Common Stock
RBKB	Rhinebeck Bancorp, Inc. - Common Stock
SANG	Sangoma Technologies Corporation - Common Shares
TBN	Tamboran Resources Corporation Common stock
UFI	Unifi, Inc. New Common Stock
VEEV	Veeva Systems Inc. Class A Common Stock
WDC	Western Digital Corporation - Common Stock
XNCR	Xencor, Inc. - Common Stock
YSXT	YSX Tech. Co., Ltd  - Class A Ordinary Shares
ZM	Zoom Communications, Inc. - Class A Common Stock
ABLV	Able View Global Inc. - Class B Ordinary Shares
BBAI	BigBear.ai, Inc. Common Stock
CAMP	CAMP4 Therapeutics Corporation - Common Stock
DCI	Donaldson Company, Inc. Common Stock
EDBL	Edible Garden AG Incorporated - Common Stock
FBYD	Falcon's Beyond Global, Inc. - Class A Common Stock
GCL	GCL Global Holdings Ltd - Ordinary Shares
HCA	HCA Healthcare, Inc. Common Stock
ICFI	ICF International, Inc. - Common Stock
JCSE	JE Cleantech Holdings Limited - Ordinary Shares
KEQU	Kewaunee Scientific Corporation - Common Stock
LBRX	LB Pharmaceuticals Inc - Common Stock
MASK	3 E Network Technology Group Ltd - Class A Ordinary Shares
NC	NACCO Industries, Inc. Common Stock
ODFL	Old Dominion Freight Line, Inc. - Common Stock
PARR	Par Pacific Holdings, Inc.  Common Stock
QRVO	Qorvo, Inc. - Common Stock
RBLX	Roblox Corporation Class A Common Stock
SANM	Sanmina Corporation - Common Stock
TBPH	Theravance Biopharma, Inc. - Ordinary Shares
UFPI	UFP Industries, Inc. - Common Stock
VEL	Velocity Financial, Inc. Common Stock
WDFC	WD-40 Company - Common Stock
YTRA	Yatra Online, Inc. - Ordinary Shares
ZNB	Zeta Network Group - Class A Ordinary Shares
ABM	ABM Industries Incorporated Common Stock
BBCP	Concrete Pumping Holdings, Inc.  - Common Stock
CAMT	Camtek Ltd. - Ordinary Shares
DCO	Ducommun Incorporated Common Stock
EDHL	Everbright Digital Holding Limited - Ordinary Shares
FC	Franklin Covey Company Common Stock
GCMG	GCM Grosvenor Inc. - Class A Common Stock
HCAC	Hall Chadwick Acquisition Corp. - Class A Ordinary Shares
ICHR	Ichor Holdings - Ordinary Shares
JCTC	Jewett-Cameron Trading Company - Common Shares
KEX	Kirby Corporation Common Stock
LBTYA	Liberty Global Ltd. - Class A Common Shares
MASS	908 Devices Inc. - Common Stock
NCDL	Nuveen Churchill Direct Lending Corp. Common Stock
ODTX	Odyssey Therapeutics, Inc. - Common Stock
PASG	Passage Bio, Inc. - Common Stock
QS	QuantumScape Corporation - Common Stock
RBNE	Robin Energy Ltd. - Common Stock
SARO	StandardAero, Inc. Common Stock
TCBI	Texas Capital Bancshares, Inc. - Common Stock
UFPT	UFP Technologies, Inc. - Common Stock
VELO	Velo3D, Inc. - Common stock
WEAV	Weave Communications, Inc. Common Stock
XOS	Xos, Inc. - Common Stock
YUMC	Yum China Holdings, Inc. Common Stock
ZNTL	Zentalis Pharmaceuticals, Inc. - common stock
ABNB	Airbnb, Inc. - Class A Common Stock
BBDC	Barings BDC, Inc. Common Stock
CANG	Cango Inc. Class A Ordinary Shares
DCOM	Dime Commercial Bancshares, Inc. Common Stock
EDIT	Editas Medicine, Inc. - Common Stock
FCAP	First Capital, Inc. - Common Stock
GCO	Genesco Inc. Common Stock
HCAI	Huachen AI Parking Management Technology Holding Co., Ltd. - Class A Ordinary Shares
ICL	ICL Group Ltd. Ordinary Shares
JDZG	JIADE LIMITED - Class A Ordinary Shares
KEY	KeyCorp Common Stock
LBTYB	Liberty Global Ltd. - Class B Common Shares
MAT	Mattel, Inc. - Common Stock
NCEL	NewcelX Ltd. - Ordinary Shares
ODYS	Odysight.ai Inc. - Common Stock
PASW	Ping An Biomedical Co., Ltd. - Class A Ordinary Shares
QSEA	Quartzsea Acquisition Corporation - Ordinary Shares
RBRK	Rubrik, Inc. Class A Common Stock
SATL	Satellogic Inc. - Class A Common Stock
TCBK	TriCo Bancshares - Common Stock
UG	United-Guardian, Inc. - Common Stock
VENU	Venu Holding Corporation Common Stock
WEC	WEC Energy Group, Inc. Common Stock
XP	XP Inc. - Class A Common Stock
YYAI	AiRWA Inc. - Common Stock
ZONE	Zone Frontier Inc. Class B Common Stock
ABOS	Acumen Pharmaceuticals, Inc. - Common Stock
BBGI	Beasley Broadcast Group, Inc. - Class A Common Stock
CAPN	Cayson Acquisition Corp - Ordinary Shares
DCOY	Decoy Therapeutics Inc. - Common Stock
EDRY	EuroDry Ltd. - Common Shares
FCBC	First Community Bankshares, Inc. - Common Stock
GCT	GigaCloud Technology Inc - Class A Ordinary Shares
HCAT	Health Catalyst, Inc - Common stock
ICLR	ICON plc - Ordinary Shares
JEF	Jefferies Financial Group Inc. Common Stock
KEYS	Keysight Technologies Inc. Common Stock
LBTYK	Liberty Global Ltd. - Class C Common Shares
MATH	Metalpha Technology Holding Limited - Ordinary Shares
NCEW	New Century Logistics (BVI) Limited - Ordinary Shares
OEC	Orion S.A. Common Shares
PATH	UiPath, Inc. Class A Common Stock
QSI	Quantum-Si Incorporated - Class A Common Stock
RC	Ready Capital Corporation Common Stock
SB	Safe Bulkers, Inc Common Stock ($0.001 par value)
TCBS	Texas Community Bancshares, Inc. - Common Stock
UGI	UGI Corporation Common Stock
VERA	Vera Therapeutics, Inc. - Class A Common Stock
WELL	Welltower Inc. Common Stock
XPEL	XPEL, Inc. - Common Stock
ZOOZ	ZOOZ Strategy Ltd. - Ordinary Shares
ABR	Arbor Realty Trust Common Stock
BBIO	BridgeBio Pharma, Inc. - Common Stock
CAPR	Capricor Therapeutics, Inc. - Common Stock
DCTH	Delcath Systems, Inc. - Common Stock
EDSA	Edesa Biotech, Inc. - Common Shares
FCBM	First Carolina Financial Services, Inc. Common Stock
GCTK	GlucoTrack, Inc. - Common Stock
HCC	Warrior Met Coal, Inc. Common Stock
ICMB	Investcorp Credit Management BDC, Inc. - Common Stock
JELD	JELD-WEN Holding, Inc. Common Stock
KEYY	Keystone Acquisition Corp. - Class A Ordinary Shares
LCCC	Lakeshore Acquisition III Corp. - Ordinary Shares
MATV	Mativ Holdings, Inc. Common Stock
NCI	Neo-Concept International Group Holdings Limited - Class A Ordinary Shares
OESX	Orion Energy Systems, Inc. - Common Stock
PATK	Patrick Industries, Inc. - Common Stock
QSR	Restaurant Brands International Inc. Common Shares
RCAT	Red Cat Holdings, Inc. - Common Stock
SBAC	SBA Communications Corporation - Class A Common Stock
TCBX	Third Coast Bancshares, Inc. Common Stock
UHAL	U-Haul Holding Company Common Stock
VERI	Veritone, Inc. - Common Stock
WEN	Wendy's Company (The) - Common Stock
XPER	Xperi Inc. Common Stock 
ZS	Zscaler, Inc. - Common Stock
ABSI	Absci Corporation - Common Stock
BBLG	Bone Biologics Corp - Common Stock
CAPS	Capstone Holding Corp. - Common Stock
DCX	Digital Currency X Technology Inc. - Class A Ordinary Shares
EDTK	Skillful Craftsman Education Technology Limited - Ordinary Share
FCCO	First Community Corporation - Common Stock
GCTS	GCT Semiconductor Holding, Inc. Common Stock
HCHL	Happy City Holdings Limited - Class A Ordinary shares
ICON	Icon Energy Corp. - Common stock
JEM	707 Cayman Holdings Limited - Ordinary Shares
KFFB	Kentucky First Federal Bancorp - Common Stock
LCFY	Locafy Limited - Ordinary Share
MATW	Matthews International Corporation - Class A Common Stock
NCLH	Norwegian Cruise Line Holdings Ltd. Ordinary Shares
OFAL	OFA Group - Class A Ordinary Shares
PAVM	PAVmed Inc. - Common Stock
QTEX	QTREX Quantum Ltd. - Ordinary Shares
RCBC	River City Bank - Common stock
SBC	SBC Medical Group Holdings Incorporated - Common Stock
TCGX	TCGX Acquisition Corp. - Class A Ordinary Shares
UHAL-B	U-Haul Holding Company Series N Non-Voting Common Stock 
VERU	Veru Inc. - Common Stock
WENC	West Enclave Merger Corp. Ordinary Shares
XPL	Solitario Resources Corp. Common Stock
ZSQR	Z Squared Inc. - Common Stock
BBN	BlackRock Taxable Municipal Bond Trust Common Shares of Beneficial Interest
CAQ	Cambridge Acquisition Corp. - Class A Ordinary Shares
DD	DuPont de Nemours, Inc. Common Stock
EDU	New Oriental Education & Technology Group, Inc. Sponsored ADR representing 10 Ordinary Share (Cayman Islands)
FCEL	FuelCell Energy, Inc. - Common Stock
GD	General Dynamics Corporation Common Stock
HCI	HCI Group, Inc. Common Stock
ICU	SeaStar Medical Holding Corporation - Common Stock
JENA	Jena Acquisition Corporation II Class A Ordinary Shares
KFII	K&F Growth Acquisition Corp. II - Class A Ordinary shares
LCID	Lucid Group, Inc. - Common Stock
MATX	Matson, Inc. Common Stock
NCMI	National CineMedia, Inc. - Common Stock
OFG	OFG Bancorp Common Stock
PAVS	Paranovus Entertainment Technology Ltd. - Class A Ordinary Shares
QTI	QT Imaging Holdings, Inc. - Common Stock
RCEL	Avita Medical, Inc. - Common Stock
SBCF	Seacoast Banking Corporation of Florida - Common Stock
TCI	Transcontinental Realty Investors, Inc. Common Stock
UHS	Universal Health Services, Inc. Common Stock
VERX	Vertex, Inc. - Class A Common Stock
WENN	Wen Acquisition Corp - Class A Ordinary Shares
XPO	XPO, Inc. Common Stock
ZSTK	ZeroStack Corp. - Common Stock
ABTC	American Bitcoin Corp. - Class A Common Stock
BBNX	Beta Bionics, Inc. - Common Stock
CAR	Avis Budget Group, Inc. - Common Stock
DDC	DDC Enterprise Limited Class A Ordinary Shares
EDUC	Educational Development Corporation - Common Stock
FCF	First Commonwealth Financial Corporation Common Stock
GDC	GD Culture Group Limited - Common Stock
HCIC	Hennessy Capital Investment Corp. VIII - Class A Ordinary Shares
ICUI	ICU Medical, Inc. - Common Stock
JHI	John Hancock Investors Trust Common Stock
KFRC	Kforce, Inc. Common Stock
LCLN	Lincoln International, Inc. Class A Common Stock
MAX	MediaAlpha, Inc. Class A Common Stock
NCNO	nCino, Inc. - Common Stock
OFIX	Orthofix Medical Inc.  - Common Stock
PAX	Patria Investments Limited - Class A Common Shares
QTRX	Quanterix Corporation - Common Stock
RCI	Rogers Communication, Inc. Common Stock
SBET	Sharplink, Inc. - Common Stock
TCMD	Tactile Systems Technology, Inc. - Common Stock
UHT	Universal Health Realty Income Trust Common Stock
VFC	V.F. Corporation Common Stock
WERN	Werner Enterprises, Inc. - Common Stock
XPOF	Xponential Fitness, Inc. Class A Common Stock
ZTG	Zenta Group Company Limited - Class A Ordinary Shares
ABTS	Abits Group Inc - Ordinary Shares
BBOT	BridgeBio Oncology Therapeutics, Inc. - Common Stock
CARE	Carter Bankshares, Inc. - Common Stock
DDD	3D Systems Corporation Common Stock
EDVA	Endovia Health Sciences, Inc. Common Stock
FCFS	FirstCash Holdings, Inc. - Common Stock
GDDY	GoDaddy Inc. Class A Common Stock
HCKT	The Hackett Group, Inc. - Common Stock
IDA	IDACORP, Inc. Common Stock
JHS	John Hancock Income Securities Trust Common Stock
KFY	Korn Ferry Common Stock
LCNB	LCNB Corporation - Common Stock
MAYS	J. W. Mays, Inc. - Common Stock
NCO	Southern Cross Acquisition I Corp. - Ordinary Shares
OFLX	Omega Flex, Inc. - Common Stock
PAY	Paymentus Holdings, Inc. Class A Common Stock
QTTB	Q32 Bio Inc. - Common Stock
RCKT	Rocket Pharmaceuticals, Inc. - Common Stock
SBFG	SB Financial Group, Inc. - Common Stock
TCRT	Alaunos Therapeutics, Inc. - Common Stock
UI	Ubiquiti Inc. Common Stock
VFF	Village Farms International, Inc. - Common Shares
WEST	Westrock Coffee Company - Common Stock
XPON	Expion Energy, Inc. - Common Stock
ZTS	Zoetis Inc. Class A Common Stock
ABUS	Arbutus Biopharma Corporation - Common Stock
BBSI	Barrett Business Services, Inc. - Common Stock
CARG	CarGurus, Inc. - Class A Common Stock
DDOG	Datadog, Inc. - Class A Common Stock
EE	Excelerate Energy, Inc. Class A Common Stock
FCHL	Fitness Champs Holdings Limited - Ordinary Shares
GDEV	GDEV Inc. - Ordinary Shares
HCMA	HCM III Acquisition Corp. - Class A Ordinary Share
IDAC	Iron Dome Acquisition I Corp. - Class A Ordinary Shares
JHX	James Hardie Industries plc. Ordinary Shares
KG	Kestrel Group, Ltd. - Common Stock
LCTX	Lineage Cell Therapeutics, Inc. Common Stock
MAZE	Maze Therapeutics, Inc. - Common Stock
NCPL	Netcapital Inc. - Common Stock
OFRM	Once Upon a Farm, PBC Common Stock
PAYC	Paycom Software, Inc. Common Stock
QTWO	Q2 Holdings, Inc. Common Stock
RCKY	Rocky Brands, Inc. - Common Stock
SBFM	Sunshine Biopharma Inc. - Common stock
TCRX	TScan Therapeutics, Inc. - Common Stock
UIS	Unisys Corporation New Common Stock
VFS	VinFast Auto Ltd. - Ordinary Shares
WETH	Wetouch Technology Inc. - Common Stock
XPRO	Expro Ltd Ordinary Shares
ZUMZ	Zumiez Inc. - Common Stock
ABVC	ABVC BioPharma, Inc. - Common Stock
BBT	Beacon Financial Corporation Common stock
CARL	Carlsmed, Inc. - Common Stock
DDS	Dillard's, Inc. Common Stock
EEFT	Euronet Worldwide, Inc. - Common Stock
FCN	FTI Consulting, Inc. Common Stock
GDHG	Golden Heaven Group Holdings Ltd.  - Class A Ordinary Shares
HCSG	Healthcare Services Group, Inc. - Common Stock
IDAI	T Stamp Inc. - Class A Common Stock
JILL	J. Jill, Inc. Common Stock
KGC	Kinross Gold Corporation Common Stock
LCUT	Lifetime Brands, Inc. - Common Stock
MB	MasterBeef Group - Ordinary Shares
NCRA	Nocera, Inc. - common stock
OGC	OceanaGold Corporation Common Shares
PAYO	Payoneer Global Inc. - Common Stock
QUAD	Quad Graphics, Inc Class A Common Stock
RCL	Royal Caribbean Cruises Ltd. Common Stock
SBGI	Sinclair, Inc. - Class A Common Stock
TCX	Tucows Inc. - Common Stock
UK	Ucommune International Ltd  - Class A Ordinary Shares
VG	Venture Global, Inc. Class A common stock
WETO	Wetour Robotics Limited - Ordinary Shares
XRAY	DENTSPLY SIRONA Inc. - Common Stock
ZURA	Zura Bio Limited - Class A Ordinary shares
ABX	Abacus Global Management, Inc. Class A Common Stock
BBVA	Banco Bilbao Vizcaya Argentaria S.A. Common Stock
CARR	Carrier Global Corporation Common Stock 
DE	Deere & Company Common Stock
EEIQ	EpicQuest Education Group International Limited - Common Stock
FCNCA	First Citizens BancShares, Inc. - Class A Common Stock
GDOT	Green Dot Corporation Class A Common Stock, $0.001 par value
HCTI	Healthcare Triangle, Inc. - Common Stock
IDCC	InterDigital, Inc. - Common Stock
JJSF	J & J Snack Foods Corp. - Common Stock
KGEI	Kolibri Global Energy Inc. - Common stock
LDI	loanDepot, Inc. Class A Common Stock
MBAI	MBody AI Ltd. - Ordinary Share
NCT	Intercont (Cayman) Limited - Class A Ordinary shares
OGE	OGE Energy Corp Common Stock
PAYS	Paysign, Inc. - Common Stock
QUBT	Quantum Computing Inc. - Common Stock
RCMT	RCM Technologies, Inc. - Common Stock
SBH	Sally Beauty Holdings, Inc. (Name to be changed from Sally Holdings, Inc.) Common Stock
TD	Toronto Dominion Bank (The) Common Stock
ULBI	Ultralife Corporation - Common Stock
VGAS	Verde Clean Fuels, Inc. - Class A Common Stock
WEX	WEX Inc. common stock
XRN	Chiron Real Estate Inc. Common Stock
ZVIA	Zevia PBC Class A Common Stock
ACA	Arcosa, Inc. Common Stock 
BBW	Build-A-Bear Workshop, Inc. Common Stock
CARS	Cars.com Inc. Common Stock 
DEA	Easterly Government Properties, Inc. Common Stock
EFC	Ellington Financial Inc. Common Stock 
FCPT	Four Corners Property Trust, Inc. Common Stock
GDRX	GoodRx Holdings, Inc. - Class A Common Stock
HCWB	HCW Biologics Inc. - Common Stock
IDN	Intellicheck, Inc. - Common Stock
JKHY	Jack Henry & Associates, Inc. - Common Stock
KGS	Kodiak Gas Services, Inc. Common Stock
LDOS	Leidos Holdings, Inc. Common Stock
MBBC	Marathon Bancorp, Inc. - Common Stock
NDAQ	Nasdaq, Inc. - Common Stock
OGEN	Oragenics Inc. Common Stock
PAYX	Paychex, Inc. - Common Stock
QUCY	Quantum Cyber N.V. - Ordinary Shares
RCON	Recon Technology, Ltd. - Class A Ordinary Shares
SBLK	Star Bulk Carriers Corp. - Common Shares
TDAC	Translational Development Acquisition Corp. - Ordinary Shares
ULCC	Frontier Group Holdings, Inc. - Common Stock
VGM	Invesco Trust for Investment Grade Municipals Common Stock (DE)
WEYS	Weyco Group, Inc. - Common Stock
XRPN	Armada Acquisition Corp. II - Class A Ordinary Shares
ZVRA	Zevra Therapeutics, Inc.  - Common Stock
ACAA	Averin Capital Acquisition Corp. - Class A Ordinary Shares
BBY	Best Buy Co., Inc. Common Stock
CART	Maplebear Inc. - Common Stock
DEC	Diversified Energy Company Common Stock
EFOI	Energy Focus, Inc. - Common Stock
FCRS	FutureCrest Acquisition Corp. Class A Ordinary Shares
GDTC	CytoMed Therapeutics Limited - Ordinary Shares
HCWC	Healthy Choice Wellness Corp. Class A Common Stock
IDR	Idaho Strategic Resources, Inc. Common Stock
JL	J-Long Group Limited - Class A Ordinary Shares
KHC	The Kraft Heinz Company - Common Stock
LE	Lands' End, Inc. - Common Stock
MBC	MasterBrand, Inc. Common Stock
NDLS	Noodles & Company - Class A Common Stock
OGG	Osisko Gold Group Inc. Common Shares
PB	Prosperity Bancshares, Inc. Common Stock
QUIK	QuickLogic Corporation - Common Stock
RCT	RedCloud Holdings plc - Ordinary Shares
SBMT	Silver Bow Mining Corp. Common Shares
TDAY	USA TODAY Co., Inc. Common Stock
ULH	Universal Logistics Holdings, Inc. - Common Stock
VGNT	Versigent PLC Ordinary Shares
WFC	Wells Fargo & Company Common Stock
XRTX	XORTX Therapeutics Inc. - Common Shares
ZWS	Zurn Elkay Water Solutions Corporation Common Stock
ACAD	ACADIA Pharmaceuticals Inc. - Common Stock
BC	Brunswick Corporation Common Stock
CASH	Pathward Financial, Inc. - Common Stock
DECK	Deckers Outdoor Corporation Common Stock
EFOR	Everforth, Inc. Common Stock
FCUV	Focus Universal Inc. - Common Stock
GDV	Gabelli Dividend & Income Trust Common Shares of Beneficial Interest
IDT	IDT Corporation Class B Common Stock
JLHL	Julong Holding Limited - Class A Ordinary Shares
KIDS	OrthoPediatrics Corp. - Common Stock
LEA	Lear Corporation Common Stock
MBGL	Mobility Global Inc. Common Stock
NDRA	ENDRA Life Sciences Inc. - Common Stock
OGI	Organigram Global Inc. - Common Shares
PBA	Pembina Pipeline Corp. Ordinary Shares (Canada)
QUMS	Quantumsphere Acquisition Corp. - Ordinary Shares
RCUS	Arcus Biosciences, Inc. Common Stock
SBR	Sabine Royalty Trust Common Stock
TDC	Teradata Corporation Common Stock
ULS	UL Solutions Inc. Class A Common Stock
VGZ	Vista Gold Corp Common Stock
WFCF	Where Food Comes From, Inc. - Common Stock
XRX	Xerox Holdings Corporation - Common Stock
ZYBT	Zhengye Biotechnology Holding Limited - Class A Ordinary Shares
ACB	Aurora Cannabis Inc. - Common Shares
BCAL	California BanCorp - Common Stock
CASS	Cass Information Systems, Inc - Common Stock
DEFT	Defi Technologies, Inc. - Common Stock
EFSC	Enterprise Financial Services Corporation - Common Stock
FCX	Freeport-McMoRan, Inc. Common Stock
GDYN	Grid Dynamics Holdings, Inc. - Class A Common Stock
HDB	HDFC Bank Limited Common Stock
IDXX	IDEXX Laboratories, Inc. - Common Stock
JLL	Jones Lang LaSalle Incorporated Common Stock
KIDZ	KIDZ AI Inc. - Class B Common Stock
LECO	Lincoln Electric Holdings, Inc. - Common Shares
MBI	MBIA Inc. Common Stock
NDSN	Nordson Corporation - Common Stock
OGN	Organon & Co. Common Stock 
PBAM	Private Bancorp of America, Inc. - Common Stock
QURE	uniQure N.V. - Ordinary Shares
RDAC	Rising Dragon Acquisition Corp. - Ordinary Shares
SBRA	Sabra Health Care REIT, Inc. - Common Stock
TDG	Transdigm Group Incorporated Common Stock
ULTA	Ulta Beauty, Inc. - Common Stock
VHC	VirnetX Holding Corp - Common Stock
WFF	WF Holding Limited - Ordinary Shares
XSLL	Xsolla SPAC 1 - Class A Ordinary Shares
ZYME	Zymeworks Inc. - Common Stock
ACCL	Acco Group Holdings Limited - Class A Ordinary Shares
BCAT	BlackRock Capital Allocation Term Trust Common Shares of Beneficial Interest
CAST	FreeCast, Inc. - Class A common stock
DEI	Douglas Emmett, Inc. Common Stock
EFSI	Eagle Financial Services Inc - Common Stock
FDBC	Fidelity D & D Bancorp, Inc. - Common Stock
HDRN	Hadron Energy, Inc. - Common Stock
IDYA	IDEAYA Biosciences, Inc. - Common Stock
JMKE	Jersey Mike's Subs Inc. Class A Common Stock
KIM	Kimco Realty Corporation (HC) Common Stock
LEDS	SemiLEDS Corporation - Common Stock
MBIN	Merchants Bancorp - Common Stock
NE	Noble Corporation plc A Ordinary Shares
OGS	ONE Gas, Inc. Common Stock
PBF	PBF Energy Inc. Class A Common Stock
QVCG	QVC Group, Inc. - Common Stock
RDAG	Republic Digital Acquisition Company - Class A Ordinary Shares
SBSI	Southside Bancshares, Inc. Common Stock
TDIC	Dreamland Limited - Class A Ordinary Shares
UMAC	Unusual Machines, Inc. Common Stock
VHCP	Vine Hill Capital Investment Corp. II - Class A Ordinary Shares
WFG	West Fraser Timber Co. Ltd Common stock
XTER	Karman Line Acquisition Corp. - Class A Ordinary Shares
ACCO	Acco Brands Corporation Common Stock
BCAX	Bicara Therapeutics Inc. - Common Stock
CASY	Caseys General Stores, Inc. - Common Stock
DELL	Dell Technologies Inc. Class C Common Stock 
EFT	Eaton Vance Floating Rate Income Trust Common Shares of Beneficial Interest
FDMM	Freedom Metals Acquisition Corp. - Class A Ordinary Shares
GEF	Greif Inc. Class A Common Stock
HDSN	Hudson Technologies, Inc. - Common Stock
IE	Ivanhoe Electric Inc. Common Stock
JMSB	John Marshall Bancorp, Inc. - Common Stock
KINS	Kingstone Companies, Inc - Common Stock
LEE	Lee Enterprises, Incorporated - Common Stock
MBIO	Mustang Bio, Inc. - Common Stock
NECB	NorthEast Community Bancorp, Inc. - Common Stock
OHAC	Oceanhawk Acquisition Corp. - Class A Ordinary Shares
PBFS	Pioneer Bancorp, Inc. - Common Stock
QXL	Quantum X Labs Inc. - Common Stock
RDCM	Radcom Ltd. - Ordinary Shares
SBUX	Starbucks Corporation - Common Stock
TDOC	Teladoc Health, Inc. Common Stock
UMBF	UMB Financial Corporation - Common Stock
VHI	Valhi, Inc. Common Stock
WFRD	Weatherford International plc - Ordinary shares
XTIA	XTI Aerospace, Inc. Common Stock  - Common Stock
ACCS	ACCESS Newswire Inc. Common Stock
BCBP	BCB Bancorp, Inc. (NJ) - Common Stock
DEO	Diageo plc Common Stock
EFTY	Etoiles Capital Group Co., Ltd. - Class A Ordinary Shares
FDMT	4D Molecular Therapeutics, Inc. - Common Stock
GEF-B	Greif, Inc. Corporation Class B Common Stock
HE	Hawaiian Electric Industries, Inc. Common Stock
IEAG	Infinite Eagle Acquisition Corp. - Class A Ordinary Shares
KITT	Nauticus Robotics, Inc. - Common stock
LEGH	Legacy Housing Corporation - Common Stock
MBLY	Mobileye Global Inc. - Class A Common Stock
OHI	Omega Healthcare Investors, Inc. Common Stock
PBH	Prestige Consumer Healthcare Inc. Common Stock
QXO	QXO, Inc. Common Stock
RDDT	Reddit, Inc. Class A Common Stock
SBXD	SilverBox Corp IV Class A Ordinary Shares
TDS	Telephone and Data Systems, Inc. Common Shares
UMC	United Microelectronics Corporation (NEW) Common Stock
VHUB	VenHub Global, Inc. - Common Stock
WGO	Winnebago Industries, Inc. Common Stock
XTND	Xtend AI Robotics, Inc. Common Stock
ACDC	ProFrac Holding Corp. - Class A Common Stock
BCC	Boise Cascade, L.L.C. Common Stock
CATO	Cato Corporation (The) Class A Common Stock
DERM	Journey Medical Corporation - Common Stock
EFX	Equifax, Inc. Common Stock
FDS	FactSet Research Systems Inc. Common Stock
GEG	Great Elm Group, Inc.  - Common Stock
HEI	Heico Corporation Common Stock
IESC	IES Holdings, Inc. - Common Stock
JOB	GEE Group Inc. Common Stock
KKR	KKR & Co. Inc. Common Stock
LEGO	Legato Merger Corp. IV Ordinary Shares
MBOT	Microbot Medical Inc.  - Common Stock
NEGG	Newegg Commerce, Inc. - Common Shares
OI	O-I Glass, Inc. Common Stock
PBHC	Pathfinder Bancorp, Inc. - Common Stock
RDGT	Ridgetech, Inc. - Ordinary Shares
SBXE	SilverBox Corp V Class A Ordinary Shares
TDTH	Trident Digital Tech Holdings Ltd - Class B Ordinary Shares
UMH	UMH Properties, Inc. Common Stock
VIA	Via Transportation, Inc. Class A Common Stock
WGS	GeneDx Holdings Corp. - Class A Common Stock
XTNT	Xtant Medical Holdings, Inc. Common Stock
ACET	Adicet Bio, Inc. - Common Stock
BCCQ	Bleichroeder Acquisition Corp. III - Class A Ordinary Shares
CATX	Perspective Therapeutics, Inc. Common Stock
DETX	Liberty Defense Holdings, Ltd. - Common Shares
EFXT	Enerflex Ltd Common Shares
FDSB	Fifth District Bancorp, Inc. - Common Stock
GEHC	GE HealthCare Technologies Inc. - Common Stock
HEI-A	Heico Corporation Common Stock
IEX	IDEX Corporation Common Stock
JOBY	Joby Aviation, Inc. Common Stock
KLAC	KLA Corporation  - Common Stock
LEN	Lennar Corporation Class A Common Stock
MBRX	Moleculin Biotech, Inc. - Common Stock
NEO	NeoGenomics, Inc. - Common Stock
OIA	Invesco Municipal Income Opportunities Trust Common Stock
PBI	Pitney Bowes Inc. Common Stock
RDI	Reading International Inc - Class A Non-voting Common Stock
SCCO	Southern Copper Corporation Common Stock
TDUP	ThredUp Inc. - Class A Common Stock
UNB	Union Bankshares, Inc. - Common Stock
VIAV	Viavi Solutions Inc. - Common Stock
WH	Wyndham Hotels & Resorts, Inc. Common Stock 
XWEL	XWELL, Inc. - Common Stock
ACFN	Acorn Energy, Inc. - Common Stock
BCDA	BioCardia, Inc. - Common Stock
CATY	Cathay General Bancorp - Common Stock
DFDV	DeFi Development Corp. - Common Stock
EG	Everest Group, Ltd. Common Stock
FDX	FedEx Corporation Common Stock
GELS	Gelteq Limited - Ordinary Shares
HELE	Helen of Troy Limited - Common Stock
IFBD	Infobird Co., Ltd - Ordinary Shares
JOE	St. Joe Company (The) Common Stock
KLAR	Klarna Group plc Ordinary Shares
LENZ	LENZ Therapeutics, Inc. - Common Stock
MBUU	Malibu Boats, Inc. - Common Stock
NEOG	Neogen Corporation - Common Stock
OII	Oceaneering International, Inc. Common Stock
PBK	PowerBank Corporation - Common Stock
RDIB	Reading International Inc - Class B Voting Common Stock
SCHL	Scholastic Corporation - Common Stock
TDW	Tidewater Inc. Common Stock
UNCY	Unicycive Therapeutics, Inc. - Common Stock
VICI	VICI Properties Inc. Common Stock
WHD	Cactus, Inc. Class A Common Stock
XXI	Twenty One Capital, Inc. Class A Common Stock
ACGC	ACP Holdings Acquisition Corp. - Class A Ordinary Shares
BCE	BCE, Inc. Common Stock
CAVA	CAVA Group, Inc. Common Stock
DFH	Dream Finders Homes, Inc. Class A Common Stock
EGAN	eGain Corporation - Common Stock
FDXF	FedEx Freight Holding Company, Inc. Common Stock
GEMI	Gemini Space Station, Inc. - Class A Common Stock
HELP	Cybin Inc. - Common Stock
IFF	International Flavors & Fragrances, Inc. Common Stock
JONE	Jones Ventures INTL Acquisition1 Corp - Class A Ordinary Shares
KLC	KinderCare Learning Companies, Inc. Common Stock
LEO	BNY Mellon Strategic Municipals, Inc. Common Stock
MBVI	M3-Brigade Acquisition VI Corp. - Class A Ordinary Shares
NEON	Neonode Inc. - Common Stock
OIM	OneIM Acquisition Corp. - Class A Ordinary Shares
PBLS	Parabilis Medicines, Inc. - Common Stock
RDN	Radian Group Inc. Common Stock
SCHW	Charles Schwab Corporation (The) Common Stock
TDWD	Tailwind 2.0 Acquisition Corp. - Class A Ordinary Shares
UNF	Unifirst Corporation Common Stock
VICR	Vicor Corporation - Common Stock
WHG	Westwood Holdings Group Inc Common Stock
XXII	22nd Century Group, Inc - Common Stock
ACGL	Arch Capital Group Ltd. - Common Stock
BCG	Binah Capital Group, Inc. - Common Stock
CB	Chubb Limited  Common Stock
DFIN	Donnelley Financial Solutions, Inc. Common Stock 
EGBN	Eagle Bancorp, Inc. - Common Stock
FE	FirstEnergy Corp. Common Stock
GEN	Gen Digital Inc. - Common Stock
HFBL	Home Federal Bancorp, Inc. of Louisiana - Common Stock
IFRX	InflaRx N.V. - Common Stock
JOUT	Johnson Outdoors Inc. - Class A Common Stock
KLIC	Kulicke and Soffa Industries, Inc. - Common Stock
LESL	Leslie's, Inc. - Common Stock
MBWM	Mercantile Bank Corporation - Common Stock
NEOV	NeoVolta Inc. - Common Stock
OIO	OIO Group - Ordinary Shares
PBM	Psyence Biomedical Ltd. - Common Shares
RDNT	RadNet, Inc. - Common Stock
SCI	Service Corporation International Common Stock
TDY	Teledyne Technologies Incorporated Common Stock
UNFI	United Natural Foods, Inc. Common Stock
VIDA	VIDA Global Inc. Class A Common Stock
WHK	WhiteHawk Minerals Corp Class A Common Stock
XYL	Xylem Inc. Common Stock New
ACH	Accendra Health, Inc. Common Stock
BCHT	Birchtech Corp. Common Stock
CBAN	Colony Bankcorp, Inc. Common Stock
DFLI	Dragonfly Energy Holdings Corp - Common Stock
EGG	Enigmatig Limited Class A Ordinary Shares
FEAM	5E Advanced Materials, Inc. - Common Stock
GENB	Generate Biomedicines, Inc. - Common Stock
HFFG	HF Foods Group Inc. - Common Stock
IFS	Intercorp Financial Services Inc. Common Shares
KLRA	Kailera Therapeutics, Inc. - Common stock
LEU	Centrus Energy Corp. Class A Common Stock
MBX	MBX Biosciences, Inc. - Common Stock
NEPH	Nephros, Inc. - Common Stock
OIS	Oil States International, Inc. Common Stock
PBT	Permian Basin Royalty Trust Common Stock
RDNW	RideNow Group, Inc. - Class B Common Stock
SCII	SC II Acquisition Corp. - Class A ordinary share
TE	T1 Energy Inc. Common Stock
VII	Viking Acquisition Corp. II Class A Ordinary Shares
WHLR	Wheeler Real Estate Investment Trust, Inc. - Common Stock
XYZ	Block, Inc. Class A Common Stock,
ACHC	Acadia Healthcare Company, Inc. - Common Stock
BCML	BayCom Corp - Common Stock
CBAT	CBAK Energy Technology Limited - Ordinary Shares
DFNS	T3 Defense Inc. - Common Stock
EGHA	EGH Acquisition Corp. - Class A ordinary shares
FEBO	Fenbo Holdings Limited - Class A Ordinary Shares
GENC	Gencor Industries, Inc. Common Stock
HFWA	Heritage Financial Corporation - Common Stock
IGAC	Invest Green Acquisition Corporation - Class A Ordinary Shares
JRSH	Jerash Holdings (US), Inc. - Common Stock
KLRS	Kalaris Therapeutics, Inc.  - Common Stock
LEVI	Levi Strauss & Co Class A Common Stock
MC	Moelis & Company Class A Common Stock
NERV	Minerva Neurosciences, Inc - Common Stock
OKE	ONEOK, Inc. Common Stock
PBYI	Puma Biotechnology Inc - Common Stock
RDVT	Red Violet, Inc. - Common Stock 
SCKT	Socket Mobile, Inc. - Common Stock
TEAD	Teads Holding Co. - Common Stock
UNIT	Uniti Group Inc. - Common Stock
VIK	Viking Holdings Ltd Ordinary Shares
WHR	Whirlpool Corporation Common Stock
XZO	Exzeo Group, Inc. Common Stock
ACHR	Archer Aviation Inc. Class A Common Stock
BCO	Brinks Company (The) Common Stock
CBC	Central Bancompany, Inc. - Class A Common Stock
DFSC	DEFSEC Technologies Inc. - common stock, no R/S concurrent with offering
EGHT	8x8 Inc - Common stock
FEED	ENvue Medical, Inc. - Common Stock
GENI	Genius Sports Limited Ordinary Shares
HG	Hamilton Insurance Group, Ltd. Class B Common Shares
IGC	IGC Pharma, Inc. Common Stock
JRVR	James River Group Holdings, Inc. - Common Stock
KLTR	Kaltura, Inc. - Common Stock
LEXX	Lexaria Bioscience Corp. - Common Stock
MCAH	Mountain Crest Acquisition 6 Corp. - Ordinary Shares
NESR	National Energy Services Reunited Corp - Ordinary Shares
OKLO	Oklo Inc. Class A common stock
PC	Premium Catering (Holdings) Limited - Ordinary Shares
RDW	Redwire Corporation Common Stock
SCL	Stepan Company Common Stock
TEAM	Atlassian Corporation  - Class A Common Stock
UNM	Unum Group Common Stock
VINP	Vinci Compass Investments Ltd. - Class A Common Shares
WHWK	Whitehawk Therapeutics, Inc. - Common Stock
ACHV	Achieve Life Sciences, Inc.  - Common Shares
BCPC	Balchem Corporation - Common Stock
CBFV	CB Financial Services, Inc. - Common Stock
DFTX	Definium Therapeutics, Inc.  - Common Shares
EGO	Eldorado Gold Corporation Ordinary Shares
FEIM	Frequency Electronics, Inc. - Common Stock
GENK	GEN Restaurant Group, Inc. - Class A Common Stock
HGBL	Heritage Global Inc. - Common Stock
IGI	Western Asset Investment Grade Opportunity Trust Inc. Common Stock
JSPR	Jasper Therapeutics, Inc. - Class A Common Stock
KLXE	KLX Energy Services Holdings, Inc.  - Common Stock
LFAC	Leapfrog Acquisition Corporation - Class A Ordinary Shares
MCB	Metropolitan Bank Holding Corp. Common Stock
NET	Cloudflare, Inc. Class A Common Stock
OKTA	Okta, Inc. - Class A Common Stock
PCAP	ProCap Acquisition Corp - Class A Ordinary Shares
RDWR	Radware Ltd. - Ordinary Shares
SCLX	Scilex Holding Company - Common Stock
TECH	Bio-Techne Corp - Common Stock
UNP	Union Pacific Corporation Common Stock
VIP	Vulcan Infrastructure and Power Inc. - Class A Common Stock
WIMI	WiMi Hologram Cloud Inc. - Class B Ordinary Shares
ACI	Albertsons Companies, Inc. Class A Common Stock
BCRX	BioCryst Pharmaceuticals, Inc. - Common Stock
CBIO	Crescent Biopharma, Inc. - Common Stock
DG	Dollar General Corporation Common Stock
EGP	EastGroup Properties, Inc. Common Stock
FELE	Franklin Electric Co., Inc. - Common Stock
GEOS	Geospace Technologies Corporation - Common Stock
HGTY	Hagerty, Inc. Class A Common Stock
IGIC	International General Insurance Holdings Ltd. - Ordinary Shares
JTAI	Jet.AI Inc. - Common Stock
KMB	Kimberly-Clark Corporation - Common Stock
LFCR	Lifecore Biomedical, Inc. - Common Stock
MCBS	MetroCity Bankshares, Inc. - Common Stock
NEU	NewMarket Corp Common Stock
OKUR	OnKure Therapeutics, Inc. - Class A Common Stock
PCAR	PACCAR Inc. - Common Stock
RDY	Dr. Reddy's Laboratories Ltd Common Stock
SCM	Stellus Capital Investment Corporation Common Stock
TECK	Teck Resources Ltd Ordinary Shares
UNTY	Unity Bancorp, Inc. - Common Stock
VIR	Vir Biotechnology, Inc. - Common Stock
WINA	Winmark Corporation - Common Stock
ACIC	American Coastal Insurance Corporation - Common Stock
BCS	Barclays PLC Common Stock
CBK	Commercial Bancgroup, Inc. - Common Stock
DGAC	Disciplined Growth Acquisition Corporation Class A Ordinary Shares
EGY	VAALCO Energy, Inc.  Common Stock
FEMY	Femasys Inc. - Common Stock
GERN	Geron Corporation - Common Stock
HGV	Hilton Grand Vacations Inc. Common Stock 
IHRT	iHeartMedia, Inc. - Class A Common Stock
JTTT	JATT III Acquisition Corp - Ordinary Shares
KMDA	Kamada Ltd. - Ordinary Shares
LFMD	LifeMD, Inc. - Common Stock
MCD	McDonald's Corporation Common Stock
NEUP	Neuphoria Therapeutics Inc. - Common Stock
OKYO	OKYO Pharma Limited - Ordinary Shares
PCB	PCB Bancorp - Common Stock
RDZN	Roadzen, Inc. - Ordinary Shares
SCNX	Scienture Holdings, Inc. - Common Stock
TECX	Tectonic Therapeutic, Inc. - Common Stock
UONE	Urban One, Inc.  - Class A Common Stock
VIRC	Virco Manufacturing Corporation - Common Stock
WING	Wingstop Inc. - Common Stock
ACIU	AC Immune SA - Common Stock
BCSF	Bain Capital Specialty Finance, Inc. Common Stock
CBL	CBL & Associates Properties, Inc. Common Stock
DGICA	Donegal Group, Inc. - Class A Common Stock
EHC	Encompass Health Corporation Common Stock
FENC	Fennec Pharmaceuticals Inc. - Common Stock
GETY	Getty Images Holdings, Inc. Class A Common Stock
HHH	Howard Hughes Holdings Inc. Common Stock
IHS	IHS Holding Limited Ordinary Shares
JUNS	Jupiter Neurosciences, Inc. - Common Stock
KMI	Kinder Morgan, Inc. Common Stock
LFST	LifeStance Health Group, Inc. - Common Stock
MCFT	MasterCraft Boat Holdings, Inc. - Common Stock
NEWP	New Pacific Metals Corp. Common Shares
OLB	The OLB Group, Inc. - Common Stock
PCG	Pacific Gas & Electric Co. Common Stock
REA	Rare Earths Americas, Inc. Common Stock
SCOR	comScore, Inc. - Common Stock
TEL	TE Connectivity plc Ordinary Shares
UONEK	Urban One, Inc.  - Class D Common Stock
VIRT	Virtu Financial, Inc. Class A Common Stock
WIT	Wipro Limited Common Stock
ACIW	ACI Worldwide, Inc. - Common Stock
BCSS	Bain Capital GSS Investment Corp. Class A Ordinary Shares
CBLL	CeriBell, Inc. - Common Stock
DGICB	Donegal Group, Inc. - Class B Common Stock
EHGO	Eshallgo Inc. - Class A Ordinary Shares
FER	Ferrovial N.V. - Ordinary Shares
GEV	GE Vernova Inc. Common Stock
HHS	Harte Hanks, Inc. - Common Stock
III	Information Services Group, Inc. - Common Stock
JVA	Coffee Holding Co., Inc. - Common Stock
KMRK	K-Tech Solutions Company Limited - Class A Ordinary Shares
LFT	Lument Finance Trust, Inc. Common Stock
MCGA	Yorkville Acquisition Corp. - Class A Ordinary Share
NEWT	NewtekOne, Inc. - Common Stock
OLED	Universal Display Corporation - Common Stock
PCOR	Procore Technologies, Inc. Common Stock
REAL	The RealReal, Inc. - Common Stock
SCPQ	Social Commerce Partners Corporation - Class A Ordinary Shares
TELA	TELA Bio, Inc. - Common stock
UP	Wheels Up Experience Inc. Class A Common Stock
VISN	Vistance Networks, Inc.  - Common Stock
WIX	Wix.com Ltd. - Ordinary Shares
ACLS	Axcelis Technologies, Inc. - Common Stock
BCTX	BriaCell Therapeutics Corp. - Common Shares
CBNA	Chain Bridge Bancorp, Inc. Class A Common Stock
DGII	Digi International Inc. - Common Stock
EHLD	Euroholdings Ltd. - Common Stock
FERA	Fifth Era Acquisition Corp I - Class A Ordinary Shares
GEVO	Gevo, Inc. - Common Stock
HIFS	Hingham Institution for Savings - Common Stock
IIIN	Insteel Industries, Inc. Common Stock
JWEL	Jowell Global Ltd. - Ordinary Shares
KMT	Kennametal Inc. Common Stock
LFTO	Liftoff Mobile, Inc. - Common Stock
MCHB	Mechanics Bancorp - Class A Common Stock
NEXA	Nexa Resources S.A. Common Shares
OLLI	Ollie's Bargain Outlet Holdings, Inc. - Common Stock
PCRX	Pacira BioSciences, Inc. - Common Stock
REAX	Real REMAX Group Inc. - Common Stock
SCSC	ScanSource, Inc. - Common Stock
TELO	Telomir Pharmaceuticals, Inc. - Common Stock
UPB	Upstream Bio, Inc. - Common Stock
VITL	Vital Farms, Inc. - Common Stock
WK	Workiva Inc. Class A Common Stock
ACM	AECOM Common Stock
BCX	BlackRock Resources Common Shares of Beneficial Interest
CBNK	Capital Bancorp, Inc. - Common Stock
DGNX	Diginex Limited - Ordinary Shares
EHTH	eHealth, Inc. - Common Stock
FERG	Ferguson Enterprises Inc. Common Stock
GFAI	Guardforce AI Co., Limited - Ordinary Shares
HIG	The Hartford Insurance Group, Inc. Common Stock
IIIV	i3 Verticals, Inc. - Common Stock
JXG	JX Luxventure Group Inc. - Common Stock
KMTS	Kestra Medical Technologies, Ltd. - Common Stock
LFUS	Littelfuse, Inc. - Common Stock
MCHP	Microchip Technology Incorporated - Common Stock
NEXM	NexMetals Mining Corp. - Common Stock
OLMA	Olema Pharmaceuticals, Inc. - Common Stock
PCSA	Processa Pharmaceuticals, Inc. - Common Stock
REBN	Reborn Coffee, Inc. - Common Stock
SCTX	Scribe Therapeutics Inc. - Common Stock
TEM	Tempus AI, Inc. - Class A Common Stock
UPBD	Upbound Group, Inc. - Common Stock
VIVK	Vivakor, Inc. - Common Stock
WKC	World Kinect Corporation Common Stock
ACMR	ACM Research, Inc. - Class A Common Stock
BDC	Belden Inc Common Stock
CBOE	Cboe Global Markets, Inc. Common Stock
DGX	Quest Diagnostics Incorporated Common Stock
EIC	Eagle Point Income Company Common Shares of Beneficial Interest
FET	Forum Energy Technologies, Inc. Common Stock
GFF	Griffon Corporation Common Stock
HIHO	Highway Holdings Limited - Common Stock
IIM	Invesco Value Municipal Income Trust Common Stock
JXN	Jackson Financial Inc. Class A Common Stock 
KN	Knowles Corporation Common Stock
LFVN	Lifevantage Corporation - Common Stock
MCHX	Marchex, Inc. - Class B Common Stock
NEXN	Nexxen International Ltd. - Ordinary Shares
OLN	Olin Corporation Common Stock
PCT	PureCycle Technologies, Inc. - Common stock
RECT	Rectitude Holdings Ltd - Ordinary Shares
SCWO	374Water Inc. - common stock
TEN	Tsakos Energy Navigation Ltd Common Shares
UPC	Universe Pharmaceuticals Inc - Class A Ordinary Shares
VIVO	VivoPower PLC - Class A Ordinary Shares
WKHS	Workhorse Group, Inc. - Common Stock
ACN	Accenture plc Class A Ordinary Shares (Ireland)
BDCI	BTC Development Corp. - Class A Ordinary Shares
CBRE	CBRE Group Inc Common Stock Class A
DH	Definitive Healthcare Corp. - Class A Common Stock
EIG	Employers Holdings Inc Common Stock
FF	FutureFuel Corp.  Common shares
GFR	Greenfire Resources Ltd. Common Shares
HII	Huntington Ingalls Industries, Inc. Common Stock
IIPR	Innovative Industrial Properties, Inc. Common Stock
JYD	Jayud Global Logistics Limited - Class A Ordinary Shares
KNDI	Kandi Technologies Group, Inc. - Ordinary Shares
LFWD	Lifeward Ltd. - Ordinary Shares
MCI	Barings Corporate Investors Common Stock
NEXR	Nexera Technologies Ltd - Ordinary Shares
OLOX	Olenox Industries Inc. - Common Stock
PCTY	Paylocity Holding Corporation - Common Stock
REED	Reed's, Inc. Common Stock
SCYX	SCYNEXIS, Inc. - Common Stock
TENB	Tenable Holdings, Inc. - Common Stock
UPLD	Upland Software, Inc. - Common Stock
VIVS	VivoSim Labs, Inc. - Common Stock
WKSP	Worksport, Ltd. - Common Stock
ACNB	ACNB Corporation - Common Stock
BDL	Flanigan's Enterprises, Inc. Common Stock
CBRL	Cracker Barrel Old Country Store, Inc. - Common Stock
DHC	Diversified Healthcare Trust  - Common Shares of Beneficial Interest
EIKN	Eikon Therapeutics, Inc. - Common Stock
FFAI	Faraday Future Intelligent Electric Inc. - Class A Common Stock
GFS	GlobalFoundries Inc. - Ordinary Share
HIMS	Hims & Hers Health, Inc. Class A Common Stock
IKT	Inhibikase Therapeutics, Inc. - Common Stock
JYNT	The Joint Corp. - Common Stock
KNF	Knife Riv Holding Co. Common Stock
LGCL	Lucas GC Limited - Class A Ordinary Shares
MCK	McKesson Corporation Common Stock
NEXT	NextDecade Corporation - Common Stock
OLP	One Liberty Properties, Inc. Common Stock
PCVX	Vaxcyte, Inc. - Common Stock
REF	Reformation Inc. Common Stock
SCZM	Santacruz Silver Mining Ltd. - Common Shares
TENX	Tenax Therapeutics, Inc. - Common Stock
UPS	United Parcel Service, Inc. Common Stock
VKI	Invesco Advantage Municipal Income Trust II Common Shares of Beneficial Interest (DE)
WLCO	Wilco 63 Corporation - Class A Ordinary Shares
ACNT	Ascent Industries Co. - Common Stock
BDMD	Baird Medical Investment Holdings Ltd - Ordinary Share
CBRS	Cerebras Systems Inc. - Class A Common Stock
DHI	D.R. Horton, Inc. Common Stock
EIX	Edison International Common Stock
FFBC	First Financial Bancorp. - Common Stock
GFUZ	General Fusion Group Ltd. - Common Shares
HIND	Vyome Holdings, Inc. - Common Stock
ILAG	Intelligent Living Application Group Inc. - Ordinary Shares
JZXN	Jiuzi Holdings, Inc. - Ordinary Shares
KNRX	KNOREX LTD. Class A Ordinary Shares
LGCY	Legacy Education Inc. Common Stock
MCO	Moody's Corporation Common Stock
NFE	New Fortress Energy Inc. - Class A Common Stock
OM	Outset Medical, Inc. - Common Stock
PCYO	Pure Cycle Corporation - Common Stock
REFI	Chicago Atlantic Real Estate Finance, Inc. - Common Stock
SD	SandRidge Energy, Inc. Common Stock
TER	Teradyne, Inc. - Common Stock
UPST	Upstart Holdings, Inc. - Common stock
VKQ	Invesco Municipal Trust Common Stock
WLDN	Willdan Group, Inc. - Common Stock
ACOG	Alpha Cognition Inc. - Common Stock
BDN	Brandywine Realty Trust Common Stock
CBSH	Commerce Bancshares, Inc. - Common Stock
EJH	E-Home Household Service Holdings Limited - Ordinary shares
FFIN	First Financial Bankshares, Inc. - Common Stock
GGB	Gerdau S.A. Common Stock
HIPO	Hippo Holdings Inc. Common Stock
ILLR	Triller Group Inc. - Common Stock
KNSA	Kiniksa Pharmaceuticals International, plc - Class A Ordinary Shares
LGIH	LGI Homes, Inc. - Common Stock
MCRB	Seres Therapeutics, Inc. - Common Stock
NFG	National Fuel Gas Company Common Stock
OMC	Omnicom Group Inc. Common Stock
PD	PagerDuty, Inc. Common Stock
REFR	Research Frontiers Incorporated - Common Stock
SDA	SunCar Technology Group Inc. - Ordinary Shares
TEX	Terex Corporation Common Stock
UPWK	Upwork Inc. - Common Stock
VKTX	Viking Therapeutics, Inc. - Common Stock
WLDS	Wearable Devices Ltd. - Ordinary Share
ACON	Aclarion, Inc. - Common Stock
BDSX	Biodesix, Inc. - Common Stock
CBT	Cabot Corporation Common Stock
DHX	DHI Group, Inc. Common Stock
EL	Estee Lauder Companies, Inc. (The) Common Stock
FFIV	F5, Inc. - Common Stock
GGG	Graco Inc. Common Stock
HIT	Health In Tech, Inc. - Class A Common Stock
ILLU	Illumination Acquisition Corp I - Class A Ordinary Shares
KNSL	Kinsale Capital Group, Inc. Common Stock
LGL	LGL Group, Inc. (The) Common Stock
MCRI	Monarch Casino & Resort, Inc. - Common Stock
NFGC	New Found Gold Corp Common Shares
OMCL	Omnicell, Inc. - Common Stock
PDCC	Pearl Diver Credit Company Inc. Common Stock
REG	Regency Centers Corporation - Common Stock
SDEV	Stablecoin Development Corporation Common Stock
TFC	Truist Financial Corporation Common Stock
UPXI	Upexi, Inc. - Common Stock
VLGEA	Village Super Market, Inc. - Class A Common Stock
WLFC	Willis Lease Finance Corporation - Common Stock
ACR	ACRES Commercial Realty Corp. Common Stock
BDTX	Black Diamond Therapeutics, Inc. - Common Stock
CBU	Community Financial System, Inc. Common Stock
DIBS	1stdibs.com, Inc. - Common Stock
ELA	Envela Corporation Common Stock
FG	F&G Annuities & Life, Inc. Common Stock
GGR	Gogoro Inc. - Ordinary Shares
HITI	High Tide Inc. - Common Shares
ILMN	Illumina, Inc. - Common Stock
KNTK	Kinetik Holdings Inc. Class A Common Stock
LGN	Legence Corp. - Class A Common stock
MCRP	Micropolis AI Robotics Ordinary Shares
OMDA	Omada Health, Inc. - Common Stock
PDEX	Pro-Dex, Inc. - Common Stock
REGN	Regeneron Pharmaceuticals, Inc. - Common Stock
SDGR	Schrodinger, Inc. - Common Stock
TFII	TFI International Inc. Common Shares
URBN	Urban Outfitters, Inc. - Common Stock
VLN	Valens Semiconductor Ltd. Ordinary Shares
WLII	Willow Lane Acquisition Corp. II - Class A Ordinary Shares
ACRE	Ares Commercial Real Estate Corporation Common Stock
BDX	Becton, Dickinson and Company Common Stock
CBUS	Cibus, Inc. - Class A Common Stock
DIN	Dine Brands Global, Inc. Common Stock
ELAB	PMGC Holdings Inc. - Common Stock
FGBI	First Guaranty Bancshares, Inc. - Common Stock
GGT	Gabelli Multi-Media Trust, Inc. (The) Common Stock
HIVE	HIVE Digital Technologies Ltd - Common Shares
ILPT	Industrial Logistics Properties Trust - Common Shares of Beneficial Interest
LGND	Ligand Pharmaceuticals Incorporated - Common Stock
MCS	Marcus Corporation (The) Common Stock
NGEN	NervGen Pharma Corp. - Common stock
OMER	Omeros Corporation - Common Stock
PDFS	PDF Solutions, Inc. - Common Stock
REI	Ring Energy, Inc. Common Stock
SDHC	Smith Douglas Homes Corp. Class A Common Stock
TFIN	Triumph Financial, Inc. Common Stock
URG	Ur Energy Inc Common Shares (Canada)
VLO	Valero Energy Corporation Common Stock
WLK	Westlake Corporation Common Stock
ACRS	Aclaris Therapeutics, Inc. - Common Stock
BE	Bloom Energy Corporation Class A Common Stock
CBZ	CBIZ, Inc. Common Stock
DINO	HF Sinclair Corporation Common Stock
ELAN	Elanco Animal Health Incorporated Common Stock
FGI	FGI Industries Ltd. - Ordinary Shares
GGZ	Gabelli Global Small and Mid Cap Value Trust (The) Common Shares of Beneficial Interest
HIW	Highwoods Properties, Inc. Common Stock
IMA	ImageneBio, Inc. - Common Stock
KOD	Kodiak Sciences Inc - Common Stock
LGO	Largo Inc. - Common Shares
MCTA	Charming Medical Limited - Class A Ordinary Shares
NGNE	Neurogene Inc. - Common Stock
OMEX	Odyssey Marine Exploration, Inc. - Common Stock
PDLB	Ponce Financial Group, Inc. - Common Stock
REKR	Rekor Systems, Inc. - Common Stock
SDHI	Siddhi Acquisition Corp - Class A Common stock
TFPM	Triple Flag Precious Metals Corp. Common Shares
URGN	UroGen Pharma Ltd. - Ordinary Shares
VLOS	Velos Acquisition I Corp. - Class A Ordinary shares
WLTH	Wealthfront Corporation - Common Stock
ACRV	Acrivon Therapeutics, Inc. - Common Stock
BEAG	Bold Eagle Acquisition Corp. - Class A Ordinary Shares
CC	Chemours Company (The) Common Stock
DIOD	Diodes Incorporated - Common Stock
ELBM	Electra Battery Materials Corporation - Common Stock
FGII	FG Imperii Acquisition Corp. - Class A Ordinary Shares
GH	Guardant Health, Inc. - Common Stock
HKIT	Hitek Global Inc. - Class A Ordinary Share
IMAX	Imax Corporation Common Stock
KOP	Koppers Holdings Inc. Common Stock
LGPS	LogProstyle Inc. Common Shares
MCY	Mercury General Corporation Common Stock
NGS	Natural Gas Services Group, Inc. Common Stock
OMF	OneMain Holdings, Inc. Common Stock
PDM	Piedmont Realty Trust, Inc. Class A Common Stock
RELL	Richardson Electronics, Ltd. - Common Stock
SDOT	Sadot Group Inc. - Common Stock
TFSL	TFS Financial Corporation - Common Stock
URI	United Rentals, Inc. Common Stock
VLTO	Veralto Corp Common Stock 
WLY	John Wiley & Sons, Inc. Common Stock
ACT	Enact Holdings, Inc. - Common Stock
BEAM	Beam Therapeutics Inc. - Common Stock
CCAP	Crescent Capital BDC, Inc. - Common Stock
ELDN	Eledon Pharmaceuticals, Inc. - Common Stock
FGL	Founder Group Limited - Class A Ordinary Shares
GHC	Graham Holdings Company Common Stock
HKPD	Cellyan Biotechnology Co., Ltd  - Class A Ordinary Shares
IMC	IMC Rare Earths Ltd Ordinary Shares
KOPN	Kopin Corporation - Common Stock
LGVN	Longeveron Inc. - Class A Common stock
MD	Pediatrix Medical Group, Inc. Common Stock
NGVC	Natural Grocers by Vitamin Cottage, Inc. Common Stock
OMH	Ohmyhome Limited - Class A Ordinary Shares
PDS	Precision Drilling Corporation Common Stock
RELY	Remitly Global, Inc. - Common stock
SDRL	Seadrill Limited Common Shares
TFX	Teleflex Incorporated Common Stock
UROY	Uranium Royalty Corp. - Common Stock
VLY	Valley National Bancorp - Common Stock
WLYB	John Wiley & Sons, Inc. Common Stock
ACTG	Acacia Research Corporation - Common Stock
BEAT	Heartbeam, Inc. - Common Stock
CCAQ	Collective Acquisition Corp. - Class A ordinary shares
DIT	AMCON Distributing Company Common Stock
ELE	Elemental Royalty Corporation - Common Stock
FGNX	FG Nexus Inc. - Common Stock
GHM	Graham Corporation Common Stock
HL	Hecla Mining Company Common Stock
IMCC	IM Cannabis Corp. - Common Shares
KOS	Kosmos Energy Ltd. Common Shares (DE)
LH	Labcorp Holdings Inc. Common Stock
MDA	MDA Space Ltd. Common Shares
NGVT	Ingevity Corporation Common Stock 
OMSE	OMS Energy Technologies Inc. - Ordinary Shares
PDSB	PDS Biotechnology Corporation - Common Stock
RENT	Rent the Runway, Inc. - Class A Common Stock
SDST	Stardust Power Inc. - Common Stock
TG	Tredegar Corporation Common Stock
USAR	USA Rare Earth, Inc. - Common Stock
VMAR	Vision Marine Technologies Inc. - Common Shares
WM	Waste Management, Inc. Common Stock
ACTU	Actuate Therapeutics, Inc. - Common stock
BEBE	TGE Value Creative Solutions Corp Class A Ordinary Shares
CCB	Coastal Financial Corporation - Common Stock
DJCO	Daily Journal Corp. (S.C.) - Common Stock
ELF	e.l.f. Beauty, Inc. Common Stock
FHB	First Hawaiian, Inc. - Common Stock
GHRS	GH Research PLC - Ordinary Shares
HLF	Herbalife Ltd. Common Shares
IMDX	Insight Molecular Diagnostics Inc. - Common Stock
KOSS	Koss Corporation - Common Stock
LHAI	Linkhome Holdings Inc. - Common stock
MDAI	Spectral AI, Inc. - Class A Common Stock
NHC	National HealthCare Corporation Common Stock
ON	ON Semiconductor Corporation - Common Stock
PDYN	Palladyne AI Corp. - Common stock
RENX	RenX Enterprises Corp. - Common Stock
SEAT	Vivid Seats Inc. - Class A common stock
TGB	Trekor Metals Limited Common Shares
USAS	Americas Gold and Silver Corporation Common Shares, no par value
VMC	Vulcan Materials Company (Holding Company) Common Stock
WMB	Williams Companies, Inc. (The) Common Stock
ACU	Acme United Corporation. Common Stock
BEEM	Beam Global - Common Stock
CCBG	Capital City Bank Group - Common Stock
DJT	Trump Media & Technology Group Corp. - Common Stock
ELLO	Ellomay Capital Ltd Ordinary Shares (Israel)
FHI	Federated Hermes, Inc. Common Stock
GHXI	Gores Holdings XI, Inc. - Class A Ordinary Shares
HLI	Houlihan Lokey, Inc. Class A Common Stock
IMKTA	Ingles Markets, Incorporated - Class A Common Stock
KOYN	CSLM Digital Asset Acquisition Corp III - Class A Ordinary Shares
LHSW	Lianhe Sowell International Group Ltd - Class A Ordinary Shares
MDB	MongoDB, Inc. - Class A Common Stock
NHI	National Health Investors, Inc. Common Stock
ONB	Old National Bancorp - Common Stock
PEB	Pebblebrook Hotel Trust Common Shares of Beneficial Interest
REPL	Replimune Group, Inc. - Common Stock
SEB	Seaboard Corporation Common Stock
TGE	The Generation Essentials Group Class A Ordinary Shares
USAU	U.S. Gold Corp. - Common Stock
VMD	Viemed Healthcare, Inc. - Common Shares
WMG	Warner Music Group Corp. - Class A Common Stock
ACVA	ACV Auctions Inc. Class A Common Stock
BEEP	Mobile Infrastructure Corporation - Common Stock
CCC	CCC Intelligent Solutions Holdings Inc. - Common Stock
DK	Delek US Holdings, Inc. Common Stock
ELMD	Electromed, Inc. Common Stock
FHN	First Horizon Corporation Common Stock
GIB	CGI Inc. Common Stock
HLIO	Helios Technologies, Inc. Common Stock
IMMR	Immersion Corporation - Common Stock
KPET	KPET Ultra Paceline Corporation Class A Ordinary Shares
LHX	L3Harris Technologies, Inc. Common Stock
MDCX	Medicus Pharma Ltd. - Common Stock
NHIC	NewHold Investment Corp III - Class A Ordinary shares
ONCH	1RT Acquisition Corp. - Class A Ordinary Share
PEBK	Peoples Bancorp of North Carolina, Inc. - Common Stock
REPX	Riley Exploration Permian, Inc. Common Stock
SECZ	Securitize Corp. Common Stock
TGEN	Tecogen Inc. Common Stock
USB	U.S. Bancorp Common Stock
VMET	Versamet Royalties Corporation - Common Stock
WMK	Weis Markets, Inc. Common Stock
ACXP	Acurx Pharmaceuticals, Inc. - Common Stock
BELFA	Bel Fuse Inc. - Class A Common Stock
CCCC	C4 Therapeutics, Inc. - Common Stock
DKI	DarkIris Inc. - Class A Ordinary Shares
ELME	Elme Communities Common Stock
FHTX	Foghorn Therapeutics Inc. - Common Stock
GIBO	GIBO Holdings Limited - Class A Ordinary Shares
HLIT	Harmonic Inc. - Common Stock
IMMX	Immix Biopharma, Inc. - Common Stock
KPLT	Katapult Holdings, Inc. - Common Stock
LICN	Lichen International Limited - Class A Ordinary Shares
MDGL	Madrigal Pharmaceuticals, Inc. - Common Stock
NHIV	NewHold Investment Corp IV - Class A Ordinary Shares
ONCO	Onconetix, Inc.  - Common Stock
PEBO	Peoples Bancorp Inc. - Common Stock
RES	RPC, Inc. Common Stock
SEDG	SolarEdge Technologies, Inc. - Common Stock
TGHL	The GrowHub Limited - Class A Ordinary Shares
USBC	USBC, Inc. Common Stock
VMI	Valmont Industries, Inc. Common Stock
WMS	Advanced Drainage Systems, Inc. Common Stock
AD	Array Digital Infrastructure, Inc. Common Shares
BELFB	Bel Fuse Inc. - Class B Common Stock
CCCT	Columbus Circle Capital Corp III - Class A Ordinary Shares
DKNG	DraftKings Inc. - Class A Common Stock
ELMT	The Elmet Group Co. - Common Stock
FIBK	First Interstate BancSystem, Inc. - Common Stock
GIC	Global Industrial Company Common Stock
HLLY	Holley Inc. Common Stock
IMNM	Immunome, Inc. - Common Stock
KPRX	Kiora Pharmaceuticals, Inc.  - Common Stock
LIDR	AEye, Inc. - Class A Common Stock
MDIA	Mediaco Holding Inc. - Class A Common Stock
NHP	National Healthcare Properties, Inc. - Class A Common Stock
ONCY	Oncolytics Biotech Inc. - Common Stock
PECE	Peace Acquisition Corp - Ordinary Shares
REVB	Revelation Biosciences, Inc. - Common Stock
SEED	Origin Agritech Limited - Ordinary Shares
TGL	Treasure Global Inc. - Common Stock
USCB	USCB Financial Holdings, Inc.  - Class A Common Stock
VMO	Invesco Municipal Opportunity Trust Common Stock
ADAC	American Drive Acquisition Company - Class A Ordinary Shares
BEN	Franklin Templeton, Inc. Common Stock
CCEC	Capital Clean Energy Carriers Corp. - Common Share
DKS	Dick's Sporting Goods Inc Common Stock
ELOG	Eastern International Ltd. - Ordinary Shares
FICO	Fair Isaac Corporation Common Stock
GIFT	Giftify, Inc. - Common Stock
HLMN	Hillman Solutions Corp. - Common Stock
IMNN	Imunon, Inc. - Common Stock
KPTI	Karyopharm Therapeutics Inc. - Common Stock
LIEN	Chicago Atlantic BDC, Inc. - Common Stock
MDLN	Medline Inc. - Class A common stock
NHTC	Natural Health Trends Corp. - Common Stock
ONDS	Ondas Inc - Common Stock
PECO	Phillips Edison & Company, Inc. - Common Stock
REXR	Rexford Industrial Realty, Inc. Common Stock
SEER	Seer, Inc. - Class A Common Stock
TGLS	Tecnoglass Holdings Inc. Common Stock
USDE	StablecoinX Inc. - Class A Common Stock
VMRK	Vivmark Residential Common Shares of Beneficial Interest
WNC	Wabash National Corporation Common Stock
ADAG	Adagene Inc. - ADS, each representing 1.25 ordinary shares
BENF	Beneficient - Class A Common Stock
CCEL	Cryo-Cell International, Inc. Common Stock
DLB	Dolby Laboratories Common Stock
ELOX	Eloxx Pharmaceuticals, Inc. - Common Stock
FIEE	FiEE, Inc - Common Stock
GIGM	GigaMedia Limited - Ordinary Shares
HLNE	Hamilton Lane Incorporated - Class A Common Stock
IMO	Imperial Oil Limited Common Stock
KR	Kroger Company (The) Common Stock
LIF	Life360, Inc. - Common Stock
MDLZ	Mondelez International, Inc. - Class A Common Stock
NI	NiSource Inc Common Stock
ONEG	OneConstruction Group Limited - Ordinary Shares
PED	Pedevco Corp. Common Stock
REYN	Reynolds Consumer Products Inc. - Common Stock
SEG	Seaport Entertainment Group Inc. Common Stock
TGS	Transportadora de Gas del Sur SA TGS Common Stock
USEA	United Maritime Corporation - Common Stock
VNCE	Vince Holding Corp. - Common Stock
WNEB	Western New England Bancorp, Inc. - Common Stock
ADAM	Adamas Trust, Inc. - Common Stock
BESS	Bimergen Energy Corporation Common Stock
CCEP	Coca-Cola Europacific Partners plc - Ordinary Shares
DLHC	DLH Holdings Corp. - Common Stock
ELPW	Elong Power Holding Limited - Class A Ordinary Shares
FIG	Figma, Inc. Class A Common Stock
GIII	G-III Apparel Group, LTD. - Common Stock
HLP	Hongli Group Inc. - Class A Ordinary Shares
IMPP	Imperial Petroleum Inc. - Common Shares
KRAQ	KRAKacquisition Corp - Class A Ordinary Shares
LIFE	Ethos Technologies Inc. - Class A Common Stock
MDRR	Medalist Diversified, Inc. - Common Stock
NIC	Nicolet Bankshares Inc. Common Stock
ONEW	OneWater Marine Inc. - Class A Common Stock
PEG	Public Service Enterprise Group Incorporated Common Stock
REZI	Resideo Technologies, Inc. Common Stock 
SEGG	Sports Entertainment Gaming Global Corporation  - Common Stock
TGT	Target Corporation Common Stock
USFD	US Foods Holding Corp. Common Stock
VNDA	Vanda Pharmaceuticals Inc. - Common Stock
WNW	Meiwu Technology Company Limited - Ordinary Shares
BETA	Beta Technologies, Inc. Class A Common Stock
CCG	Cheche Group Inc. - Class A Ordinary Shares
DLO	DLocal Limited - Class A Common Shares
ELS	Equity Lifestyle Properties, Inc. Common Stock
FIGR	Figure Technology Solutions, Inc. - Class A Common Stock
GIL	Gildan Activewear, Inc. Class A Sub. Vot. Common Stock
HLT	Hilton Worldwide Holdings Inc. Common Stock 
IMRX	Immuneering Corporation - Class A Common Stock
KRC	Kilroy Realty Corporation Common Stock
LII	Lennox International, Inc. Common Stock
MDT	Medtronic plc. Ordinary Shares
NIKI	Niki BioSolutions, Inc. - Common Stock
ONFO	Onfolio Holdings Inc. - Common Stock
PEGA	Pegasystems Inc. - Common Stock
RF	Regions Financial Corporation Common Stock
SEI	Solaris Energy Infrastructure, Inc. Class A Common Stock
TGTX	TG Therapeutics, Inc. - Common Stock
USGO	U.S. GoldMining Inc. - Common stock
VNME	Vendome Acquisition Corporation I - Class A Ordinary Shares
WOK	WORK Medical Technology Group LTD - Class A Ordinary Shares
ADBT	Advasa Holdings, Inc. - Common stock
BETR	Better Home & Finance Holding Company - Class A Common Stock
CCHH	CCH Holdings Ltd - Class A Ordinary Shares
DLPN	Dolphin Entertainment, Inc. - Common Stock
ELTK	Eltek Ltd. - Ordinary Shares
FIGS	FIGS, Inc. Class A Common Stock
GILD	Gilead Sciences, Inc. - Common Stock
HLXC	Helix Acquisition Corp. III - Class A Ordinary Shares
IMSR	Terrestrial Energy Inc. - Common Stock
KREF	KKR Real Estate Finance Trust Inc. Common Stock
LILA	Liberty Latin America Ltd. - Class A Common Stock
MDU	MDU Resources Group, Inc. Common Stock (Holding Company)
NINE	Nine Energy Service, Inc. Common Stock
ONIT	Onity Group Inc. Common Stock
PEN	Penumbra, Inc. Common Stock
RFAI	RF Acquisition Corp II - Ordinary Shares
SEIC	SEI Investments Company - Common Stock
TH	Target Hospitality Corp. - Common Stock
USIO	Usio, Inc. - Common Stock
VNO	Vornado Realty Trust Common Stock
WOLF	Wolfspeed, Inc. Common Stock New
ADC	Agree Realty Corporation Common Stock
BF-A	Brown Forman Inc Class A Common Stock
CCI	Crown Castle Inc. Common Stock
DLR	Digital Realty Trust, Inc. Common Stock
ELTX	Elicio Therapeutics, Inc. - Common Stock
FIGX	FIGX Capital Acquisition Corp. - Class A ordinary share
GILT	Gilat Satellite Networks Ltd. - Ordinary Shares
HMC	Honda Motor Company, Ltd. Common Stock
IMTE	Integrated Media Technology Limited - Ordinary Shares
KRG	Kite Realty Group Trust Common Stock
LILAK	Liberty Latin America Ltd. - Class C Common Stock
MDWD	MediWound Ltd. - Ordinary Shares
NIQ	NIQ Global Intelligence plc Ordinary Shares
ONL	Orion Properties Inc. Common Stock
PENG	Penguin Solutions, Inc. - Common Stock
RFAM	RF Acquisition Corp III - Ordinary Shares
SELF	Global Self Storage, Inc. - Common Stock
THC	Tenet Healthcare Corporation Common Stock
USLM	United States Lime & Minerals, Inc. - Common Stock
VNOM	Viper Energy, Inc.  - Class A Common Stock
WOOF	Petco Health and Wellness Company, Inc. - Class A Common Stock
ADCT	ADC Therapeutics SA Common Shares
BF-B	Brown Forman Inc Class B Common Stock
CCII	Cohen Circle Acquisition Corp. II - Class A Ordinary Shares
DLTH	Duluth Holdings Inc. - Class B Common Stock
ELUT	Elutia, Inc. - Class A Common Stock
FINS	Angel Oak Financial Strategies Income Term Trust Common Shares of Beneficial Interest
GIPR	Generation Income Properties Inc. - Common stock
HMH	HMH Holding Inc. - Common Stock
IMTX	Immatics N.V. - Ordinary Shares
KRMD	KORU Medical Systems, Inc. - Common Stock
LIME	Neutron Holdings, Inc. - Common Stock
MDXG	MiMedx Group, Inc - Common Stock
NIVF	NewGenIvf Group Limited - Class A Ordinary Shares
ONMD	OneMedNet Corp - Class A Common Stock
PENN	PENN Entertainment, Inc. - Common Stock
RFIL	RF Industries, Ltd. - Common Stock
SENEA	Seneca Foods Corp. - Class A Common Stock
THCH	TH International Limited - Ordinary shares
USNA	USANA Health Sciences, Inc. Common Stock
VNRX	VolitionRX Limited Common Stock
WOR	Worthington Enterprises, Inc. Common Shares
ADEA	Adeia Inc.  - Common Stock
BFAM	Bright Horizons Family Solutions Inc. Common Stock
CCJ	Cameco Corporation Common Stock
DLTR	Dollar Tree, Inc. - Common Stock
ELV	Elevance Health, Inc. Common Stock
FINW	FinWise Bancorp - Common Stock
GIS	General Mills, Inc. Common Stock
HMN	Horace Mann Educators Corporation Common Stock
IMUX	Immunic, Inc.  - Common Stock
KRMN	Karman Holdings Inc. Common Stock
LIMN	Liminatus Pharma, Inc. - Class A Common Stock
MDXH	MDxHealth SA - Ordinary Shares
NIXX	Nixxy, Inc. - Common Stock
ONON	On Holding AG Class A Ordinary Shares
RFL	Rafael Holdings, Inc. Class B Common Stock
SENEB	Seneca Foods Corp. - Class B Common Stock
THEO	BOA Acquisition Corp. II - Class A Ordinary Shares
USPH	U.S. Physical Therapy, Inc. Common Stock
VNT	Vontier Corporation Common Stock 
WPAC	White Pearl Acquisition Corp. Class A Ordinary Shares
ADGM	Adagio Medical Holdings, Inc - Common Stock
BFC	Bank First Corporation - Common Stock
CCL	Carnival Corporation Ltd. Common Shares
DLX	Deluxe Corporation Common Stock
ELVA	Electrovaya Inc. - Common Shares
FIP	FTAI Infrastructure Inc. - Common Stock
GITS	Global Interactive Technologies, Inc. Common Stock - Common Stock
HMR	Heidmar Maritime Holdings Corp. - Common Stock
IMVT	Immunovant, Inc.  - Common Stock
KRNT	Kornit Digital Ltd. - Ordinary Shares
LIN	Linde plc - Ordinary Shares
MEC	Mayville Engineering Company, Inc. Common Stock
NJR	NewJersey Resources Corporation Common Stock
ONT	Onterris, Inc. Common Stock
PEPG	PepGen Inc. - Common Stock
RGA	Reinsurance Group of America, Incorporated Common Stock
SENS	Senseonics Holdings, Inc. - Common Stock
THFF	First Financial Corporation  - Common Stock
UTHR	United Therapeutics Corporation - Common Stock
VNTG	Vantage Corp Class A Ordinary Shares
WPM	Wheaton Precious Metals Corp Common Shares (Canada)
ADI	Analog Devices, Inc. - Common Stock
BFH	Bread Financial Holdings, Inc. Common Stock
CCLD	CareCloud, Inc. - Common Stock
DLXY	Delixy Holdings Limited - Class A Ordinary Shares
ELVN	Enliven Therapeutics, Inc.  - Common Stock
FIRY	Firy Inc. Class A Common Stock
GIW	GigCapital8 Corp. - Class A Ordinary Shares
HNGE	Hinge Health, Inc. Class A Common Stock
IMXI	International Money Express, Inc. - Common Stock
KRNY	Kearny Financial - Common Stock
LINC	Lincoln Educational Services Corporation - Common Stock
MED	MEDIFAST INC Common Stock
ONTO	Onto Innovation Inc. Common Stock
PERF	Perfect Corp. Class A Ordinary Share
RGC	Regencell Bioscience Holdings Limited - Ordinary Shares
SEPN	Septerna, Inc. - Common Stock
THH	TryHard Holdings Limited - Ordinary Shares
UTI	Universal Technical Institute Inc Common Stock
VOGX	Vogenx Inc - Common Stock
WPRT	Westport Fuel Systems Inc - Common Shares
ADIG	ADI Global Distribution Inc. Common Stock
BFLY	Butterfly Network, Inc. Class A Common Stock
CCNE	CNB Financial Corporation - Common Stock
DMAA	Drugs Made In America Acquisition Corp. - Ordinary Shares
ELWT	Elauwit Connection, Inc. - Common Stock
FIS	Fidelity National Information Services, Inc. Common Stock
GIX	GigCapital9 Corp. - Class A Ordinary Share
HNI	HNI Corporation Common Stock
INAB	IN8bio, Inc. - Common Stock
KRO	Kronos Worldwide Inc Common Stock
LIND	Lindblad Expeditions Holdings Inc.  - Common Stock
MEDP	Medpace Holdings, Inc. - Common Stock
NKLR	Terra Innovatum Global N.V. - Ordinary shares
OOMA	Ooma, Inc. Common Stock
PERI	Perion Network Ltd - Ordinary Shares
RGCO	RGC Resources Inc. - Common Stock
SER	Serina Therapeutics, Inc. Common Stock
THM	International Tower Hill Mines, Ltd. Ordinary Shares (Canada)
UTL	UNITIL Corporation Common Stock
VOR	Vor Biopharma Inc. - Common Stock
WRAP	Wrap Technologies, Inc. - Common Stock
ADIL	Adial Pharmaceuticals, Inc - Common Stock
BFRG	Bullfrog AI Holdings, Inc. - Common Stock
CCO	Clear Channel Outdoor Holdings, Inc. Common Stock
DMAC	DiaMedica Therapeutics Inc. - Common Stock
EMA	Emera Incorporated Common Shares
FISI	Financial Institutions, Inc. - Common Stock
GIXI	Gix Internet Ltd. - Ordinary Shares
HNNA	Hennessy Advisors, Inc. - Common Stock
INAC	Indigo Acquisition Corp. - Ordinary Shares
KROS	Keros Therapeutics, Inc. - common stock
LINE	Lineage, Inc. - Common Stock
MEDS	DataMeds AI, Inc. - Common Stock
NKSH	National Bankshares, Inc. - Common Stock
OPAD	Offerpad Solutions Inc.  - Class A Common Stock
PESI	Perma-Fix Environmental Services, Inc. - Common Stock
RGEN	Repligen Corporation - Common Stock
SERA	Sera Prognostics, Inc. - Class A Common Stock
THO	Thor Industries, Inc. Common Stock
UTMD	Utah Medical Products, Inc. - Common Stock
VOXR	Vox Royalty Corp. - common stock
WRB	W.R. Berkley Corporation Common Stock
ADM	Archer-Daniels-Midland Company Common Stock
BFRI	Biofrontera Inc. - Common Stock
CCOI	Cogent Communications Holdings, Inc. - Common Stock
DMC	Del Monte Corporation Ordinary Shares
EMAT	Evolution Metals & Technologies Corp. - Common Stock
FISN	Deep Fission, Inc. - Common Stock
GKOS	Glaukos Corporation Common Stock
HNRG	Hallador Energy Company - Common Stock
INBK	First Internet Bancorp - Common Stock
KRRO	Korro Bio, Inc. - Common Stock
LINK	Interlink Electronics, Inc. - Common Stock
MEGL	Magic Empire Global Limited - Class A Ordinary Shares
NKTR	Nektar Therapeutics - Common Stock
OPAL	OPAL Fuels Inc. - Class A Common Stock
PETS	PetMed Express, Inc. - Common Stock
RGLD	Royal Gold, Inc. - Common Stock
SERV	Serve Robotics Inc. - Common Stock
THRM	Gentherm Inc - Common Stock
UTSI	UTStarcom Holdings Corp - Ordinary Shares
VOYA	Voya Financial, Inc. Common Stock
WRBY	Warby Parker Inc. Class A Common Stock
ADMA	ADMA Biologics Inc - Common Stock
BFS	Saul Centers, Inc. Common Stock
CCS	Century Communities, Inc. Common Stock
DMII	Drugs Made In America Acquisition II Corp. - Ordinary Shares
EMBC	Embecta Corp. - Common Stock
FISV	Fiserv, Inc. - Common Stock
GL	Globe Life Inc. Common Stock
HNST	The Honest Company, Inc. - Common Stock
INBS	Intelligent Bio Solutions Inc.  - Common Stock
KRSA	Korsana Biosciences, Inc. - Common Stock
LION	Lionsgate Studios Corp Common Shares
MEI	Methode Electronics, Inc. Common Stock
NKTX	Nkarta, Inc. - Common Stock
OPBK	OP Bancorp - Common Stock
PETZ	TDH Holdings, Inc. - Common Shares
RGNT	Regentis Biomaterials Ltd. Ordinary Shares
SES	SES AI Corporation Class A Common Stock
THRY	Thryv Holdings, Inc. - Common Stock
UTZ	Utz Brands Inc Class A Common Stock 
VOYG	Voyager Technologies, Inc. Class A Common Stock
WRLD	World Acceptance Corporation - Common Stock
ADNT	Adient plc Ordinary Shares 
BFST	Business First Bancshares, Inc. - Common Stock
CCSI	Consensus Cloud Solutions, Inc. - Common Stock
DMRA	Damora Therapeutics, Inc. - Ordinary Shares
EMBJ	Embraer S.A. Common Stock
FITB	Fifth Third Bancorp Common Stock
GLBE	Global-E Online Ltd. - ordinary shares
HNVR	Hanover Bancorp, Inc. - Common Stock
INBX	Inhibrx Biosciences, Inc. - Common Stock
KRSP	Rice Acquisition Corporation 3 Class A Ordinary Shares
LIQT	LiqTech International, Inc. - Common Stock
MELI	MercadoLibre, Inc. - Common Stock
NL	NLI Holdings, Inc. Common Stock
OPCH	Option Care Health, Inc. - Common Stock
PEW	GrabAGun Digital Holdings Inc. Common Stock
RGNX	REGENXBIO Inc. - Common Stock
SEV	Aptera Motors Corp. - Class B Common Stock
TIC	TIC Solutions, Inc. Common Stock
UUU	Universal Safety Products, Inc. Common Stock
VPG	Vishay Precision Group, Inc. Common Stock
WRN	Western Copper and Gold Corporation Common Stock
ADP	Automatic Data Processing, Inc. - Common Stock
BG	Bunge Limited Common Shares
CCTG	CCSC Technology International Holdings Limited - Class A Ordinary Shares
DMRC	Digimarc Corporation - Common Stock
EME	EMCOR Group, Inc. Common Stock
FIVE	Five Below, Inc. - Common Stock
GLBS	Globus Maritime Limited - Common Stock
HODO	House of Doge Inc. - Common Stock
INCR	Intercure Ltd. - ordinary shares
KRT	Karat Packaging Inc. - Common Stock
LITE	Lumentum Holdings Inc. - Common Stock
MENS	Jyong Biotech Ltd. - Ordinary shares
NLOP	Net Lease Office Properties Common Shares of Beneficial Interest
OPEN	Opendoor Technologies Inc  - Common Stock
PFAI	Pinnacle Food Group Limited - Class A Common Shares
RGP	Resources Connection, Inc. - Common Stock
SEVN	Seven Hills Realty Trust  - Common Stock
TIGO	Millicom International Cellular S.A. - Common Stock
UUUU	Energy Fuels Inc Ordinary Shares (Canada)
VPV	Invesco Pennsylvania Value Municipal Income Trust Common Stock (DE)
WS	Worthington Steel, Inc. Common Shares
ADPT	Adaptive Biotechnologies Corporation - Common Stock
BGC	BGC Group, Inc. - Class A Common Stock
CCU	Compania Cervecerias Unidas, S.A. Common Stock
DNA	Ginkgo Bioworks Holdings, Inc. Class A Common Stock
EMIS	Emmis Acquisition Corp. - Class A Ordinary Share
FIVN	Five9, Inc. - Common Stock
GLDG	GoldMining Inc. Common Shares
HOFT	Hooker Furnishings Corporation - Common Stock
INCY	Incyte Corporation - Common Stock
KRUS	Kura Sushi USA, Inc. - Class A Common Stock
LITS	Lite Strategy, Inc. - Common Stock
MEOH	Methanex Corporation - Common Stock
NLY	Annaly Capital Management Inc. Common Stock
OPFI	OppFi Inc. Class A Common Stock
PFE	Pfizer, Inc. Common Stock
RGR	Sturm, Ruger & Company, Inc. Common Stock
SEZL	Sezzle Inc. - Common Stock
TII	Titan Mining Corporation Common Shares
UVE	UNIVERSAL INSURANCE HOLDINGS INC Common Stock
VRA	Vera Bradley, Inc. - Common Stock
WSBC	WesBanco, Inc. - Common Stock
ADSE	ADS-TEC ENERGY PLC - Ordinary Shares
BGDE	Big Digital Energy, Inc. - Common Stock
CCXI	Churchill Capital Corp XI - Class A Ordinary Shares
DNLI	Denali Therapeutics Inc. - Common Stock
EML	Eastern Company (The) - Common Stock
FIX	Comfort Systems USA, Inc. Common Stock
GLE	Global Engine Group Holding Limited - Class A Ordinary Shares
HOG	Harley-Davidson, Inc. Common Stock
INDB	Independent Bank Corp. - Common Stock
KRYS	Krystal Biotech, Inc. - Common Stock
LIVE	Live Ventures Incorporated - Common Stock
MERC	Mercer International Inc. - Common Stock
NMAD	Nomad Power Solutions, Inc. - Common Stock
OPHC	OptimumBank Holdings, Inc. Common Stock
PFG	Principal Financial Group Inc - Common Stock
RGS	Regis Corporation - Common Stock
SF	Stifel Financial Corporation Common Stock
TIL	Instil Bio, Inc. - Common Stock
UVSP	Univest Financial Corporation - Common Stock
VRAX	Virax Biolabs Group Limited - Ordinary Shares
WSBF	Waterstone Financial, Inc. - Common Stock
ADSK	Autodesk, Inc. - Common Stock
BGIN	Bgin Blockchain Limited - Class A Ordinary Shares
CD	Chaince Digital Holdings Inc. - American Ordinary Shares
DNMX	Dynamix Corporation III - Class A Ordinary Shares
EMN	Eastman Chemical Company Common Stock
FIZZ	National Beverage Corp. - Common Stock
GLED	GalaxyEdge Acquisition Corporation Ordinary Shares
HOLO	MicroCloud Hologram Inc. - Ordinary Shares
INDI	indie Semiconductor, Inc. - Class A Common Stock
KSCP	Knightscope, Inc. - Class A Common Stock
LIVN	LivaNova PLC - Ordinary Shares
MESH	Meshflow Acquisition Corp. - Class A Ordinary Shares
NMAX	Newsmax, Inc. Class B Common Stock
OPI	Office Properties Income Trust - Common shares of beneficial interest
PFGC	Performance Food Group Company Common Stock
RGT	Royce Global Trust, Inc. Common Stock
SFBC	Sound Financial Bancorp, Inc. - Common Stock
TILE	Interface, Inc. - Common Stock
UVV	Universal Corporation Common Stock
VRCA	Verrica Pharmaceuticals Inc. - Common Stock
WSBK	Winchester Bancorp, Inc. - Common Stock
ADT	ADT Inc. Common Stock
BGL	Blue Gold Limited - Class A ordinary shares
CDE	Coeur Mining, Inc. Common Stock
DNN	Denison Mines Corp Ordinary Shares (Canada)
EMPD	Empery Digital Inc. - Common stock
FJET	Starfighters Space, Inc. Common Stock
GLIBA	Liberty Capital Corporation - Series A GCI Group Common Stock
HOMB	Home BancShares, Inc. Common Stock
INDO	Indonesia Energy Corporation Limited Ordinary Shares
KSS	Kohl's Corporation Common Stock
LKFN	Lakeland Financial Corporation - Common Stock
MET	MetLife, Inc. Common Stock
NMFC	New Mountain Finance Corporation - Common Stock
OPK	Opko Health, Inc. - Common Stock
PFIS	Peoples Financial Services Corp.  - Common Stock
RGTI	Rigetti Computing, Inc.  - Common stock
SFBS	ServisFirst Bancshares, Inc. Common Stock
TIPT	Tiptree Inc. - Common Stock
UWMC	UWM Holdings Corporation Class A Common Stock
VRDN	Viridian Therapeutics, Inc.  - Common Stock
WSC	WillScot Holdings Corporation - Class A Common Stock
ADTN	ADTRAN Holdings, Inc. - Common Stock
BGLC	BioNexus Gene Lab Corp - Common stock
CDIO	Cardio Diagnostics Holdings Inc. - Common stock
DNOW	DNOW Inc. Common Stock
EMR	Emerson Electric Company Common Stock
FKWL	Franklin Wireless Corp. - common stock
GLIBK	Liberty Capital Corporation - Series C GCI Group Common Stock
HON	Honeywell International Inc. - Common Stock
INDP	Indaptus Therapeutics, Inc. - Common Stock
KT	KT Corporation Common Stock
LKQ	LKQ Corporation - Common Stock
NMG	Nouveau Monde Graphite Inc. Common Shares
OPLN	OPENLANE, Inc. Common Stock
PFLT	PennantPark Floating Rate Capital Ltd. Common Stock
RH	RH Common Stock
SFD	Smithfield Foods, Inc. - Common Stock
TISI	Team, Inc. Common Stock
UYSC	UY Scuti Acquisition Corp. - Ordinary Shares
VREX	Varex Imaging Corporation - Common Stock
WSE	Wise Group plc - Class A Ordinary Shares
ADUR	Aduro Clean Technologies Inc. - Common Stock
BGM	BGM Group Ltd. - Class A Ordinary Shares
CDLX	Cardlytics, Inc. - Common Stock
DNTH	Dianthus Therapeutics, Inc. - Common Stock
ENB	Enbridge Inc Common Stock
FLD	Fold Holdings, Inc. - Class A Common Stock
GLMD	Galmed Pharmaceuticals Ltd. - Ordinary Shares
HONA	Honeywell Aerospace Inc. - Common Stock
INDV	Indivior Pharmaceuticals, Inc.  - Common Stock
KTB	Kontoor Brands, Inc. Common Stock 
LKSP	Lake Superior Acquisition Corp. - Class A Ordinary Shares
METC	Ramaco Resources, Inc. - Class A Common Stock
NMIH	NMI Holdings Inc - Common Stock
OPRT	Oportun Financial Corporation - common stock
PFS	Provident Financial Services, Inc Common Stock
RHI	Robert Half Inc. Common Stock
SFHG	Samfine Creation Holdings Group Limited - Class A Ordinary Share
TITN	Titan Machinery Inc. - Common Stock
UZX	Linkage Global Inc - Class A Ordinary Shares
VRM	Vroom, Inc. - Common Stock
WSFS	WSFS Financial Corporation - Common Stock
ADUS	Addus HomeCare Corporation - Common Stock
BGMS	Bio Green Med Solution, Inc. - Common Stock
CDNA	CareDx, Inc. - Common Stock
DNUT	Krispy Kreme, Inc. - Common Stock
ENGN	enGene Therapeutics Inc. - Common Stock
FLEX	Flex Ltd. - Ordinary Shares
GLND	Greenland Energy Company - Common Stock
HOOD	Robinhood Markets, Inc. - Class A Common Stock
INEO	INNEOVA Holdings Limited - Class A Ordinary Shares
KTCC	Key Tronic Corporation - Common Stock
METCB	Ramaco Resources, Inc. - Class B Common Stock
NMP	NMP Acquisition Corp. - Class A Ordinary Shares
OPRX	OptimizeRx Corporation - Common Stock
PFSA	Profusa, Inc. - Common Stock
RHLD	Resolute Holdings Management Common Stock 
SFIX	Stitch Fix, Inc. - Class A Common Stock
TJGC	TJGC Group Limited - Class A Ordinary Shares
VRME	VerifyMe, Inc. - Common Stock
WSHP	WeShop Holdings Limited - Class A Ordinary Shares
ADV	Advantage Solutions Inc.  - Class A Common Stock
BGS	B&G Foods, Inc. Common Stock
CDNL	Cardinal Infrastructure Group Inc. - Class A Common Stock
DOC	Healthpeak Properties, Inc. Common Stock
ENGS	Energys Group Limited - Ordinary Shares
FLG	Flagstar Bank, N.A. Common Stock
GLNG	Golar LNG Limited - Common Shares
HOPE	Hope Bancorp, Inc. - Common Stock
INFQ	Infleqtion, Inc. Common Stock
KTOS	Kratos Defense & Security Solutions, Inc. - Common Stock
LLYVA	Liberty Live Holdings, Inc. - Series A Liberty Live Group Common Stock
MEVO	M Evo Global Acquisition Corp II - Class A Ordinary Shares
NMRA	Neumora Therapeutics, Inc. - Common Stock
OPTH	Optimi Health Corp. - Common Shares
PFSI	PennyMac Financial Services, Inc. Common Stock
RIBB	Ribbon Acquisition Corp - Class A Ordinary Shares
SFM	Sprouts Farmers Market, Inc. - Common Stock
TJX	TJX Companies, Inc. (The) Common Stock
VRNS	Varonis Systems, Inc. - Common Stock
WSM	Williams-Sonoma, Inc. Common Stock (DE)
ADVB	Advanced Biomed Inc. - Common Stock
BGSF	BGSF, Inc. Common Stock
CDNS	Cadence Design Systems, Inc. - Common Stock
DOCN	DigitalOcean Holdings, Inc. Common Stock
ENHA	Enhanced Group Inc. Class A Common Stock
FLGT	Fulgent Genetics, Inc. - Common Stock
GLOB	Globant S.A. Common Shares
HOS	Hornbeck Offshore Services, Inc. Common Stock
INFU	InfuSystems Holdings, Inc. Common Stock
KTTA	Pasithea Therapeutics Corp. - Common Stock
LLYVK	Liberty Live Holdings, Inc. - Series C Liberty Live Group Common Stock
MF	MindForge Inc. - Class A Ordinary Shares
NMRK	Newmark Group, Inc. - Class A Common Stock
OPTT	Ocean Power Technologies, Inc. Common Stock
PFX	PhenixFIN Corporation  - Common Stock
RICK	RCI Hospitality Holdings, Inc. - Common Stock
SFNC	Simmons First National Corporation - Common Stock
TK	Teekay Corporation Ltd. Common Stock
VRRM	Verra Mobility Corporation - Class A Common Stock
WSO	Watsco, Inc. Common Stock
AEAQ	Activate Energy Acquisition Corp. - Class A Ordinary Share
BGSI	Boyd Group Services Inc. Common Shares
CDP	COPT Defense Properties Common Shares of Beneficial Interest
DOCS	Doximity, Inc. Class A Common Stock
ENLT	Enlight Renewable Energy Ltd. - Ordinary Shares
FLL	Full House Resorts, Inc. - Common Stock
GLOO	Gloo Holdings, Inc. - Common Stock
HOUR	Hour Loop, Inc. - common stock
ING	ING Group, N.V. Common Stock
KTWO	K2 Capital Acquisition Corporation - Class A Ordinary Share
LMAT	LeMaitre Vascular, Inc. - Common Stock
MFC	Manulife Financial Corporation Common Stock
NMTC	NeuroOne Medical Technologies Corporation - Common Stock
OPTU	Optimum Communications, Inc. Class A common stock
RIG	Transocean Ltd (Switzerland) Common Stock
SFST	Southern First Bancshares, Inc. - Common Stock
TKC	Turkcell Iletisim Hizmetleri AS Common Stock
VRSK	Verisk Analytics, Inc. - Common Stock
WSO-B	Watsco, Inc. Class B Common Stock
AEBI	Aebi Schmidt Holding AG - Common Stock
BH	Biglari Holdings Inc. Class B Common Stock
CDRE	Cadre Holdings, Inc. Common Stock
DOCU	DocuSign, Inc. - Common Stock
ENLV	Enlivex Ltd. - Ordinary Shares
FLNA	Filana Therapeutics, Inc. - Common Stock
GLPI	Gaming and Leisure Properties, Inc. - Common Stock
HOV	Hovnanian Enterprises, Inc. Class A Common Stock
INGM	Ingram Micro Holding Corporation Common Stock
KULR	KULR Technology Group, Inc. Common Stock
LMB	Limbach Holdings, Inc. - Common Stock
MFI	mF International Limited - Class A Ordinary Shares
NN	NextNav Inc. - Common stock
OPTX	Syntec Optics Holdings, Inc. - Class A Common Stock
PGAC	Pantages Capital Acquisition Corporation - Class A Ordinary Shares
RIGL	Rigel Pharmaceuticals, Inc. - Common Stock
SFWL	Shengfeng Development Limited - Class A Ordinary Shares
TKNO	Alpha Teknova, Inc. - Common Stock
VRSN	VeriSign, Inc. - Common Stock
WST	West Pharmaceutical Services, Inc. Common Stock
AEC	Anfield Energy Inc. - Common Shares
BH-A	Biglari Holdings Inc. Class A Common Stock
CDRO	Codere Online Luxembourg, S.A. - Ordinary Shares
DOGZ	Dogness (International) Corporation - Class A Common Stock
ENOV	Enovis Corporation Common Stock
FLNC	Fluence Energy, Inc. - Class A Common Stock
GLRE	Greenlight Reinsurance, Ltd. - Class A Ordinary Shares
HOVR	New Horizon Aircraft Ltd. - Class A Ordinary Shares
INGN	Inogen, Inc - Common Stock
KURA	Kura Oncology, Inc. - Common Stock
LMND	Lemonade, Inc. Common Stock
MFIN	Medallion Financial Corp. - Common Stock
NNBR	NN, Inc. - Common Stock
OPXS	Optex Systems Holdings, Inc. - Common Stock
PGC	Peapack-Gladstone Financial Corporation - Common Stock
RILY	BRC Group Holdings, Inc. - Common Stock
SG	Sweetgreen, Inc. Class A Common Stock
TKO	TKO Group Holdings, Inc. Class A Common Stock
VRT	Vertiv Holdings, LLC Class A Common Stock
WSTN	Westin Acquisition Corp - Class A Ordinary Share
AEE	Ameren Corporation Common Stock
BHAV	BHAV Acquisition Corp - Class A Ordinary Shares
CDT	CDT Equity Inc. - Common Stock
DOLE	Dole plc Ordinary Shares
ENPH	Enphase Energy, Inc. - Common Stock
FLNG	FLEX LNG Ltd. Ordinary Shares
GLSI	Greenwich LifeSciences, Inc. - Common stock
HOWL	Werewolf Therapeutics, Inc. - Common Stock
INGR	Ingredion Incorporated Common Stock
KUST	Kustom Entertainment, Inc. - Common Stock
LMNR	Limoneira Co - Common Stock
MFP	Midera Food Processing, Inc. - Common Stock
NNE	Nano Nuclear Energy Inc. - common stock
OPY	Oppenheimer Holdings, Inc. Class A Common Stock (DE)
PGEN	Precigen, Inc. - Common Stock
RIME	Algorhythm Holdings, Inc. - Common Stock
SGA	Saga Communications, Inc. - Class A Common Stock
TKR	Timken Company (The) Common Stock
VRTS	Virtus Investment Partners, Inc. Common Stock
WT	WisdomTree, Inc. Common Stock
AEHL	Antelope Enterprise Holdings Limited - Class A Ordinary Shares
BHB	Bar Harbor Bankshares, Inc. Common Stock
CDTG	CDT Environmental Technology Investment Holdings Limited - ordinary shares
DOMH	Dominari Holdings Inc. - Common Stock
ENR	Energizer Holdings, Inc. Common Stock
FLNT	Fluent, Inc. - Common Stock
GLU	Gabelli Global Utility Common Shares of Beneficial Ownership
HP	Helmerich & Payne, Inc. Common Stock
INHD	Inno Holdings Inc. - Common Stock
KVHI	KVH Industries, Inc. - Common Stock
LMRI	Lumexa Imaging Holdings, Inc. - Common Stock
MG	Mistras Group Inc Common Stock
NNI	Nelnet, Inc. Common Stock
OR	OR Royalties Inc. Common Shares
PGNY	Progyny, Inc. - Common Stock
RIO	Rio Tinto Plc Common Stock
SGC	Superior Group of Companies, Inc. - Common Stock
TLF	Tandy Leather Factory, Inc. - common stock
VRTX	Vertex Pharmaceuticals Incorporated - Common Stock
WTBA	West Bancorporation - Common Stock
AEHR	Aehr Test Systems - Common Stock
BHC	Bausch Health Companies Inc. Common Stock
CDW	CDW Corporation - Common Stock
DOMO	Domo, Inc. - Class B Common Stock
ENS	EnerSys Common Stock
FLO	Flowers Foods, Inc. Common Stock
GLUE	Monte Rosa Therapeutics, Inc. - Common Stock
HPAI	Helport AI Limited - Ordinary Shares
INIO	INNIO N.V. - Ordinary Shares
KVUE	Kenvue Inc. Common Stock
LMT	Lockheed Martin Corporation Common Stock
MGA	Magna International, Inc. Common Stock
NNN	NNN REIT, Inc. Common Stock
ORA	Ormat Technologies, Inc. Common Stock
PGR	Progressive Corporation (The) Common Stock
RIOT	Riot Platforms, Inc. - Common Stock
SGHC	Super Group (SGHC) Limited Ordinary Shares
TLIH	Ten-League International Holdings Limited - Ordinary Shares
VRXA	Veraxa Biotech AG - Ordinary Shares
WTF	Waton Financial Limited - Ordinary Shares
AEI	Alset Inc. - Common Stock
BHE	Benchmark Electronics, Inc. Common Stock
CDXS	Codexis, Inc. - Common Stock
DORM	Dorman Products, Inc. - Common Stock
ENSC	Ensysce Biosciences, Inc. - Common Stock
FLOC	Flowco Holdings Inc. Class A Common Stock
GLW	Corning Incorporated Common Stock
HPE	Hewlett Packard Enterprise Company Common Stock
INKT	MiNK Therapeutics, Inc. - Common Stock
KVYO	Klaviyo, Inc. Series A Common Stock
LNAI	Lunai Bioworks Inc. - Common Stock
MGEE	MGE Energy Inc. - Common Stock
NNNN	Anbio Biotechnology - Class A Ordinary Shares
ORBS	Eightco Holdings Inc. - Common Stock
PGY	Pagaya Technologies Ltd. - Class A Ordinary Shares
RITM	Rithm Capital Corp. Common Stock
SGHT	Sight Sciences, Inc. - Common Stock
TLN	Talen Energy Corporation - Common Stock
VS	Versus Systems Inc. - Common Stock
WTFC	Wintrust Financial Corporation - Common Stock
AEIS	Advanced Energy Industries, Inc. - Common Stock
BHF	Brighthouse Financial, Inc. - Common Stock
CDZI	Cadiz, Inc. - Common Stock
DOUG	Douglas Elliman Inc. Common Stock
ENSG	The Ensign Group, Inc. - Common Stock
FLR	Fluor Corporation Common Stock
GLXG	Galaxy Payroll Group Limited - Class A Ordinary Shares
HPK	HighPeak Energy, Inc. - Common Stock
INLF	INLIF LIMITED - Class A Ordinary shares
KWR	Quaker Houghton Common Stock
LNC	Lincoln National Corporation Common Stock
MGIH	Millennium Group International Holdings Limited - Ordinary Shares
NNOX	NANO-X IMAGING LTD - Ordinary Shares
ORC	Orchid Island Capital, Inc. Common Stock
PH	Parker-Hannifin Corporation Common Stock
RITR	Reitar Logtech Holdings Limited - Ordinary shares
SGI	Somnigroup International Inc. Common Stock
TLNC	Talon Capital Corp. - Class A Ordinary Shares
VSAT	ViaSat, Inc. - Common Stock
WTG	Wintergreen Acquisition Corp. - Ordinary Shares
AEM	Agnico Eagle Mines Limited Common Stock
BHM	Bluerock Homes Trust, Inc. Class A Common Stock
CE	Celanese Corporation Common Stock
DOV	Dover Corporation Common Stock
ENTA	Enanta Pharmaceuticals, Inc. - Common Stock
FLS	Flowserve Corporation Common Stock
GLXY	Galaxy Digital Inc. - Class A common stock
HPP	Hudson Pacific Properties, Inc. Common Stock
INLX	Intellinetics, Inc. Common Stock
KWY	Kingsway Corporation Common Stock
LNG	Cheniere Energy, Inc. Common Stock
MGLD	The Marygold Companies, Inc. Common Stock
NNVC	NanoViricides, Inc. Common Stock
PHAR	Pharming Group N.V. - ADS, each representing 10 ordinary shares
RIVN	Rivian Automotive, Inc. - Class A Common Stock
SGLD	Scorpio Gold Corporation - Common Stock
TLPH	Talphera, Inc. - Common Stock
VSEC	VSE Corporation - Common Stock
WTI	W&T Offshore, Inc. Common Stock
AEMD	Aethlon Medical, Inc. - Common Stock
BHR	Braemar Hotels & Resorts Inc. Common Stock
CECO	CECO Environmental Corp. - Common Stock
DOW	Dow Inc. Common Stock 
ENTG	Entegris, Inc. - Common Stock
FLUT	Flutter Entertainment plc Ordinary Shares
GM	General Motors Company Common Stock
HPQ	HP Inc. Common Stock
INM	InMed Pharmaceuticals Inc. - Common Shares
KXIN	Kaixin Holdings - Ordinary Shares
LNKS	Linkers Industries Limited - Class A Ordinary Shares
MGM	MGM Resorts International Common Stock
NOA	North American Construction Group Ltd. Common Shares (no par)
ORI	Old Republic International Corporation Common Stock
PHAT	Phathom Pharmaceuticals, Inc. - Common Stock
RJET	Republic Airways Holdings Inc. - Common Stock
SGLY	Singularity Future Technology Ltd. - Common Stock
TLRY	Tilray Brands, Inc. - Common Stock
VSH	Vishay Intertechnology, Inc. Common Stock
WTM	White Mountains Insurance Group, Ltd. Common Stock
AENT	Alliance Entertainment Holding Corporation - common stock
BHRB	Burke & Herbert Financial Services Corp. - Common Stock
CEG	Constellation Energy Corporation - Common Stock When-Issued
DOX	Amdocs Limited - Ordinary Shares
ENTX	Entera Bio Ltd. - Ordinary Shares
FLUX	Flux Power Holdings, Inc. - Common Stock
GME	GameStop Corporation Common Stock
HQ	Horizon Quantum Holdings Ltd. - Class A Ordinary Shares
INMB	INmune Bio Inc. - Common stock
KYIV	Kyivstar Group Ltd. - Common Shares
LNN	Lindsay Corporation Common Stock
MGN	Megan Holdings Limited - Class A Ordinary Shares
NOC	Northrop Grumman Corporation Common Stock
ORIC	Oric Pharmaceuticals, Inc. - Common Stock
PHGE	BiomX Inc. Common Stock
RJF	Raymond James Financial, Inc. Common Stock
SGML	Sigma Lithium Corporation - common shares
TLS	Telos Corporation - Common Stock
VSME	VS Media Holdings Limited - Class A Ordinary Shares
WTRG	Essential Utilities, Inc. Common Stock
AEO	American Eagle Outfitters, Inc. Common Stock
BHST	BioHarvest Sciences Inc. - Common Stock
CELC	Celcuity Inc. - Common Stock
DPC	DPC Holdings PLC Ordinary Shares
ENVA	Enova International, Inc. Common Stock
FLWS	1-800-FLOWERS.COM, Inc. - Class A Common Stock
GMED	Globus Medical, Inc. Class A Common Stock
HQI	HireQuest, Inc. - Common Stock
INMD	InMode Ltd.  - Ordinary Shares
KYMR	Kymera Therapeutics, Inc. - Common Stock
LNSR	LENSAR, Inc. - Common Stock
MGNI	Magnite, Inc. - Common Stock
NODK	NI Holdings, Inc. - Common Stock
ORIO	Orion Digital Corp. - Common Shares
PHIN	PHINIA Inc. Common Stock
RKDA	Arcadia Biosciences, Inc. - Common Stock
SGMT	Sagimet Biosciences Inc. - Series A Common Stock
TLSA	Tiziana Life Sciences Ltd - Common Shares
VSNT	Versant Media Group, Inc. - Class A Common Stock
WTS	Watts Water Technologies, Inc. Class A Common Stock
AEON	AEON Biopharma, Inc. Class A Common Stock
BHVN	Biohaven Ltd. Common Shares 
CELH	Celsius Holdings, Inc. - Common Stock
DPRO	Draganfly Inc. - Common Shares
ENVB	Enveric Biosciences, Inc.  - Common Stock
FLXS	Flexsteel Industries, Inc. - Common Stock
GMEX	GMEX ROBOTICS CORPORATION - Class A Ordinary Shares
HQY	HealthEquity, Inc. - Common Stock
INN	Summit Hotel Properties, Inc. Common Stock
KYNB	Kyntra Bio, Inc. - Common Stock
LNT	Alliant Energy Corporation - Common Stock
MGNX	MacroGenics, Inc. - Common Stock
NOEM	CO2 Energy Transition Corp. - Common Stock
ORIQ	Origin Investment Corp I - Ordinary Shares
PHIO	Phio Pharmaceuticals Corp. - Common Stock
RKLB	Rocket Lab Corporation - Common Stock
SGP	SpyGlass Pharma, Inc. - Common Stock
TLSI	TriSalus Life Sciences, Inc. - Common Stock
VST	Vistra Corp. Common Stock
WTTR	Select Water Solutions, Inc. Class A common stock
AEP	American Electric Power Company, Inc. - Common Stock
BIAF	bioAffinity Technologies, Inc. - Common Stock
CELU	Celularity Inc. - Class A Common Stock
DPU	Top KingWin Ltd - Class A Ordinary Shares
ENVX	Enovix Corporation - Common Stock
FLY	Firefly Aerospace Inc. - Common Stock
GMHS	Gamehaus Holdings Inc. - Class A Ordinary Shares
HR	Healthcare Realty Trust Incorporated Common Stock
INNV	InnovAge Holding Corp. - Common Stock
KYTX	Kyverna Therapeutics, Inc. - Common Stock
LNTH	Lantheus Holdings, Inc. - Common Stock
MGPI	MGP Ingredients, Inc. - Common Stock
NOG	Northern Oil and Gas, Inc. Common Stock
ORKA	Oruka Therapeutics, Inc. - Common Stock
PHM	PulteGroup, Inc. Common Stock
RKT	Rocket Companies, Inc. Class A Common Stock
SGRX	SANGRIX INC. - Class A Ordinary Shares
TLYS	Tilly's, Inc. Common Stock
VSTM	Verastem, Inc. - Common Stock
WTW	Willis Towers Watson Public Limited Company - Ordinary Shares
AER	AerCap Holdings N.V. Ordinary Shares
BID	Tribeca Strategic Acquisition Corp. - Class A Ordinary Shares
CELZ	Creative Medical Technology Holdings, Inc. - Common Stock
DPZ	Domino's Pizza Inc - Common Stock
EOG	EOG Resources, Inc. Common Stock
FLYE	Fly-E Group, Inc. - Common Stock
GMM	Global Mofy AI Limited  - Class A Ordinary Shares
HRB	H&R Block, Inc. Common Stock
INO	Inovio Pharmaceuticals, Inc. - Common Stock
LNZA	LanzaTech Global, Inc. - Common Stock
MGRC	McGrath RentCorp - Common Stock
NOMA	NOMADAR Corp. - Class A Common Stock
ORKT	Orangekloud Technology Inc. - Class A Ordinary Shares
PHOE	Phoenix Asia Holdings Limited - Ordinary Shares
RKTO	Rocket One Inc. - Common Stock
SGRY	Surgery Partners, Inc. - Common Stock
TM	Toyota Motor Corporation Common Stock
VSTS	Vestis Corporation Common Stock
WU	Western Union Company (The) Common Stock
AERT	Aeries Technology, Inc. - Class A Ordinary Share
BIIB	Biogen Inc. - Common Stock
CENN	Cenntro Inc. - Common Stock
DRCT	Direct Digital Holdings, Inc. - Class A Common Stock
EOLS	Evolus, Inc. - Common Stock
FLYW	Flywire Corporation - Voting Common Stock
GMRS	GMR Solutions Inc. Class A Common Stock
HRI	Herc Holdings Inc. Common Stock 
INOD	Innodata Inc. - Common Stock
LOAN	Manhattan Bridge Capital, Inc - Common Stock
MGRT	Mega Fortune Company Limited - Ordinary Shares
NOMD	Nomad Foods Limited Ordinary Shares
ORLY	O'Reilly Automotive, Inc. - Common Stock
PHR	Phreesia, Inc. Common Stock
RL	Ralph Lauren Corporation Common Stock
SGU	Star Group L.P. Common Stock
TMC	TMC the metals company Inc. - Common Stock
VSXY	Victorias Secret & Co. Common Stock 
WULF	TeraWulf Inc. - Common Stock
AES	The AES Corporation Common Stock
BIII	Black Spade Acquisition III Co Class A Ordinary Shares
CENT	Central Garden & Pet Company - Common Stock
DRDB	Roman DBDR Acquisition Corp. II - Ordinary shares
EONR	EON Resources Inc. Class A Common Stock
FLYX	flyExclusive, Inc. Class A Common Stock
GNE	Genie Energy Ltd. Class B Common Stock Stock
HRL	Hormel Foods Corporation Common Stock
INR	Infinity Natural Resources, Inc. Class A Common Stock
LOAR	Loar Holdings Inc. Common Stock
MGRX	Mangoceuticals, Inc. - Common Stock
NOV	NOV Inc. Common Stock
ORMP	Oramed Pharmaceuticals Inc. - Common Stock
PHUN	Phunware, Inc. - Common Stock
RLAY	Relay Therapeutics, Inc. - Common Stock
SHAK	Shake Shack, Inc. Class A Common Stock
TMCI	Treace Medical Concepts, Inc. - Common Stock
VTAK	Catheter Precision, Inc. Common Stock
WVE	Wave Life Sciences, Inc. - Common Stock
AESI	Atlas Energy Solutions Inc. Common Stock
BILL	BILL Holdings, Inc. Common Stock
CENTA	Central Garden & Pet Company - Class A Common Stock Nonvoting
DRH	Diamondrock Hospitality Company - Common Stock
EOSE	Eos Energy Enterprises, Inc. - Common Stock
FMAC	Future Money Acquisition Corporation - Ordinary Shares
GNK	Genco Shipping & Trading Limited Ordinary Shares New (Marshall Islands)
HRMY	Harmony Biosciences Holdings, Inc. - Common Stock
INSE	Inspired Entertainment, Inc. - Common Stock
LOB	Live Oak Bancshares, Inc. Common Stock
MGTX	MeiraGTx Holdings plc - Ordinary Shares
NOVT	Novanta Inc. - Common Shares
ORRF	Orrstown Financial Services, Inc. - Common Stock
PHVS	Pharvaris N.V. - Ordinary Shares
RLGT	Radiant Logistics, Inc. Common Stock
SHAZ	SharonAI Holdings, Inc. - Class A Common Stock
TMCR	The Metals Royalty Company Inc. - Common Stock
VTEX	VTEX Class A Common Shares
WVVI	Willamette Valley Vineyards, Inc. - Common Stock
AESP	Aeon Acquisition I Corp. - Class A Ordinary Shares
BIO	Bio-Rad Laboratories, Inc. Class A Common Stock
CENX	Century Aluminum Company - Common Stock
DRI	Darden Restaurants, Inc. Common Stock
EP	Empire Petroleum Corporation Common Stock
FMAO	Farmers & Merchants Bancorp, Inc. - Common Stock
GNL	Global Net Lease, Inc. Common Stock
HROW	Harrow, Inc. - Common Stock
INSG	Inseego Corp. - Common Stock
LOBO	LOBO TECHNOLOGIES LTD. - Class A Ordinary Shares
MGX	Metagenomi Therapeutics, Inc. - Common Stock
NOW	ServiceNow, Inc. Common Stock
OSBC	Old Second Bancorp, Inc. - Common Stock
PI	Impinj, Inc. - Common Stock
RLI	RLI Corp. Common Stock (DE)
SHBI	Shore Bancshares, Inc. - Common Stock
TMDE	TMD Energy Limited Ordinary Shares
VTGN	Vistagen Therapeutics, Inc. - Common Stock
WW	WW International, Inc.  - Common Stock
AEVA	Aeva Technologies, Inc. - Common Stock
BIO-B	Bio-Rad Laboratories, Inc. Class B  Common Stock
CEPF	Cantor Equity Partners IV, Inc. - Class A Ordinary Shares
DRIO	DarioHealth Corp. - Common Stock
EPAC	Enerpac Tool Group Corp. Common Stock
FMBH	First Mid Bancshares, Inc. - Common Stock
GNLN	Greenlane Holdings, Inc. - Class A Common Stock
HRTG	Heritage Insurance Holdings, Inc. Common Stock
INSM	Insmed Incorporated - Common Stock
LOCL	Local Bounti Corporation Common Stock
MGY	Magnolia Oil & Gas Corporation Class A Common Stock
NP	Neptune Insurance Holdings Inc. Class A Common Stock
OSCR	Oscar Health, Inc. Class A Common Stock
PICS	PicS N.V. - Class A Common Shares
RLJ	RLJ Lodging Trust Common Shares of Beneficial Interest $0.01 par value
SHC	Sotera Health Company - Common Stock
TMDX	TransMedics Group, Inc. - Common Stock
VTIX	Virtuix Holdings Inc. - Class A Common Stock
WWD	Woodward, Inc. - Common Stock
AEXA	American Exceptionalism Acquisition Corp. A Class A Ordinary Shares
BIOA	BioAge Labs, Inc. - Common Stock
CEPL	Capstone Energy Plus, Inc. - Common Stock
DRMA	Dermata Therapeutics, Inc. - Common Stock
EPAM	EPAM Systems, Inc. Common Stock
FMC	FMC Corporation Common Stock
GNLX	Genelux Corporation - Common Stock
HRTX	Heron Therapeutics, Inc.   - Common Stock
INSP	Inspire Medical Systems, Inc. Common Stock
LOCO	El Pollo Loco Holdings, Inc. - Common Stock
MGYR	Magyar Bancorp, Inc. - Common Stock
NPAC	New Providence Acquisition Corp. III - Ordinary Shares
OSG	Octave Specialty Group, Inc. Common Stock
PII	Polaris Inc. Common Stock
RLMD	Relmada Therapeutics, Inc. - Common Stock
SHEN	Shenandoah Telecommunications Co - Common Stock
VTN	Invesco Trust for Investment Grade New York Municipals Common Stock
WWR	Westwater Resources, Inc. Common Stock
AEYE	AudioEye, Inc. - Common Stock
BIOT	Instinct Bio Technical Company Holdings Inc. - Common stock
CEPO	Cantor Equity Partners I, Inc. - Class A Ordinary Shares
DRS	Leonardo DRS, Inc. - Common Stock
EPC	Edgewell Personal Care Company Common Stock
FMFC	Kandal M Venture Limited - Class A ordinary Shares
GNPX	Genprex, Inc. - Common Stock
HRZN	Horizon Technology Finance Corporation - Common Stock
INSW	International Seaways, Inc. Common Stock 
LODE	Comstock Inc. Common Stock
MH	McGraw Hill, Inc. Common Stock
NPB	Northpointe Bancshares, Inc. Common Stock
OSIS	OSI Systems, Inc. - Common Stock
PIII	P3 Health Partners Inc. - Class A Common Stock
RLYB	Rallybio Corporation - Common Stock
SHFS	SHF Holdings, Inc. - Class A Common Stock
TMP	Tompkins Financial Corporation Common Stock
VTOL	Bristow Group, Inc. Common Stock
WWW	Wolverine World Wide, Inc. Common Stock
AFCG	Advanced Flower Capital Inc. - Common Stock
BIOX	Bioceres Crop Solutions Corp. - Ordinary Shares
CEPS	Cantor Equity Partners VI, Inc. - Class A Ordinary Shares
DRTS	Alpha Tau Medical Ltd. - Ordinary Shares
EPD	Enterprise Products Partners L.P. Common Stock
FMNB	Farmers National Banc Corp. - Common Stock
GNRC	Generac Holdlings Inc. Common Stock
HSBC	HSBC Holdings, plc. Common Stock
INTA	Intapp, Inc. - Common Stock
LONA	LeonaBio, Inc. - Common Stock
MHH	Mastech Digital, Inc Common Stock
NPCE	Neuropace, Inc. - Common Stock
OSK	Oshkosh Corporation (Holding Company)Common Stock
PINE	Alpine Income Property Trust, Inc. Common Stock
RM	Regional Management Corp. Common Stock
SHIM	Shimmick Corporation - Common Stock
TMQ	Trilogy Metals Inc. Common Stock
VTR	Ventas, Inc. Common Stock
WXM	WF International Limited - Ordinary Shares
AFG	American Financial Group, Inc. Common Stock
BIRD	Smartbird, Inc. - Class A Common Stock
CEPV	Cantor Equity Partners V, Inc. - Class A Ordinary Shares
DRUG	Bright Minds Biosciences Inc. - common stock
EPM	Evolution Petroleum Corporation, Inc. Common Stock
FMST	Foremost Clean Energy Ltd. - Common Shares
GNS	Genius Group Limited Ordinary Shares
HSCS	HeartSciences Inc. - Common Stock
LOOP	Loop Industries, Inc. - Common Stock
MHK	Mohawk Industries, Inc. Common Stock
NPK	National Presto Industries, Inc. Common Stock
OSPN	OneSpan Inc. - Common Stock
PINS	Pinterest, Inc. Class A Common Stock
RMBI	Richmond Mutual Bancorporation, Inc. - Common Stock
SHIP	Seanergy Maritime Holdings Corp. - Common Stock
TMS	Teamshares Inc. - Common Stock
VTRS	Viatris Inc. - Common Stock
WY	Weyerhaeuser Company Common Stock
AFJK	Aimei Health Technology Co., Ltd - Ordinary Share
BIRK	Birkenstock Holding plc Ordinary Shares
CERS	Cerus Corporation - Common Stock
DRVN	Driven Brands Holdings Inc. - Common Stock
EPOW	E-Power Inc. - Class A Ordinary Shares
FMX	Fomento Economico Mexicano S.A.B. de C.V. Common Stock
GNSS	Genasys Inc. - Common Stock
HSDT	Solana Company - Class A Common Stock
INTG	The Intergroup Corporation - Common Stock
LOPE	Grand Canyon Education, Inc. - Common Stock
MHO	M/I Homes, Inc. Common Stock
NPKI	NPK International Inc. Common Stock
OSPR	Osprey Acquisition Corp. III - Class A Ordinary Shares
PIPR	Piper Sandler Companies Common Stock
RMBS	Rambus, Inc. - Common Stock
SHLS	Shoals Technologies Group, Inc. - Class A Common Stock
TMTS	Spartacus Acquisition Corp. II - Class A Ordinary Shares
VTS	Vitesse Energy, Inc. Common Stock
WYFI	WhiteFiber, Inc. - Ordinary Shares
AFL	AFLAC Incorporated Common Stock
BIT	BlackRock Multi-Sector Income Trust Common Shares of Beneficial Interest
CERT	Certara, Inc. - Common Stock
DSAC	Daedalus Special Acquisition Corp. - Class A Ordinary Shares
EPR	EPR Properties Common Stock
FN	Fabrinet Ordinary Shares
GNTX	Gentex Corporation - Common Stock
HSHP	Himalaya Shipping Ltd. Common Shares
INTJ	Intelligent Group Limited - Class A Ordinary Shares
LOVE	The Lovesac Company - Common Stock
MI	NFT Limited Class A Ordinary Share
NPO	Enpro Inc. Common Stock
OSS	One Stop Systems, Inc. - Common Stock
PJT	PJT Partners Inc. Class A Common Stock
RMCF	Rocky Mountain Chocolate Factory, Inc. - Common Stock
SHMD	SCHMID Group N.V. - Class A Ordinary Shares
TMUS	T-Mobile US, Inc. - Common Stock
VTSI	VirTra, Inc. - Common Stock
WYNN	Wynn Resorts, Limited - Common Stock
AFRI	Forafric Global PLC - Ordinary Shares
BIVI	BioVie Inc. - Common stock
CET	Central Securities Corporation Common Stock
DSGN	Design Therapeutics, Inc. - Common Stock
EPRT	Essential Properties Realty Trust, Inc. Common Stock
FNB	F.N.B. Corporation Common Stock
GNW	Genworth Financial Inc Common Stock
HSIC	Henry Schein, Inc. - Common Stock
INTR	Inter & Co. Inc. - Class A Common Shares
MIAC	Meridian3 Industrials Acquisition Corp - Class A Ordinary Shares
NPT	Texxon Holding Limited - Ordinary shares
OST	Ostin Technology Group Co., Ltd. - Class A Ordinary Shares
PK	Park Hotels & Resorts Inc. Common Stock 
RMCO	Royalty Management Holding Corporation - Class A Common Stock
SHO	Sunstone Hotel Investors, Inc. Sunstone Hotel Investors, Inc. Common Shares
TNC	Tennant Company Common Stock
VTVT	vTv Therapeutics Inc. - Class A Common Stock
WYY	WidePoint Corporation Common Stock
AFRM	Affirm Holdings, Inc. - Class A Common Stock
BIXI	Bitcoin Infrastructure Acquisition Corp Ltd. - Class A Ordinary Shares
CETX	Cemtrex Inc. - Common Stock
DSGR	Distribution Solutions Group, Inc. - Common Stock
EPRX	Eupraxia Pharmaceuticals Inc. - Common Stock
FND	Floor & Decor Holdings, Inc. Common Stock
GO	Grocery Outlet Holding Corp. - Common Stock
HSLV	Highlander Silver Corp. Common Shares
INTS	Intensity Therapeutics, Inc. - Common Stock
LPA	Logistic Properties of the Americas Ordinary Shares
MIAX	Miami International Holdings, Inc. Common Stock
NPWR	NET Power Inc. Class A Common Stock
OSTX	OS Therapies Incorporated Common Stock
PKBK	Parke Bancorp, Inc. - Common Stock
RMD	ResMed Inc. Common Stock
SHOE	Shoe Station Group, Inc. - Common Stock
TNDM	Tandem Diabetes Care, Inc. - Common Stock
VUZI	Vuzix Corporation  - Common Stock
AFYA	Afya Limited - Class A Common Shares
BIYA	Baiya International Group Inc.  - Ordinary Shares
CETY	Clean Energy Technologies, Inc. - Common Stock
DSGX	The Descartes Systems Group Inc. - Common Stock
EPSM	Epsium Enterprise Limited - Class A Ordinary Shares
FNF	Fidelity National Financial, Inc. Common Stock
GOAI	Eva Live Inc. - Common Stock
HST	Host Hotels & Resorts, Inc. - Common Stock
INTT	inTest Corporation Common Stock
LPAA	Launch One Acquisition Corp. - Class A Ordinary Shares
MICC	The Magnum Ice Cream Company N.V. Ordinary Shares
NRC	NRC Health - Common Stock
OSUR	OraSure Technologies, Inc. - Common Stock
PKE	Park Aerospace Corp. Common Stock
RMIX	Suncrete, Inc. - Class A Common Stock
SHOO	Steven Madden, Ltd. - Common Stock
TNET	TriNet Group, Inc. Common Stock
VVOS	Vivos Therapeutics, Inc. - Common Stock
AG	First Majestic Silver Corp. Ordinary Shares (Canada)
BJ	BJ's Wholesale Club Holdings, Inc. Common Stock
CEVA	CEVA, Inc. - Common Stock
DSP	Viant Technology Inc. - common stock
EPSN	Epsilon Energy Ltd. - Common Shares
FNGR	FingerMotion, Inc. - common stock
GOGO	Gogo Inc. - Common Stock
HSTM	HealthStream, Inc. - Common Stock
INTU	Intuit Inc. - Common Stock
LPBB	Launch Two Acquisition Corp. - Class A Ordinary Shares
MIDD	The Middleby Corporation - Common Stock
NRDS	NerdWallet, Inc. - Class A Common Stock
OSW	OneSpaWorld Holdings Limited - Common Shares
PKG	Packaging Corporation of America Common Stock
RMNI	Rimini Street, Inc. - Common Stock
SHOT	RMG ML Sports Holdings - Class A Ordinary Shares
TNGX	Tango Therapeutics, Inc. - Common Stock
VVR	Invesco Senior Income Trust Common Stock (DE)
AGBK	AGI Inc Class A Common Shares
BJDX	Bluejay Diagnostics, Inc. - Common Stock
CF	CF Industries Holdings, Inc. Common Stock
DSS	DSS, Inc. Common Stock
EQ	Equillium, Inc. - Common Stock
FNKO	Funko, Inc. - Class A Common Stock
GOLD	Gold.com, Inc. Common Stock
HSY	The Hershey Company Common Stock
INTZ	Intrusion Inc. - Common Stock
LPCN	Lipocine Inc. - Common Stock
MIMI	Mint Incorporation Limited - Class A Ordinary Shares
NRDY	Nerdy Inc. Class A Common Stock
OTAI	Starlink AI Acquisition Corporation Ordinary Shares
PKOH	Park-Ohio Holdings Corp. - Common Stock
RMR	The RMR Group Inc. - Class A Common Stock
SHPH	Shuttle Pharmaceuticals Holdings, Inc. - common stock
TNMG	TNL Mediagene - Ordinary Shares
VVV	Valvoline Inc. Common Stock
AGCC	Agencia Comercial Spirits Ltd - Class A Ordinary Share
BJRI	BJ's Restaurants, Inc. - Common Stock
CFBK	CF Bankshares Inc. - Common Stock
DSWL	Deswell Industries, Inc. - Common Shares
EQBK	Equity Bancshares, Inc. Class A Common Stock
FNLC	First Bancorp, Inc (ME) - Common Stock
GOLF	Acushnet Holdings Corp. Common Stock
HTB	HomeTrust Bancshares, Inc. Common Stock
INV	Innventure, Inc. - Common Stock
LPCV	Launchpad Cadenza Acquisition Corp I - Class A Ordinary Share
MIND	MIND Technology, Inc. - Common Stock
NREF	NexPoint Real Estate Finance, Inc. Common Stock
OTEX	Open Text Corporation - Common Shares
PL	Planet Labs PBC Class A Common Stock
RMSG	Real Messenger Corporation - Ordinary Shares
SHW	Sherwin-Williams Company (The) Common Stock
TNON	Tenon Medical, Inc. - Common Stock
VVX	V2X, Inc. Common Stock
AGCO	AGCO Corporation Common Stock
BKD	Brookdale Senior Living Inc. Common Stock
CFFI	C&F Financial Corporation - Common Stock
DSX	Diana Shipping inc. common stock
EQH	Equitable Holdings, Inc. Common Stock
FNRN	First Northern Community Bancorp - Common stock
HTCO	High-Trend International Group - Class A Ordinary Shares
INVA	Innoviva, Inc. - Common Stock
LPG	Dorian LPG Ltd. Common Stock
MINE	Mayfair Gold Corp. Common Shares
NRG	NRG Energy, Inc. Common Stock
OTF	Blue Owl Technology Finance Corp. Common Stock
PLAB	Photronics, Inc. - Common Stock
RMT	Royce Micro-Cap Trust, Inc. Common Stock
SI	Shoulder Innovations, Inc. Common Stock
TNXP	Tonix Pharmaceuticals Holding Corp. - Common Stock
VWAV	VisionWave Holdings, Inc. - Common Stock
AGEN	Agenus Inc. - Common Stock
BKE	Buckle, Inc. (The) Common Stock
CFFN	Capitol Federal Financial, Inc. - Common Stock
DSY	Big Tree Cloud Holdings Limited - Class A Ordinary Shares
EQIX	Equinix, Inc. - Common Stock
FNUC	Frontier Nuclear and Minerals Inc. - Common Shares
HTCR	Heartcore Enterprises, Inc. - Common Stock
INVE	Identiv, Inc. - Common Stock
LPLA	LPL Financial Holdings Inc. - Common Stock
MIR	Mirion Technologies, Inc. Class A Common Stock
NRGV	Energy Vault Holdings, Inc. Common Stock
OTGA	OTG Acquisition Corp. I - Class A Ordinary Share
PLAG	Planet Green Holdings Corp. Common Stock
RMTI	Rockwell Medical, Inc. - Common Stock
SIBN	SI-BONE, Inc. - Common Stock
TNYA	Tenaya Therapeutics, Inc. - Common Stock
VYGR	Voyager Therapeutics, Inc. - Common Stock
AGI	Alamos Gold Inc. Class A Common Shares
BKH	Black Hills Corporation Common Stock
CFG	Citizens Financial Group, Inc. Common Stock
DT	Dynatrace, Inc. Common Stock
EQPT	EquipmentShare.com Inc - Class A Common Stock
FNWB	First Northwest Bancorp - Common Stock
GORO	Goldgroup Mining Inc. Common Shares
HTFL	Heartflow, Inc. - Common Stock
INVH	Invitation Homes Inc. Common Stock
LPTH	LightPath Technologies, Inc. - Class A Common Stock
MIRA	MIRA Pharmaceuticals, Inc. - Common Stock
NRIM	Northrim BanCorp Inc - Common Stock
OTIS	Otis Worldwide Corporation Common Stock 
PLAY	Dave & Buster's Entertainment, Inc. - Common Stock
RNA	Atrium Therapeutics, Inc. - Common Stock
SID	Companhia Siderurgica Nacional S.A. Common Stock
TOL	Toll Brothers, Inc. Common Stock
VYX	NCR Voyix Corporation Common Stock
AGIG	Abundia Global Impact Group Inc. Common stock
BKHA	Black Hawk Acquisition Corporation - Class A Ordinary Shares
CFR	Cullen/Frost Bankers, Inc. Common Stock
DTCX	Datacentrex, Inc. - Common Stock
EQS	Equus Total Return, Inc. Common Stock
FNWD	Finward Bancorp - common stock
GOSS	Gossamer Bio, Inc. - Common Stock
HTGC	Hercules Capital, Inc. Common Stock
INVX	Innovex International, Inc. Common Stock
LPX	Louisiana-Pacific Corporation Common Stock
MIRM	Mirum Pharmaceuticals, Inc. - common stock
NRIX	Nurix Therapeutics, Inc. - Common stock
OTLK	Outlook Therapeutics, Inc. - Common Stock
PLBC	Plumas Bancorp - Common Stock
RNAC	Cartesian Therapeutics, Inc. - Common Stock
SIDU	Sidus Space, Inc. - Class A Common Stock
TOMZ	TOMI Environmental Solutions, Inc. - Common Stock
VZ	Verizon Communications Inc. Common Stock
AGIO	Agios Pharmaceuticals, Inc. - Common Stock
BKKT	Bakkt, Inc. Class A Common Stock
CG	The Carlyle Group Inc. - Common Stock
DTE	DTE Energy Company Common Stock
EQT	EQT Corporation Common Stock
FOA	Finance of America Companies Inc. Class A Common Stock
GOVX	GeoVax Labs, Inc. - Common Stock
HTLD	Heartland Express, Inc. - Common Stock
INVZ	Innoviz Technologies Ltd. - Ordinary shares
LQDA	Liquidia Corporation - Common Stock
MIST	Milestone Pharmaceuticals Inc. - Common Shares
NRSN	NeuroSense Therapeutics Ltd. - Ordinary Shares
OTTR	Otter Tail Corporation - Common Stock
PLBL	Polibeli Group Ltd - Class A Ordinary Shares
RNAZ	TransCode Therapeutics, Inc. - Common Stock
SIEB	Siebert Financial Corp. - Common Stock
TONT	Graf Global Corp. Class A ordinary shares
VZLA	Vizsla Silver Corp. Common Shares
AGL	agilon health, inc. Common Stock
BKNG	Booking Holdings Inc. - Common Stock
CGAU	Centerra Gold Inc. Common Shares
DTI	Drilling Tools International Corporation  - Common Stock
EQX	Equinox Gold Corp. Common Shares
FOFO	Hang Feng Technology Innovation Co., Ltd. - Ordinary Shares
GP	GreenPower Motor Company Inc. - Common Shares
HTLM	HomesToLife Ltd - Ordinary Shares
IOND	Ionic Digital Inc. - Class A Common Stock
LQDT	Liquidity Services, Inc. - Common Stock
MITK	Mitek Systems, Inc. - Common Stock
NRT	North European Oil Royality Trust Common Stock
OUST	Ouster, Inc. - Common Stock
PLBY	Playboy, Inc. - Common Stock
RNG	RingCentral, Inc. Class A Common Stock
SIF	SIFCO Industries, Inc. Common Stock
TONX	TON Strategy Company - Common Stock
AGM	Federal Agricultural Mortgage Corporation Common Stock
BKR	Baker Hughes Company - Common Stock
CGC	Canopy Growth Corporation - Common Shares
DTIL	Precision BioSciences, Inc. - Common Stock
ERAS	Erasca, Inc. - Common Stock
FOR	Forestar Group Inc Common Stock 
GPAC	General Purpose Acquisition Corp. - Class A Ordinary Shares
HTO	H2O America  - Common Stock
IONQ	IonQ, Inc. Common Stock
LRCX	Lam Research Corporation - Common Stock
MITQ	Moving iMage Technologies, Inc. Common Stock
NRXP	NRX Pharmaceuticals, Inc. - Common Stock
OUT	OUTFRONT Media Inc. Common Stock
PLCE	Children's Place, Inc. (The) - Common Stock
RNGR	Ranger Energy Services, Inc. Class A Common Stock
SIG	Signet Jewelers Limited Common Shares
TOON	Kartoon Studios, Inc. Common Stock
AGM-A	Federal Agricultural Mortgage Corporation Common Stock
BKSY	BlackSky Technology Inc. Class A Common Stock
CGCF	Cartesian Growth Corporation IV - Class A Ordinary Shares
DTM	DT Midstream, Inc. Common Stock 
ERIE	Erie Indemnity Company - Class A Common Stock
FORM	FormFactor, Inc. - Common Stock
GPAT	GP-Act III Acquisition Corp. - Class A Ordinary Share
HTOO	Fusion Fuel Green PLC - Ordinary Shares
IONS	Ionis Pharmaceuticals, Inc. - Common Stock
LRHC	La Rosa Holdings Corp. - Common Stock
MITT	TPG Mortgage Investment Trust, Inc. Common Stock
NRXS	Neuraxis, Inc. Common Stock
OVBC	Ohio Valley Banc Corp. - Common Stock
PLCI	Pelican Acquisition II Corporation - Ordinary Shares
RNGT	Range Capital Acquisition Corp II - Class A Ordinary Shares
SIGA	SIGA Technologies Inc. - Common Stock
TOP	TOP Financial Group Limited - Class A Ordinary Shares
AGMB	AgomAb Therapeutics NV - ADRs representing one common share.
BKTI	BK Technologies Corporation Common Stock
CGEM	Cullinan Therapeutics, Inc. - Common Stock
DTSQ	DT Cloud Star Acquisition Corporation - Ordinary Shares
ERII	Energy Recovery, Inc. - Common Stock
FORR	Forrester Research, Inc. - Common Stock
GPC	Genuine Parts Company Common Stock
HTZ	Hertz Global Holdings, Inc - Common Stock
IOR	Income Opportunity Realty Investors, Inc. Common Stock
LRMR	Larimar Therapeutics, Inc. - Common Stock
MKC	McCormick & Company, Incorporated Common Stock
NSAI	NorthStrive Acquisition Corp I. - Class A Ordinary Shares
OVID	Ovid Therapeutics Inc. - Common Stock
PLD	Prologis, Inc. Common Stock
RNR	RenaissanceRe Holdings Ltd. Common Stock
SIGI	Selective Insurance Group, Inc. - Common Stock
TOPP	Toppoint Holdings Inc. Common Stock
AGMH	AGM Group Holdings Inc. - Class A Ordinary Shares
BKU	BankUnited, Inc. Common Stock
CGEN	Compugen Ltd. - Ordinary Shares
DTSS	Datasea Intelligent Technology Ltd. - Class A Ordinary Shares
ERNA	Ernexa Therapeutics Inc. - Common Stock
FOSL	Fossil Group, Inc. - Common Stock
GPGI	GPGI, Inc. Class A Common Stock
HUBB	Hubbell Inc Common Stock
IOSP	Innospec Inc. - Common Stock
LRN	Stride, Inc. Common Stock
MKC-V	McCormick & Company, Incorporated Common Stock
NSC	Norfolk Southern Corporation Common Stock
OVLY	Oak Valley Bancorp (CA) - Common Stock
PLG	Platinum Group Metals Ltd. Ordinary Shares (Canada)
RNST	Renasant Corporation Common Stock
SII	Sprott Inc. Common Shares
TOPS	TOP Ships, Inc. Common Stock
AGNC	AGNC Investment Corp. - Common Stock
BKV	BKV Corporation Common Stock
CGNT	Cognyte Software Ltd. - Ordinary Shares
DTST	Data Storage Corporation - Common Stock
ERO	Ero Copper Corp. Common Shares
FOUR	Shift4 Payments, Inc. Class A Common Stock
GPI	Group 1 Automotive, Inc. Common Stock
HUBC	Hub Cyber Security Ltd. - Ordinary Shares
IOT	Samsara Inc. Class A Common Stock
LSAK	Lesaka Technologies, Inc. - Common Stock
MKDW	MKDWELL Tech Inc. - Ordinary Shares
NSIT	Insight Enterprises, Inc. - Common Stock
OWL	Blue Owl Capital Inc. Class A Common Stock
PLGO	Pelagos Insurance Capital Limited Common Shares
RNTX	Rein Therapeutics, Inc. - Common Stock
SILC	Silicom Ltd - Ordinary Shares
TORO	Toro Corp. - Common stock
AGNT	AGNT, Inc. - Common Stock
BKYI	BIO-key International, Inc. - Common Stock
CGNX	Cognex Corporation - Common Stock
DUK	Duke Energy Corporation (Holding Company) Common Stock
EROC	ERock, Inc. Class A Common Stock
FOX	Fox Corporation - Class B Common Stock
GPMT	Granite Point Mortgage Trust Inc. Common Stock
HUBG	Hub Group, Inc. - Class A Common Stock
IOTR	iOThree Limited - Ordinary Shares
LSBK	Lake Shore Bancorp, Inc. - Common Stock
MKL	Markel Group Inc. Common Stock
NSP	Insperity, Inc. Common Stock
OWLS	OBOOK Holdings Inc. - Class A Common Shares
PLMK	Plum Acquisition Corp. IV - Class A Ordinary Shares
RNXT	RenovoRx, Inc. - Common Stock
SILO	Silo Pharma, Inc. - Common Stock
TOST	Toast, Inc. Class A Common Stock
AGO	Assured Guaranty Ltd. Common Stock
BL	BlackLine, Inc. - Common Stock
CGON	CG Oncology, Inc. - Common stock
DUKR	DUKE Robotics Corp. - Common Stock
ES	Eversource Energy (D/B/A) Common Stock
FOXA	Fox Corporation - Class A Common Stock
GPN	Global Payments Inc. Common Stock
HUBS	HubSpot, Inc. Common Stock
IOVA	Iovance Biotherapeutics, Inc. - Common Stock
LSCC	Lattice Semiconductor Corporation - Common Stock
MKLY	McKinley Acquisition Corporation - Class A Ordinary Shares
NSPR	InspireMD Inc. - Common Stock
OWLT	Owlet, Inc. Class A Common Stock
PLMR	Palomar Holdings, Inc. - Common stock
ROAD	Construction Partners, Inc. - Common Stock
SIMA	SIM Acquisition Corp. I - Class A Ordinary Shares
TOVX	Theriva Biologics, Inc. Common Stock
AGPU	Axe Compute Inc. - Common Stock
BLBD	Blue Bird Corporation - Common Stock
CGTL	Creative Global Technology Holdings Limited - Class A Ordinary Shares
DUO	Fangdd Network Group Ltd. - Class A Ordinary Shares
ESAB	ESAB Corporation Common Stock
FOXF	Fox Factory Holding Corp. - Common Stock
GPOR	Gulfport Energy Corporation Common Shares
HUDI	Huadi International Group Co., Ltd. - Ordinary Shares
IP	International Paper Company Common Stock
LSE	Leishen Energy Holding Co., Ltd. - Class A Ordinary Shares
MKSI	MKS Inc. - Common Stock
NSRX	Nasus Pharma Ltd. Ordinary Shares
OXBR	Oxbridge Re Holdings Limited - Ordinary Shares
PLNT	Planet Fitness, Inc. Common Stock
ROC	Rank One Computing Corporation - Common stock
SIND	Sinda Ltd. Common Stock
TOWN	Towne Bank - Common Stock
AGRO	Adecoagro S.A. Common Shares
BLCO	Bausch + Lomb Corporation Common Shares
CGTX	Cognition Therapeutics, Inc. - Common Stock
DUOL	Duolingo, Inc. - Class A Common Stock
ESCA	Escalade, Incorporated - Common Stock
FOXX	Foxx Development Holdings Inc. - Common Stock
GPRE	Green Plains, Inc. - Common Stock
HUHU	HUHUTECH International Group Inc. - Ordinary Shares
IPAR	Interparfums, Inc. - Common Stock
LSF	Laird Superfood, Inc. Common Stock
MKTW	MarketWise, Inc. - Class A Common Stock
NSSC	NAPCO Security Technologies, Inc. - Common Stock
OXM	Oxford Industries, Inc. Common Stock
PLOW	Douglas Dynamics, Inc. Common Stock
ROCK	Gibraltar Industries, Inc. - Common Stock
SINT	SiNtx Technologies, Inc. - Common Stock
TOYO	TOYO Co., Ltd - Ordinary Shares
AGRZ	Agroz Inc. - Class A Ordinary Shares
BLDP	Ballard Power Systems, Inc. - Common Shares
CHAI	Core AI Holdings, Inc. - Common Shares
DUOT	Duos Technologies Group, Inc. - Common Stock
ESE	ESCO Technologies Inc. Common Stock
FPH	Five Point Holdings, LLC Class A Common Shares
GPRK	Geopark Ltd Common Shares
HUM	Humana Inc. Common Stock
IPDN	Professional Diversity Network, Inc. - Common Stock
LSTA	Lisata Therapeutics, Inc. - Common Stock
MKTX	MarketAxess Holdings, Inc. - Common Stock
NSTS	NSTS Bancorp, Inc. - Common Stock
OXY	Occidental Petroleum Corporation Common Stock
PLPC	Preformed Line Products Company - Common Stock
ROG	Rogers Corporation Common Stock
SION	Sionna Therapeutics, Inc. - Common Stock
TP	Ticketplus Ltd. Ordinary Shares
AGX	Argan, Inc. Common Stock
BLDR	Builders FirstSource, Inc. Common Stock
CHAR	Charlton Aria Acquisition Corporation - Class A Ordinary Shares
DV	DoubleVerify Holdings, Inc. Common Stock
ESEA	Euroseas Ltd. - Common Stock
FPI	Farmland Partners Inc. Common Stock
GPRO	GoPro, Inc. - Class A Common Stock
HUMA	Humacyte, Inc. - Common Stock
IPEX	Inflection Point Acquisition Corp. - Class A Ordinary Shares
LSTR	Landstar System, Inc. - Common Stock
MKZR	MacKenzie Realty Capital, Inc. - Common Stock
NSYS	Nortech Systems Incorporated - Common Stock
OYSE	Oyster Enterprises II Acquisition Corp - Class A Ordinary Shares
PLRX	Pliant Therapeutics, Inc. - Common Stock
ROIV	Roivant Sciences Ltd. - Common Shares
SIRI	SiriusXM Holdings Inc. - Common Stock
TPB	Turning Point Brands, Inc. Common Stock
AGYS	Agilysys, Inc. - Common Stock
BLFS	BioLife Solutions, Inc. - Common Stock
CHCI	Comstock Holding Companies, Inc. - Class A Common Stock
DVA	DaVita Inc. Common Stock
ESI	Element Solutions Inc. Common Stock
FPS	Forgent Power Solutions, Inc. Class A Common Stock
GPUS	Hyperscale Data, Inc. Common Stock
HUN	Huntsman Corporation Common Stock
IPFX	Inflection Point Acquisition Corp. VI - Class A Ordinary Shares
LTBR	Lightbridge Corporation - Common Stock
MLAA	Mountain Lake Acquisition Corp. II - Class A Ordinary Shares
NTAP	NetApp, Inc. - Common Stock
OZK	Bank OZK - Common Stock
PLRZ	Polyrizon Ltd. - Ordinary Shares
ROK	Rockwell Automation, Inc. Common Stock
SITC	SITE Centers Corp. Common Stock
TPC	Tutor Perini Corporation Common Stock
AHCO	AdaptHealth Corp.  - Common Stock
BLIN	Bridgeline Digital, Inc. - Common Stock
CHCO	City Holding Company - Common Stock
DVLT	Datavault AI Inc. - Common Stock
ESLA	Estrella Immunopharma, Inc. - Common Stock
FR	First Industrial Realty Trust, Inc. Common Stock
GRAB	Grab Holdings Limited - Class A Ordinary Shares
HURA	TuHURA Biosciences, Inc. - Common Stock
IPGP	IPG Photonics Corporation - Common Stock
LTC	LTC Properties, Inc. Common Stock
MLAB	Mesa Laboratories, Inc. - Common Stock
NTB	Bank of N.T. Butterfield & Son Limited (The) Voting Ordinary Shares
PLSE	Pulse Biosciences, Inc - Common Stock
ROKU	Roku, Inc. - Class A Common Stock
SITE	SiteOne Landscape Supply, Inc. Common Stock
TPCS	TechPrecision Corporation - Common stock
AHMA	Ambitions Enterprise Management Co. L.L.C - Class A Ordinary Shares
BLIV	BeLive Holdings - ordinary shares
CHCT	Community Healthcare Trust Incorporated Common Stock
DVN	Devon Energy Corporation Common Stock
ESLT	Elbit Systems Ltd. - Ordinary Shares
FRAF	Franklin Financial Services Corporation - Common Stock
GRAL	GRAIL, Inc. - Common Stock
HURC	Hurco Companies, Inc. - Common Stock
IPI	Intrepid Potash, Inc Common Stock
LTGO	Latigo Biotherapeutics, Inc. - Common Stock
MLCI	Mount Logan Capital Inc. - Common Stock
NTCL	NETCLASS TECHNOLOGY INC - Class A Ordinary Shares
PLSM	Pulsenmore Ltd. - Ordinary Shares
ROL	Rollins, Inc. Common Stock
SITM	SiTime Corporation - Common Stock
TPET	Trio Petroleum Corp. Common Stock
AHR	American Healthcare REIT, Inc. Common Stock
BLK	BlackRock, Inc. Common Stock
CHD	Church & Dwight Company, Inc. Common Stock
DWSN	Dawson Geophysical Company - Common Stock
ESNT	Essent Group Ltd. Common Shares
FRBA	First Bank  - Common Stock
GRAN	Grande Group Limited - Class A Ordinary Shares
HURN	Huron Consulting Group Inc. - Common Stock
IPM	Intelligent Protection Management Corp.  - Common Stock
LTGR	Long Table Growth Corp. - Class A Ordinary Shares
MLEC	Moolec Science SA - Ordinary Shares
NTCT	NetScout Systems, Inc. - Common Stock
PLTK	Playtika Holding Corp. - Common Stock
ROLR	High Roller Technologies, Inc. Common Stock
SJ	Scienjoy Holding Corporation - Class A Ordinary Shares
TPG	TPG Inc. - Class A Common Stock
AHRT	AH Realty Trust, Inc. Common Stock
BLKB	Blackbaud, Inc. - Common Stock
CHDN	Churchill Downs, Incorporated - Common Stock
DWTX	Dogwood Therapeutics, Inc.  - Common Stock
ESOA	Energy Services of America Corporation - Common Stock
FRBT	Forbright, Inc. - Class A Common Stock
GRBK	Green Brick Partners, Inc. Common Stock
HUT	Hut 8 Corp. - Common Stock
IPSC	Century Therapeutics, Inc. - Common Stock
LTH	Life Time Group Holdings, Inc. Common Stock
MLGO	MicroAlgo, Inc. - Ordinary Shares
NTGR	NETGEAR, Inc. - Common Stock
ROMA	Roma Green Finance Limited - Class A Ordinary Shares
SJM	The J.M. Smucker Company Common Stock
TPL	Texas Pacific Land Corporation Common Stock
AHT	Ashford Hospitality Trust Inc Common Stock
BLLN	BillionToOne, Inc. - Class A common stock
CHEC	Chenghe Acquisition III Co. - Class A Ordinary Shares
DX	Dynex Capital, Inc. Common Stock
ESP	Espey Mfg. & Electronics Corp. Common Stock
FRD	Friedman Industries Inc. - Common Stock
GRC	Gorman-Rupp Company (The) Common Stock
HVII	Hennessy Capital Investment Corp. VII - Ordinary Shares
IPST	IP Strategy Holdings, Inc. - Common Stock
LTRN	Lantern Pharma Inc. - Common Stock
MLI	Mueller Industries, Inc. Common Stock
NTHI	NeOnc Technologies Holdings, Inc. - Common Stock
PLTS	Platinum Analytics Cayman Limited - Class A Ordinary Shares
ROOT	Root, Inc. - Common Stock
SJT	San Juan Basin Royalty Trust Common Stock
TPR	Tapestry, Inc. Common Stock
AI	C3.ai, Inc. Class A Common Stock
BLMN	Bloomin' Brands, Inc. - Common Stock
CHEF	The Chefs' Warehouse, Inc. - Common Stock
DXC	DXC Technology Company Common Stock 
ESQ	Esquire Financial Holdings, Inc. - Common Stock
FRGT	Freight Technologies, Inc. - Ordinary Shares
GRCE	Grace Therapeutics, Inc. - Common Stock
HVMC	Highview Merger Corp. - Class A Ordinary Share
IPVV	InterPrivate Investment Partners V, Inc. - Class A Ordinary Shares
LTRX	Lantronix, Inc. - Common Stock
MLKN	MillerKnoll, Inc. - Common Stock
NTIC	Northern Technologies International Corporation - Common Stock
PLUG	Plug Power, Inc. - Common Stock
ROP	Roper Technologies, Inc. - Common Stock
SKE	Skeena Resources Limited Common Shares
TPST	Tempest Therapeutics, Inc. - Common Stock
AIAI	AIAI Holdings Corporation - Class A common stock
BLND	Blend Labs, Inc. Class A Common Stock
CHGA	Change Agents Corporation  - Common Stock
DXCM	DexCom, Inc. - Common Stock
ESRT	Empire State Realty Trust, Inc. Class A Common Stock
FRHC	Freedom Holding Corp. - Common Stock
GRDN	Guardian Pharmacy Services, Inc. Class A Common Stock
HVT	Haverty Furniture Companies, Inc. Common Stock
IPW	iPower Inc. - Common Stock
LUCD	Lucid Diagnostics Inc. - Common Stock
MLM	Martin Marietta Materials, Inc. Common Stock
NTIP	Network-1 Technologies, Inc. Common Stock
PLUN	Plutonian Acquisition Corp II Class A Ordinary Shares
ROST	Ross Stores, Inc. - Common Stock
SKIL	Skillsoft Corp. Class A Common Stock
TPVG	TriplePoint Venture Growth BDC Corp. Common Stock
AIB	AIB Data Centers Inc. Common Stock
BLNE	Beeline Holdings, Inc. - Common Stock
CHGG	Chegg, Inc. Common Stock
DXLG	Destination XL Group, Inc. - Common Stock
ESS	Essex Property Trust, Inc. Common Stock
FRME	First Merchants Corporation - Common Stock
GRDX	GridAI Technologies Corp.  - Common Stock
HVT-A	Haverty Furniture Companies, Inc. Common Stock
IPWR	Ideal Power Inc. - Common Stock
LUCK	Lucky Strike Entertainment Corporation Class A Common Stock
MLP	Maui Land & Pineapple Company, Inc. Common Stock
NTLA	Intellia Therapeutics, Inc. - Common Stock
PLUR	Pluri Inc. - Common Stock
RPAY	Repay Holdings Corporation - Class A Common Stock
SKIN	SkinHealth Systems Inc. - Class A Common Stock
TR	Tootsie Roll Industries, Inc. Common Stock
AIBZ	Bitzero Holdings Inc. - Common Shares
BLNK	Blink Charging Co. - Common Stock
CHH	Choice Hotels International, Inc. Common Stock
DXPE	DXP Enterprises, Inc. - Common Stock
ESTA	Establishment Labs Holdings Inc. - Common Shares
FRMI	Fermi Inc. - Common Stock
GRI	GRI Bio, Inc. - Common Stock
HWBK	Hawthorn Bancshares, Inc. - Common Stock
IPXG	Inection Point Acquisition Corp. VII  - Class A Ordinary Shares
LUCY	Innovative Eyewear, Inc. - Common Stock
MLR	Miller Industries, Inc. Common Stock
NTNX	Nutanix, Inc. - Class A Common Stock
PLUS	ePlus inc. - Common Stock
RPC	Ridgepost Capital, Inc. Class A Common Stock
SKK	SKK Holdings Limited - Class A Ordinary Shares
TRAD	APEX Tech Acquisition Inc. Ordinary Shares
AIDX	20/20 Biolabs, Inc. - Common Stock
BLRK	Bluerock Acquisition Corp. - Class A Ordinary Shares
CHKP	Check Point Software Technologies Ltd. - Ordinary Shares
DXST	Decent Holding Inc. - Class A Ordinary Shares
ESTC	Elastic N.V. Ordinary Shares
FRMM	Forum Markets, Incorporated - Common Stock
GRML	Greenland Mines Ltd - Common Stock
HWC	Hancock Whitney Corporation - Common Stock
IQI	Invesco Quality Municipal Income Trust Common Stock
LUD	Luda Technology Group Limited Ordinary Shares
MLSS	Milestone Scientific, Inc. Common Stock
NTR	Nutrien Ltd. Common Shares
PLUT	Plutus Financial Group Limited - Ordinary Shares
RPD	Rapid7, Inc. - Common Stock
SKM	SK Telecom Co., Ltd. Common Stock
TRAK	ReposiTrak, Inc. Common Stock
AIFA	All In FutureTech Alliance, Inc. - Common Stock
BLSH	Bullish Ordinary Shares
CHMG	Chemung Financial Corp  - Common Stock
DXYZ	Destiny Tech100 Inc. Common Stock
ETD	Ethan Allen Interiors Inc. Common Stock
FRNM	Freenome, Inc. - Common stock
GRMN	Garmin Ltd. Common Stock (Switzerland)
HWH	HWH International Inc. - Common Stock
IQST	iQSTEL Inc. - Common Stock
LULU	lululemon athletica inc. - Common Stock
MLTX	MoonLake Immunotherapeutics - Class A Ordinary Shares
NTRA	Natera, Inc. - Common Stock
PLX	Protalix BioTherapeutics, Inc. (DE) Common Stock
RPGL	Republic Power Group Limited - Class A Ordinary Shares
SKT	Tanger Inc. Common Stock
TRAW	Traws Pharma, Inc. - Common Stock
AIFC	AI Financial Corporation - Common Stock
BLSM	BlossomHill Therapeutics, Inc. - Common Stock
CHMI	Cherry Hill Mortgage Investment Corporation Common Stock
DY	Dycom Industries, Inc. Common Stock
ETN	Eaton Corporation, PLC Ordinary Shares
FRO	Frontline Plc Ordinary Shares
GRND	Grindr Inc. Common Stock
HWKN	Hawkins, Inc. - Common Stock
IQV	IQVIA Holdings, Inc. Common Stock
LUMN	Lumen Technologies, Inc. Common Stock
MLYS	Mineralys Therapeutics, Inc. - Common Stock
NTRB	Nutriband Inc. - Common Stock
PLXS	Plexus Corp. - Common Stock
RPID	Rapid Micro Biosystems, Inc. - Class A Common Stock
SKWD	Skyward Specialty Insurance Group, Inc. - Common Stock
TRAX	First Tracks Biotherapeutics, Inc. - Ordinary Shares
AIFF	Firefly Neuroscience, Inc.  - Common Stock
BLUW	Blue Water Acquisition Corp. III - Class A Ordinary Shares
CHNR	China Natural Resources, Inc. - Common Shares
DYAI	Dyadic International, Inc. - Common Stock
ETO	Eaton Vance Tax-Advantage Global Dividend Opp Common Stock
FROG	JFrog Ltd. - Ordinary shares
GRNQ	Greenpro Capital Corp. - Common Stock
HWM	Howmet Aerospace Inc. Common Stock
IR	Ingersoll Rand Inc. Common Stock
LUNG	Pulmonx Corporation - Common Stock
MMA	Mixed Martial Arts Group Limited Ordinary Shares
NTRP	NextTrip, Inc. - Common Stock
PLYX	Polaryx Therapeutics, Inc. - Common Stock
RPM	RPM International Inc. Common Stock
SKY	Champion Homes, Inc. Common Stock
TRBG	TurboGen Ltd. - Ordinary Shares
AIFU	AIFU Inc. - Class A Ordinary Share
BLX	Bladex, Inc. Class E Common Stock
CHOW	ChowChow Cloud International Holdings Limited Ordinary Shares
DYN	Dyne Therapeutics, Inc. - Common Stock
ETON	Eton Pharmaceuticals, Inc. - Common Stock
FRPH	FRP Holdings, Inc. - Common Stock
GRNT	Granite Ridge Resources, Inc. Common Stock
HXHX	Haoxin Holdings Limited - Class A Ordinary Shares
IRAB	Iris Acquisition Corp II Class A Ordinary Shares
LUNR	Intuitive Machines, Inc. - Class A Common Stock
MMED	MiniMed Group, Inc. - Common Stock
NTRS	Northern Trust Corporation - Common Stock
RPRX	Royalty Pharma plc - Class A Ordinary Shares
SKYA	SkyAI, Inc. - Common Stock
TRC	Tejon Ranch Co Common Stock
AIG	American International Group, Inc. New Common Stock
BLZE	Backblaze, Inc. - Common Stock
CHPG	ChampionsGate Acquisition Corporation - Class A Ordinary Share
DYNC	Dynamix Corporation - Class A Ordinary Share
ETOR	eToro Group Ltd. - Class A Common Shares
FRPT	Freshpet, Inc. - Common Stock
GRO	Brazil Potash Corp. Common Shares
HXL	Hexcel Corporation Common Stock
IRD	Opus Genetics, Inc. - Common Stock
LUV	Southwest Airlines Company Common Stock
MMI	Marcus & Millichap, Inc. Common Stock
NTSK	Netskope, Inc. - Class A Common Stock
PMA	Ming Shing Group Holdings Limited - Ordinary Shares
RPT	Rithm Property Trust Inc. Common stock
SKYE	Skye Bioscience, Inc. - Common Stock
TRDA	Entrada Therapeutics, Inc. - Common Stock
AII	American Integrity Insurance Group, Inc. Common Stock
BLZR	Trailblazer Acquisition Corp. - Class A Ordinary Shares
CHPT	ChargePoint Holdings, Inc. Common Stock
DYOR	Insight Digital Partners II - Class A Ordinary Shares
ETR	Entergy Corporation Common Stock
FRSH	Freshworks Inc. - Class A Common Stock
GROV	Grove Collaborative Holdings, Inc. Class A Common Stock
HY	Hyster-Yale, Inc. Class A common stock
IRDM	Iridium Communications Inc - Common Stock
LVLU	Lulu's Fashion Lounge Holdings, Inc. - Common Stock
MMM	3M Company Common Stock
NTST	NetSTREIT Corp. Common Stock
PMAX	Powell Max Limited - Class A Ordinary Shares
RR	Richtech Robotics Inc. - Class B Common Stock
SKYH	Sky Harbour Group Corporation Class A Common Stock
TREE	LendingTree, Inc. - Common Stock
AIIA	AI Infrastructure Acquisition Corp. Class A Ordinary Shares
BMA	Banco Macro S.A.  ADR (representing Ten Class B Common Shares)
CHR	Cheer Holding, Inc.  - Class A Ordinary Share
ETS	Elite Express Holding Inc. - Class A Common Stock
FRST	Primis Financial Corp. - Common Stock
GROW	U.S. Global Investors, Inc. - Class A Common Stock
HYFM	Hydrofarm Holdings Group, Inc. - Common Stock
IREN	IREN Limited - Ordinary Shares
LVO	LiveOne, Inc. - Common Stock
MMS	Maximus, Inc. Common Stock
NTWK	NETSOL Technologies Inc. - Common Stock
PMCB	PharmaCyte  Biotech, Inc. - Common Stock
RRBI	Red River Bancshares, Inc. - Common Stock
SKYQ	Sky Quarry Inc. - Common Stock
TREO	Tactical Resources Corp. - Common Shares
AIIO	Robo.ai Inc. - Class B Ordinary Shares
BMBL	Bumble Inc. - common stock
CHRD	Chord Energy Corporation - Common Stock
ETSS	Energy Transition Special Opportunities Class A Ordinary Shares
FRT	Federal Realty Investment Trust Common Stock
GROY	Gold Royalty Corp. Common Shares
HYFT	MindWalk Holdings Corp. - Common Stock
IRHO	Iron Horse Acquisitions II Corp. - Common Stock
LVS	Las Vegas Sands Corp. Common Stock
MMSI	Merit Medical Systems, Inc. - Common Stock
NTWO	Newbury Street II Acquisition Corp - Class A Ordinary Shares
PMEC	Primech Holdings Ltd. - Ordinary Shares
RRC	Range Resources Corporation Common Stock
SKYW	SkyWest, Inc. - Common Stock
TREX	Trex Company, Inc. Common Stock
AIIR	Air Global PLC - Ordinary shares
BMEA	Biomea Fusion, Inc. - Common Stock
CHRN	ChronoScale Holdings Corporation - Common Stock
ETSY	Etsy, Inc. Common Stock
FRTT	Fort Technology Inc. - Common Shares
GRPN	Groupon, Inc. - Common Stock
HYLN	Hyliion Holdings Corp. Class A Common Stock
IRIX	IRIDEX Corporation - Common Stock
LVWR	LiveWire Group, Inc. Common Stock
MMTX	Miluna Acquisition Corp - Class A Ordinary Shares
NU	Nu Holdings Ltd. Class A Ordinary Shares
PMI	Picard Medical, Inc. Common Stock
RREV	RRE Ventures Acquisition Corp. - Class A Ordinary Shares
SKYX	SKYX Platforms Corp. - Common Stock
TRGP	Targa Resources, Inc. Common Stock
AIM	AIM ImmunoTech Inc. Common Stock
BMEZ	BlackRock Health Sciences Term Trust Common Shares of Beneficial Interest
CHRS	Coherus Oncology, Inc. - Common Stock
ETX	Eaton Vance Municipal Income 2028 Term Trust Common Shares of Beneficial Interest
FRVO	Fervo Energy Company - Class A common stock
GRRR	Gorilla Technology Group Inc. - Ordinary shares
HYMC	Hycroft Mining Holding Corporation - Class A Common Stock
IRM	Iron Mountain Incorporated (Delaware)Common Stock REIT
LW	Lamb Weston Holdings, Inc. Common Stock 
MMYT	MakeMyTrip Limited - Ordinary Shares
NUAI	New Era Energy & Digital, Inc. - Common Stock
PMN	ProMIS Neurosciences Inc. - Common Shares
RRGB	Red Robin Gourmet Burgers, Inc. - Common Stock
SLAB	Silicon Laboratories, Inc. - Common Stock
TRGS	TRG Latin America Acquisitions Corp. - Class A Ordinary Shares
AIMD	Ainos, Inc. - Common Stock
BMGL	Basel Medical Group Ltd - ordinary shares
CHRW	C.H. Robinson Worldwide, Inc. - Common Stock
EU	enCore Energy Corp. - Common Stock
FSBC	Five Star Bancorp - Common Stock
GRSD	Grandstand Limited - Ordinary Shares
HYNE	Hoyne Bancorp, Inc. - Common Stock
IRMD	iRadimed Corporation - Common Stock
LWAC	LightWave Acquisition Corp. - Class A Ordinary Shares
MNDO	MIND C.T.I. Ltd. - Ordinary Shares
NUCL	Eagle Nuclear Energy Corp. - Common stock
PMT	PennyMac Mortgage Investment Trust Common Shares of Beneficial Interest
RRR	Red Rock Resorts, Inc. - Class A Common Stock
SLB	SLB Limited Common Shares
TRI	Thomson Reuters Corp - Common Shares
AIN	Albany International Corporation Common Stock
BMHL	Bluemount Holdings Limited - Class B Ordinary Shares
CHSN	Chanson International Holding - Class A Ordinary Shares
EUDA	Euda Health Holdings Limited - Ordinary Shares
FSBW	FS Bancorp, Inc. - Common Stock
GRWG	GrowGeneration Corp. - Common Stock
HYPD	Hyperion DeFi, Inc. - Common Stock
IRON	Disc Medicine, Inc. - Common Stock
LWAY	Lifeway Foods, Inc. - Common Stock
MNDR	Mobile-health Network Solutions - Class A Ordinary Shares
NUE	Nucor Corporation Common Stock
PMTR	Perimeter Acquisition Corp. I - Class A Ordinary Shares
RRX	Regal Rexnord Corporation Common Stock
SLBT	SL Science Holding Limited - Ordinary Shares
TRIN	Trinity Capital Inc. Common Stock
AIOS	AIOS Tech Inc. - Class A Common Shares
BMI	Badger Meter, Inc. Common Stock
CHTR	Charter Communications, Inc. - Class A Common Stock
EURK	Eureka Acquisition Corp - Class A Ordinary Share
FSCO	FS Credit Opportunities Corp. Common Stock
GRX	The Gabelli Healthcare & Wellness Trust Common Shares of Beneficial Interest
HYPR	Hyperfine, Inc.  - Class A Common Stock
IRT	Independence Realty Trust, Inc. Common Stock
LWLG	Lightwave Logic, Inc. - Common Stock
MNDY	monday.com Ltd. - Ordinary Shares
NUR	Nuran Wireless Inc. - Common Shares
PMTS	CPI Card Group Inc. - Common Stock
RS	Reliance, Inc. Common Stock
SLDB	Solid Biosciences Inc. - Common Stock
TRIP	TripAdvisor, Inc. - Common Stock
AIOT	PowerFleet, Inc. - Common Stock
BMM	Blue Moon Metals Inc. - Common Shares
CHWY	Chewy, Inc. Class A Common Stock
EVAC	EQV Ventures Acquisition Corp. II Class A Ordinary Shares
FSEA	First Seacoast Bancorp, Inc. - Common Stock
GS	Goldman Sachs Group, Inc. (The) Common Stock
HZO	MarineMax, Inc.  (FL) Common Stock
IRTC	iRhythm Holdings, Inc.  - Common Stock
LXEO	Lexeo Therapeutics, Inc. - Common Stock
MNKD	MannKind Corporation - Common Stock
NUS	Nu Skin Enterprises, Inc. Common Stock
PMVP	PMV Pharmaceuticals, Inc. - Common Stock
RSG	Republic Services, Inc. Common Stock
SLDE	Slide Insurance Holdings, Inc. - Common Stock
TRMB	Trimble Inc. - Common Stock
AIP	Arteris, Inc.  - Common Stock
BMN	BlackRock 2037 Municipal Target Term Trust Common Shares of Beneficial Interest
CHYM	Chime Financial, Inc. - Class A Common Stock
EVC	Entravision Communications Corporation Common Stock
FSHP	Flag Ship Acquisition Corp. - Ordinary Shares
GSAT	Globalstar, Inc. - Common Stock
IRWD	Ironwood Pharmaceuticals, Inc. - Class A Common Stock
LXFR	Luxfer Holdings PLC Ordinary Shares
MNOV	MediciNova, Inc. - Common Stock
NUTX	Nutex Health Inc. - Common Stock
PN	PN Smart Energy Limited - Class A Ordinary Shares
RSI	Rush Street Interactive, Inc. Class A Common Stock
SLDP	Solid Power, Inc. - Class A Common Stock
TRMD	TORM plc - Class A Common Stock
AIR	AAR Corp. Common Stock
BMNR	BitMine Immersion Technologies, Inc. Common Stock
CI	The Cigna Group Common Stock
EVCM	EverCommerce Inc. - Common Stock
FSI	Flexible Solutions International Inc. Common Stock (CDA)
GSBC	Great Southern Bancorp, Inc. - Common Stock
ISBA	Isabella Bank Corporation - Common stock
LXP	LXP Industrial Trust Common Stock (Maryland REIT)
MNPR	Monopar Therapeutics Inc. - Common Stock
NUVB	Nuvation Bio Inc. Class A Common Stock
PNBK	Patriot National Bancorp Inc. - Common Stock
RSKD	Riskified Ltd. Class A Ordinary Shares
SLE	Super League Enterprise, Inc. - Common Stock
TRMK	Trustmark Corporation - Common Stock
AIRE	reAlpha Tech Corp. - Common Stock
BMO	Bank Of Montreal Common Stock
CIA	Citizens, Inc. Class A Common Stock ($1.00 Par)
EVER	EverQuote, Inc. - Class A Common Stock
FSK	FS KKR Capital Corp. Common Stock
GSBD	Goldman Sachs BDC, Inc. Common Stock
ISNR	Snow Rothschild Acquisition Corp. - Class A Ordinary Shares
LXRX	Lexicon Pharmaceuticals, Inc. - Common Stock
MNRO	Monro, Inc.  - Common Stock
NUWE	Nuwellis, Inc. - Common Stock
PNC	PNC Financial Services Group, Inc. (The) Common Stock
RSSS	Research Solutions, Inc - Common Stock
SLF	Sun Life Financial Inc. Common Stock
TRN	Trinity Industries, Inc. Common Stock
AIRG	Airgain, Inc. - Common Stock
BMR	Beamr Imaging Ltd. - Ordinary Share
CIEN	Ciena Corporation Common Stock
EVEX	Eve Holding, Inc. Common Stock
FSLR	First Solar, Inc. - Common Stock
GSHD	Goosehead Insurance, Inc. - Class A Common Stock
ISOU	IsoEnergy Ltd. Common Shares
LXU	LSB Industries, Inc. Common Stock
MNSB	MainStreet Bancshares, Inc. - Common Stock
NVA	Nova Minerals Corp Common Stock
PNFP	Pinnacle Financial Partners, Inc. Common stock
RSVR	Reservoir Media, Inc.. - Common Stock
SLG	SL Green Realty Corp Common Stock
TRNO	Terreno Realty Corporation Common Stock
AIRI	Air Industries Group Common Stock
BMRA	Biomerica, Inc. - Common Stock
CIFR	Cipher Digital Inc. - Common Stock
EVF	Eaton Vance Senior Income Trust Common Stock
FSLY	Fastly, Inc. - Class A Common Stock
GSHR	Gesher Acquisition Corp. II - Class A Ordinary Shares
ISPC	iSpecimen Inc. - Common Stock
LYB	LyondellBasell Industries NV Ordinary Shares Class A (Netherlands)
MNST	Monster Beverage Corporation - Common Stock
NVAX	Novavax, Inc. - Common Stock
PNNT	PennantPark Investment Corporation Common Stock
RTAC	Renatus Tactical Acquisition Corp I - Class A Ordinary Shares
SLGB	Smart Logistics Global Limited - Class A Ordinary Shares
TRNR	Interactive Strength Inc. - Common Stock
AIRJ	AirJoule Technologies Corporation - Class A Common Stock
BMRC	Bank of Marin Bancorp - Common Stock
CIGL	Concorde International Group Ltd - Class A Ordinary Shares
EVGN	Evogene Ltd. - Ordinary Shares
FSM	Fortuna Mining Corp. Common Shares
GSIT	GSI Technology, Inc. - Common Stock
ISPR	Ispire Technology Inc. - Common Stock
LYEL	Lyell Immunopharma, Inc. - Common Stock
MNTK	Montauk Renewables, Inc. - Common Stock
NVCR	NovoCure Limited - Ordinary Shares
PNR	Pentair plc. Ordinary Share
RTB	RTB Digital, Inc. - Common Stock
SLGL	Sol-Gel Technologies Ltd. - Ordinary Shares
TRNS	Transcat, Inc. - Common Stock
AIRO	AIRO Group Holdings, Inc. - Common Stock
BMRN	BioMarin Pharmaceutical Inc. - Common Stock
CIIT	Tianci International, Inc. - Common Stock
EVGO	EVgo Inc. - Common Stock
FSP	Franklin Street Properties Corp. Common Stock
GSIW	Garden Stage Limited - Class A Ordinary Shares
ISRG	Intuitive Surgical, Inc. - Common Stock
LYFT	Lyft, Inc. - Class A Common Stock
MNTN	MNTN, Inc. Class A Common Stock
NVCT	Nuvectis Pharma, Inc. - Common Stock
PNRG	PrimeEnergy Resources Corporation - Common Stock
SLGN	Silgan Holdings Inc. Common Stock
TRON	Tron Inc. - Common Stock
AIRS	AirSculpt Technologies, Inc. - Common Stock
BMY	Bristol-Myers Squibb Company Common Stock
CIM	Chimera Investment Corporation Common Stock
EVH	Evolent Health, Inc Class A Common Stock
FSS	Federal Signal Corporation Common Stock
GSL	Global Ship Lease Inc New Class A Common Shares
ISTR	Investar Holding Corporation - Common Stock
LYNX	Lyntris Inc. Common Stock
MNTS	Momentus Inc. - Class A Common Stock
PNTG	The Pennant Group, Inc. - Common Stock
RUBI	Rubico Inc. - Common Stock
SLI	Standard Lithium Ltd. Common Shares
TROO	TROOPS, Inc.  - Ordinary Shares
AIRT	Air T, Inc. - Common Stock
BNAI	Brand Engagement Network Inc. - Common Stock
CINF	Cincinnati Financial Corporation - Common Stock
EVI	EVI Industries, Inc.  Common Stock
FSTR	L.B. Foster Company - Common Stock
GSM	Ferroglobe PLC - Ordinary Shares
IT	Gartner, Inc. Common Stock
LYTS	LSI Industries Inc. - Common Stock
MNY	MoneyHero Limited - Class A Ordinary Shares
NVEC	NVE Corporation - Common Stock
PNW	Pinnacle West Capital Corporation Common Stock
RUM	RUM Group Inc. - Class A Common Stock
SLM	SLM Corporation - Common Stock
TROW	T. Rowe Price Group, Inc. - Common Stock
AISP	Airship AI Holdings, Inc - Class A Common Stock
BNC	CEA Industries Inc. - Common Stock
CING	Cingulate Inc. - Common Stock
EVLV	Evolv Technologies Holdings, Inc. - Class A Common Stock
FSUN	FirstSun Capital Bancorp - Common Stock
GSRF	GSR IV Acquisition Corp. - Class A ordinary share
ITG	ITG, Inc. - Class A Common Stock
LYV	Live Nation Entertainment, Inc. Common Stock
MOB	Mobilicom Limited - Ordinary Shares
NVGS	Navigator Holdings Ltd. Ordinary Shares (Marshall Islands)
POAS	Phaos Technology Holdings (Cayman) Limited Class A Ordinary Shares
RUN	Sunrun Inc. - Common Stock
SLMT	Brera Holdings PLC - Class B Ordinary Shares
TROX	Tronox Holdings plc Ordinary Shares (UK)
AIT	Applied Industrial Technologies, Inc. Common Stock
BNED	Barnes & Noble Education, Inc Common Stock
CINT	CI&T Inc Class A Common Shares
EVMN	Evommune, Inc. Common Stock
FSV	FirstService Corporation - Common Shares
GSRV	GSR V Acquisition Corp. - Class A ordinary shares
ITGR	Integer Holdings Corporation Common Stock
LZ	LegalZoom.com, Inc. - Common Stock
MOBI	Mobia Medical, Inc. - Common Stock
NVMI	Nova Ltd. - Ordinary Shares
POCI	Precision Optics Corporation, Inc. - Common stock
RUSHA	Rush Enterprises, Inc. - Class A Common Stock
SLND	Southland Holdings, Inc. Common Stock
TRP	TC Energy Corporation Common Stock
AIV	Apartment Investment and Management Company Common Stock
BNGO	Bionano Genomics, Inc. - Common Stock
CION	CION Investment Corporation Common Stock
EVN	Eaton Vance Municipal Income Trust Common Stock
FT	Franklin Universal Trust Common Stock
GSUN	Golden Sun Technology Group Limited - Class A Ordinary Shares
ITHA	ITHAX Acquisition Corp III - Class A Ordinary Shares
LZB	La-Z-Boy Incorporated Common Stock
MOBX	Mobix Labs, Inc. - Class A Common Stock
NVNI	Nvni Group Limited - Ordinary Shares
PODC	PodcastOne, Inc. - Common Stock
RUSHB	Rush Enterprises, Inc. - Class B Common Stock
SLNG	Stabilis Solutions, Inc. - Common Stock
TRS	TriMas Corporation - Common Stock
AIXC	AIxCrypto Holdings, Inc. - Common Stock
BNKK	Bonk, Inc. - Common Stock
CIRC	Circle8 Group, Inc. - Common Stock
EVOX	Evolution Global Acquisition Corp - Class A Ordinary Shares
FTAI	FTAI Aviation Ltd. - Common Stock
GT	The Goodyear Tire & Rubber Company - Common Stock
ITIC	Investors Title Company - Common Stock
LZM	Lifezone Metals Limited Ordinary Shares
MOD	Modine Manufacturing Company Common Stock
NVNO	enVVeno Medical Corporation - Common Stock
PODD	Insulet Corporation - Common Stock
RVLV	Revolve Group, Inc. Class A Common Stock
SLNH	Soluna Holdings, Inc. - Common Stock
TRSG	Tungray Technologies Inc - Class A Ordinary Shares
AIZ	Assurant, Inc. Common Stock
BNL	Broadstone Net Lease, Inc. Common Stock
CISO	CISO Global, Inc. - Common Stock
EVR	Evercore Inc. Class A Common Stock
FTCI	FTC Solar, Inc. - Common Stock
GTBP	GT Biopharma, Inc. - Common Stock
ITOC	iTonic Holdings Ltd - Class A Ordinary Shares
LZMH	LZ Technology Holdings Limited - Class B Ordinary Shares
MODD	Modular Medical, Inc. - common stock
NVO	Novo Nordisk A/S Common Stock
POET	POET Technologies Inc. - Common Shares
RVMD	Revolution Medicines, Inc. - Common Stock
SLP	Simulations Plus, Inc. - Common Stock
TRST	TrustCo Bank Corp NY - Common Stock
AJG	Arthur J. Gallagher & Co. Common Stock
BNS	Bank Nova Scotia Halifax Pfd 3 Ordinary Shares
CISS	C3is Inc. - Common Stock
EVRG	Evergy, Inc. - Common Stock
FTDR	Frontdoor, Inc. - Common Stock
GTE	Gran Tierra Energy Inc. Common Stock
ITP	IT Tech Packaging, Inc. Common Stock
MOG-A	Moog Inc. Class A Common Stock
NVR	NVR, Inc. Common Stock
POLA	Polar Power, Inc. - Common Stock
RVP	Retractable Technologies, Inc. Common Stock
SLQT	SelectQuote, Inc. Common Stock
TRT	Trio-Tech International Common Stock
AKA	a.k.a. Brands Holding Corp. Common Stock
BNTC	Benitec Biopharma Inc. - Common Stock
CITR	CitroTech Inc. Common Stock
EVTC	Evertec, Inc. Common Stock
FTEK	Fuel Tech, Inc. - Common Stock
GTEC	Greenland Technologies Holding Corporation - Class A Ordinary Shares
ITRG	Integra Resources Corp. Common Shares
MOG-B	Moog Inc. Class B Common Stock
NVRI	Enviri Corporation Common Stock
POLE	Andretti Acquisition Corp. II - Class A Ordinary Shares
RVSB	Riverview Bancorp Inc - Common Stock
SLS	SELLAS Life Sciences Group, Inc.  - Common Stock
TRTX	TPG RE Finance Trust, Inc. Common Stock
AKAM	Akamai Technologies, Inc. - Common Stock
BNY	The Bank of New York Mellon Corporation Common Stock
CIVB	Civista Bancshares, Inc.  - Common Stock
EVTL	Vertical Aerospace Ltd. Ordinary Shares
FTF	Franklin Limited Duration Income Trust Common Shares of Beneficial Interest
GTEN	Gores Holdings X, Inc. - Class A ordinary shares
ITRI	Itron, Inc. - Common Stock
MOH	Molina Healthcare Inc Common Stock
NVS	Novartis AG Common Stock
PONO	Pono Capital Four, Inc. - Class A Ordinary Shares
RVSN	Rail Vision Ltd. - Ordinary Shares
SLSN	Solesence, Inc. - Common stock
TRU	TransUnion Common Stock
AKAN	Akanda Corp. - Common Shares
BOBS	Bob's Discount Furniture, Inc. Common Stock
CIX	CompX International Inc. Common Stock
EW	Edwards Lifesciences Corporation Common Stock
FTFT	Future FinTech Group Inc. - Common Stock
GTERA	Globa Terra Acquisition Corporation - Class A Ordinary Shares
ITRN	Ituran Location and Control Ltd. - Ordinary Shares
MORN	Morningstar, Inc. - Common Stock
NVST	Envista Holdings Corporation Common Stock
POOL	Pool Corporation - Common Stock
RVT	Royce Small-Cap Trust, Inc. Common Stock
SLSR	Solaris Resources Inc. Common Shares
TRUG	TruGolf Holdings, Inc. - Class A Common Stock
AKBA	Akebia Therapeutics, Inc. - Common Stock
BOC	Boston Omaha Corporation Class A Common Stock
CJMB	Callan JMB Inc. - Common Stock
EWAV	East West Ave Acquisition Corp. - Common Stock
FTH	Faeth Therapeutics, Inc.  - Common Stock
GTES	Gates Industrial Corporation Ltd. Common Shares
ITT	ITT Inc. Common Stock 
MOS	Mosaic Company (The) Common Stock
NVT	nVent Electric plc Ordinary Shares 
POR	Portland General Electric Co Common Stock
RVTY	Revvity, Inc. Common Stock
SLVM	Sylvamo Corporation Common Stock
TRUP	Trupanion, Inc. - Common Stock
AKO-A	Embotelladora Andina S.A. Common Stock
BODI	The Beachbody Company, Inc. - Class A Common Stock
CKX	CKX Lands, Inc. Common Stock
EWBC	East West Bancorp, Inc. - Common Stock
FTHA	Forefront Tech Holdings Acquisition Corp - Class A Ordinary Shares
GTIM	Good Times Restaurants Inc. - Common Stock
ITW	Illinois Tool Works Inc. Common Stock
MOV	Movado Group Inc. Common Stock
NVTS	Navitas Semiconductor Corporation - Common Stock
POST	Post Holdings, Inc. Common Stock
RWAY	Runway Growth Finance Corp. - Common Stock
SLXN	Silexion Therapeutics Corp - Ordinary Shares
TRV	The Travelers Companies, Inc. Common Stock
AKO-B	Embotelladora Andina S.A. Common Stock
BOE	Blackrock Enhanced Global Dividend Trust Common Shares of Beneficial Interest
CL	Colgate-Palmolive Company Common Stock
EWTX	Edgewise Therapeutics, Inc. - Common Stock
FTHM	Fathom Holdings Inc. - Common Stock
GTLB	GitLab Inc. - Class A Common Stock
IVDA	Iveda Solutions, Inc. - Common Stock
MOVE	Corvex, Inc. - Common Stock
NWAX	New America Acquisition I Corp. Class A Common Stock
POWI	Power Integrations, Inc. - Common Stock
RWT	Redwood Trust, Inc. Common Stock
SM	SM Energy Company Common Stock
TRVI	Trevi Therapeutics, Inc. - Common Stock
AKR	Acadia Realty Trust Common Stock
BOF	BranchOut Food Inc. - Common Stock
CLAR	Clarus Corporation - Common Stock
EXC	Exelon Corporation - Common Stock
FTI	TechnipFMC plc Ordinary Share
GTM	ZoomInfo Technologies Inc. - Common Stock
IVF	INVO Fertility, Inc. - Common Stock
MP	MP Materials Corp. Common Stock
NWBI	Northwest Bancshares, Inc. - Common Stock
POWL	Powell Industries, Inc. - Common Stock
RXO	RXO, Inc. Common Stock
SMA	SmartStop Self Storage REIT, Inc. Common Stock
TRX	TRX Gold Corporation Common Stock
AKTS	Aktis Oncology, Inc. - Common stock
BOH	Bank of Hawaii Corporation Common Stock
CLB	Core Laboratories Inc. Common Stock
EXE	Expand Energy Corporation - Common Stock
FTK	Flotek Industries, Inc. Common Stock
GTN	Gray Media, Inc. Common Stock
IVR	INVESCO MORTGAGE CAPITAL INC Common Stock
MPAA	Motorcar Parts of America, Inc. - Common Stock
NWE	NorthWestern Energy Group, Inc.  - Common Stock
POWW	Outdoor Holding Company - Common Stock
RXRX	Recursion Pharmaceuticals, Inc. - Class A Common Stock
SMBC	Southern Missouri Bancorp, Inc. - Common Stock
TSAT	Telesat Corporation - Class A Common Shares and Class B Variable Voting Shares
ALAB	Astera Labs, Inc. - Common Stock
BOKF	BOK Financial Corporation - Common Stock
CLBK	Columbia Financial, Inc. - Common Stock
EXEL	Exelixis, Inc. - Common Stock
FTLF	FitLife Brands, Inc. - Common Stock
GTN-A	Gray Media, Inc. Class A Common Stock
IVT	InvenTrust Properties Corp. Common Stock
MPB	Mid Penn Bancorp - Common Stock
NWFL	Norwood Financial Corp. - Common Stock
PPC	Pilgrim's Pride Corporation - Common Stock
RXST	RxSight, Inc. - Common Stock
SMBK	SmartFinancial, Inc. Common Stock
TSBK	Timberland Bancorp, Inc. - Common Stock
ALB	Albemarle Corporation Common Stock
BOLD	Boundless Bio, Inc. - Common Stock
CLBR	Colombier Acquisition Corp. III Class A Ordinary Shares
EXFY	Expensify, Inc. - Class A Common Stock
FTNT	Fortinet, Inc. - Common Stock
GTX	Garrett Motion Inc. - Common Stock
IVVD	Invivyd, Inc. - Common Stock
MPC	Marathon Petroleum Corporation Common Stock
NWL	Newell Brands Inc. - Common Stock
PPCB	Propanc Biopharma, Inc. - Common Stock
RXT	Rackspace Technology, Inc. - Common Stock
SMC	Summit Midstream Corporation Common Stock
TSCO	Tractor Supply Company - Common Stock
ALC	Alcon Inc. Ordinary Shares
BOLT	Bolt Biotherapeutics, Inc. - Common Stock
CLBT	Cellebrite DI Ltd. - Ordinary Shares
EXK	Endeavour Silver Corporation Ordinary Shares (Canada)
FTRA	FutureCorp Space Acquisition 1 Class A Ordinary Shares
GTY	Getty Realty Corporation Common Stock
IVZ	Invesco Ltd Common Stock
MPLT	MapLight Therapeutics, Inc. - Common Stock
NWN	Northwest Natural Holding Company Common Stock
PPG	PPG Industries, Inc. Common Stock
RY	Royal Bank Of Canada Common Stock
SMCI	Super Micro Computer, Inc. - Common Stock
TSEM	Tower Semiconductor Ltd. - Ordinary Shares
ALCO	Alico, Inc. - Common Stock
BON	Bon Natural Life Limited - Class A Ordinary Shares
CLDI	Calidi Biotherapeutics, Inc. Common Stock
EXLS	ExlService Holdings, Inc. - Common Stock
FTRE	Fortrea Holdings Inc. - Common Stock
GUAC	Berto Acquisition Corp. II - Ordinary Shares
IXHL	Incannex Healthcare Inc. - Common Stock
MPT	Medical Properties Trust, Inc. common stock
NWPX	NWPX Infrastructure, Inc. - Common Stock
PPHC	Public Policy Holding Company, Inc. - Common Stock
RYAM	Rayonier Advanced Materials Inc. Common Stock
SMG	Scotts Miracle-Gro Company (The) Common Stock
TSHA	Taysha Gene Therapies, Inc. - Common Stock
ALDF	Aldel Financial II Inc. - Class A Ordinary Shares
BOOM	DMC Global Inc. - Common Stock
CLDT	Chatham Lodging Trust (REIT) Common Shares of Beneficial Interest
EXOD	Exodus Movement, Inc. Class A Common Stock
FTS	Fortis Inc. Common Shares
GURE	Gulf Resources, Inc. - Common Stock
IZEA	IZEA Worldwide, Inc. - Common Stock
MPTI	M-tron Industries, Inc. Common Stock
NWS	News Corporation - Class B Common Stock
PPIH	Perma-Pipe International Holdings, Inc. - Common Stock
RYAN	Ryan Specialty Holdings, Inc. Class A Common Stock
SMHI	SEACOR Marine Holdings Inc. Common Stock 
ALDX	Aldeyra Therapeutics, Inc. - Common Stock
BOOT	Boot Barn Holdings, Inc. Common Stock
CLDX	Celldex Therapeutics, Inc. - Common Stock
EXOZ	eXoZymes Inc. - Common Stock
FTV	Fortive Corporation Common Stock 
GUT	Gabelli Utility Trust (The) Common Stock
IZM	ICZOOM Group Inc. - Class A Ordinary Shares
MPU	Mega Matrix Inc. Class A Ordinary Shares
NWSA	News Corporation - Class A Common Stock
PPL	PPL Corporation Common Stock
RYDE	Ryde Group Ltd. Class A Ordinary Shares
SMID	Smith-Midland Corporation - Common Stock
TSLX	Sixth Street Specialty Lending, Inc. Common Stock
ALEC	Alector, Inc. - Common Stock
BORR	Borr Drilling Limited Common Shares
CLF	Cleveland-Cliffs Inc. Common Stock
EXP	Eagle Materials Inc Common Stock
FTW	Presidio Production Company Class A Common Stock
GUTS	Fractyl Health, Inc. - Common Stock
MPV	Barings Participation Investors Common Stock
NWTG	Newton Golf Company, Inc. - Common Stock
PPLI	People Incorporated - Common Stock
RYET	Ruanyun Edai Technology Inc. - Ordinary shares
SMJF	SMJ International Holdings Inc. Class A Ordinary Shares
TSN	Tyson Foods, Inc. Common Stock
ALF	Centurion Acquisition Corp. - Class A Ordinary Shares
BOSC	B.O.S. Better Online Solutions - Ordinary Shares
CLFD	Clearfield, Inc. - Common Stock
EXPD	Expeditors International of Washington, Inc. Common Stock
FUBO	FuboTV Inc. Class A Common Stock
GVA	Granite Construction Incorporated Common Stock
MPWR	Monolithic Power Systems, Inc. - Common Stock
NX	Quanex Building Products Corporation Common Stock
PPSI	Pioneer Power Solutions, Inc. - Common Stock
RYM	RYTHM, Inc. - Common Stock
SMMT	Summit Therapeutics Inc.  - Common Stock
TSQ	Townsquare Media, Inc. Class A Common Stock
ALG	Alamo Group, Inc. Common Stock
BOT	RoboStrategy, Inc. - Common Stock
CLGN	CollPlant Biotechnologies Ltd. - Ordinary Shares
EXPE	Expedia Group, Inc. - Common Stock
FUFU	BitFuFu Inc. - Class A Ordinary Shares
GWAV	Greenwave Technology Solutions, Inc. - Common Stock
MQ	Marqeta, Inc. - Class A Common Stock
NXAT	Nexus Advanced Technologies Inc. - Ordinary Shares
PPTA	Perpetua Resources Corp. - Common Shares
RYN	Rayonier Inc. REIT Common Stock
SMP	Standard Motor Products, Inc. Common Stock
TSSI	TSS, Inc. - Common Stock
ALGM	Allegro MicroSystems, Inc. - Common Stock
BOTJ	Bank of the James Financial Group, Inc. - Common Stock
CLH	Clean Harbors, Inc. Common Stock
EXPO	Exponent, Inc. - Common Stock
FUL	H. B. Fuller Company Common Stock
GWH	ESS Tech, Inc. Common Stock
MRAM	Everspin Technologies, Inc. - Common Stock
NXDR	Nextdoor Holdings, Inc. Class A Common Stock
PR	Permian Resources Corporation Class A Common Stock
RYOJ	rYojbaba Co., Ltd. - Common Shares
SMPL	The Simply Good Foods Company - Common Stock
TTAM	Titan America SA Common Shares
ALGN	Align Technology, Inc. - Common Stock
BOW	Bowhead Specialty Holdings Inc. Common Stock
CLIK	Click Holdings Limited - Ordinary Share
EXR	Extra Space Storage Inc Common Stock
FULC	Fulcrum Therapeutics, Inc. - Common Stock
GWRE	Guidewire Software, Inc. Common Stock
MRBK	Meridian Corporation - Common Stock
NXDT	NexPoint Diversified Real Estate Trust Common Stock
PRAA	PRA Group, Inc. - Common Stock
RYTM	Rhythm Pharmaceuticals, Inc. - Common Stock
SMR	NuScale Power Corporation Class A Common Stock
TTAN	ServiceTitan, Inc. - Class A Common Stock
ALGS	Aligos Therapeutics, Inc. - Common stock
BOX	Box, Inc. Class A Common Stock
CLIR	ClearSign Technologies Corporation - Common Stock
EXTR	Extreme Networks, Inc. - Common Stock
FULT	Fulton Financial Corporation - Common Stock
GWRS	Global Water Resources, Inc. - common stock
MRCO	Mercator Acquisition Corp. - Class A Ordinary Shares
NXE	Nexgen Energy Ltd. Common Shares
PRAX	Praxis Precision Medicines, Inc. - Common Stock
RYZ	Ryerson Holding Corporation Common Stock
SMRT	SmartRent, Inc. Class A Common Stock
TTC	Toro Company (The) Common Stock
ALGT	Allegiant Travel Company - Common Stock
BOXL	Boxlight Corporation - Class A Common Stock
CLMB	Climb Global Solutions, Inc. - Common Stock
EXYN	Exyn Technologies, Inc. - Common Stock
FUN	Six Flags Entertainment Corporation Common Stock New
GWW	W.W. Grainger, Inc. Common Stock
MRCY	Mercury Systems Inc - Common Stock
NXGL	NexGel, Inc - Common Stock
PRCH	Porch Group, Inc. - Common Stock
RZLT	Rezolute, Inc. - Common Stock (NV)
SMSI	Smith Micro Software, Inc. - Common Stock
TTD	The Trade Desk, Inc. - Class A Common Stock
ALH	Alliance Laundry Holdings Inc. Common Stock
BP	BP p.l.c. Common Stock
CLMT	Calumet, Inc - Common Stock
EYE	National Vision Holdings, Inc. - Common Stock
FUNC	First United Corporation - Common Stock
GXAI	Gaxos.ai Inc. - Common Stock
MRDN	Meridian Holdings Inc. - Common Stock
NXH	Neighborhood Intelligence, Inc.  - Common Stock
PRCT	PROCEPT BioRobotics Corporation - Common Stock
RZLV	Rezolve AI PLC - Ordinary Shares
SMTC	Semtech Corporation - Common Stock
TTE	TotalEnergies SE Ordinary Shares
ALHC	Alignment Healthcare, Inc. - Common Stock
BPAC	Blueport Acquisition Ltd - Class A Ordinary Shares
CLNE	Clean Energy Fuels Corp. - Common Stock
EYPT	EyePoint, Inc. - Common Stock
FURY	Fury Gold Mines Limited Common Shares
GXO	GXO Logistics, Inc. Common Stock 
NXL	Nexalin Technology, Inc. - Common Stock
PRDO	Perdoceo Education Corporation - Common Stock
SMTI	Sanara MedTech Inc. - Common Stock
TTEC	TTEC Holdings, Inc. - Common Stock
ALIS	Calisa Acquisition Corp - Ordinary shares
BPOP	Popular, Inc. - Common Stock
CLNN	Clene Inc. - Common Stock
EZGO	EZGO Technologies Ltd. - Ordinary Shares
FUSB	First US Bancshares, Inc. - Common Stock
GYGY	Game Your Game, Inc. - Common Stock
MRKR	Marker Therapeutics, Inc. - Common Stock
NXP	Nuveen Select Tax Free Income Portfolio Common Stock
PRE	Prenetics Global Limited - Class A Ordinary Share
SMTK	SmartKem, Inc. - Common Stock
TTEK	Tetra Tech, Inc. - Common Stock
ALIT	Alight, Inc. Class A Common Stock
BPRN	Princeton Bancorp, Inc. - Common Stock
CLOV	Clover Health Investments, Corp.  - Class A Common stock
EZPW	EZCORP, Inc. - Class A Non-Voting Common Stock
FUSE	Fusemachines Inc. - Common stock
GYRE	Gyre Therapeutics, Inc. - Common Stock
MRLN	Merlin, Inc. - Common Stock
NXPI	NXP Semiconductors N.V. - Common Stock
PRFX	PRF Technologies Ltd. - Ordinary Shares
SMWB	Similarweb Ltd. Ordinary Shares
TTGT	TechTarget, Inc. - Common Stock
ALK	Alaska Air Group, Inc. Common Stock
BQ	Boqii Holding Limited Class A Ordinary Shares
CLPR	Clipper Realty Inc. Common Stock
EZRA	Reliance Global Group, Inc. - Common Stock
FVAV	Fortress Value Acquisition Corp. V - Class A Ordinary Shares
GYRO	Gyrodyne , LLC - Common Stock
MRNA	Moderna, Inc. - Common Stock
NXPL	NextPlat Corp - Common Stock
PRG	PROG Holdings, Inc. Common Stock
SMX	SMX (Security Matters) Public Limited Company - Ordinary Shares
TTI	Tetra Technologies, Inc. Common Stock
ALKS	Alkermes plc - Ordinary Shares
BR	Broadridge Financial Solutions, Inc. Common Stock
CLPS	CLPS Incorporation - Common Stock
FVCB	FVCBankcorp, Inc. - Common Stock
MRNO	Murano Global Investments PLC - Ordinary Shares
NXRT	NexPoint Residential Trust, Inc. Common Stock
PRGO	Perrigo Company plc Ordinary Shares
SMXT	Solarmax Technology Inc. - Common Stock
TTMI	TTM Technologies, Inc. - Common Stock
ALKT	Alkami Technology, Inc. - Common Stock
BRAG	Bragg Gaming Group Inc. - Common Shares
CLPT	ClearPoint Neuro Inc. - Common Stock
FVN	Future Vision II Acquisition Corporation - Ordinary Shares
MRP	Millrose Properties, Inc. Class A Common Stock
NXST	Nexstar Media Group, Inc. - Common Stock
PRGS	Progress Software Corporation - Common Stock
SN	SharkNinja, Inc. Ordinary Shares
TTRX	Turn Therapeutics Inc. - Common Stock
ALL	Allstate Corporation (The) Common Stock
BRAI	Braiin Limited - Common Stock
CLRB	Cellectar Biosciences, Inc. - Common Stock
FVR	FrontView REIT, Inc. Common Stock
MRSH	Marsh Common Stock
NXT	Nextpower Inc. - Common Stock
PRHI	Presurance Holdings, Inc. - Common Stock
SNA	Snap-On Incorporated Common Stock
TTWO	Take-Two Interactive Software, Inc. - Common Stock
ALLE	Allegion plc Ordinary Shares
BRBR	BellRing Brands, Inc. Common Stock 
CLRO	ClearOne, Inc. - Common Stock
FVRR	Fiverr International Ltd. Ordinary Shares, no par value
MRT	Marti Technologies, Inc. Class A Ordinary Shares
NXTC	NextCure, Inc. - Common Stock
PRI	Primerica, Inc. Common Stock
SNAL	Snail, Inc. - Class A Common Stock
TU	Telus Corporation Ordinary Shares
ALLO	Allogene Therapeutics, Inc. - Common Stock
BRBS	Blue Ridge Bankshares, Inc. Common Stock
CLS	Celestica, Inc. Common Stock
FWAC	Futurewave Acquisition Corporation - Ordinary Shares
MRTN	Marten Transport, Ltd. - Common Stock
NXTS	Nexentis Technologies Inc. - Common Stock
PRIM	Primoris Services Corporation Common Stock
SNAP	Snap Inc. Class A Common Stock
TULP	Bloomia Holdings, Inc. - Common Stock
ALLR	Allarity Therapeutics, Inc. - Common stock
BRC	Brady Corporation Common Stock
CLSK	CleanSpark, Inc. - Common Stock
FWDI	Forward Industries, Inc. - Common Stock
MRVI	Maravai LifeSciences Holdings, Inc. - Class A common stock
NXTT	Next Technology Holding Inc. - Ordinary Shares
PRK	Park National Corporation Common Stock
SND	Smart Sand, Inc. - Common Stock
TUSK	Mammoth Energy Services, Inc. - Common Stock
ALLT	Allot Ltd. - Ordinary Shares
BRCB	Black Rock Coffee Bar, Inc. - Class A Common Stock
CLST	Catalyst Bancorp, Inc. - common stock
FWONA	Liberty Media Corporation - Series A Liberty Formula One Common Stock
MRVL	Marvell Technology, Inc. - Common Stock
NXXT	NextNRG, Inc. - Common Stock
PRKS	United Parks & Resorts Inc. Common Stock
SNDA	Sonida Senior Living, Inc. Common Stock
TV	Grupo Televisa S.A.B. Common Stock
ALLY	Ally Financial Inc. Common Stock
BRCC	BRC Inc. Class A Common Stock
CLVT	Clarivate Plc Ordinary Shares
FWONK	Liberty Media Corporation - Series C Liberty Formula One Common Stock
MRX	Marex Group Limited - Ordinary Shares
NYAX	Nayax Ltd. - Ordinary Shares
PRLB	Proto Labs, Inc. Common stock
SNDK	Sandisk Corporation - Common Stock When-Issued
TVA	Texas Ventures Acquisition III Corp - Class A Ordinary Share
ALM	Almonty Industries Inc. - Common Shares
BREZ	Breeze Acquisition Corp. II - Ordinary Shares
CLW	Clearwater Paper Corporation Common Stock
FWRD	Forward Air Corporation - Common Stock
MS	Morgan Stanley Common Stock
NYC	American Strategic Investment Co. Class A Common Stock
PRLD	Prelude Therapeutics Incorporated - Common Stock
SNDL	SNDL Inc. - Common Shares
TVAI	Thayer Ventures Acquisition Corporation II - Class A Ordinary Shares
ALMR	Alamar Biosciences, Inc. - Class A common stock
BRFH	Barfresh Food Group Inc. - Common Stock
CLWT	Euro Tech Holdings Company Limited - Ordinary Shares
FWRG	First Watch Restaurant Group, Inc. - Common Stock
MSA	MSA Safety Incorporated Common Stock
NYT	New York Times Company (The) Common Stock
PRM	Perimeter Solutions, SA Common Stock
SNDR	Schneider National, Inc. Common Stock
TVC	Tennessee Valley Authority Common Stock
ALMS	Alumis Inc. - Common Stock
BRIA	BrilliA Inc Class A Ordinary Shares
CLX	Clorox Company (The) Common Stock
FXAC	FortuneX Acquisition Corporation - Ordinary shares
MSAI	MultiSensor AI Holdings, Inc. - Common Stock
NYXH	Nyxoah SA - Ordinary Shares
PRMB	Primo Brands Corporation Class A Common Stock
SNDX	Syndax Pharmaceuticals, Inc. - Common Stock
TVGN	Tevogen Inc. - Common Stock
ALMU	Aeluma, Inc. - Common Stock
BRID	Bridgford Foods Corporation - Common Stock
CLYM	Climb Bio, Inc. - Common Stock
FXHO	UTime Limited - Class A Ordinary Shares
MSB	Mesabi Trust Common Stock
PRME	Prime Medicine, Inc. - Common Stock
SNES	SenesTech, Inc. - Common Stock
TVIV	Texas Ventures Acquisition IV Corp - Class A Ordinary Shares
ALNT	Allient Inc. - Common Stock
BRK-A	Berkshire Hathaway Inc. Common Stock
CM	Canadian Imperial Bank of Commerce Common Stock
FXNC	First National Corporation - Common Stock
MSBI	Midland States Bancorp, Inc. - Common Stock
PROF	Profound Medical Corp. - common stock
SNEX	StoneX Group Inc. - Common Stock
TVRD	Tvardi Therapeutics, Inc. - Common Stock
ALNY	Alnylam Pharmaceuticals, Inc. - Common Stock
CMBT	CMB.TECH NV Ordinary Shares
MSCI	MSCI Inc. Common Stock
PROK	ProKidney Corp. - Class A Ordinary Shares
SNFCA	Security National Financial Corporation - Class A Common Stock
TVTX	Travere Therapeutics, Inc. - Common Stock
ALOV	Aldabra 4 Liquidity Opportunity Vehicle, Inc. - Class A Ordinary Shares
BRKH	Burtech Acquisition Corp II - Class A Ordinary Shares
CMC	Commercial Metals Company Common Stock
MSEX	Middlesex Water Company - Common Stock
PROP	Prairie Operating Co. - Common Stock
SNGX	Soligenix, Inc. - Common Stock
TW	Tradeweb Markets Inc. - Class A Common Stock
ALOY	REalloys Inc. - Common Stock
BRKR	Bruker Corporation - Common Stock
CMCL	Caledonia Mining Corporation Plc Common Shares
PROV	Provident Financial Holdings, Inc. - Common Stock
SNN	Smith & Nephew SNATS, Inc. Common Stock
TWAV	TaoWeave, Inc. - Common Stock
ALP	Alpha Compute Corp  - Ordinary Shares
BRLS	Borealis Foods Inc. - Class A Common Shares
CMCO	Columbus McKinnon Corporation - Common Stock
MSGE	Madison Square Garden Entertainment Corp. Class A Common Stock
PRPL	Purple Innovation, Inc. - Common Stock
SNOA	Sonoma Pharmaceuticals, Inc. - Common Stock
TWFG	TWFG, Inc. - Common Stock
ALPS	ALPS Group Inc - Ordinary Share
BRLT	Brilliant Earth Group, Inc. - Class A Common Stock
CMCSA	Comcast Corporation - Class A Common Stock
MSGM	Motorsport Games Inc. - Class A Common Stock
PRPO	Precipio, Inc. - Common Stock
SNOW	Snowflake Inc. Common Stock
TWG	Top Wealth Group Holding Limited - Class A Ordinary Shares
ALPX	Alpex Acquisition Corporation - Class A Ordinary Shares
BRN	Barnwell Industries, Inc. Common Stock
CMCT	Creative Media  - Common Stock
MSGS	Madison Square Garden Sports Corp. Class A Common Stock (New)
PRQR	ProQR Therapeutics N.V. - Ordinary Shares
SNPS	Synopsys, Inc. - Common Stock
TWI	Titan International, Inc. (DE) Common Stock
ALRM	Alarm.com Holdings, Inc. - Common Stock
BRNX	BrenX Ltd. - Ordinary Shares
CMDB	Costamare Bulkers Holdings Limited Common Stock
MSGY	Masonglory Limited - Class A Ordinary Shares
PRSO	Peraso Inc. - Common Stock
SNSC	SunScout Holding Limited Class A Ordinary Shares
TWIN	Twin Disc, Incorporated - Common Stock
ALRS	Alerus Financial Corporation - Common Stock
BRO	Brown & Brown, Inc. Common Stock
CME	CME Group Inc. - Class A Common Stock
MSI	Motorola Solutions, Inc. Common Stock
PRSU	Pursuit Attractions and Hospitality, Inc. Common Stock
SNT	Senstar Technologies Corporation - Common Shares
TWLO	Twilio Inc. Class A Common Stock
ALSN	Allison Transmission Holdings, Inc. Common Stock
BROS	Dutch Bros Inc. Class A Common Stock
CMG	Chipotle Mexican Grill, Inc. Common Stock
MSLE	Satellos Bioscience Inc. - Common Stock
PRTA	Prothena Corporation plc - Ordinary Shares
SNTG	Sentage Holdings Inc. - Class A Ordinary Shares
TWLV	Twelve Seas Investment Company III - Class A Ordinary Shares
ALT	Altimmune, Inc. - Common Stock
BRR	ProCap Financial, Inc. - Common Stock
CMI	Cummins Inc. Common Stock
MSM	MSC Industrial Direct Company, Inc. Common Stock
PRTH	Priority Technology Holdings, Inc. - Common Stock
SNTI	Senti Biosciences Holdings, Inc. - Common Stock
TWST	Twist Bioscience Corporation - Common Stock
ALTG	Alta Equipment Group Inc. Class A Common Stock
BRSL	Brightstar Lottery PLC Trading under the Legal Name to begin at the market open on July 21, 2025. Ordinary Shares
CMND	Clearmind Medicine Inc. - Common Shares
MSN	Emerson Radio Corporation Common Stock
PRTS	CarParts.com, Inc. - Common Stock
SNWV	SANUWAVE Health, Inc. - Common Stock
TXG	10x Genomics, Inc. - Common Stock
ALTI	AlTi Global, Inc. - Class A Common Stock
BRSP	BrightSpire Capital, Inc. Class A Common Stock
CMP	Compass Minerals Intl Inc Common Stock
MSS	Maison Solutions Inc. - Class A Common Stock
PRU	Prudential Financial, Inc. Common Stock
SNX	TD SYNNEX Corporation Common Stock
TXMD	TherapeuticsMD, Inc. - Common Stock
ALTO	Alto Ingredients, Inc. - Common Stock
BRT	BRT Apartments Corp. (MD) Common Stock
CMPR	Cimpress plc - Ordinary Shares
MSTR	Strategy Inc - Class A Common Stock
PRVA	Privia Health Group, Inc. - Common Stock
SNYR	Synergy CHC Corp. - Common Stock
ALUB	Alussa Energy Acquisition Corp. II Class A Ordinary Shares
BRTX	BioRestorative Therapies, Inc. - Common Stock
CMPX	Compass Therapeutics, Inc. - Common Stock
MTA	Metalla Royalty & Streaming Ltd. Common Shares
PRZO	ParaZero Technologies Ltd. - Ordinary Shares
SO	Southern Company (The) Common Stock
TXNM	TXNM Energy, Inc. Common Stock
ALV	Autoliv, Inc. Common Stock
BRUN	Boost Run Inc. - Class A Common Stock
CMRC	Commerce.com, Inc. - Series 1 Common Stock
MTAL	Metals Acquisition Corp. II Class A Ordinary Shares
PS	Pershing Square Inc. Common Stock
SOAR	Volato Group, Inc. Class A Common Stock
TXRH	Texas Roadhouse, Inc. - Common Stock
ALVO	Alvotech - Ordinary Shares
BRVE	Braveheart Bio, Inc. - Common Stock
CMRE	Costamare Inc. Common Stock $0.0001 par value
MTB	M&T Bank Corporation Common Stock
PSA	Public Storage Common Stock
SOBO	South Bow Corporation Common Shares
TXT	Textron Inc. Common Stock
ALX	Alexander's, Inc. Common Stock
BRX	Brixmor Property Group Inc. Common Stock
CMS	CMS Energy Corporation Common Stock
MTC	MMTec, Inc. - Common Shares
PSBD	Palmer Square Capital BDC Inc. Common Stock
SOBR	SOBR Safe, Inc. - Common Stock
TY	Tri Continental Corporation Common Stock
ALXO	ALX Oncology Holdings Inc. - Common Stock
BRZE	Braze, Inc. - Class A Common Stock
CMT	Core Molding Technologies Inc Common Stock
MTCH	Match Group, Inc. - Common Stock
PSFE	Paysafe Limited Common Shares
SOC	Sable Offshore Corp. Common Stock
TYG	Tortoise Energy Infrastructure Corporation Common Stock
ALZN	Alzamend Neuro, Inc. - Common Stock
BSAA	BEST SPAC I Acquisition Corp. - Class A Ordinary Shares
CMTG	Claros Mortgage Trust, Inc. Common Stock
MTD	Mettler-Toledo International, Inc. Common Stock
PSHG	Performance Shipping Inc. - Common Shares
SOCA	Solarius Capital Acquisition Corp. - Class A Ordinary Share
TYGO	Tigo Energy, Inc. - Common Stock
AM	Antero Midstream Corporation Common Stock
BSBK	Bogota Financial Corp. - Common Stock
CMTL	Comtech Telecommunications Corp. - Common Stock
MTDR	Matador Resources Company Common Stock
PSIG	PS International Group Ltd. - Ordinary Shares
SOFI	SoFi Technologies, Inc.  - Common Stock
TYL	Tyler Technologies, Inc. Common Stock
AMAC	AMR Resources Acquisition Corp - Class A Ordinary Shares
BSEM	BioStem Technologies, Inc. - Common Stock
CMTV	Community Bancorp.  - Common stock
MTEK	Maris-Tech Ltd. - ordinary shares
PSIX	Power Solutions International, Inc. - Common Stock
SOLS	Solstice Advanced Materials Inc. - Common Stock
TYRA	Tyra Biosciences, Inc. - Common Stock
AMAL	Amalgamated Financial Corp. - Common Stock
BSET	Bassett Furniture Industries, Incorporated - Common Stock
CNA	CNA Financial Corporation Common Stock
MTEN	Mingteng International Corporation Inc. - Class A Ordinary Shares
PSKY	Paramount Skydance Corporation - Class B Common Stock
SOLV	Solventum Corporation Common Stock
TZOO	Travelzoo - Common Stock
AMAN	Amanat Acquisition Corp - Class A Ordinary Shares
BSIN	Big Sky Industrial Inc. - Common Stock
CNC	Centene Corporation Common Stock
MTEX	Mannatech, Incorporated - Common Stock
PSMT	PriceSmart, Inc. - Common Stock
SON	Sonoco Products Company Common Stock
AMAT	Applied Materials, Inc. - Common Stock
BSP	Bending Spoons S.p.A. - Ordinary Shares
CNCK	Coincheck Group N.V. - Ordinary Shares
MTG	MGIC Investment Corporation Common Stock
PSN	Parsons Corporation Common Stock
SONM	DNA X, Inc. - Common Stock
AMBA	Ambarella, Inc. - Ordinary Shares
BSRR	Sierra Bancorp - Common Stock
CNDT	Conduent Incorporated - Common Stock
MTH	Meritage Homes Corporation Common Stock
PSNL	Personalis, Inc. - Common Stock
SONO	Sonos, Inc. - Common Stock
AMBP	Ardagh Metal Packaging S.A. Ordinary Shares
BST	BlackRock Science and Technology Trust Common Shares of Beneficial Interest
CNET	ZW Data Action Technologies Inc. - Common Stock
MTN	Vail Resorts, Inc. Common Stock
PSO	Pearson, Plc Common Stock
SOPH	SOPHiA GENETICS SA - Ordinary Shares
AMBQ	Ambiq Micro, Inc. Common Stock
BSTZ	BlackRock Science and Technology Term Trust Common Shares of Beneficial Interest
CNEY	CN Energy Group Inc. - Class A Ordinary Shares
MTNB	Matinas Biopharma Holdings, Inc. Common Stock
PSQH	PSQ Holdings, Inc. Class A Common Stock
SORA	AsiaStrategy - Ordinary Shares
AMC	AMC Entertainment Holdings, Inc. Class A Common Stock
BSVN	Bank7 Corp. - Common stock
CNH	CNH Industrial N.V. Common Shares
MTNE	CH4 Natural Solutions Corporation Class A Ordinary Shares
PSQL	Pasqal Holding SA - Ordinary Shares
SORN	Soren Acquisition Corp. - Class A Ordinary Shares
AMCI	AMC Robotics Corporation - Common Stock
BSX	Boston Scientific Corporation Common Stock
CNI	Canadian National Railway Company Common Stock
MTR	Mesa Royalty Trust Common Stock
PSTL	Postal Realty Trust, Inc. Class A Common Stock
SOS	SOS Limited Class A Ordinary Shares
AMCR	Amcor plc Ordinary Shares
BSY	Bentley Systems, Incorporated - Class B Common Stock
CNK	Cinemark Holdings Inc Cinemark Holdings, Inc. Common Stock
MTRX	Matrix Service Company - Common Stock
PSUS	Pershing Square USA, Ltd. Common Shares
SOTK	Sono-Tek Corporation - Common Stock
AMCX	AMC Global Media Inc. - Class A Common Stock
BTBD	BT Brands, Inc. - Common Stock
CNL	Collective Mining Ltd. - Common Stock
MTSI	MACOM Technology Solutions Holdings, Inc. - Common Stock
PSX	Phillips 66 Common Stock
SOUL	Soulpower Acquisition Corporation Class A Ordinary Shares
BTBT	Bit Digital, Inc. - Ordinary Share
CNM	Core & Main, Inc. Class A Common Stock
MTUS	Metallus Inc. Common Shares
PTAC	Patriot Acquisition Corp. - Class A Ordinary Shares
SOUN	SoundHound AI, Inc. - Class A Common Stock
AMG	Affiliated Managers Group, Inc. Common Stock
BTCS	BTCS Inc. - Common Stock
CNMD	CONMED Corporation Common Stock
MTVA	MetaVia Inc.  - Common Stock
PTC	PTC Inc. - Common Stock
SOWG	Sow Good Inc. - Common Stock
AMGN	Amgen Inc. - Common Stock
BTCT	BTC Digital Ltd. - Ordinary Shares
CNNE	Cannae Holdings, Inc. Common Stock
MTW	Manitowoc Company, Inc. (The) Common Stock
PTCT	PTC Therapeutics, Inc. - Common Stock
SPAI	Safe Pro Group Inc. - Common Stock
AMH	American Homes 4 Rent Common Shares of Beneficial Interest
BTDR	Bitdeer Technologies Group - Ordinary Shares
CNO	CNO Financial Group, Inc. Common Stock
MTX	Minerals Technologies Inc. Common Stock
PTEN	Patterson-UTI Energy, Inc. - Common Stock
SPB	Spectrum Brands Holdings, Inc. Common Stock
AMIX	Autonomix Medical, Inc. - Common Stock
BTE	Baytex Energy Corp Common Shares
CNOB	ConnectOne Bancorp, Inc. - Common Stock
MTZ	MasTec, Inc. Common Stock
PTGX	Protagonist Therapeutics, Inc. - Common Stock
SPCB	SuperCom, Ltd. - Ordinary Shares
AMKR	Amkor Technology, Inc. - Common Stock
BTG	B2Gold Corp Common shares (Canada)
CNP	CenterPoint Energy, Inc (Holding Co) Common Stock
MU	Micron Technology, Inc. - Common Stock
PTHS	Pelthos Therapeutics Inc. Common Stock
SPCE	Virgin Galactic Holdings, Inc. Common Stock
AMLX	Amylyx Pharmaceuticals, Inc. - Common Stock
BTGO	BitGo Holdings, Inc. Class A Common Stock
CNQ	Canadian Natural Resources Limited Common Stock
MUFG	Mitsubishi UFJ Financial Group, Inc. Common Stock
PTLE	PTL LTD - Class A Ordinary Shares
SPCX	Space Exploration Technologies Corp. - Class A Common Stock
AMOD	Alpha Modus Holdings, Inc. - Class A Common Stock
BTI	British American Tobacco  Industries, p.l.c. Common Stock ADR
CNR	Core Natural Resources, Inc. Common Stock
MUR	Murphy Oil Corporation Common Stock
PTLO	Portillo's Inc. - Class A Common Stock
SPEG	Silver Pegasus Acquisition Corp - Class A Ordinary Shares
AMP	Ameriprise Financial, Inc. Common Stock
BTLN	Brightline Interactive, Inc. - Common Stock
CNS	Cohen & Steers Inc Common Stock
MUSA	Murphy USA Inc. Common Stock
PTN	Palatin Technologies, Inc. - Common Stock
SPFI	South Plains Financial, Inc. - Common Stock
AMPG	Amplitech Group, Inc. - Common Stock
BTMD	Biote Corp. - Class A common stock
CNSP	CNS Pharmaceuticals, Inc. - Common Stock
MUX	McEwen Inc. Common Stock
PTON	Peloton Interactive, Inc. - Common Stock
SPG	Simon Property Group, Inc. Common Stock
AMPH	Amphastar Pharmaceuticals, Inc. - Common Stock
BTOC	Armlogi Holding Corp. - common stock
CNSY	Cerenome, Inc. - Common Stock
MUZE	Muzero Acquisition Corp - Class A Ordinary Shares
PTOR	Praetorian Acquisition Corp. - Class A Ordinary Shares
SPGI	S&P Global Inc. Common Stock
AMPL	Amplitude, Inc. - Class A Common Stock
BTQ	BTQ Technologies Corp. - Common Stock
CNTB	Connect Biopharma Holdings Limited - Ordinary Shares
MVBF	MVB Financial Corp. - Common Stock
PTRN	Pattern Group Inc. - Series A Common Stock
SPH	Suburban Propane Partners, L.P. Common Stock
AMPX	Amprius Technologies, Inc. Common Stock
BTSG	BrightSpring Health Services, Inc. - Common Stock
CNTN	Canton Strategic Holdings, Inc. - Common Stock
MVIS	MicroVision, Inc. - Common Stock
PUBM	PubMatic, Inc. - Class A Common Stock
SPHL	Springview Holdings Ltd - Ordinary shares
AMPY	Amplify Energy Corp. Common Stock
BTTC	Black Titan Corp - Ordinary Shares
CNTX	Context Therapeutics Inc. - Common Stock
MVST	Microvast Holdings, Inc. - Common Stock
PUK	Prudential Public Limited Company Common Stock
SPHR	Sphere Entertainment Co. Class A Common Stock
AMR	Alpha Metallurgical Resources, Inc. Common Stock
BTU	Peabody Energy Corporation Common Stock 
CNTY	Century Casinos, Inc. - Common Stock
MWA	MUELLER WATER PRODUCTS Common Stock
PULM	Pulmatrix, Inc. - Common Stock
SPIR	Spire Global, Inc. Class A Common Stock
AMRC	Ameresco, Inc. Class A Common Stock
BTX	BlackRock Technology and Private Equity Term Trust Common Shares of Beneficial Interest
CNVS	Cineverse Corp. - Class A Common Stock
MWG	Multi Ways Holdings Limited Class A Ordinary Shares
PUMP	ProPetro Holding Corp. Common Stock
SPKL	Spark I Acquisition Corp. - Class A Ordinary Share
AMRX	Amneal Pharmaceuticals, Inc. - Class A Common Stock
BUDA	Buda Juice, Inc. Common Stock
CNX	CNX Resources Corporation Common Stock
MWH	SOLV Energy, Inc. - Class A common stock
PURR	Hyperliquid Strategies Inc - Common Stock
SPMC	Sound Point Meridian Capital, Inc. Common Stock
AMRZ	Amrize Ltd Ordinary Shares
BULL	Webull Corporation - Class A Ordinary Shares
CNXC	Concentrix Corporation - Common Stock
MWYN	Marwynn Holdings, Inc. - Common stock
PUSA	Aureus Greenway Holdings Inc. - Common Stock
SPNT	SiriusPoint Ltd. Common Shares
AMS	American Shared Hospital Services Common Stock
BUR	Burford Capital Limited Ordinary Shares
CNXN	PC Connection, Inc. - Common Stock
MX	Magnachip Semiconductor Corporation Common Stock
PVH	PVH Corp. Common Stock
SPOK	Spok Holdings, Inc. - Common Stock
AMSC	American Superconductor Corporation - Common Stock
BURL	Burlington Stores, Inc. Common Stock
CNXU	Conexeu Sciences Inc. - Common Stock
MXC	Mexco Energy Corporation Common Stock
PVLA	Palvella Therapeutics, Inc. - Common Stock
SPOT	Spotify Technology S.A. Ordinary Shares
AMSF	AMERISAFE, Inc. - Common Stock
BUSE	First Busey Corporation - Common Stock
COAG	Hemab Therapeutics Holdings, Inc. - Common Stock
MXCT	MaxCyte, Inc. - Common Stock
PW	Power REIT (MD) Common Stock
SPPL	SIMPPLE LTD. - Ordinary Shares
AMSS	AMASS Brands Inc. - Common Stock
BUUU	BUUU Group Limited - Class A Ordinary Share
COCH	Envoy Medical, Inc. - Class A Common Stock
MXL	MaxLinear, Inc - Common Stock
PWCM	PowerCompute, Inc. - Common Stock
SPRB	Spruce Biosciences, Inc. - Common Stock
AMST	Amesite Inc. - Common Stock
BV	BrightView Holdings, Inc. Common Stock
COCO	The Vita Coco Company, Inc. - Common Stock
MYE	Myers Industries, Inc. Common Stock
PWP	Perella Weinberg Partners - Class A Common Stock
SPRC	SciSparc Ltd. - Ordinary Shares
AMT	American Tower Corporation (REIT) Common Stock
BVC	BitVentures Limited - Ordinary Share
COCP	Cocrystal Pharma, Inc. - Common Stock
MYFW	First Western Financial, Inc. - Common Stock
PWR	Quanta Services, Inc. Common Stock
SPRO	Spero Therapeutics, Inc. - Common Stock
AMTB	Amerant Bancorp Inc. Class A Common Stock
BVFL	BV Financial, Inc. - Common Stock
CODA	Coda Octopus Group, Inc. - Common stock
MYGN	Myriad Genetics, Inc. - Common Stock
PWRL	Powerlaw Corp. - Common Stock
SPRU	Spruce Power Holding Corporation Class A Common Stock
AMTM	Amentum Holdings, Inc. Common Stock
BVS	Bioventus Inc. - Class A Common Stock
CODX	Co-Diagnostics, Inc. - Common Stock
MYO	Myomo Inc. Common Stock
PXED	Phoenix Education Partners, Inc. Common Stock
SPRY	ARS Pharmaceuticals, Inc. - Common Stock
AMTX	Aemetis, Inc - Common Stock
BW	Babcock & Wilcox Enterprises, Inc. Common Stock
COF	Capital One Financial Corporation Common Stock
MYPS	PLAYSTUDIOS, Inc.  - Class A Common Stock
PXLW	Pixelworks, Inc. - Common Stock
SPSC	SPS Commerce, Inc. - Common Stock
AMWL	American Well Corporation Class A Common Stock
BWA	BorgWarner Inc. Common Stock
COFS	ChoiceOne Financial Services, Inc. - Common Stock
MYRG	MYR Group, Inc. - Common Stock
PXS	Pyxis Tankers Inc. - Common Stock
SPT	Sprout Social, Inc - Class A Common Stock
AMZE	Amaze Holdings, Inc. Common Stock
BWB	Bridgewater Bancshares, Inc. - Common Stock
COGT	Cogent Biosciences, Inc. - Common Stock
MYSE	Myseum.AI, Inc. - Common Stock
PYPD	PolyPid Ltd. - Ordinary Shares
SPTX	Seaport Therapeutics, Inc. - Common Stock
BWEN	Broadwind, Inc. - Common Stock
COHR	Coherent Corp. Common Stock
MYSZ	My Size, Inc. - Common Stock
PYPL	PayPal Holdings, Inc. - Common Stock
SPWH	Sportsman's Warehouse Holdings, Inc. - Common Stock
AN	AutoNation, Inc. Common Stock
BWFG	Bankwell Financial Group, Inc. - Common Stock
COHU	Cohu, Inc. - Common Stock
MYX	Maywood Acquisition Corp. 2 - Class A Ordinary Share
PYXS	Pyxis Oncology, Inc. - Common Stock
SPWR	SunPower Inc. - Common Stock
ANAB	AnaptysBio, Inc. - Common Stock
BWIN	The Baldwin Insurance Group, Inc. - Class A Common Stock
COIN	Coinbase Global, Inc. - Class A Common Stock
MZTI	The Marzetti Company - Common Stock
PZG	Paramount Gold Nevada Corp. Common Stock
SPXC	SPX Technologies, Inc. Common Stock
ANDE	The Andersons, Inc. - Common Stock
BWIV	Blue Water Acquisition Corp. IV Class A Ordinary Shares
COKE	Coca-Cola Consolidated, Inc. - Common Stock
MZYX	MOZAYYX Acquisition Corp. Class A Ordinary Shares
PZZA	Papa John's International, Inc. - Common Stock
SQFT	Presidio Property Trust, Inc. - Class A Common Stock
ANDG	Andersen Group Inc. Class A Common Stock
BWLP	BW LPG Limited Common Shares
COLA	Columbus Acquisition Corp - Ordinary Shares
SQM	Sociedad Quimica y Minera S.A. Common Stock
ANET	Arista Networks, Inc. Common Stock
BWMN	Bowman Consulting Group Ltd. - Common Stock
COLB	Columbia Banking System, Inc. - Common Stock
SR	Spire Inc. Common Stock
ANF	Abercrombie & Fitch Company Common Stock
BWMX	Betterware de Mexico, S.A.P.I. de C.V. Ordinary Shares
COLD	Americold Realty Trust, Inc. Common Stock
SRAD	Sportradar Group AG - Class A Ordinary Shares
ANGH	Anghami Inc. - Ordinary Shares
BWXT	BWX Technologies, Inc. Common Stock
COLL	Collegium Pharmaceutical, Inc. - Common Stock
SRBK	SR Bancorp, Inc. - Common stock
ANGI	Angi Inc. - Class A Common Stock
BX	Blackstone Inc. Common Stock
COLM	Columbia Sportswear Company - Common Stock
SRCE	1st Source Corporation - Common Stock
ANGO	AngioDynamics, Inc. - Common Stock
BXBL	BOXABL, Inc.  - Common stock
COMP	Compass, Inc. Class A Common Stock
SRE	DBA Sempra Common Stock
ANGX	Angel Studios, Inc. Class A Common Stock
BXC	Bluelinx Holdings Inc. Common Stock
CON	Concentra Group Holdings Parent, Inc. Common Stock
SRFM	Surf Air Mobility Inc. Common Stock
ANIK	Anika Therapeutics Inc. - Common Stock
BXDC	Blackstone Digital Infrastructure Trust Inc. Common Stock
COO	The Cooper Companies, Inc.  - Common Stock
SRG	Seritage Growth Properties Class A Common Stock
ANIP	ANI Pharmaceuticals, Inc. - Common Stock
BXMT	Blackstone Mortgage Trust, Inc. Common Stock
COOK	Traeger, Inc. Common Stock
SRI	Stoneridge, Inc. Common Stock
ANIX	Anixa Biosciences, Inc. - Common Stock
BXP	BXP, Inc. Common Stock
COOT	Australian Oilseeds Holdings Limited - Ordinary Shares
SRPT	Sarepta Therapeutics, Inc. - Common Stock
ANNA	AleAnna, Inc. - Class A Common Stock
BY	Byline Bancorp, Inc. Common Stock
COP	ConocoPhillips Common Stock
SRRK	Scholar Rock Holding Corporation - Common Stock
ANNX	Annexon, Inc. - common stock
BYAH	Park Ha Biological Technology Co., Ltd. - Class A Ordinary Shares
COPL	Copley Acquisition Corp Ordinary Shares
SRTA	Strata Critical Medical, Inc. - Class A Common Stock
ANPA	Rich Sparkle Holdings Limited - Ordinary Shares
BYD	Boyd Gaming Corporation Common Stock
COPR	Idaho Copper Corporation Common Stock
SRTS	Sensus Healthcare, Inc. - Common Stock
ANRO	Alto Neuroscience, Inc. Common Stock
BYFC	Broadway Financial Corporation - Class A Common Stock
COR	Cencora, Inc. Common Stock
SRXH	SRX Global Inc. Common Stock
ANTA	Antalpha Platform Holding Company - Class A Ordinary Shares
BYND	Beyond Meat, Inc. - Common stock
CORT	Corcept Therapeutics Incorporated - Common Stock
SRZN	Surrozen, Inc. - Common Stock
ANTX	AN2 Therapeutics, Inc. - Common Stock
BYRN	Byrna Technologies, Inc. - Common Stock
CORZ	Core Scientific, Inc. - Common Stock
SSAC	SPACSphere Acquisition Corp. - Class A Ordinary Shares
ANVS	Annovis Bio, Inc. Common Stock
BYSI	BeyondSpring, Inc. - Ordinary Shares
COSM	Cosmos Health Inc. - Common Stock
SSB	SouthState Bank Corporation Common Stock
ANY	Sphere 3D Corp. - Common Shares
BZAI	Blaize Holdings, Inc. - Common Stock
COSO	CoastalSouth Bancshares, Inc. Common Stock
SSBI	Summit State Bank - Common Stock
AOMR	Angel Oak Mortgage REIT, Inc. Common Stock
BZFD	BuzzFeed, Inc. - Class A Common Stock
SSD	Simpson Manufacturing Company, Inc. Common Stock
AON	Aon plc Class A Ordinary Shares (Ireland)
BZH	Beazer Homes USA, Inc. Common Stock
COTY	Coty Inc. Class A Common Stock
SSEA	Starry Sea Acquisition Corp - Ordinary Shares
AORT	Artivion, Inc. Common Stock
COUR	Coursera, Inc. Common Stock
SSII	SS Innovations International Inc. - Common Stock
AOS	A.O. Smith Corporation Common Stock
COYA	Coya Therapeutics, Inc. - Common Stock
SSM	Sono Group N.V. - Ordinary Shares
AOSL	Alpha and Omega Semiconductor Limited - Common Shares
CP	Canadian Pacific Kansas City Limited Common Shares
SSMR	Sunshine Silver Mining & Refining Company Common Stock
AOUT	American Outdoor Brands, Inc. - Common Stock
CPA	Copa Holdings, S.A. Class A Common Stock
SSNC	SS&C Technologies Holdings, Inc. - Common Stock
AP	Ampco-Pittsburgh Corporation Common Stock
CPAY	Corpay, Inc. Common Stock
SSP	E.W. Scripps Company (The) - Class A Common Stock
APA	APA Corporation - Common Stock
CPB	The Campbell's Company - Common Stock
SSRM	SSR Mining Inc. - Common Stock
APAC	StoneBridge Acquisition II Corporation - Class A Ordinary Shares
CPBI	Central Plains Bancshares, Inc. - Common Stock
SST	System1, Inc. Class A Common Stock
APAM	Artisan Partners Asset Management Inc. Class A Common Stock
CPHC	Canterbury Park Holding Corporation - Common Stock
SSTI	SoundThinking, Inc. - Common Stock
APC	ARKO Petroleum Corp. - Class A Common Stock
CPHI	China Pharma Holdings, Inc. Common Stock
SSTK	Shutterstock, Inc. Common Stock
APD	Air Products and Chemicals, Inc. Common Stock
CPIX	Cumberland Pharmaceuticals Inc. - Common Stock
SSYS	Stratasys, Ltd. - Common Stock
APEI	American Public Education, Inc. - Common Stock
CPK	Chesapeake Utilities Corporation Common Stock
ST	Sensata Technologies Holding plc Ordinary Shares
APG	APi Group Corporation Common Stock
CPNG	Coupang, Inc. Class A Common Stock
STAA	STAAR Surgical Company - Common Stock
APH	Amphenol Corporation Common Stock
CPOP	Pop Culture Group Co., Ltd - Class A Ordinary Shares
STAG	Stag Industrial, Inc. Common Stock
APLD	Applied Digital Corporation - Common Stock
CPRI	Capri Holdings Limited Ordinary Shares
STAK	STAK Inc. - Class A Ordinary Shares
APLE	Apple Hospitality REIT, Inc. Common Shares
CPRT	Copart, Inc. - Common Stock
STBA	S&T Bancorp, Inc. - Common Stock
APLM	Apollomics Inc. - Class A Ordinary Shares
CPS	Cooper-Standard Holdings Inc. Common Stock
STC	Stewart Information Services Corporation Common Stock
APMC	AmperCap Acquisition Company - Ordinary Shares
CPSH	CPS Technologies Corp. - Common Stock
STDN	Standard Nuclear, Inc. Class A Common Stock
APMD	Apnimed, Inc. - Common Stock
CPSS	Consumer Portfolio Services, Inc. - Common Stock
STE	STERIS plc (Ireland) Ordinary Shares
APO	Apollo Global Management, Inc. (New) Common Stock
CPT	Camden Property Trust Common Stock
STEM	Stem, Inc. Class A Common Stock
APOG	Apogee Enterprises, Inc. - Common Stock
CR	Crane Company Common Stock
STEP	StepStone Group Inc. - Class A Common Stock
APP	Applovin Corporation - Class A Common Stock
CRAC	Crown Reserve Acquisition Corp. I - Class A Ordinary Shares
STEX	Streamex Corp. - Common Stock
APPF	AppFolio, Inc. - Class A Common Stock
CRAI	CRA International,Inc. - Common Stock
STFS	Star Fashion Culture Holdings Limited - Class A Ordinary Shares
APPN	Appian Corporation - Class A Common Stock
CRAN	Crane Harbor Acquisition Corp. II - Class A Ordinary Shares
STGW	Stagwell Inc. - Class A Common Stock
APPS	Digital Turbine, Inc. - Common Stock
CRAQ	Cal Redwood Acquisition Corp. - Class A Ordinary Shares
STI	Solidion Technology, Inc. - Common Stock
APRE	Aprea Therapeutics, Inc. - Common Stock
CRBG	Corebridge Financial Inc. Common Stock
STIM	Neuronetics, Inc. - Common Stock
APT	Alpha Pro Tech, Ltd. Common Stock
CRBP	Corbus Pharmaceuticals Holdings, Inc. - Common Stock
STKE	Sol Strategies Inc. - Common Shares
APTV	Aptiv PLC Ordinary Shares
CRBU	Caribou Biosciences, Inc. - Common Stock
STKS	The ONE Group Hospitality, Inc. - Common Stock
APUR	Aperture AC - Class A Ordinary Shares
CRC	California Resources Corporation Common Stock
STLA	Stellantis N.V. Common Shares
APUS	Apimeds Pharmaceuticals US, Inc. Common Stock
CRCL	Circle Internet Group, Inc. Class A Common Stock
STLD	Steel Dynamics, Inc. - Common Stock
APVO	Aptevo Therapeutics Inc. - Common Stock
CRCT	Cricut, Inc. - Class A common stock
STLN	Starling Oncology, Inc. - Common Stock
APWC	Asia Pacific Wire & Cable Corporation Limited  - Common shares, Par value .01 per share
CRD-A	Crawford & Company Common Stock
STM	STMicroelectronics N.V. Common Stock
APXT	Apex Treasury Corporation - Class A Ordinary Share
CRD-B	Crawford & Company Common Stock
STN	Stantec Inc Common Stock
APYX	Apyx Medical Corporation - Common Stock
CRDF	Cardiff Oncology, Inc. - Common Stock
STNE	StoneCo Ltd. - Class A Common Share
AQB	AquaBounty Technologies, Inc. - Common Stock
CRDL	Cardiol Therapeutics Inc. - Class A Common Shares
STNG	Scorpio Tankers Inc. Common Shares
AQMS	Aqua Metals, Inc. - Common Stock
CRDO	Credo Technology Group Holding Ltd - Ordinary Shares
STOK	Stoke Therapeutics, Inc. - Common Stock
AQN	Algonquin Power & Utilities Corp. Common Shares
CRE	Cre8 Enterprise Limited - Class A Ordinary Shares
STRA	Strategic Education, Inc. - Common Stock
AQST	Aquestive Therapeutics, Inc. - Common Stock
CREX	Creative Realities, Inc. - Common Stock
STRL	Sterling Infrastructure, Inc. - Common Stock
AR	Antero Resources Corporation Common Stock
CRGO	Freightos Limited - Ordinary shares
STRO	Sutro Biopharma, Inc. - Common Stock
ARAI	Arrive AI Inc. - Common Stock
CRGY	Crescent Energy Company Class A Common Stock
STRR	Star Equity Holdings, Inc. - Common Stock
ARAY	Accuray Incorporated - Common Stock
CRH	CRH PLC Ordinary Shares
STRT	STRATTEC SECURITY CORPORATION - Common Stock
ARBB	ARB IOT Group Limited - Ordinary Shares
CRI	Carter's, Inc. Common Stock
STRW	Strawberry Fields REIT, Inc. Common Stock
ARBE	Arbe Robotics Ltd. - Ordinary Shares
CRIS	Curis, Inc. - Common Stock
STRZ	Starz Entertainment Corp. - Common Shares
ARCB	ArcBest Corporation - Common Stock
CRK	Comstock Resources, Inc. Common Stock
STT	State Street Corporation Common Stock
ARCI	Archimedes Tech SPAC Partners III Co. - Ordinary Share
CRL	Charles River Laboratories International, Inc. Common Stock
STTK	Shattuck Labs, Inc. - Common Stock
ARCL	ARC Group Acquisition I Corp - Class A Ordinary Shares
STUB	StubHub Holdings, Inc. Class A Common Stock
ARCT	Arcturus Therapeutics Holdings Inc. - Common Stock
CRMD	CorMedix Inc. - Common Stock
STVN	Stevanato Group S.p.A. Ordinary Shares
ARDT	Ardent Health, Inc. Common Stock
CRML	Critical Metals Corp. - Ordinary Shares
STX	Seagate Technology Holdings PLC - Ordinary Shares (Ireland)
ARDX	Ardelyx, Inc. - Common Stock
CRMT	America's Car-Mart, Inc. - Common Stock
STXS	Stereotaxis, Inc. Common Stock
ARE	Alexandria Real Estate Equities, Inc. Common Stock
CRNC	Cerence Inc. - Common Stock
STZ	Constellation Brands, Inc. Common Stock
AREC	American Resources Corporation - Class A Common Stock
CRNT	Ceragon Networks Ltd. - Ordinary Shares
SU	Suncor Energy  Inc. Common Stock
ARES	Ares Management Corporation Class A Common Stock
CRON	Cronos Group Inc. - Common Share
SUGP	SU Group Holdings Limited - Class A Ordinary Shares
ARHS	Arhaus, Inc. - Class A Common Stock
CROX	Crocs, Inc. - Common Stock
SUI	Sun Communities, Inc. Common Stock
ARIS	Aris Mining Corporation Common Shares
CRS	Carpenter Technology Corporation Common Stock
SUIG	Sui Group Holdings Limited - Common Stock
ARKO	ARKO Corp. - Common Stock
CRSP	CRISPR Therapeutics AG - Common Shares
SUJA	Suja Life, Inc. - Class A Common Stock
ARKR	Ark Restaurants Corp. - Common Stock
CRSR	Corsair Gaming, Inc. - Common Stock
SUMA	SUMA Acquisition Corporation - Class A Ordinary Shares
ARL	American Realty Investors, Inc. Common Stock
CRT	Cross Timbers Royalty Trust Common Stock
SUNB	Sunbelt Rentals Holdings, Inc. Common Stock
ARLO	Arlo Technologies, Inc. Common Stock
CRTO	Criteo S.A. - Ordinary Shares
SUNE	SUNation Energy, Inc. - Common Stock
ARMK	Aramark Common Stock
CRUS	Cirrus Logic, Inc. - Common Stock
SUNS	Sunrise Realty Trust, Inc. - Common Stock
ARMP	Armata Pharmaceuticals, Inc. Common Stock
CRVL	CorVel Corp. - Common Stock
SUPN	Supernus Pharmaceuticals, Inc. - Common Stock
AROC	Archrock, Inc. Common Stock
CRVO	CervoMed Inc. - Common Stock
SUPX	SuperX AI Technology Limited - Ordinary Shares
AROW	Arrow Financial Corporation - Common Stock
CRVS	Corvus Pharmaceuticals, Inc. - Common Stock
SURG	SurgePays, Inc. - Common Stock
ARQ	Arq, Inc. - Common Stock
SVA	Sinovac Biotech, Ltd. - Ordinary Shares (Antigua/Barbudo)
ARQQ	Arqit Quantum Inc. - Ordinary Shares
CRWS	Crown Crafts, Inc. - Common Stock
SVAQ	Silicon Valley Acquisition Corp. - Class A Ordinary Shares
ARQT	Arcutis Biotherapeutics, Inc. - Common stock
CRWV	CoreWeave, Inc. - Class A Common Stock
SVC	Service Properties Trust - Common Shares of Beneficial Interest
ARRY	Array Technologies, Inc. - Common Stock
CSAI	Cloudastructure, Inc. - Class A Common Stock
SVCC	Stellar V Capital Corp. - Class A Ordinary Shares
ARTC	Art Technology Acquisition Corp. - Class A Ordinary Shares
CSBR	Champions Oncology, Inc. - Common Stock
SVCO	Silvaco Group, Inc. - Common Stock
ARTL	Artelo Biosciences, Inc. - Common Stock
SVIV	Spring Valley Acquisition Corp. IV - Class A Ordinary Shares
ARTNA	Artesian Resources Corporation - Class A Non-Voting Common Stock
CSGP	CoStar Group, Inc. - Common Stock
SVM	Silvercorp Metals Inc. Common Shares
ARTV	Artiva Biotherapeutics, Inc. - Common Stock
CSHR	CoinShares PLC - Ordinary Shares
SVRA	Savara, Inc. - Common Stock
ARTW	Art's-Way Manufacturing Co., Inc. - Common Stock
CSIQ	Canadian Solar Inc. - Common Shares
SVRN	SVRN, Inc. - Common Stock
ARVN	Arvinas, Inc. - Common Stock
CSL	Carlisle Companies Incorporated Common Stock
SVV	Savers Value Village, Inc. Common Stock
ARW	Arrow Electronics, Inc. Common Stock
CSPI	CSP Inc. - Common Stock
SW	Smurfit WestRock plc Ordinary Shares
ARWR	Arrowhead Pharmaceuticals, Inc. - Common Stock
CSQR	Csquare, Inc. Common Stock
SWAG	Stran & Company, Inc. - Common Stock
ARX	Accelerant Holdings Class A Common Shares
CSR	D/B/A Centerspace Common Stock
SWBI	Smith & Wesson Brands, Inc. - Common Stock
ARXS	Arxis, Inc. - Class A Common Stock
CSTE	Caesarstone Ltd. - Ordinary Shares
SWIM	Latham Group, Inc. - Common Stock
AS	Amer Sports, Inc. Ordinary Shares
CSTL	Castle Biosciences, Inc. - Common stock
SWK	Stanley Black & Decker, Inc. Common Stock
ASAN	Asana, Inc. Class A Common Stock
CSTM	Constellium SE Ordinary Shares (France)
SWKS	Skyworks Solutions, Inc. - Common Stock
ASB	Associated Banc-Corp Common Stock
CSV	Carriage Services, Inc. Common Stock
SWMR	Swarmer, Inc - common stock
ASBP	Aspire-Lakewood Holdings, Inc. - Common Stock
CSW	CSW Industrials, Inc. Common Stock
SWVL	Swvl Holdings Corp - Ordinary Shares
ASC	Ardmore Shipping Corporation Common Stock
CSWC	Capital Southwest Corporation - Common Stock
SWX	Southwest Gas Holdings, Inc. Common Stock (DE)
ASH	Ashland Inc. Common Stock
CSX	CSX Corporation - Common Stock
SXC	SunCoke Energy, Inc. Common Stock
ASIC	Ategrity Specialty Insurance Company Holdings Common Stock
CTAA	ClearThink 1 Acquisition Corp. - Class A Ordinary Shares
SXI	Standex International Corporation Common Stock
ASIX	AdvanSix Inc. Common Stock 
CTAS	Cintas Corporation - Common Stock
SXT	Sensient Technologies Corporation Common Stock
ASLE	AerSale Corporation - Common Stock
CTBI	Community Trust Bancorp, Inc. - Common Stock
SXTC	China SXT Pharmaceuticals, Inc. - Class A Ordinary Shares
ASM	Avino Silver & Gold Mines Ltd. Common Shares (Canada)
CTEV	Claritev Corporation Class A Common Stock
SXTP	60 Degrees Pharmaceuticals, Inc. - Common Stock
ASMB	Assembly Biosciences, Inc. - Common Stock
CTGO	Contango Silver & Gold Inc. Common Stock
SYBT	Stock Yards Bancorp, Inc. - Common Stock
ASND	Ascendis Pharma A/S - Ordinary Share
CTKB	Cytek Biosciences, Inc. - Common Stock
SYF	Synchrony Financial Common Stock
ASO	Academy Sports and Outdoors, Inc. - Common Stock
CTM	Castellum, Inc. Common Stock
SYK	Stryker Corporation Common Stock
ASPC	A SPAC III Acquisition Corp. - Class A Ordinary Shares
CTMX	CytomX Therapeutics, Inc. - Common Stock
SYM	Symbotic Inc. - Class A Common Stock
ASPI	ASP Isotopes Inc. - Common Stock
CTNM	Contineum Therapeutics, Inc. - Common stock
SYNA	Synaptics Incorporated - Common Stock
ASPN	Aspen Aerogels, Inc. Common Stock
CTNT	Cheetah Net Supply Chain Service Inc. - Class A Common Stock
SYNX	Silynxcom Ltd. Ordinary Shares
ASPS	Altisource Portfolio Solutions S.A. - Common Stock
CTO	CTO Realty Growth, Inc. Common Stock
SYPR	Sypris Solutions, Inc. - Common Stock
ASR	Grupo Aeroportuario del Sureste, S.A. de C.V. Common Stock
CTOR	Citius Oncology, Inc.  - Common Stock
SYRE	Spyre Therapeutics, Inc. - Common Stock
ASRV	AmeriServ Financial Inc. - Common Stock
CTOS	Custom Truck One Source, Inc. Common Stock
SYY	Sysco Corporation Common Stock
ASST	Strive, Inc. - Class A Common Stock
CTRE	CareTrust REIT, Inc. Common Stock
SZZL	Sizzle Acquisition Corp. II - Class A ordinary shares
ASTC	Astrotech Corporation - Common Stock
CTRI	Centuri Holdings, Inc. Common Stock
ASTE	Astec Industries, Inc. - Common Stock
CTRM	Castor Maritime Inc. - Common Shares
ASTH	Astrana Health Inc. - Common Stock
CTRN	Citi Trends, Inc. - Common Stock
ASTI	Ascent Solar Technologies, Inc - Common Stock
CTS	CTS Corporation Common Stock
ASTL	Algoma Steel Group Inc. - Common Shares
CTSH	Cognizant Technology Solutions Corporation - Class A Common Stock
ASTS	AST SpaceMobile, Inc. - Class A Common Stock
CTSO	Cytosorbents Corporation - Common Stock
ASUR	Asure Software Inc - Common Stock
CTVA	Corteva, Inc. Common Stock 
ASYS	Amtech Systems, Inc. - Common Stock
CTW	CTW - Class A Ordinary Shares
ATAI	AtaiBeckley Inc. - Common Stock
CTXR	Citius Pharmaceuticals, Inc. - Common Stock
ATCH	AtlasClear Holdings, Inc. Common Stock
CUB	Lionheart Holdings - Class A Ordinary Shares
ATCX	Atlas Critical Minerals Corporation - Common Stock
CUBE	CubeSmart Common Shares
ATEC	Alphatec Holdings, Inc. - Common Stock
CUBI	Customers Bancorp, Inc Common Stock
ATEN	A10 Networks, Inc. Common Stock
CUE	Cue Biopharma, Inc. - Common Stock
ATER	Aterian, Inc. - Common Stock
CULP	Culp, Inc. - Common Shares
ATEX	Anterix Inc. - Common Stock
CUPR	Cuprina Holdings (Cayman) Limited - Class A Ordinary shares
ATGL	Alpha Technology Group Limited - Class A Ordinary Shares
CURB	Curbline Properties Corp. Common Stock
ATHR	Aether Holdings, Inc. - Common Stock
CURI	CuriosityStream Inc.  - Class A Common Stock
ATI	ATI Inc. Common Stock
CURR	Currenc Group Inc. - Ordinary Shares
ATII	Archimedes Tech SPAC Partners II Co. - Ordinary Shares
CURV	Torrid Holdings Inc. Common Stock
ATKR	Atkore Inc. Common Stock
CURX	Curanex Pharmaceuticals Inc - Common Stock
ATLC	Atlanticus Holdings Corporation - Common Stock
CUZ	Cousins Properties Incorporated Common Stock
ATLO	Ames National Corporation - Common Stock
CV	CapsoVision, Inc. - Common Stock
ATLQ	JAB Acquisition Corp I - Class A Ordinary Shares
CVBF	CVB Financial Corporation - Common Stock
ATLX	Atlas Lithium Corporation - Common Stock
CVCO	Cavco Industries, Inc. - Common Stock
ATMU	Atmus Filtration Technologies Inc. Common Stock
CVE	Cenovus Energy Inc Common Stock
ATNI	ATN International, Inc. - Common Stock
CVEO	Civeo Corporation (Canada) Common Shares
ATNM	Actinium Pharmaceuticals, Inc. (Delaware) Common Stock
CVGI	Commercial Vehicle Group, Inc. - Common Stock
ATO	Atmos Energy Corporation Common Stock
CVI	CVR Energy Inc. Common Stock
ATOM	Atomera Incorporated - Common Stock
CVKD	Cadrenal Therapeutics, Inc. - Common Stock
ATOS	Atossa Therapeutics, Inc. - Common Stock
CVLG	Covenant Logistics Group, Inc. Class A Common Stock
ATPC	Agape ATP Corporation - Common Stock
CVLT	Commvault Systems, Inc. - Common Stock
ATR	AptarGroup, Inc. Common Stock
CVM	Cel-Sci Corporation Common Stock
ATRA	Atara Biotherapeutics, Inc. - Common Stock
CVNA	Carvana Co. Class A Common Stock
ATRC	AtriCure, Inc. - Common Stock
CVR	Chicago Rivet & Machine Co. Common Stock
ATRO	Astronics Corporation - Common Stock
CVRX	CVRx, Inc. - Common Stock
ATS	ATS Corporation Common Shares
CVS	CVS Health Corporation Common Stock
ATTO	Attovia Therapeutics, Inc. - Common Stock
CVSA	Covista Inc. Common Shares
ATXG	Addentax Group Corp. - Common Stock
CVU	CPI Aerostructures, Inc. Common Stock
ATYR	aTyr Pharma, Inc. - Common Stock
CVV	CVD Equipment Corporation - Common Stock
AU	AngloGold Ashanti PLC Ordinary Shares
CVX	Chevron Corporation Common Stock
AUB	Atlantic Union Bankshares Corporation Common Stock
CW	Curtiss-Wright Corporation Common Stock
AUBN	Auburn National Bancorporation, Inc. - Common Stock
CWBC	Community West Bancshares - Common Stock
AUC	ATIF Holdings Limited - Ordinary Shares
CWCO	Consolidated Water Co. Ltd. - Ordinary Shares
AUDC	AudioCodes Ltd. - Ordinary Shares
CWD	CaliberCos Inc. - Class A Common Stock
AUGO	Aura Minerals Inc. - Common Shares
CWEN	Clearway Energy, Inc. Class C Common Stock
AUID	authID Inc. - Common Stock
CWH	Camping World Holdings, Inc. Class A Common Stock
AUNA	Auna SA Class A Ordinary Shares
CWK	Cushman & Wakefield Ltd. Common Shares
AUPH	Aurinia Pharmaceuticals Inc - Common Shares
CWST	Casella Waste Systems, Inc. - Class A Common Stock
AUR	Aurora Innovation, Inc.  - Class A Common Stock
CWT	California Water Service Group Common Stock
AURA	Aura Biosciences, Inc. - Common Stock
CXAI	CXApp Inc. - Class A Common Stock
AURE	Aurelion Inc.  - Class A Ordinary Shares
CXDO	Crexendo, Inc. - Common Stock
AUST	Austin Gold Corp. Common Shares
CXII	Churchill Capital Corp XII - Class A Ordinary Shares
AUUD	Auddia Inc. - Common Stock
CXM	Sprinklr, Inc. Class A Common Stock
AUXX	Gold X2 Mining Inc. Common Shares
CXT	Crane NXT, Co. Common Stock
AVA	Avista Corporation Common Stock
CXW	CoreCivic, Inc. Common Stock
AVAH	Aveanna Healthcare Holdings Inc. - Common Stock
CYAB	Cyabra, Inc. - Common Stock
AVAT	Avalanche Treasury Corporation - Class A Common Stock
CYCU	Cycurion, Inc. - Common Stock
AVAV	AeroVironment, Inc. - Common Stock
CYD	China Yuchai International Limited Common Stock
AVBC	Avidia Bancorp, Inc. Common Stock
CYH	Community Health Systems, Inc. Common Stock
AVBH	Avidbank Holdings, Inc. - Common Stock
CYN	Cyngn Inc. - Common stock
AVBP	ArriVent BioPharma, Inc. - Common Stock
CYPH	Cypherpunk Technologies Inc. - Common Stock
AVD	American Vanguard Corporation Common Stock ($0.10 Par Value)
CYRX	CryoPort, Inc. - Common Stock
AVEX	AEVEX Corp. Class A Common Stock
CYTK	Cytokinetics, Incorporated - Common Stock
CZFS	Citizens Financial Services, Inc. - Common Stock
AVIR	Atea Pharmaceuticals, Inc. - common stock
CZNC	Citizens & Northern Corp - Common Stock
AVLN	Avalyn Pharma Inc. - common stock
CZR	Caesars Entertainment, Inc. - Common Stock
AVNT	Avient Corporation Common Stock
CZWI	Citizens Community Bancorp, Inc. - Common Stock
AVNW	Aviat Networks, Inc. - Common Stock
AVO	Mission Produce, Inc. - Common Stock
AVPT	AvePoint, Inc. - Class A Common Stock
AVR	Anteris Technologies Global Corp. - Common Stock
AVT	Avnet, Inc. - Common Stock
AVTR	Avantor, Inc. Common Stock
AVTX	Avalo Therapeutics, Inc. - Common Stock
AVX	Avax One Technology Ltd. - Common Shares
AVXL	Anavex Life Sciences Corp. - Common Stock
AVY	Avery Dennison Corporation Common Stock
AWI	Armstrong World Industries Inc Common Stock
AWK	American Water Works Company, Inc. Common Stock
AWR	American States Water Company Common Stock
AWRE	Aware, Inc. - Common Stock
AWX	Avalon Holdings Corporation Common Stock
AX	Axos Financial, Inc. Common Stock
AXG	Solowin Holdings - Class A Ordinary Share
AXGN	Axogen, Inc. - Common Stock
AXIL	AXIL Brands, Inc. Common Stock
AXIN	Axiom Intelligence Acquisition Corp 1 - Class A Ordinary Shares
AXON	Axon Enterprise, Inc. - Common Stock
AXP	American Express Company Common Stock
AXR	AMREP Corporation Common Stock
AXS	Axis Capital Holdings Limited Common Stock
AXSM	Axsome Therapeutics, Inc. - Common Stock
AXTA	Axalta Coating Systems Ltd. Common Shares
AXTI	AXT Inc - Common Stock
AYA	Aya Gold & Silver Inc. - Common Shares
AYI	Acuity Inc. Common Stock
AYTU	Aytu BioPharma, Inc.  - Common Stock
AZ	A2Z Cust2Mate Solutions Corp. - Common Shares
AZI	Autozi Internet Technology (Global) Ltd. - Class A Ordinary Shares
AZIO	Azio AI Holdings, Inc. - Common stock
AZN	AstraZeneca PLC Ordinary Shares
AZO	AutoZone, Inc. Common Stock
AZTA	Azenta, Inc. - Common Stock
AZTR	Azitra Inc Common Stock"""
ETF_CATALOG_TSV = """SPY	State Street SPDR S&P 500 ETF Trust
QQQ	Invesco QQQ Trust, Series 1
VOO	Vanguard S&P 500 ETF
VTI	Vanguard Morningstar Total Stock Market ETF
DIA	State Street SPDR Dow Jones Industrial Average ETF Trust
IWM	iShares Russell 2000 Index Fund
SCHD	Schwab US Dividend Equity ETF
VYM	Vanguard High Dividend Yield ETF
DVY	iShares Select Dividend ETF
HDV	iShares Core High Dividend ETF
JEPI	JPMorgan Equity Premium Income ETF
JEPQ	JPMorgan Nasdaq Equity Premium Income ETF
VNQ	Vanguard Real Estate ETF
GLD	SPDR Gold Shares
IAU	iShares Gold Trust Shares
SLV	iShares Silver Trust
TLT	iShares 20+ Year Treasury Bond ETF
IEF	iShares 7-10 Year Treasury Bond ETF
SHY	iShares 1-3 Year Treasury Bond ETF
AGG	iShares Core U.S. Aggregate Bond ETF
BND	Vanguard Total Bond Market ETF
LQD	iShares iBoxx $ Investment Grade Corporate Bond ETF
HYG	iShares iBoxx $ High Yield Corporate Bond ETF
EEM	iShares MSCI Emerging Index Fund
VEA	Vanguard FTSE Developed Markets ETF
EFA	iShares MSCI EAFE ETF
XLK	State Street Technology Select Sector SPDR ETF
XLF	State Street Financial Select Sector SPDR ETF
XLV	State Street Health Care Select Sector SPDR ETF
XLE	State Street Energy Select Sector SPDR ETF
SMH	VanEck Semiconductor ETF
SOXX	iShares PHLX SOX Semiconductor Sector Index Fund
AGNG	Global X Aging Population ETF
BAB	Invesco Taxable Municipal Bond ETF
BBAG	JPMorgan BetaBuilders U.S. Aggregate Bond ETF
BIL	State Street SPDR Bloomberg 1-3 Month T-Bill ETF
FNDA	Schwab Fundamental U.S. Small Company ETF
AFK	VanEck Africa Index ETF
BIV	Vanguard Intermediate-Term Bond ETF
AGGY	WisdomTree Yield Enhanced U.S. Aggregate Bond Fund
AAXJ	iShares MSCI All Country Asia ex Japan ETF
AIQ	Global X Artificial Intelligence & Technology ETF
BKLN	Invesco Senior Loan ETF
BBAX	JPMorgan BetaBuilders Developed Asia Pacific-ex Japan ETF
BILS	State Street SPDR Bloomberg 3-12 Month T-Bill ETF
FNDB	Schwab Fundamental U.S. Broad Market ETF
ANGL	VanEck Fallen Angel High Yield Bond ETF
BLV	Vanguard Long-Term Bond ETF
AGZD	WisdomTree Interest Rate Hedged U.S. Aggregate Bond Fund
ACWI	iShares MSCI ACWI ETF
ALTY	Global X Alternative Income ETF
BMVP	Invesco Bloomberg MVP Multi-factor ETF
BBCA	JPMorgan BetaBuilders Canada ETF
BWX	State Street SPDR Bloomberg International Treasury Bond ETF
FNDC	Schwab Fundamental International Small Equity ETF
BBH	VanEck Biotech ETF
AIVI	WisdomTree International AI Enhanced Value Fund
ACWV	iShares MSCI Global Min Vol Factor ETF
AQWA	Global X Clean Water ETF
BSCA	Invesco BulletShares 2036 Corporate Bond ETF
BBCB	JPMorgan BetaBuilders USD Investment Grade Corporate Bond ETF
BWZ	State Street SPDR Bloomberg Short Term International Treasury Bond ETF
FNDE	Schwab Fundamental Emerging Markets Equity ETF
BIZD	VanEck BDC Income ETF
BNDP	Vanguard Core-Plus Bond Index ETF
AIVL	WisdomTree U.S. AI Enhanced Value Fund
ACWX	iShares MSCI ACWI ex U.S. ETF
ARGT	Global X MSCI Argentina ETF
BSCQ	Invesco BulletShares 2026 Corporate Bond ETF
BBEM	JPMorgan BetaBuilders Emerging Markets Equity ETF
CERY	State Street SPDR Bloomberg Enhanced Roll Yield Commodity Strategy No K-1 ETF
FNDF	Schwab Fundamental International Equity ETF
BRF	VanEck Brazil Small-Cap ETF
BNDW	Vanguard Total World Bond ETF
BTCW	WisdomTree Bitcoin Fund 
ASEA	Global X FTSE Southeast Asia ETF
BSCR	Invesco BulletShares 2027 Corporate Bond ETF
BBEU	JPMorgan BetaBuilders Europe ETF
CNRG	State Street SPDR S&P Kensho Clean Power ETF
FNDX	Schwab Fundamental U.S. Large Company ETF
BUZZ	VanEck Social Sentiment ETF
BNDX	Vanguard Total International Bond ETF
CEW	WisdomTree Emerging Currency Strategy Fund
AGGM	iShares 1-10 Year U.S. Aggregate Bond ETF
AUAU	Global X Gold Miners ETF
BSCS	Invesco BulletShares 2028 Corporate Bond ETF
BBHY	JPMorgan BetaBuilders USD High Yield Corporate Bond ETF
CWB	State Street SPDR Bloomberg Convertible Securities ETF
SCCR	Schwab Core Bond ETF
CBON	VanEck China Bond ETF
BSV	Vanguard Short-Term Bond ETF
CXSE	WisdomTree China ex-State-Owned Enterprises Fund
AGZ	iShares  Agency Bond ETF
AUSF	Global X Adaptive U.S. Factor ETF
BSCT	Invesco BulletShares 2029 Corporate Bond ETF
BBIB	JPMorgan BetaBuilders U.S. Treasury Bond 3-10 Year ETF
CWI	State Street SPDR MSCI ACWI ex-US ETF
SCHA	Schwab U.S. Small-Cap ETF
CLOB	VanEck AA-BB CLO ETF
EDV	Vanguard Extended Duration Treasury ETF
DDLS	WisdomTree Dynamic International SmallCap Equity Fund
AIA	iShares Asia 50 ETF
BCCC	Global X Bitcoin Covered Call ETF
BSCU	Invesco BulletShares 2030 Corporate Bond ETF
BBIN	JPMorgan BetaBuilders International Equity ETF
DGT	State Street SPDR Global Dow ETF
SCHB	Schwab U.S. Broad Market ETF
CLOI	VanEck CLO ETF
ESGV	Vanguard ESG U.S. Stock ETF
DDWM	WisdomTree Dynamic International Equity Fund
AOA	iShares Core 80/20 Aggressive Allocation ETF
BITS	Global X Blockchain & Bitcoin Strategy ETF
BSCV	Invesco BulletShares 2031 Corporate Bond ETF
BBJP	JPMorgan BetaBuilders Japan ETF
SCHC	Schwab International Small-Cap Equity ETF
CMCI	VanEck CMCI Commodity Strategy ETF
IVOG	Vanguard S&P Mid-Cap 400 Growth ETF
DEM	WisdomTree Emerging Markets High Dividend Fund
AOK	iShares Core 30/70 Conservative Allocation ETF
BKCH	Global X Blockchain ETF
BSCW	Invesco BulletShares 2032 Corporate Bond ETF
BBLB	JPMorgan BetaBuilders U.S. Treasury Bond 20+ Year ETF
DWX	State Street SPDR S&P International Dividend ETF
CNXT	VanEck ChiNext Innovators ETF
IVOO	Vanguard S&P Mid-Cap 400 ETF
DES	WisdomTree U.S. SmallCap Dividend Fund
AOM	iShares Core 40/60 Moderate Allocation ETF
BOTZ	Global X Robotics & Artificial Intelligence ETF
BSCX	Invesco BulletShares 2033 Corporate Bond ETF
BBMC	JPMorgan BetaBuilders U.S. Mid Cap Equity ETF
EBND	State Street SPDR Bloomberg Emerging Markets Local Bond ETF
SCHE	Schwab Emerging Markets Equity ETF
CRAK	VanEck Oil Refiners ETF
IVOV	Vanguard S&P Mid-Cap 400 Value ETF
DEW	WisdomTree Global High Dividend Fund
AOR	iShares Core 60/40 Balanced Allocation ETF
BRAZ	Global X Brazil Active ETF
BSCY	Invesco BulletShares 2034 Corporate Bond ETF
BBRE	JPMorgan BetaBuilders MSCI U.S. REIT ETF
EDIV	State Street SPDR S&P Emerging Markets Dividend ETF
SCHF	Schwab International Equity ETF
DAPP	VanEck Digital Transformation ETF
MGC	Vanguard Morningstar Mega Cap ETF
DFE	WisdomTree Europe SmallCap Dividend Fund
AQLT	iShares MSCI Global Quality Factor ETF
BTRN	Global X Bitcoin Trend Strategy ETF
BSCZ	Invesco BulletShares 2035 Corporate Bond ETF
BBSB	JPMorgan BetaBuilders U.S. Treasury Bond 1-3 Year ETF
EEMX	State Street SPDR MSCI Emerging Markets Fossil Fuel Reserves Free ETF
SCHG	Schwab U.S. Large-Cap Growth ETF
DESK	VanEck Office and Commercial REIT ETF
MGK	Vanguard Morningstar Mega Cap Growth ETF
DFJ	WisdomTree Japan SmallCap Fund
ARTY	iShares Future AI & Tech ETF
BUG	Global X Cybersecurity ETF
BSGR	Invesco BulletShares 2027 Treasury Bond ETF
BBSC	JPMorgan BetaBuilders U.S. Small Cap Equity ETF
EFAX	State Street SPDR MSCI EAFE Fossil Fuel Reserves Free ETF
SCHH	Schwab U.S. REIT ETF
DGIN	VanEck Digital India ETF
MGV	Vanguard Morningstar Mega Cap Value ETF
DGRE	WisdomTree Emerging Markets Quality Dividend Growth Fund
BAI	iShares A.I. Innovation and Tech Active ETF
CATH	Global X S&P 500 Catholic Values ETF
BSGT	Invesco BulletShares 2029 Treasury Bond ETF
BBUS	JPMorgan BetaBuilders U.S. Equity ETF
EFIV	State Street SPDR S&P 500 ESG ETF
SCHI	Schwab 5-10 Year Corporate Bond ETF
DURA	VanEck Durable High Dividend ETF
MUNY	Vanguard New York Tax-Exempt Bond ETF
DGRS	WisdomTree U.S. SmallCap Quality Dividend Growth Fund
BALI	iShares U.S. Large Cap Premium Income Active ETF
CEFA	Global X S&P Catholic Values Developed ex-U.S. ETF
BSJQ	Invesco BulletShares 2026 High Yield Corporate Bond ETF
HELO	JPMorgan Hedged Equity Laddered Overlay ETF
EMHC	State Street SPDR Bloomberg Emerging Markets USD Bond ETF
SCHJ	Schwab 1-5 Year Corporate Bond ETF
EINC	VanEck Energy Income ETF
VAW	Vanguard Materials ETF
DGRW	WisdomTree U.S. Quality Dividend Growth Fund
BALQ	iShares Nasdaq Premium Income Active ETF
CHIQ	Global X MSCI China Consumer Discretionary ETF
BSJR	Invesco BulletShares 2027 High Yield Corporate Bond ETF
HEQQ	JPMorgan Nasdaq Hedged Equity Laddered Overlay ETF
EWX	State Street SPDR S&P Emerging Markets Small Cap ETF
SCHK	Schwab 1000 Index ETF
EMBX	VanEck Emerging Markets Bond ETF
VB	Vanguard Morningstar Small-Cap ETF
DGS	WisdomTree Emerging Market SmallCap Fund
BCLO	iShares BBB-B CLO Active ETF
CHPX	Global X AI Semiconductor & Quantum ETF
BSJS	Invesco BulletShares 2028 High Yield Corporate Bond ETF
HOLA	JPMorgan International Hedged Equity Laddered Overlay ETF
FEZ	State Street SPDR EURO STOXX 50 ETF
SCHM	Schwab U.S. Mid Cap ETF
EMET	VanEck Copper and Electrification Metals ETF
VBCA	Vanguard Target Maturity 2027 Corporate Bond ETF
DHS	WisdomTree U.S. High Dividend Fund
BDVL	iShares Disciplined Volatility Equity Active ETF
CHRI	Global X S&P 500 Christian Values ETF
BSJT	Invesco BulletShares 2029 High Yield Corporate Bond ETF
JADE	JPMorgan Active Developing Markets Equity ETF
FITE	State Street SPDR S&P Kensho Future Security ETF
SCHO	Schwab Short-Term U.S. Treasury ETF
EMLC	VanEck J. P. Morgan EM Local Currency Bond ET
VBCB	Vanguard Target Maturity 2028 Corporate Bond ETF
DIM	WisdomTree International MidCap Dividend Fund
BDYN	iShares Dynamic Equity Active ETF
CLIP	Global X 1-3 Month T-Bill ETF
BSJU	Invesco BulletShares 2030 High Yield Corporate Bond ETF
JAVA	JPMorgan Active Value ETF
FLRN	State Street SPDR Bloomberg Investment Grade Floating Rate ETF
SCHP	Schwab U.S. TIPS ETF
ESPO	VanEck Video Gaming and eSports ETF
VBCC	Vanguard Target Maturity 2029 Corporate Bond ETF
DLN	WisdomTree U.S. LargeCap Dividend Fund
BEMB	iShares J.P. Morgan Broad USD Emerging Markets Bond ETF
CLOU	Global X Cloud Computing ETF
BSJV	Invesco BulletShares 2031 High Yield Corporate Bond ETF
JBND	JPMorgan Active Bond ETF
GII	State Street SPDR S&P Global Infrastructure ETF
SCHQ	Schwab Long-Term U.S. Treasury ETF
ETHV	VanEck Ethereum ETF
VBCD	Vanguard Target Maturity 2030 Corporate Bond ETF
DLS	WisdomTree International SmallCap Fund
BFLX	iShares Flexible Equity Active ETF
COLO	Global X MSCI Colombia ETF
BSJW	Invesco BulletShares 2032 High Yield Corporate Bond ETF
JCAL	JPMorgan California Tax Free Bond ETF
SCHR	Schwab Intermediate-Term U.S. Treasury ETF
EVX	VanEck Environmental Services ETF
VBCE	Vanguard Target Maturity 2031 Corporate Bond ETF
DNL	WisdomTree Global ex-U.S. Quality Growth Fund
BGRN	iShares USD Green Bond ETF
COMD	Global X Commodity Strategy ETF
BSJX	Invesco BulletShares 2033 High Yield Corporate Bond ETF
JCHI	JPMorgan Active China ETF
GMF	State Street SPDR S&P Emerging Asia Pacific ETF
SCHV	Schwab U.S. Large-Cap Value ETF
FLTR	VanEck IG Floating Rate ETF
VBCF	Vanguard Target Maturity 2032 Corporate Bond ETF
DOL	WisdomTree True Developed International Fund
BGRO	iShares Large Cap Growth Active ETF
COPX	Global X Copper Miners ETF
BSJY	Invesco BulletShares 2034 High Yield Corporate Bond ETF
JCPB	JPMorgan Core Plus Bond ETF
GNR	State Street SPDR S&P Global Natural Resources ETF
SCHX	Schwab U.S. Large-Cap ETF
GDX	VanEck Gold Miners ETF
VBCG	Vanguard Target Maturity 2033 Corporate Bond ETF
DON	WisdomTree U.S. MidCap Dividend Fund
BIDD	iShares International Dividend Active ETF
CPTL	Global X Morningstar Capital Allocation Leaders ETF
BSMQ	Invesco BulletShares 2026 Municipal Bond ETF
JCPI	JPMorgan Inflation Managed Bond ETF
GWX	State Street SPDR S&P International Small Cap ETF
SCHY	Schwab International Dividend Equity ETF
GDXJ	VanEck Junior Gold Miners ETF
VBCH	Vanguard Target Maturity 2034 Corporate Bond ETF
DTD	WisdomTree U.S. Total Dividend Fund
BILT	iShares Infrastructure Active ETF
CTEC	Global X ClimateTech ETF
BSMR	Invesco BulletShares 2027 Municipal Bond ETF
JDIV	JPMorgan Dividend Leaders ETF
GXC	State Street SPDR S&P China ETF
SCHZ	Schwab US Aggregate Bond ETF
GENZ	VanEck Digital Native Economy ETF
VBCI	Vanguard Target Maturity 2035 Corporate Bond ETF
DTH	WisdomTree International High Dividend Fund
BINC	iShares Flexible Income Active ETF
DAX	Global X DAX Germany ETF
BSMS	Invesco BulletShares 2028 Municipal Bond ETF
JDOC	JPMorgan Healthcare Leaders ETF
HAIL	State Street SPDR S&P Kensho Smart Mobility ETF
SCMB	Schwab Municipal Bond ETF
GLIN	VanEck India Growth Leaders ETF
VBCJ	Vanguard Target Maturity 2036 Corporate Bond ETF
DWM	WisdomTree International Equity Fund
BITA	iShares Bitcoin Premium Income ETF
DIV	Global X Super Dividend ETF
BSMT	Invesco BulletShares 2029 Municipal Bond ETF
JEMA	JPMorgan ActiveBuilders Emerging Markets Equity ETF
HYMB	State Street SPDR Nuveen ICE High Yield Municipal Bond ETF
SCUS	Schwab Ultra-Short Income ETF
GPZ	VanEck Alternative Asset Manager ETF
VBIL	Vanguard 0-3 Month Treasury Bill ETF
DWMF	WisdomTree International Multifactor Fund
BKF	iShares MSCI BIC ETF
DJIA	Global X Dow 30 Covered Call ETF
BSMU	Invesco BulletShares 2030 Municipal Bond ETF
IBND	State Street SPDR Bloomberg International Corporate Bond ETF
SCYB	Schwab High Yield Bond ETF
GRNB	VanEck Green Bond ETF
VBK	Vanguard Morningstar Small-Cap Growth ETF
DXJ	WisdomTree Japan Hedged Equity Fund
BLCR	iShares Large Cap Core Active ETF
DRIV	Global X Autonomous & Electric Vehicles ETF
BSMV	Invesco BulletShares 2031 Municipal Bond ETF
JNK	State Street SPDR Bloomberg High Yield Bond ETF
SGVT	Schwab Government Money Market ETF
HAP	VanEck Natural Resources ETF
VBR	Vanguard Morningstar Small-Cap Value ETF
EES	WisdomTree U.S. SmallCap Fund
BLCV	iShares Large Cap Value Active ETF
DTCR	Global X Data Center & Digital Infrastructure ETF
BSMW	Invesco BulletShares 2032 Municipal Bond ETF
JFLI	JPMorgan Flexible Income ETF
KBE	State Street SPDR S&P Bank ETF
SMBS	Schwab Mortgage-Backed Securities ETF
HODL	VanEck Bitcoin Trust 
VCEB	Vanguard ESG U.S. Corporate Bond ETF
ELD	WisdomTree Emerging Markets Local Debt Fund
BMED	iShares Health Innovation Active ETF
DYLG	Global X Dow 30 Covered Call & Growth ETF
BSMY	Invesco BulletShares 2034 Municipal Bond ETF
JFLX	JPMorgan Flexible Debt ETF
KCE	State Street SPDR S&P Capital Markets ETF
STCE	Schwab Crypto Thematic Natural Language Processing ETF
HYD	VanEck High Yield Muni ETF
VCHY	Vanguard U.S. High-Yield Corporate Bond Index ETF
EMCB	WisdomTree Emerging Markets Corporate Bond Fund
BPAY	iShares FinTech Active ETF
EART	Global X Rare Earth & Critical Materials ETF
BSMZ	Invesco BulletShares 2035 Municipal Bond ETF
JGLO	JPMorgan Global Select Equity ETF
KIE	State Street SPDR S&P Insurance ETF
HYEM	VanEck Emerging Markets High Yield Bond ETF
VCIT	Vanguard Intermediate-Term Corporate Bond ETF
EMMF	WisdomTree Emerging Markets Multifactor Fund
BREM	iShares Emerging Markets Bond Active ETF
EBIZ	Global X E-commerce ETF
BSSX	Invesco BulletShares 2033 Municipal Bond ETF
JGRO	JPMorgan Active Growth ETF
KOMP	State Street SPDR S&P Kensho New Economies Composite ETF
IBOT	VanEck Robotics ETF
VCLT	Vanguard Long-Term Corporate Bond ETF
EPI	WisdomTree India Earnings Fund
BRHY	iShares High Yield Active ETF
EDGQ	Global X Nasdaq-100 Income Edge ETF
BSTS	Invesco BulletShares 2028 Treasury Bond ETF
JIDE	JPMorgan International Dynamic ETF
KRE	State Street SPDR S&P Regional Banking ETF
IDX	VanEck Indonesia Index ETF
VCR	Vanguard Consumer Discretion ETF
EPS	WisdomTree U.S. LargeCap Fund
BRLN	iShares Floating Rate Loan Active ETF
EDGX	Global X U.S. 500 Income Edge ETF
BSTU	Invesco BulletShares 2030 Treasury Bond ETF
JIG	JPMorgan International Growth ETF
LGLV	State Street SPDR US Large Cap Low Volatility Index ETF
IHY	VanEck International High Yield Bond ETF
VCRB	Vanguard Core Bond ETF
EUDG	WisdomTree Europe Quality Dividend Growth Fund
BRTR	iShares Total Return Active ETF
EFAS	Global X MSCI SuperDividend EAFE ETF
BSTV	Invesco BulletShares 2031 Treasury Bond ETF
JIRE	JPMorgan International Research Enhanced Equity ETF
LVLN	State Street SPDR S&P Leveraged Loan ETF
INDZ	VanEck India Select ETF
VCRM	Vanguard Core Tax-Exempt Bond ETF
EZM	WisdomTree U.S. MidCap Fund
BTOT	iShares Total USD Fixed Income Market ETF
EGLE	Global X S&P 500 U.S. Revenue Leaders ETF
BTCO	Invesco Galaxy Bitcoin ETF 
JIVE	JPMorgan International Value ETF
MDY	State Street SPDR S&P MIDCAP 400 ETF Trust
ISRA	VanEck Israel ETF
VCSH	Vanguard Short-Term Corporate Bond ETF
GCC	WisdomTree EnhancedContinuous Commodity Index Fund
BYLD	iShares Yield Optimized Bond ETF
EHCC	Global X Ethereum Covered Call ETF
CGW	Invesco S&P Global Water Index ETF
JLVP	JPMorgan U.S. Large Cap Value Plus ETF
MDYG	State Street SPDR S&P 400 Mid Cap Growth ETF
ITM	VanEck Intermediate Muni ETF
VDC	Vanguard Consumer Staples ETF
GDE	WisdomTree Efficient Gold Plus Equity Strategy Fund
CALI	iShares Short-Term California Muni Active ETF
EMBD	Global X Emerging Markets Bond ETF
CQQQ	Invesco China Technology ETF
JMEE	JPMorgan Small & Mid Cap Enhanced Equity ETF
MDYV	State Street SPDR S&P 400 Mid Cap Value ETF
JULV	VanEck U.S. Equity Buffer ETF - July
VDE	Vanguard Energy ETF
GDMN	WisdomTree Efficient Gold Plus Gold Miners Strategy Fund
CEMB	iShares J.P. Morgan EM Corporate Bond ETF
EMC	Global X Emerging Markets Great Consumer ETF
CSD	Invesco S&P Spin-Off ETF
JMHI	JPMorgan High Yield Municipal ETF
MMTM	State Street SPDR S&P 1500 Momentum Tilt ETF
LFEQ	VanEck Long/Flat Trend ETF
VDG	Vanguard Developed Markets ex-US Growth Index ETF
GDT	WisdomTree Efficient TIPS Plus Gold Fund
CLOA	iShares AAA CLO Active ETF
EMM	Global X Emerging Markets ex-China ETF
CSTK	Invesco Comstock Contrarian Equity ETF
JMMF	JPMorgan 100% U.S. Treasury Securities Money Market ETF
NANR	State Street SPDR S&P North American Natural Resources ETF
MBBB	VanEck Moody's Analytics BBB Corporate Bond ETF
VDIG	Vanguard Wellington Dividend Growth Active ETF
GTR	WisdomTree Target Range Fund
CMBS	iShares CMBS Bond ETF
FINX	Global X FinTech ETF
CUT	Invesco MSCI Global Timber ETF
JMOM	JPMorgan U.S. Momentum Factor ETF
NZAC	State Street SPDR MSCI ACWI Climate Paris Aligned ETF
MIG	VanEck Moody's Analytics IG Corporate Bond ETF
VDV	Vanguard Developed Markets ex-US Value Index ETF
HEDJ	WisdomTree Europe Hedged Equity Fund
CMDY	iShares Bloomberg Roll Select Commodity Strategy ETF
FLAG	Global X S&P 500 U.S. Market Leaders Top 50 ETF
CVY	Invesco Zacks Multi-Asset Income ETF
JMSI	JPMorgan Sustainable Municipal Income ETF
ONEO	State Street SPDR Russell 1000 Momentum Focus ETF
MLN	VanEck Long Muni ETF
HYIN	WisdomTree Private Credit and Alternative Income Fund
CMF	iShares California Muni Bond ETF
FLOW	Global X U.S. Cash Flow Kings 100 ETF
CZA	Invesco Zacks Mid-Cap ETF
JMST	JPMorgan Ultra-Short Municipal Income ETF
ONEV	State Street SPDR Russell 1000 Low Volatility Focus ETF
MOAT	VanEck Morningstar Wide Moat ETF
VEU	Vanguard FTSE All World Ex US ETF
HYZD	WisdomTree Interest Rate Hedged High Yield Bond Fund
CNYA	iShares MSCI China A ETF
GNOM	Global X Genomics & Biotechnology ETF
DBA	Invesco DB Agriculture Fund
JMTG	JPMorgan Mortgage-Backed Securities ETF
ONEY	State Street SPDR Russell 1000 Yield Focus ETF
MOO	VanEck Agribusiness ETF
VEXC	Vanguard Emerging Markets Ex-China ETF
IHDG	WisdomTree International Hedged Quality Dividend Growth Fund
COMT	iShares GSCI Commodity Dynamic Roll Strategy ETF
GOEX	Global X Gold Explorers ETF
DBB	Invesco DB Base Metals Fund
JMUB	JPMorgan Municipal ETF
PSK	State Street SPDR ICE Preferred Securities ETF
MORT	VanEck Mortgage REIT Income ETF
VFH	Vanguard Financials ETF
INDH	WisdomTree India Hedged Equity Fund
CORO	iShares International Country Rotation Active ETF
GREK	Global X MSCI Greece ETF
DBC	Invesco DB Commodity Index Tracking Fund
JOYT	JPMorgan Equity and Options Total Return ETF
QEFA	State Street SPDR MSCI EAFE StrategicFactors ETF
MOTG	VanEck Morningstar Global Wide Moat ETF
VFMF	Vanguard U.S. Multifactor ETF
IQDG	WisdomTree International Quality Dividend Growth Fund
CRBN	iShares Low Carbon Optimized MSCI ACWI ETF
GURU	Global X Guru Index ETF
DBE	Invesco DB Energy Fund
JPEF	JPMorgan Equity Focus ETF
QEMM	State Street SPDR MSCI Emerging Markets StrategicFactors ETF
MOTI	VanEck Morningstar International Moat ETF
VFMO	Vanguard U.S. Momentum Factor ETF
MTGP	WisdomTree Mortgage Plus Bond Fund
CSHP	iShares Dynamic Short-Term Active ETF
GXDW	Global X Dorsey Wright Thematic ETF
DBO	Invesco DB Oil Fund
JPEM	JPMorgan Diversified Return Emerging Markets Equity ETF
QNDX	State Street SPDR Portfolio Nasdaq 100 ETF
MVAL	VanEck Morningstar Wide Moat Value ETF
VFMV	Vanguard U.S. Minimum Volatility ETF
NTSD	WisdomTree Efficient U.S. Plus International Equity Fund
DGRO	iShares Core Dividend Growth ETF
GXIG	Global X Investment Grade Corporate Bond ETF
DBP	Invesco DB Precious Metals Fund
JPFP	JPMorgan Managed Futures Plus ETF
QUS	State Street SPDR MSCI USA StrategicFactors ETF
NLR	VanEck Uranium and Nuclear ETF
VFQY	Vanguard U.S. Quality Factor ETF
NTSE	WisdomTree Emerging Markets Efficient Core Fund
DIVB	iShares Core Dividend ETF
GXLC	Global X U.S. 500 ETF
DIVG	Invesco S&P 500 High Dividend Growers ETF
JPHY	JPMorgan Active High Yield ETF
QWLD	State Street SPDR MSCI World StrategicFactors ETF
NODE	VanEck Onchain Economy ETF
VFVA	Vanguard U.S. Value Factor ETF
NTSI	WisdomTree International Efficient Core Fund
DMAX	iShares Large Cap Max Buffer Dec ETF
GXPC	Global X PureCap MSCI Communication Services ETF
DJD	Invesco Dow Jones Industrial Average Dividend ETF
JPIB	JPMorgan International Bond Opportunities ETF
ROKT	State Street SPDR S&P Kensho Final Frontiers ETF
OIH	VanEck Oil Services ETF
VGHY	Vanguard High-Yield Active ETF
NTSX	WisdomTree U.S. Efficient Core Fund
DMXF	iShares ESG Advanced MSCI EAFE ETF
GXPD	Global X PureCap MSCI Consumer Discretionary ETF
DVVY	Invesco Diversified Dividend Opportunities ETF
JPIE	JPMorgan Income ETF
RWO	State Street SPDR Dow Jones Global Real Estate ETF
OUNZ	VanEck Merk Gold ETF
VGIT	Vanguard Intermediate-Term Treasury ETF
OPPE	WisdomTree European Opportunities Fund
DSI	iShares ESG MSCI KLD 400 ETF
GXPE	Global X PureCap MSCI Energy ETF
DWAS	Invesco Dorsey Wright SmallCap Momentum ETF
JPIN	JPMorgan Diversified Return International Equity ETF
RWR	State Street SPDR Dow Jones REIT ETF
PFXF	VanEck Preferred Securities ex Financials ETF
VGK	Vanguard FTSEEuropean ETF
OPPG	WisdomTree GeoAlpha Opportunities Fund
GXPS	Global X PureCap MSCI Consumer Staples ETF
EELV	Invesco S&P Emerging Markets Low Volatility ETF
JPLD	JPMorgan Limited Duration Bond ETF
RWX	State Street SPDR Dow Jones International Real Estate ETF
PIT	VanEck Commodity Strategy ETF
VGLT	Vanguard Long-Term Treasury ETF
OPPJ	WisdomTree Japan Opportunities Fund
DVYA	iShares Asia / Pacific Dividend 30 Index Fund Exchange Traded Fund
GXPT	Global X PureCap MSCI Information Technology ETF
EEMO	Invesco S&P Emerging Markets Momentum ETF
JPMB	JPMorgan USD Emerging Markets Sovereign Bond ETF
SDY	State Street SPDR S&P Dividend ETF
PPH	VanEck Pharmaceutical ETF
VGMS	Vanguard Multi-Sector Income Bond ETF
QGRW	WisdomTree U.S. Quality Growth Fund
DVYE	iShares Emerging Markets Dividend Index Fund Exchange Traded Fund
HEAL	Global X HealthTech ETF
EFAA	Invesco MSCI EAFE Income Advantage ETF
JPME	JPMorgan Diversified Return U.S. Mid Cap Equity ETF
SHE	State Street SPDR MSCI USA Gender Diversity ETF
RAAX	VanEck Real Assets ETF
VGSH	Vanguard Short-Term Treasury ETF
QHY	WisdomTree U.S. High Yield Corporate Bond Fund
DYNF	iShares U.S. Equity Factor Rotation Active ETF
HERO	Global X Video Games & Esports ETF
EQAL	Invesco Russell 1000 Equal Weight ETF
JPRE	JPMorgan Realty Income ETF
SHM	State Street SPDR Nuveen ICE Short Term Municipal Bond ETF
RACK	VanEck Data Center Supply Chain ETF
VGT	Vanguard Information Tech ETF
QIG	WisdomTree U.S. Corporate Bond Fund
EAGG	iShares ESG Aware U.S. Aggregate Bond ETF
HYDR	Global X Hydrogen ETF
EQWL	Invesco S&P 100 Equal Weight ETF
JPRF	JPMorgan Preferred and Income Securities ETF
SIMS	State Street SPDR S&P Kensho Intelligent Structures ETF
REMX	VanEck Rare Earth and Strategic Metals ETF
VGUS	Vanguard Ultra-Short Treasury ETF
QMID	WisdomTree U.S. MidCap Quality Growth Fund
ECH	iShares MSCI Chile ETF
IPAV	Global X Infrastructure Development ex-U.S. ETF
ERTH	Invesco MSCI Sustainable Future ETF
JPSE	JPMorgan Diversified Return U.S. Small Cap Equity ETF
SJNK	State Street SPDR Bloomberg Short Term High Yield Bond ETF
RTH	VanEck Retail ETF
VGVT	Vanguard Government Securities Active ETF
QSIG	WisdomTree U.S. Short Term Corporate Bond Fund
ECNS	iShares MSCI China Small-Cap ETF
IRVH	Global X Interest Rate Volatility & Inflation Hedge ETF
EVMT	Invesco Electric Vehicle Metals Commodity Strategy No K-1 ETF
JPST	JPMorgan Ultra-Short Income ETF
SLYG	State Street SPDR S&P 600 Small Cap Growth ETF
SHYD	VanEck Short High Yield Muni ETF
VHT	Vanguard Health Care ETF
QSML	WisdomTree U.S. SmallCap Quality Growth Fund
EDEN	iShares MSCI Denmark ETF
KROP	Global X AgTech & Food Innovation ETF
FDIQ	Invesco Bloomberg Financial Data Providers ETF
JPSV	JPMorgan Active Small Cap Value ETF
SLYV	State Street SPDR S&P 600 Small Cap Value ETF
SLX	VanEck Steel ETF
VIG	Vanguard Div Appreciation ETF
SHAG	WisdomTree Yield Enhanced U.S. Short-Term Aggregate Bond Fund
LIT	Global X Lithium & Battery Tech ETF
FLXI	Invesco Flexible Income ETF
JPUS	JPMorgan Diversified Return U.S. Equity ETF
SMLV	State Street SPDR US Small Cap Low Volatility Index ETF
SMB	VanEck Short Muni ETF
VIGI	Vanguard International Dividend Appreciation ETF
UNIY	WisdomTree Voya Yield Enhanced USD Universal Bond Fund
EEMA	iShares MSCI Emerging Markets Asia ETF
LLDR	Global X Long-Term Treasury Ladder ETF
FXA	Invesco CurrencyShares Australian Dollar Trust
JQUA	JPMorgan U.S. Quality Factor ETF
SPAB	State Street SPDR Portfolio Aggregate Bond ETF
VIOG	Vanguard S&P Small-Cap 600 Growth ETF
USDU	WisdomTree Bloomberg U.S. Dollar Bullish Fund
EEMS	iShares MSCI Emerging Markets Small Cap ETF
LNGX	Global X U.S. Natural Gas ETF
FXB	Invesco CurrencyShares British Pound Sterling Trust
JSCP	JPMorgan Short Duration Core Plus ETF
SPBO	State Street SPDR Portfolio Corporate Bond ETF
SMHC	VanEck China Semiconductor ETF
VIOO	Vanguard S&P Small-Cap 600 ETF
USFR	WisdomTree Floating Rate Treasury Fund
EEMV	iShares MSCI Emerging Markets Min Vol Factor ETF
MILN	Global X Millennial Consumer ETF
FXC	Invesco CurrencyShares Canadian Dollar Trust
JTEK	JPMorgan U.S. Tech Leaders ETF
SPDG	State Street SPDR Portfolio S&P Sector Neutral Dividend ETF
SMHX	VanEck Fabless Semiconductor ETF
VIOV	Vanguard S&P Small-Cap 600 Value ETF
USIN	WisdomTree 7-10 Year Laddered Treasury Fund
MLDR	Global X Intermediate-Term Treasury Ladder ETF
FXE	Invesco CurrencyShares Euro Currency Trust
JTNY	JPMorgan New York Tax Free Bond ETF
SPDW	State Street SPDR Portfolio Developed World ex-US ETF
SMOG	VanEck Low Carbon Energy ETF
VIS	Vanguard Industrials ETF
USMF	WisdomTree U.S. Multifactor Fund
EFAV	iShares MSCI EAFE Min Vol Factor ETF
MLPA	Global X MLP ETF
FXF	Invesco CurrencyShares Swiss Franc Trust
JUSA	JPMorgan U.S. Research Enhanced Large Cap ETF
SPEM	State Street SPDR Portfolio Emerging Markets ETF
SMOT	VanEck Morningstar SMID Moat ETF
VMBS	Vanguard Mortgage-Backed Securities ETF
USSH	WisdomTree 1-3 Year Laddered Treasury Fund
EFG	iShares MSCI EAFE Growth ETF
MLPD	Global X MLP & Energy Infrastructure Covered Call ETF
FXY	Invesco CurrencyShares Japanese Yen Trust
JVAL	JPMorgan U.S. Value Factor ETF
SPEU	State Street SPDR Portfolio Europe ETF
TRUC	VanEck Communication Services TruSector ETF
WAMA	WisdomTree US Adaptive Moving Average Fund
EFNL	iShares MSCI Finland ETF
MLPX	Global X MLP & Energy Infrastructure ETF
GGME	Invesco Next Gen Media and Gaming ETF
LCDS	JPMorgan Fundamental Data Science Large Core ETF
SPGM	State Street SPDR Portfolio MSCI Global Stock Market ETF
TRUD	VanEck Consumer Discretionary TruSector ETF
VNQI	Vanguard Global ex-U.S. Real Estate ETF
WCBR	WisdomTree Cybersecurity Fund
EFRA	iShares Environmental Infrastructure and Industrials ETF
NDIA	Global X India Active ETF
GOVI	Invesco Equal Weight 0-30 Year Treasury ETF
LGDS	JPMorgan Fundamental Data Science Large Growth ETF
SPHY	State Street SPDR Portfolio High Yield Bond ETF
TRUF	VanEck Financials TruSector ETF
VO	Vanguard Morningstar Mid-Cap ETF
WCLD	WisdomTree Cloud Computing Fund
EFV	iShares MSCI EAFE Value ETF
NORW	Global X MSCI Norway ETF
GRPM	Invesco S&P MidCap 400 GARP ETF
LVDS	JPMorgan Fundamental Data Science Large Value ETF
SPIB	State Street SPDR Portfolio Intermediate Term Corporate Bond ETF
TRUH	VanEck Healthcare TruSector ETF
VOE	Vanguard Morningstar Mid-Cap Value ETF
WDAF	WisdomTree Asia Defense Fund
EGUS	iShares ESG Aware MSCI USA Growth ETF
NYSX	Global X NYSE 100 ETF
GRPZ	Invesco S&P SmallCap 600 GARP ETF
MCDS	JPMorgan Fundamental Data Science Mid Core ETF
SPIP	State Street SPDR Portfolio TIPS ETF
TRUI	VanEck Industrials TruSector ETF
VONE	Vanguard Russell 1000 ETF
WDEF	WisdomTree Europe Defense Fund
EIDO	iShares MSCI Indonesia ETF
ONOF	Global X Adaptive U.S. Risk Management ETF
GSY	Invesco Ultra Short Duration ETF
ROCQ	JPMorgan Nasdaq Equity Premium Yield ETF
SPLB	State Street SPDR Portfolio Long Term Corporate Bond ETF
TRUM	VanEck Materials TruSector ETF
VONG	Vanguard Russell 1000 Growth ETF
WDGF	WisdomTree Global Defense Fund
EIRL	iShares MSCI Ireland ETF
ORBX	Global X Space Tech ETF
GTO	Invesco Total Return Bond ETF
ROCY	JPMorgan Equity Premium Yield ETF
SPMB	State Street SPDR Portfolio Mortgage Backed Bond ETF
TRUN	VanEck Energy TruSector ETF
VONV	Vanguard Russell 1000 Value ETF
WDIG	WisdomTree Efficient Rare Earth Plus Strategic Metals Fund
EIS	iShares MSCI Israel ETF
PAVE	Global X U.S. Infrastructure Development ETF
GTOC	Invesco Core Fixed Income ETF
SCDS	JPMorgan Fundamental Data Science Small Core ETF
SPMD	State Street SPDR Portfolio S&P 400 Mid Cap ETF
TRUO	VanEck Consumer Staples TruSector ETF
WDNA	WisdomTree BioRevolution Fund
EMB	iShares J.P. Morgan USD Emerging Markets Bond ETF
PFFD	Global X U.S. Preferred ETF
GTOH	Invesco Short Duration High Yield ETF
SPSB	State Street SPDR Portfolio Short Term Corporate Bond ETF
TRUR	VanEck Real Estate TruSector ETF
VOOG	Vanguard S&P 500 Growth ETF
WDRN	WisdomTree Physical AI, Humanoids and Drones Fund
EMGF	iShares Emerging Markets Equity Factor ETF
PFFV	Global X Variable Rate Preferred ETF
GTOQ	Invesco High Yield Systematic Bond ETF
SPSM	State Street SPDR Portfolio S&P 600 Small Cap ETF
TRUT	VanEck Technology TruSector ETF
VOOV	Vanguard S&P 500 Value ETF
WIMA	WisdomTree International Adaptive Moving Average Fund
EMHY	iShares J.P. Morgan EM High Yield Bond ETF
QCLR	Global X NASDAQ 100 Collar 95-110 ETF
GTOS	Invesco Short Duration Total Return Bond ETF
SPTB	State Street SPDR Portfolio Treasury ETF
TRUU	VanEck Utilities TruSector ETF
VOT	Vanguard Morningstar Mid-Cap Growth ETF
WQTM	WisdomTree Quantum Computing Fund
EMIF	iShares Emerging Markets Infrastructure ETF
QDIV	Global X S&P 500 Quality Dividend ETF
HBRD	Invesco U.S. Hybrid Bond ETF
SPTI	State Street SPDR Portfolio Intermediate Term Treasury ETF
VAVX	VanEck Avalanche ETF
VOX	Vanguard Communication Services  ETF
WSPC	WisdomTree Space Economy Fund
EMXC	iShares MSCI Emerging Markets ex China ETF
QRMI	Global X NASDAQ 100 Risk Managed Income ETF
IBBQ	Invesco Nasdaq Biotechnology ETF
SPTL	State Street SPDR Portfolio Long Term Treasury ETF
VBNB	VanEck BNB ETF
VPL	Vanguard FTSE Pacific ETF
WTAI	WisdomTree Artificial Intelligence and Innovation Fund
EMXF	iShares ESG Advanced MSCI EM ETF
QTR	Global X NASDAQ 100 Tail Risk ETF
ICLO	Invesco AAA CLO Floating Rate Note ETF
SPTM	State Street SPDR Portfolio S&P 1500 Composite Stock Market ETF
VEFA	VanEck MSCI EAFE Analyst Sentiment ETF
VPLS	Vanguard Core Plus Bond ETF
WTBN	WisdomTree Bianco Total Return Fund
ENHI	iShares Enhanced International Active ETF
QYLD	Global X NASDAQ 100 Covered Call ETF
IDHQ	Invesco S&P International Developed Quality ETF
SPTS	State Street SPDR Portfolio Short Term Treasury ETF
VNM	VanEck Vietnam ETF
VPU	Vanguard Utilities ETF
WTIP	WisdomTree Inflation Plus Fund
ENHU	iShares Enhanced Large Cap Core Active ETF
QYLG	Global X Nasdaq 100 Covered Call & Growth ETF
IDLV	Invesco S&P International Developed Low Volatility ETF
SPTU	State Street SPDR Portfolio Ultra Short T-Bill ETF
VSOL	VanEck Solana ETF
VSDB	Vanguard Short Duration Bond ETF
WTLS	WisdomTree Efficient Long/Short U.S. Equity Fund
ENOR	iShares MSCI Norway ETF
RMHY	Global X Adaptive Risk Managed Yield ETF
IDMO	Invesco S&P International Developed Momentum ETF
WARP	VanEck Space ETF
VSDM	Vanguard Short Duration Tax-Exempt Bond ETF
WTMF	WisdomTree Managed Futures Strategy Fund
ENZL	iShares MSCI New Zealand ETF
RNRG	Global X Renewable Energy Producers ETF
IFLN	Invesco Bloomberg Enhanced Fallen Angels ETF
SPYD	State Street SPDR Portfolio S&P 500 High Dividend ETF
XMPT	VanEck CEF Muni Income ETF
VSGX	Vanguard ESG International Stock ETF
WTMU	WisdomTree Core Laddered Municipal Fund
EPHE	iShares MSCI Philippines ETF
RSSL	Global X Russell 2000 ETF
IGPT	Invesco AI and Next Gen Software ETF
SPYG	State Street SPDR Portfolio S&P 500 Growth ETF
VSS	Vanguard FTSE All-Wld ex-US SmCp Idx ETF
WTMY	WisdomTree High Income Laddered Municipal Fund
EPOL	iShares MSCI Poland ETF
RYLD	Global X Russell 2000 Covered Call ETF
IIGD	Invesco Investment Grade Defensive ETF
SPYM	State Street SPDR Portfolio S&P 500 ETF
VT	Vanguard Total World Stock Index ETF
WTPI	WisdomTree Equity Premium Income Fund
EPP	iShares MSCI Pacific Ex-Japan Index Fund
RYLG	Global X Russell 2000 Covered Call & Growth ETF
IMF	Invesco Managed Futures Strategy ETF
SPYV	State Street SPDR Portfolio S&P 500 Value ETF
VTC	Vanguard Total Corporate Bond ETF
WTRE	WisdomTree New Economy Real Estate Fund
EPU	iShares MSCI Peru and Global Exposure ETF
SDEM	Global X MSCI SuperDividend Emerging Markets ETF
IMFL	Invesco International Developed Dynamic Multifactor ETF
SPYX	State Street SPDR S&P 500 Fossil Fuel Reserves Free ETF
VTEB	Vanguard Tax-Exempt Bond ETF
WTV	WisdomTree U.S. Value Fund
EQLT	iShares MSCI Emerging Markets Quality Factor ETF
SDIV	Global X SuperDividend ETF
IMTG	Invesco Agency MBS ETF
TFI	State Street SPDR Nuveen ICE Municipal Bond ETF
VTEC	Vanguard California Tax-Exempt Bond ETF
XC	WisdomTree True Emerging Markets Fund
ERET	iShares Environmentally Aware Real Estate ETF
SHLD	Global X Defense Tech ETF
IMVP	Invesco India ETF
TIPX	State Street SPDR Bloomberg 1a??10 Year TIPS ETF
VTEI	Vanguard Tax-Managed Funds Vanguard Intermediate-Term Tax-Exempt Bond ETF
XSOE	WisdomTree Emerging Markets Ex-State Owned Enterprises Fund
ESGD	iShares ESG Aware MSCI EAFE ETF
SIL	Global X Silver Miners ETF
INTM	Invesco Intermediate Municipal ETF
UCBG	State Street SPDR UC Investments 90/10 Endowment Strategy Index ETF
VTEL	Vanguard Long-Term Tax-Exempt Bond ETF
ESGE	iShares ESG Aware MSCI EM ETF
SLDR	Global X Short-Term Treasury Ladder ETF
IPKW	Invesco International BuyBack Achievers ETF
VLU	State Street SPDR S&P 1500 Value Tilt ETF
VTES	Vanguard Wellington Fund Vanguard Short-Term Tax Exempt Bond ETF
ESGU	iShares ESG Aware MSCI USA ETF
SNSR	Global X Internet of Things ETF
IQSZ	Invesco Global Equity Net Zero ETF
WDIV	State Street SPDR S&P Global Dividend ETF
VTG	Vanguard Total Treasury ETF
ESML	iShares ESG Aware MSCI USA Small-Cap ETF
SOCL	Global X Social Media ETF
IROC	Invesco Rochester High Yield Municipal ETF
WIP	State Street SPDR FTSE International Government Inflation-Protected Bond ETF
VTHR	Vanguard Russell 3000 ETF
ESMV	iShares ESG Optimized MSCI USA Min Vol Factor ETF
SPFF	Global X SuperIncome Preferred ETF
IUS	Invesco RAFI Strategic US ETF
XAR	State Street SPDR S&P Aerospace & Defense ETF
ETEC	iShares Breakthrough Environmental Solutions ETF
SRET	Global X SuperDividend REIT ETF
KBWB	Invesco KBW Bank ETF
XBI	State Street SPDR S&P Biotech ETF
VTIP	Vanguard Short-Term Inflation-Protected Securities Index Fund ETF Shares
ETHA	iShares Ethereum Trust ETF
TLTX	Global X Treasury Bond Enhanced Income ETF
KBWD	Invesco KBW High Dividend Yield Financial ETF
XCNY	State Street SPDR S&P Emerging Markets ex-China ETF
VTP	Vanguard Total Inflation-Protected Securities ETF
ETHB	iShares Staked Ethereum Trust ETF
TYLG	Global X Information Technology Covered Call & Growth ETF
KBWP	Invesco KBW Property & Casualty Insurance ETF
XES	State Street SPDR S&P Oil & Gas Equipment & Services ETF
VTV	Vanguard Morningstar Value ETF
EUFN	iShares MSCI Europe Financials ETF
URA	Global X Uranium ETF
KBWY	Invesco KBW Premium Yield Equity REIT ETF
XHB	State Street SPDR S&P Homebuilders ETF
VTWG	Vanguard Russell 2000 Growth ETF
EUHY	iShares Euro High Yield Corporate Bond USD Hedged ETF
VNAM	Global X MSCI Vietnam ETF
KLMN	Invesco MSCI North America Climate ETF
XHE	State Street SPDR S&P Health Care Equipment ETF
VTWO	Vanguard Russell 2000 ETF
EUIG	iShares Euro Investment Grade Corporate Bond USD Hedged ETF
XCLR	Global X S&P 500 Collar 95-110 ETF
KLMT	Invesco MSCI Global Climate 500 ETF
XHS	State Street SPDR S&P Health Care Services ETF
VTWV	Vanguard Russell 2000 Value ETF
EUSA	iShares MSCI USA Equal Weighted ETF
XRMI	Global X S&P 500 Risk Managed Income ETF
KNCT	Invesco Next Gen Connectivity ETF
XITK	State Street SPDR FactSet Innovative Technology ETF
VUG	Vanguard Morningstar Growth ETF
EUSB	iShares ESG Advanced Universal USD Bond ETF
XTR	Global X S&P 500 Tail Risk ETF
MTRA	Invesco International Growth Focus ETF
XLB	State Street Materials Select Sector SPDR ETF
VUSB	Vanguard Ultra-Short Bond ETF
EVLU	iShares MSCI Emerging Markets Value Factor ETF
XYLD	Global X S&P 500 Covered Call ETF
OMFL	Invesco Russell 1000 Dynamic Multifactor ETF
XLBI	State Street Materials Select Sector SPDR Premium Income ETF
VUSG	Vanguard Wellington U.S. Growth Active ETF
EVUS	iShares ESG Aware MSCI USA Value ETF
XYLG	Global X S&P 500 Covered Call & Growth ETF
OMFS	Invesco Russell 2000 Dynamic Multifactor ETF
XLC	State Street Communication Services Select Sector SPDR ETF
VUSV	Vanguard Wellington U.S. Value Active ETF
EWA	iShares MSCI Australia Index Fund
ZAP	Global X U.S. Electrification ETF
PBD	Invesco Global Clean Energy ETF
XLCI	State Street Communication Services Select Sector SPDR Premium Income ETF
VV	Vanguard Morningstar Large-Cap ETF
EWC	iShares MSCI Canada Index Fund
ZCBA	Global X Zero Coupon Bond 2030 ETF
PBE	Invesco Biotechnology & Genome ETF
VWO	Vanguard FTSE Emerging Markets ETF
EWD	iShares MSCI Sweden ETF
ZCBB	Global X Zero Coupon Bond 2031 ETF
PBJ	Invesco Food & Beverage ETF
XLEI	State Street Energy Select Sector SPDR Premium Income ETF
VWOB	Vanguard Emerging Markets Government Bond ETF
EWG	iShares MSCI Germany Index Fund
ZCBC	Global X Zero Coupon Bond 2032 ETF
PBP	Invesco S&P 500 BuyWrite ETF
VXF	Vanguard Extended Market ETF
EWH	iShares MSCI Hong Kong Index Fund
ZCBE	Global X Zero Coupon Bond 2033 ETF
PBTP	Invesco 0-5 Yr US TIPS ETF
XLFI	State Street Financial Select Sector SPDR Premium Income ETF
VXUS	Vanguard Total International Stock ETF
EWI	iShares MSCI Italy ETF
ZCBF	Global X Zero Coupon Bond 2034 ETF
PBUS	Invesco MSCI USA ETF
XLI	State Street Industrial Select Sector SPDR ETF
EWJ	iShares MSCI Japan Index Fund
ZCBG	Global X Zero Coupon Bond 2035 ETF
PBW	Invesco WilderHill Clean Energy ETF
XLII	State Street Industrial Select Sector SPDR Premium Income ETF
VYMI	Vanguard International High Dividend Yield ETF
EWJV	iShares MSCI Japan Value ETF
PCEF	Invesco CEF Income Composite ETF
EWK	iShares MSCI Belgium ETF
PCY	Invesco Emerging Markets Sovereign Debt ETF
XLKI	State Street Technology Select Sector SPDR Premium Income ETF
EWL	iShares MSCI Switzerland ETF
PDBA	Invesco Agriculture Commodity Strategy No K-1 ETF
XLP	State Street Consumer Staples Select Sector SPDR ETF
EWM	iShares MSCI Malaysia Index Fund
PDBC	Invesco Optimum Yield Diversified Commodity Strategy No K-1 ETF
XLRE	State Street Real Estate Select Sector SPDR ETF
EWN	iShares MSCI Netherlands Index Fund
PDN	Invesco RAFI Developed Markets ex-U.S. Small-Mid ETF
XLRI	State Street Real Estate Select Sector SPDR Premium Income ETF
EWO	iShares MSCI Austria ETF
PDP	Invesco Dorsey Wright Momentum ETF
XLSI	State Street Consumer Staples Select Sector SPDR Premium Income ETF
EWP	iShares MSCI Spain ETF
PEJ	Invesco Leisure and Entertainment ETF
XLU	State Street Utilities Select Sector SPDR ETF
EWQ	iShares MSCI France Index Fund
PEY	Invesco High Yield Equity Dividend Achievers ETF
XLUI	State Street Utilities Select Sector SPDR Premium Income ETF
EWS	iShares MSCI Singapore ETF
PEZ	Invesco Dorsey Wright Consumer Cyclicals Momentum ETF
EWT	iShares MSCI Taiwan ETF
PFI	Invesco Dorsey Wright Financial Momentum ETF
XLVI	State Street Health Care Select Sector SPDR Premium Income ETF
EWU	iShares MSCI United Kingdom ETF
PFIG	Invesco Fundamental Investment Grade Corporate Bond  ETF
XLY	State Street Consumer Discretionary Select Sector SPDR ETF
EWUS	iShares MSCI United Kingdom Small Cap ETF
PFM	Invesco Dividend Achievers ETF
XLYI	State Street Consumer Discretionary Select Sector SPDR Premium Income ETF
EWW	iShares MSCI Mexico ETF
PGF	Invesco Financial Preferred ETF
XME	State Street SPDR S&P Metals & Mining ETF
EWY	iShares MSCI South Korea ETF
PGHY	Invesco Global ex-US High Yield Corporate Bond ETF
XNTK	State Street SPDR NYSE Technology ETF
EWZ	iShares MSCI Brazil ETF
PGJ	Invesco Golden Dragon China ETF
XOP	State Street SPDR S&P Oil & Gas Exploration & Production ETF
EWZS	iShares MSCI Brazil Small-Cap ETF
PGX	Invesco Preferred ETF
XPH	State Street SPDR S&P Pharmaceuticals ETF
EXI	iShares Global Industrials ETF
PHDG	Invesco S&P 500 Downside Hedged ETF
XRT	State Street SPDR S&P Retail ETF
EZA	iShares MSCI South Africa Index Fund
PHO	Invesco Water Resources ETF
XSD	State Street SPDR S&P Semiconductor ETF
EZU	iShares MSCI Eurozone ETF
PICB	Invesco International Corporate Bond ETF
XSW	State Street SPDR S&P Software & Services ETF
FALN	iShares Fallen Angels USD Bond ETF
PID	Invesco International Dividend Achievers ETF
XTL	State Street SPDR S&P Telecom ETF
FLOT	iShares Floating Rate Bond ETF
PIE	Invesco Dorsey Wright Emerging Markets Momentum ETF
XTN	State Street SPDR S&P Transportation ETF
FXI	iShares China Large-Cap ETF
PIO	Invesco Global Water ETF
GARP	iShares MSCI USA Quality GARP ETF
PIPE	Invesco SteelPath MLP & Energy Infrastructure ETF
GGOV	iShares Global Government Bond USD Hedged Active ETF
PIZ	Invesco Dorsey Wright Developed Markets Momentum ETF
GHYG	iShares US & Intl High Yield Corp Bond ETF
PJP	Invesco Pharmaceuticals ETF
GLDM	SPDR Gold MiniShares Trust
PKB	Invesco Building & Construction ETF
GLOF	iShares Global Equity Factor ETF
PKW	Invesco BuyBack Achievers ETF
GMMF	iShares Government Money Market ETF
PNQI	Invesco Nasdaq Internet ETF
GNMA	iShares GNMA Bond ETF
POWA	Invesco Bloomberg Pricing Power ETF
GOVM	iShares 1-10 Year Treasury Bond ETF
PPA	Invesco Aerospace & Defense ETF
GOVT	iShares U.S. Treasury Bond ETF
PRF	Invesco RAFI US 1000 ETF
GOVZ	iShares 25  Year Treasury STRIPS Bond ETF
PRFZ	Invesco RAFI US 1500 Small-Mid ETF
GSG	iShares GSCI Commodity-Indexed Trust Fund
PRN	Invesco Dorsey Wright Industrials Momentum ETF
GVI	iShares Intermediate Government/Credit Bond ETF
PSCC	Invesco S&P SmallCap Consumer Staples ETF
HAWX	iShares Currency Hedged MSCI ACWI ex U.S. ETF
PSCD	Invesco S&P SmallCap Consumer Discretionary ETF
PSCE	Invesco S&P SmallCap Energy ETF
HEEM	iShares Currency Hedged MSCI Emerging Markets ETF
PSCF	Invesco S&P SmallCap Financials ETF
HEFA	iShares Currency Hedged MSCI EAFE ETF
PSCH	Invesco S&P SmallCap Health Care ETF
HEWJ	iShares Currency Hedged MSCI Japan ETF
PSCI	Invesco S&P SmallCap Industrials ETF
HEZU	iShares Currency Hedged MSCI Eurozone ETF
PSCM	Invesco S&P SmallCap Materials ETF
HIMU	iShares High Yield Muni Active ETF
PSCT	Invesco S&P SmallCap Information Technology ETF
HSCZ	iShares Currency Hedged MSCI EAFE Small-Cap ETF
PSCU	Invesco S&P SmallCap Utilities & Communication Services ETF
HYBB	iShares BB Rated Corporate Bond ETF
PSI	Invesco Semiconductors ETF
HYDB	iShares High Yield Systematic Bond ETF
PSL	Invesco Dorsey Wright Consumer Staples Momentum ETF
PSP	Invesco Global Listed Private Equity ETF
HYGH	iShares Interest Rate Hedged High Yield Bond ETF
PSR	Invesco Active U.S. Real Estate Fund
HYGW	iShares High Yield Corporate Bond BuyWrite Strategy ETF
PTF	Invesco Dorsey Wright Technology Momentum ETF
HYXF	iShares ESG Advanced High Yield Corporate Bond ETF
PTH	Invesco Dorsey Wright Healthcare Momentum ETF
IAGG	iShares International Aggregate Bond Fund
PUI	Invesco Dorsey Wright Utilities Momentum ETF
IAI	iShares U.S. Broker-Dealers & Securities Exchanges ETF
PVI	Invesco Floating Rate Municipal Income ETF
IAK	iShares U.S. Insurance ETF
PWB	Invesco Large Cap Growth ETF
IALT	iShares Systematic Alternatives Active ETF
PWV	Invesco Large Cap Value ETF
IAT	iShares U.S. Regional Banks ETF
PWZ	Invesco California AMT-Free Municipal Bond Portfolio
PXE	Invesco Energy Exploration & Production ETF
IAUM	iShares Gold Trust Micro Shares
PXF	Invesco RAFI Developed Markets ex-U.S. ETF
IBAT	iShares Energy Storage & Materials ETF
PXH	Invesco RAFI Emerging Markets ETF
IBB	iShares Biotechnology ETF
PXI	Invesco Dorsey Wright Energy Momentum ETF
IBCA	iShares iBonds Dec 2035 Term Corporate ETF
PXJ	Invesco Oil & Gas Services ETF
IBCB	iShares iBonds Dec 2036 Term Corporate ETF
PYZ	Invesco Dorsey Wright Basic Materials Momentum ETF
IBDR	iShares iBonds Dec 2026 Term Corporate ETF
PZA	Invesco National AMT-Free Municipal Bond ETFo
IBDS	iShares iBonds Dec 2027 Term Corporate ETF
PZT	Invesco New York AMT-Free Municipal Bond ETF
IBDT	iShares iBonds Dec 2028 Term Corporate ETF
QBIG	Invesco Top QQQ ETF
IBDU	iShares iBonds Dec 2029 Term Corporate ETF
QETH	Invesco Galaxy Ethereum ETF
IBDV	iShares iBonds Dec 2030 Term Corporate ETF
QEW	Invesco QQQ Equal Weight ETF
IBDW	iShares iBonds Dec 2031 Term Corporate ETF
QOWZ	Invesco Nasdaq Free Cash Flow Achievers ETF
IBDX	iShares iBonds Dec 2032 Term Corporate ETF
QQA	Invesco QQQ Income Advantage ETF
IBDY	iShares iBonds Dec 2033 Term Corporate ETF
QQHG	Invesco QQQ Hedged Advantage ETF
IBDZ	iShares iBonds Dec 2034 Term Corporate ETF
QQLV	Invesco QQQ Low Volatility ETF
IBGA	iShares iBonds Dec 2044 Term Treasury ETF
QQMG	Invesco ESG NASDAQ 100 ETF
IBGB	iShares iBonds Dec 2045 Term Treasury ETF
IBGC	iShares iBonds Dec 2046 Term Treasury ETF
QQQJ	Invesco NASDAQ Next Gen 100 ETF
IBGK	iShares iBonds Dec 2054 Term Treasury ETF
QQQM	Invesco NASDAQ 100 ETF
IBGL	iShares iBonds Dec 2055 Term Treasury ETF
QQQS	Invesco NASDAQ Future Gen 200 ETF
IBGM	iShares iBonds Dec 2056 Term Treasury ETF
QSOL	Invesco Galaxy Solana ETF
IBHF	iShares iBonds 2026 Term High Yield and Income ETF
QVML	Invesco S&P 500 QVM Multi-factor ETF
IBHG	iShares iBonds 2027 Term High Yield and Income ETF
QVMM	Invesco S&P MidCap 400 QVM Multi-factor ETF
IBHH	iShares iBonds 2028 Term High Yield and Income ETF
QVMS	Invesco S&P SmallCap 600 QVM Multi-factor ETF
IBHI	iShares iBonds 2029 Term High Yield and Income ETF
QVMT	Invesco S&P 500 Concentrated QVM ETF
IBHJ	iShares iBonds 2030 Term High Yield and Income ETF
RDIV	Invesco S&P Ultra Dividend Revenue ETF
IBHK	iShares iBonds 2031 Term High Yield and Income ETF
RFG	Invesco S&P MidCap 400 Pure Growth ETF
IBHL	iShares iBonds 2032 Term High Yield and Income ETF
RFV	Invesco S&P MidCap 400 Pure Value ETF
IBHM	iShares iBonds 2033 Term High Yield and Income ETF
RPG	Invesco S&P 500 Pure Growth ETF
IBIC	iShares iBonds Oct 2026 Term TIPS ETF
RPV	Invesco S&P 500 Pure Value ETF
IBID	iShares iBonds Oct 2027 Term TIPS ETF
RSP	Invesco S&P 500 Equal Weight ETF
IBIE	iShares iBonds Oct 2028 Term TIPS ETF
RSPA	Invesco S&P 500 Equal Weight Income Advantage ETF
IBIF	iShares iBonds Oct 2029 Term TIPS ETF
RSPC	Invesco S&P 500 Equal Weight Communication Services ETF
IBIG	iShares iBonds Oct 2030 Term TIPS ETF
RSPD	Invesco S&P 500 Equal Weight Consumer Discretionary ETF
IBIH	iShares iBonds Oct 2031 Term TIPS ETF
RSPE	Invesco ESG S&P 500 Equal Weight ETF
IBII	iShares iBonds Oct 2032 Term TIPS ETF
RSPF	Invesco S&P 500 Equal Weight Financial ETF
IBIJ	iShares iBonds Oct 2033 Term TIPS ETF
RSPG	Invesco S&P 500 Equal Weight Energy ETF
IBIK	iShares iBonds Oct 2034 Term TIPS ETF
RSPH	Invesco S&P 500 Equal Weight Health Care ETF
IBIL	iShares iBonds Oct 2035 Term TIPS ETF
RSPM	Invesco S&P 500 Equal Weight Materials ETF
IBIM	iShares iBonds Oct 2036 Term TIPS ETF
RSPN	Invesco S&P 500 Equal Weight Industrials Portfolio
IBIT	iShares Bitcoin Trust ETF
RSPR	Invesco S&P 500 Equal Weight Real Estate ETF
IBLC	iShares Blockchain and Tech ETF
RSPS	Invesco S&P 500 Equal Weight Consumer Staples ETF
IBMO	iShares iBonds Dec 2026 Term Muni Bond ETF
RSPT	Invesco S&P 500 Equal Weight Technology ETF
IBMP	iShares iBonds Dec 2027 Term Muni Bond ETF
RSPU	Invesco S&P 500 Equal Weight Utilities ETF
IBMQ	iShares iBonds Dec 2028 Term Muni Bond ETF
RWJ	Invesco S&P SmallCap 600 Revenue ETF
IBMR	iShares iBonds Dec 2029 Term Muni Bond ETF
RWK	Invesco S&P MidCap 400 Revenue ETF
IBMS	iShares iBonds Dec 2030 Term Muni Bond ETF
RWL	Invesco S&P 500 Revenue ETF
IBMT	iShares iBonds Dec 2031 Term Muni Bond ETF
RZG	Invesco S&P SmallCap 600 Pure Growth ETF
IBMU	iShares iBonds Dec 2032 Term Muni Bond ETF
RZV	Invesco S&P SmallCap 600 Pure Value ETF
IBMV	iShares iBonds Dec 2033 Term Muni Bond ETF
SATO	Invesco Alerian Galaxy Crypto Economy ETF
IBMW	iShares iBonds Dec 2034 Term Muni Bond ETF
SOXQ	Invesco PHLX Semiconductor ETF
IBMX	iShares iBonds Dec 2035 Term Muni Bond ETF
SPGP	Invesco S&P 500 GARP ETF
IBRN	iShares Neuroscience and Healthcare ETF
SPHB	Invesco S&P 500 High Beta ETF
IBTG	iShares iBonds Dec 2026 Term Treasury ETF
SPHD	Invesco S&P 500 High Dividend Low Volatility ETF
IBTH	iShares iBonds Dec 2027 Term Treasury ETF
SPHQ	Invesco S&P 500 Quality ETF
IBTI	iShares iBonds Dec 2028 Term Treasury ETF
SPLV	Invesco S&P 500 Low Volatility ETF
IBTJ	iShares iBonds Dec 2029 Term Treasury ETF
SPMO	Invesco S&P 500 Momentum ETF
IBTK	iShares iBonds Dec 2030 Term Treasury ETF
SPVM	Invesco S&P 500 Value with Momentum ETF
IBTL	iShares iBonds Dec 2031 Term Treasury ETF
TAN	Invesco Solar ETF
IBTM	iShares iBonds Dec 2032 Term Treasury ETF
TBLL	Invesco Short Term Treasury ETF
IBTO	iShares iBonds Dec 2033 Term Treasury ETF
TROT	Invesco MSCI Treasury Duration Rotation ETF
IBTP	iShares iBonds Dec 2034 Term Treasury ETF
UDN	Invesco DB USD Index Bearish ETF
IBTQ	iShares iBonds Dec 2035 Term Treasury ETF
UPGD	Invesco Bloomberg Analyst Rating Improvers ETF
IBTR	iShares iBonds Dec 2036 Term Treasury ETF
UUP	Invesco DB USD Index Bullish Fund ETF
ICF	iShares Select U.S. REIT ETF
VRIG	Invesco Variable Rate Investment Grade ETF
ICLN	iShares Global Clean Energy ETF
VRP	Invesco Variable Rate Preferred ETF
ICOP	iShares Copper and Metals Mining ETF
XLG	Invesco S&P 500 Top 50 ETF
ICPI	iShares 0-1 Year TIPS Bond ETF
XMHQ	Invesco S&P MidCap Quality ETF
ICSH	iShares Ultra Short Duration Bond Active ETF
XMLV	Invesco S&P MidCap Low Volatility ETF
ICVT	iShares Convertible Bond ETF
XMMO	Invesco S&P MidCap Momentum ETF
IDEF	iShares Defense Industrials and Tech Active ETF
XMVM	Invesco S&P MidCap Value with Momentum ETF
IDEV	iShares Core MSCI International Developed Markets ETF
XSHD	Invesco S&P SmallCap High Dividend Low Volatility ETF
IDGT	iShares U.S. Digital Infrastructure and Real Estate ETF
XSHQ	Invesco S&P SmallCap Quality ETF
IDNA	iShares Genomics Immunology and Healthcare ETF
XSLV	Invesco S&P SmallCap Low Volatility ETF
IDRV	iShares Self-Driving EV and Tech ETF
XSMO	Invesco S&P SmallCap Momentum ETF
IDU	iShares U.S. Utilities ETF
XSVM	Invesco S&P SmallCap Value with Momentum ETF
IDV	iShares International Select Dividend ETF
IDYN	iShares International Equity Factor Rotation Active ETF
IEFA	iShares Core MSCI EAFE ETF
IEI	iShares 3-7 Year Treasury Bond ETF
IEMG	iShares Core MSCI Emerging Markets ETF
IEO	iShares U.S. Oil & Gas Exploration & Production ETF
IETC	iShares U.S. Tech Independence Focused ETF
IEUR	iShares Core MSCI Europe ETF
IEUS	iShares MSCI Europe Small-Cap ETF
IEV	iShares Europe ETF
IEZ	iShares U.S. Oil Equipment & Services ETF
IFGL	iShares International Developed Real Estate ETF
IFRA	iShares U.S. Infrastructure ETF
IGBH	iShares Interest Rate Hedged Long-Term Corporate Bond ETF
IGE	iShares North American Natural Resources ETF
IGEB	iShares Investment Grade Systematic Bond ETF
IGF	iShares Global Infrastructure ETF
IGIB	iShares 5-10 Year Investment Grade Corporate Bond ETF
IGLB	iShares 10  Year Investment Grade Corporate Bond ETF
IGM	iShares Expanded Tech Sector ETF
IGOV	iShares International Treasury Bond ETF
IGRO	iShares International Dividend Growth ETF
IGSB	iShares 1-5 Year Investment Grade Corporate Bond ETF
IGV	iShares Expanded Tech-Software Sector ETF
IHAK	iShares Cybersecurity and Tech ETF
IHE	iShares U.S. Pharmaceutical ETF
IHF	iShares U.S. Health Care Providers ETF
IHI	iShares U.S. Medical Devices ETF
IJH	iShares Core S&P Mid-Cap ETF
IJJ	iShares S&P Mid-Cap 400 Value ETF
IJK	iShares S&P Mid-Cap 400 Growth ETF
IJR	iShares Core S&P Small-Cap ETF
IJS	iShares S&P SmallCap 600 Value ETF
IJT	iShares S&P SmallCap 600 Growth ETF
ILCB	iShares Morningstar Large-Cap ETF
ILCG	iShares Morningstar Large-Cap Growth ETF
ILCV	iShares Morningstar Large-Cap  Value ETF
ILF	iShares Latin America 40 ETF
ILIT	iShares Lithium Miners and Producers ETF
ILTB	iShares Core 10  Year USD Bond ETF
IMCB	iShares Morningstar Mid-Cap ETF
IMCG	iShares Morningstar Mid-Cap Growth ETF
IMCV	iShares Morningstar Mid-Cap Value ETF
IMTB	iShares Core 5-10 Year USD Bond ETF
IMTM	iShares MSCI Intl Momentum Factor ETF
INDA	iShares MSCI India ETF
INDY	iShares India 50 ETF
INMU	iShares Intermediate Muni Income Active ETF
INRO	iShares U.S. Industry Rotation Active ETF
INTF	iShares International Equity Factor ETF
IOO	iShares Global 100 ETF
IPAC	iShares Core MSCI Pacific ETF
IQLT	iShares MSCI Intl Quality Factor ETF
IQQ	iShares Nasdaq 100 ETF
IRTR	iShares LifePath Retirement ETF
ISCB	iShares Morningstar Small-Cap ETF
ISCF	iShares International Small-Cap Equity Factor ETF
ISCG	iShares Morningstar Small-Cap Growth ETF
ISCV	iShares Morningstar Small-Cap Value ETF
ISHG	iShares 1-3 Year International Treasury Bond ETF
ISMF	iShares Managed Futures Active ETF
ISTB	iShares Core 1-5 Year USD Bond ETF
ISTM	iShares Strategic Metals ETF
ISVL	iShares International Developed Small Cap Value Factor ETF
ITA	iShares U.S. Aerospace & Defense ETF
ITB	iShares U.S. Home Construction ETF
ITDB	iShares LifePath Target Date 2030 ETF
ITDC	iShares LifePath Target Date 2035 ETF
ITDD	iShares LifePath Target Date 2040 ETF
ITDE	iShares LifePath Target Date 2045 ETF
ITDF	iShares LifePath Target Date 2050 ETF
ITDG	iShares LifePath Target Date 2055 ETF
ITDH	iShares LifePath Target Date 2060 ETF
ITDI	iShares LifePath Target Date 2065 ETF
ITDJ	iShares LifePath Target Date 2070 ETF
ITOT	iShares Core S&P Total U.S. Stock Market ETF
IUSB	iShares Core Universal USD Bond ETF
IUSG	iShares Core S&P U.S. Growth ETF
IUSV	iShares Core S&P U.S. Value ETF
IVE	iShares S&P 500 Value ETF
IVLU	iShares MSCI Intl Value Factor ETF
IVV	iShares Core S&P 500 ETF
IVVB	iShares Large Cap Deep Quarterly Laddered ETF
IVVM	iShares Large Cap Moderate Quarterly Laddered ETF
IVVW	iShares S&P 500 BuyWrite ETF
IVW	iShares S&P 500 Growth ETF
IWB	iShares Russell 1000 ETF
IWC	iShares Microcap ETF
IWD	iShares Russell 1000 Value ETF
IWF	iShares Russell 1000 Growth Fund
IWL	iShares Russell Top 200 ETF
IWMW	iShares Russell 2000 BuyWrite ETF
IWN	iShares Russell 2000 Value ETF
IWO	iShares Russell 2000 Growth Fund
IWP	iShares Russell Midcap Growth ETF
IWR	iShares Russell Mid-Cap ETF
IWS	iShares Russell Mid-Cap Value ETF
IWV	iShares Russell 3000 Fund
IWX	iShares Russell Top 200 Value ETF
IWY	iShares Russell Top 200 Growth ETF
IXC	iShares Global Energy ETF
IXG	iShares Global Financial ETF
IXJ	iShares Global Healthcare ETF
IXN	iShares Global Tech ETF
IXP	iShares Global Comm Services ETF
IXUS	iShares Core MSCI Total International Stock ETF
IYC	iShares U.S. Consumer Discretionary ETF
IYE	iShares U.S. Energy ETF
IYF	iShares U.S. Financial ETF
IYG	iShares U.S. Financial Services ETF
IYH	iShares U.S. Healthcare ETF
IYJ	iShares U.S. Industrials ETF
IYK	iShares U.S. Consumer Staples ETF
IYLD	iShares Morningstar Multi-Asset Income ETF
IYM	iShares U.S. Basic Materials ETF
IYR	iShares U.S. Real Estate ETF
IYT	iShares U.S. Transportation ETF
IYW	iShares U.S. Technology ETF
IYY	iShares Dow Jones U.S. ETF
IYZ	iShares U.S. Telecommunications ETF
JPXN	iShares JPX-Nikkei 400 ETF
JXI	iShares Global Utilities ETF
KSA	iShares MSCI Saudi Arabia ETF
KWT	iShares MSCI Kuwait ETF
KXI	iShares Global Consumer Staples ETF
LCTD	iShares World ex U.S. Carbon Transition Readiness Aware Active ETF
LCTU	iShares U.S. Carbon Transition Readiness Aware Active ETF
LDEM	iShares ESG MSCI EM Leaders ETF
LDRC	iShares iBonds 1-5 Year Corporate Ladder ETF
LDRH	iShares iBonds 1-5 Year High Yield and Income Ladder ETF
LDRI	iShares iBonds 1-5 Year TIPS Ladder ETF
LDRT	iShares iBonds 1-5 Year Treasury Ladder ETF
LEMB	iShares J.P. Morgan EM Local Currency Bond
LMUB	iShares Long-Term National Muni Bond ETF
LQDB	iShares BBB Rated Corporate Bond ETF
LQDH	iShares Interest Rate Hedged Corporate Bond ETF
LQDI	iShares Inflation Hedged Corporate Bond ETF
LQDW	iShares Investment Grade Corporate Bond BuyWrite Strategy ETF
LRGF	iShares U.S. Equity Factor ETF
MADE	iShares U.S. Manufacturing ETF
MAXJ	iShares Large Cap Max Buffer Jun ETF
MBB	iShares MBS ETF
MBBA	iShares Mortgage-Backed Securities Active ETF
MCHI	iShares MSCI China ETF
MEAR	iShares Short Maturity Municipal Bond Active ETF
MMAX	iShares Large Cap Max Buffer Mar ETF
MTUM	iShares MSCI USA Momentum Factor ETF
MUB	iShares National Muni Bond ETF
MXI	iShares Global Materials ETF
NEAR	iShares Short Duration Bond Active ETF
NYF	iShares New York Muni Bond ETF
OEF	iShares S&P 100 Fund
PABD	iShares Paris-Aligned Climate Optimized MSCI World ex USA ETF
PABU	iShares Paris-Aligned Climate Optimized MSCI USA ETF
PFF	iShares Preferred and Income Securities ETF
PICK	iShares MSCI Global Select Metals & Mining Producers Fund
PMMF	iShares Prime Money Market ETF
POWR	iShares U.S. Power Infrastructure ETF
QAT	iShares MSCI Qatar ETF
QLTA	iShares Aaa A Rated Corporate Bond ETF
QNXT	iShares Nasdaq-100 ex Top 30 ETF
QTOP	iShares Nasdaq Top 30 Stocks ETF
QUAL	iShares MSCI USA Quality Factor ETF
REET	iShares Global REIT ETF
REM	iShares Mortgage Real Estate ETF
REZ	iShares Residential and Multisector Real Estate ETF
RING	iShares MSCI Global Gold Miners ETF
RXI	iShares Global Consumer Discretionary ETF
SCJ	iShares MSCI Japan Sm Cap
SCZ	iShares MSCI EAFE Small-Cap ETF
SDG	iShares MSCI Global Sustainable Development Goals ETF
SECU	iShares Securitized Income Active ETF
SGOV	iShares 0-3 Month Treasury Bond ETF
SHV	iShares 0-1 Year Treasury Bond ETF
SHYG	iShares 0-5 Year High Yield Corporate Bond ETF
SHYM	iShares Short Duration High Yield Muni Active ETF
SIZE	iShares MSCI USA Size Factor ETF
SLQD	iShares 0-5 Year Investment Grade Corporate Bond ETF
SLVP	iShares MSCI Global Silver and Metals Miners ETF
SMAX	iShares Large Cap Max Buffer Sep ETF
SMIN	Ishares MSCI India Small Cap ETF
SMLF	iShares U.S. Small-Cap Equity Factor ETF
SMMD	iShares Russell 2500 ETF
SMMV	iShares MSCI USA Small-Cap Min Vol Factor ETF
SQLT	iShares MSCI USA Small-Cap Quality Factor ETF
STEN	iShares Large Cap 10% Target Buffer Sep ETF
STIP	iShares 0-5 Year TIPS Bond ETF
SUB	iShares Short-Term National Muni Bond ETF
SUSA	iShares ESG Optimized MSCI USA ETF
SUSB	iShares ESG Aware 1-5 Year USD Corporate Bond ETF
SUSC	iShares ESG Aware USD Corporate Bond ETF
SUSL	iShares ESG MSCI USA Leaders ETF
SVAL	iShares US Small Cap Value Factor ETF
SYSB	iShares Systematic Bond ETF
TCHI	iShares MSCI China Multisector Tech ETF
TECB	iShares U.S. Tech Breakthrough Multisector ETF
TEK	iShares Technology Opportunities Active ETF
TEND	iShares Large Cap 10% Target Buffer Dec ETF
TENJ	iShares Large Cap 10% Target Buffer Jun ETF
TENM	iShares Large Cap 10% Target Buffer Mar ETF
TEXN	iShares Texas Equity ETF
TFLO	iShares Treasury Floating Rate Bond ETF
THD	iShares MSCI Thailand ETF
THRO	iShares U.S. Thematic Rotation Active ETF
TIP	iShares TIPS Bond ETF
TLH	iShares 10-20 Year Treasury Bond ETF
TLTW	iShares 20+ Year Treasury Bond BuyWrite Strategy ETF
TOK	iShares MSCI Kokusai ETF
TOPC	iShares S&P 500 3% Capped ETF
TOPT	iShares Top 20 U.S. Stocks ETF
TUR	iShares MSCI Turkey ETF
TWOX	iShares Large Cap Accelerated Outcome ETF
UAE	iShares MSCI UAE ETF
URTH	iShares MSCI World ETF
USCL	iShares Climate Conscious & Transition MSCI USA ETF
USHY	iShares Broad USD High Yield Corporate Bond ETF
USIG	iShares Broad USD Investment Grade Corporate Bond ETF
USLN	iShares Broad USD Floating Rate Loan ETF
USMV	iShares MSCI USA Min Vol Factor ETF
USRT	iShares Core U.S. REIT ETF
USXF	iShares ESG Advanced MSCI USA ETF
VEGI	iShares MSCI Agriculture Producers ETF
VLUE	iShares MSCI USA Value Factor ETF
WOOD	iShares Global Timber & Forestry ETF
WSML	iShares MSCI World Small-Cap ETF
XJH	iShares ESG Select Screened S&P Mid-Cap ETF
XJR	iShares ESG Select Screened S&P Small-Cap ETF
XOEF	iShares S&P 500 ex S&P 100 ETF
XT	iShares Future Exponential Technologies ETF
XVV	iShares ESG Select Screened S&P 500 ETF"""
STOCK_NAMES = dict(line.split("\t",1) for line in STOCK_CATALOG_TSV.splitlines() if line.strip())
ETF_NAMES = dict(line.split("\t",1) for line in ETF_CATALOG_TSV.splitlines() if line.strip())
COMMON_STOCK_POOL = tuple(STOCK_NAMES)
ETF_POOL = tuple(ETF_NAMES)
CORE_STOCKS = COMMON_STOCK_POOL[:49]
CORE_ETFS = ETF_POOL[:32]
DEFAULT_STOCKS = COMMON_STOCK_POOL[:COMMON_STOCK_LIMIT]
DEFAULT_ETFS = ETF_POOL[:ETF_LIMIT]


def thai_time(value):
    if value is None or value == "":
        return "ยังไม่มีข้อมูล"
    try:
        stamp = pd.Timestamp(value, unit="s", tz="UTC") if isinstance(value,(int,float)) else pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.tz_convert("Asia/Bangkok").strftime("%d/%m/%Y %H:%M:%S") + " น. (ไทย)"
    except (ValueError, TypeError):
        return "ไม่ทราบเวลา"


def completed_daily_history(history, now=None):
    """Conservatively exclude today's bar in the exchange timezone.

    This avoids comparing incomplete intraday volume with completed daily volume.
    After the close, today's candle is intentionally used from the next local day.
    """
    f = normalize_history(history)
    current = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    # Daily yf.download output for the US ETF basket can have a naive index.
    market_today = current.tz_convert(f.index.tz or "America/New_York").date()
    return f.loc[f.index.date < market_today]


def snapshot_return(history, months):
    if history is None or history.empty:
        return None
    start = history.index[-1] - pd.DateOffset(months=months)
    if history.index[0] > start:
        return None
    subset = history.loc[history.index >= start]
    first = number(subset.Close.iloc[0])
    return (float(subset.Close.iloc[-1])/first-1)*100 if len(subset)>1 and first and first>0 else None


def normalize_symbol(ticker):
    value=str(ticker).strip().upper()
    dashed=value.replace(".","-")
    return dashed if dashed in STOCK_NAMES else value


def clean_industry(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text.casefold() in ("", "nan", "none", "null", "n/a", "—", "ไม่ระบุ") else text


def asset_directory_rows(tickers):
    columns=["Ticker","Asset_Type","Security_Name","Industry","Industry_Source","Industry_Time","Status","Data_Source","Data_Time","Price_AsOf","Data_Status"]
    return pd.DataFrame([{"Ticker":t,"Asset_Type":"ETF" if t in ETF_NAMES else "Common Stock" if t in STOCK_NAMES else "ไม่ระบุ",
                          "Security_Name":STOCK_NAMES.get(t,ETF_NAMES.get(t,t)),"Industry":None,"Industry_Source":"","Industry_Time":"","Status":"ไม่มีข้อมูล",
                          "Data_Source":"ทะเบียนรายชื่อ","Data_Time":"","Price_AsOf":"","Data_Status":"ยังไม่โหลดราคา"}
                         for t in dict.fromkeys(tickers)],columns=columns)


def select_universe(csv_frame):
    supplied=[normalize_symbol(t) for t in csv_frame.Ticker] if "Ticker" in csv_frame else []
    stocks=tuple(dict.fromkeys((*CORE_STOCKS,*(t for t in supplied if t in STOCK_NAMES),*COMMON_STOCK_POOL)))[:COMMON_STOCK_LIMIT]
    etfs=tuple(dict.fromkeys((*CORE_ETFS,*(t for t in supplied if t in ETF_NAMES),*ETF_POOL)))[:ETF_LIMIT]
    return stocks+etfs


def remember_quotes(existing, incoming):
    result={ticker:row.copy() for ticker,row in existing.items()}
    for row in incoming.to_dict("records"):
        ticker=row["Ticker"]
        previous=result.get(ticker,{})
        if row.get("Data_Status")=="โหลดสำเร็จ" or not previous:
            if previous.get("Data_Time") and row.get("Data_Time"):
                try:
                    if pd.Timestamp(previous["Data_Time"])>pd.Timestamp(row["Data_Time"]):
                        continue
                except (ValueError,TypeError):
                    pass
            result[ticker]=row
        else:
            result[ticker]["Data_Status"]="โหลดใหม่ไม่สำเร็จ — แสดงข้อมูลเดิมถ้ามี"
    return result


def numeric_watchlist_series(values):
    """Use a nullable-compatible float destination, including for integer CSVs.

    pandas 3 rejects assigning numbers to its new string dtype, and rejects
    fractional quotes in integer columns. Convert the whole numeric column
    before applying incoming values instead of relying on implicit upcasting.
    """
    converted = pd.to_numeric(values, errors="coerce")
    array = converted.to_numpy(dtype="float64", na_value=np.nan, copy=True)
    array[~np.isfinite(array)] = np.nan
    return pd.Series(array, index=values.index, dtype="float64")


def build_universe_frame(csv_frame, saved=None, classifications=None):
    """Fixed counts; preserve CSV observations and keep excluded rows separately."""
    original=csv_frame.copy()
    original["Ticker"]=original.Ticker.map(normalize_symbol)
    original=original.drop_duplicates("Ticker",keep="last")
    tickers=select_universe(original)
    frame=asset_directory_rows(tickers).set_index("Ticker")
    canonical=frame[["Asset_Type","Security_Name"]].copy()
    selected=original.loc[original.Ticker.isin(tickers)].set_index("Ticker")
    if not selected.empty:
        for col in selected.columns:
            if col not in ("Asset_Type","Security_Name","ETF_Name"):
                frame[col]=selected[col].reindex(frame.index).combine_first(frame[col] if col in frame else pd.Series(index=frame.index,dtype=object))
        frame.loc[selected.index,"CSV_Screener_Status"]=selected.Status
        # Import metadata explicitly: a file modification time is not a quote time.
        for col,default in [("Data_Source","CSV เดิม"),("Data_Status","จาก CSV"),("Data_Time",""),("Price_AsOf","")]:
            frame.loc[selected.index,col]=selected[col].fillna(default) if col in selected else default
    for col in WATCHLIST_NUMERIC_COLUMNS:
        if col not in frame:
            frame[col]=np.nan
        frame[col]=numeric_watchlist_series(frame[col])
    if saved:
        fresh=pd.DataFrame([row for t,row in saved.items() if t in frame.index])
        if not fresh.empty:
            fresh=fresh.drop_duplicates("Ticker",keep="last").set_index("Ticker")
            failed=fresh["Data_Status"].astype(str).str.contains("ไม่สำเร็จ",regex=False)
            frame.loc[fresh.index[failed],"Data_Status"]=fresh.loc[failed,"Data_Status"]
            close=pd.to_numeric(fresh.get("Close",pd.Series(index=fresh.index,dtype=float)),errors="coerce")
            old_dates=pd.to_datetime(frame.loc[fresh.index,"Data_Time"],utc=True,errors="coerce")
            new_dates=pd.to_datetime(fresh.get("Data_Time",pd.Series(index=fresh.index,dtype=str)),utc=True,errors="coerce")
            allowed=close.gt(0) & new_dates.notna() & (old_dates.isna() | new_dates.ge(old_dates))
            for col in fresh.columns:
                if col in ("Asset_Type","Security_Name"):
                    continue
                values=fresh.loc[allowed,col].dropna()
                if not values.empty:
                    if col in WATCHLIST_NUMERIC_COLUMNS:
                        # Include internal numeric metadata as well as visible metrics.
                        values = numeric_watchlist_series(values)
                    elif col not in frame:
                        frame[col] = pd.Series(index=frame.index, dtype=object)
                    else:
                        # Unknown CSV/provider fields may legitimately contain mixed
                        # scalar types. Preserve them without a strict string target.
                        frame[col] = frame[col].astype(object)
                    frame.loc[values.index,col]=values
            # A successfully recalculated missing return must not masquerade as
            # an older CSV return under the new price timestamp.
            version = pd.to_numeric(fresh.get("Return_Calc_Version", pd.Series(index=fresh.index, dtype=float)), errors="coerce")
            calculated = allowed & version.eq(RETURN_CALC_VERSION)
            for col in ("Historical_Return", "Return_2Y", "Return_3Y"):
                if col in fresh:
                    frame.loc[fresh.index[calculated], col] = pd.to_numeric(fresh.loc[calculated, col], errors="coerce")
    frame[["Asset_Type","Security_Name"]]=canonical
    for ticker, metadata in (classifications or {}).items():
        if ticker not in frame.index or not metadata.get("Industry"):
            continue
        old_time = pd.to_datetime(frame.at[ticker, "Industry_Time"], utc=True, errors="coerce")
        new_time = pd.to_datetime(metadata.get("Industry_Time"), utc=True, errors="coerce")
        if pd.notna(old_time) and (pd.isna(new_time) or old_time > new_time):
            continue
        for col in ("Industry", "Industry_Source", "Industry_Time"):
            frame.at[ticker, col] = metadata.get(col, "")
    for col in WATCHLIST_NUMERIC_COLUMNS:
        frame[col]=numeric_watchlist_series(frame[col])
    outside=original.loc[~original.Ticker.isin(tickers)].copy()
    return frame.reset_index(),outside


def scan_snapshot_row(ticker, history, stamp):
    f=completed_daily_history(history)
    if f.empty:
        raise ValueError("ไม่พบแท่งรายวันที่สมบูรณ์")
    row=asset_directory_rows((ticker,)).iloc[0].to_dict()
    snapshot=daily_snapshot(f)
    if number(snapshot.get("Close")) is None or snapshot["Close"]<=0:
        raise ValueError("ราคาไม่เป็นบวก")
    row.update(snapshot)
    complete=all(snapshot.get(k) is not None for k in ("Close","EMA20","EMA50"))
    row.update({"Status":("PASS" if snapshot["Close"]>snapshot["EMA20"]>snapshot["EMA50"] else "FAIL") if complete else "ไม่มีข้อมูล",
                "Historical_Return":snapshot_return(f,12),"Return_2Y":snapshot_return(f,24),"Return_3Y":snapshot_return(f,36),
                "Return_Calc_Version":RETURN_CALC_VERSION,"History_Years_Loaded":0,
                "Data_Time":stamp,"Price_AsOf":snapshot.get("Bar_Date",""),
                "Data_Status":"โหลดสำเร็จ","Data_Source":"Yahoo Finance / สแกนรายวัน"})
    return row


# === PERSISTENT DATA / BACKGROUND UPDATES ===
import os
import sqlite3
import threading
import time
import zlib
from collections import deque
from io import StringIO

APP_VERSION = "2026-09-10.6"
CACHE_FILE = Path(os.environ.get("DASHBOARD_CACHE_FILE", str(Path(__file__).resolve().parent / "dashboard_cache.sqlite3")))
SCAN_TIME_BUDGET_SECONDS = 600
_PROVIDER_LOCK = threading.RLock()


class DashboardCache:
    """SQLite holds successful history and summaries; failures never replace prices."""
    def __init__(self, path):
        self.path = Path(path)
        self.error = ""
        self._fallback = {}
        self._fallback_quotes = {}
        self._fallback_classifications = {}
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, body BLOB NOT NULL, metadata TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS quotes (ticker TEXT PRIMARY KEY, body TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS classifications (ticker TEXT PRIMARY KEY, body TEXT NOT NULL)")
                existing_info = db.execute("SELECT key, body FROM objects WHERE key LIKE 'info:%' AND substr(key,6) NOT IN (SELECT ticker FROM classifications)").fetchall()
            for key, compressed in existing_info:
                try:
                    self.save_classification(key[5:], json.loads(zlib.decompress(compressed)))
                except (ValueError, TypeError, zlib.error):
                    pass
        except (OSError, sqlite3.Error) as exc:
            self.error = str(exc)

    def connect(self):
        return sqlite3.connect(str(self.path), timeout=5)

    def save_classification(self, ticker, info):
        is_etf = ticker in ETF_NAMES or info.get("quoteType") == "ETF"
        value = clean_industry(info.get("category") if is_etf else info.get("industry"))
        metadata = {"Industry": value, "Industry_Source": "Yahoo Finance / หมวด ETF" if is_etf else "Yahoo Finance / Industry",
                    "Industry_Time": info.get("_Fetched_At_UTC", "")}
        with self._lock:
            try:
                if not self.error:
                    with self.connect() as db:
                        db.execute("INSERT INTO classifications VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body",
                                   (ticker, json.dumps(metadata, ensure_ascii=False)))
                    return
            except (OSError, sqlite3.Error) as exc:
                self.error = str(exc)
            self._fallback_classifications[ticker] = metadata

    def classifications(self):
        with self._lock:
            if not self.error:
                try:
                    with self.connect() as db:
                        return {ticker: json.loads(body) for ticker, body in db.execute("SELECT ticker, body FROM classifications")}
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self.error = str(exc)
            return self._fallback_classifications.copy()

    def get(self, key):
        with self._lock:
            try:
                if not self.error:
                    with self.connect() as db:
                        row = db.execute("SELECT body, metadata FROM objects WHERE key=?", (key,)).fetchone()
                    if row:
                        return json.loads(zlib.decompress(row[0])), json.loads(row[1])
            except (OSError, sqlite3.Error, ValueError, zlib.error) as exc:
                self.error = str(exc)
            return self._fallback.get(key, (None, {}))

    def put(self, key, value, meta):
        encoded = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
        metadata = json.dumps(meta, ensure_ascii=False, default=str, allow_nan=False)
        with self._lock:
            try:
                if not self.error:
                    with self.connect() as db:
                        db.execute("INSERT INTO objects VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body, metadata=excluded.metadata",
                                   (key, zlib.compress(encoded.encode()), metadata))
                    return
            except (OSError, sqlite3.Error) as exc:
                self.error = str(exc)
            # Keep only a small number of full histories if the disk is unavailable.
            self._fallback[key] = (value, meta)
            while len(self._fallback) > 64:
                self._fallback.pop(next(iter(self._fallback)))

    def history(self, ticker, interval="1d"):
        body, meta = self.get(f"history:{interval}:{ticker}")
        if body is None:
            return None, {}
        try:
            frame = pd.read_json(StringIO(body), orient="split")
            if interval == "1d":
                frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).tz_localize(None)
            else:
                frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(meta.get("timezone", "America/New_York"))
            return normalize_history(frame), meta
        except (ValueError, KeyError, TypeError):
            return None, {}

    def save_history(self, ticker, frame, stamp, interval="1d", years=HISTORY_YEARS, full_refreshed_at=None):
        f = normalize_history(frame)[["Open", "High", "Low", "Close", "Volume"]].copy()
        market_tz = str(f.index.tz or "America/New_York")
        if interval == "1d":
            f.index = f.index.tz_localize(None).normalize()
        meta = {"fetched_at": stamp, "full_refreshed_at": full_refreshed_at or stamp,
                "years": years, "timezone": market_tz, "adjusted": True,
                "last_bar": str(f.index[-1]), "version": 1}
        self.put(f"history:{interval}:{ticker}", f.to_json(orient="split", date_format="iso", double_precision=15), meta)
        if interval == "1d":
            row = scan_snapshot_row(ticker, f, stamp)
            row["History_Years_Loaded"] = years
            self.save_quotes(pd.DataFrame([row]))
        return f

    def quotes(self):
        with self._lock:
            if not self.error:
                try:
                    with self.connect() as db:
                        return {t: json.loads(body) for t, body in db.execute("SELECT ticker, body FROM quotes")}
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self.error = str(exc)
            return {t: r.copy() for t, r in self._fallback_quotes.items()}

    def save_quotes(self, rows):
        if rows is None or rows.empty:
            return
        # A transaction prevents older concurrent responses from replacing newer rows.
        with self._lock:
            tickers = list(dict.fromkeys(rows.Ticker))
            old = {}
            if not self.error:
                try:
                    with self.connect() as db:
                        placeholders = ",".join("?" for _ in tickers)
                        old = {t: json.loads(body) for t, body in db.execute(f"SELECT ticker, body FROM quotes WHERE ticker IN ({placeholders})", tickers)}
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self.error = str(exc)
            if self.error:
                old = {t: self._fallback_quotes[t] for t in tickers if t in self._fallback_quotes}
            merged = remember_quotes(old, rows)
            clean = json.loads(pd.DataFrame([merged[t] for t in tickers]).to_json(orient="records", double_precision=15))
            try:
                if not self.error:
                    with self.connect() as db:
                        db.executemany("INSERT INTO quotes VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body",
                                       [(r["Ticker"], json.dumps(r, ensure_ascii=False, allow_nan=False)) for r in clean])
                    return
            except (OSError, sqlite3.Error) as exc:
                self.error = str(exc)
            self._fallback_quotes.update({r["Ticker"]: r for r in clean})


@st.cache_resource
def get_data_cache(_version=APP_VERSION):
    return DashboardCache(CACHE_FILE)


def market_date(now=None):
    stamp = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("America/New_York").date()


def checked_today(meta, now=None):
    try:
        return market_date(meta["fetched_at"]) == market_date(now)
    except (KeyError, ValueError, TypeError):
        return False


def summary_is_current(row, now=None):
    # A new column must trigger backfill even when an old 2-year scan ran today.
    return (row.get("Data_Status") == "โหลดสำเร็จ"
            and number(row.get("Return_Calc_Version")) == RETURN_CALC_VERSION
            and (number(row.get("History_Years_Loaded")) or 0) >= HISTORY_YEARS
            and checked_today({"fetched_at": row.get("Data_Time")}, now))


def history_request(old, meta, years=HISTORY_YEARS):
    try:
        refreshed = pd.Timestamp(meta.get("full_refreshed_at", meta.get("fetched_at")))
        if refreshed.tzinfo is None:
            refreshed = refreshed.tz_localize("UTC")
        reconcile = (pd.Timestamp.now(tz="UTC") - refreshed).total_seconds() > 30 * 86400
    except (ValueError, TypeError, AttributeError):
        reconcile = True
    if old is None or old.empty or int(meta.get("years", 0)) < years or reconcile:
        return {"period": f"{max(years, int(meta.get('years', 0)))}y"}
    # Include overlap for corrected bars; the full stored series remains in use.
    return {"start": (old.index[-1] - pd.Timedelta(days=7)).strftime("%Y-%m-%d")}


def merge_daily_history(old, new, now=None):
    fresh = normalize_history(new)[["Open", "High", "Low", "Close", "Volume"]].copy()
    fresh.index = fresh.index.tz_localize(None).normalize()
    if old is None or old.empty:
        return fresh, False
    saved = normalize_history(old).copy()
    saved.index = saved.index.tz_localize(None).normalize()
    common = saved.index.intersection(fresh.index)
    completed = common[common.date < market_date(now)]
    # Splits, dividends or historical corrections can change adjusted prices.
    # Re-fetch the complete window rather than mixing different adjustment bases.
    cols = ["Open", "High", "Low", "Close"]
    changed = bool(len(completed) and not np.allclose(saved.loc[completed, cols], fresh.loc[completed, cols], rtol=1e-6, atol=1e-8))
    combined = pd.concat([saved, fresh]).sort_index()
    return combined.loc[~combined.index.duplicated(keep="last")], changed


def _extract_batch(batch, ticker, count):
    if batch is None or batch.empty:
        raise ValueError("Yahoo ไม่ส่งราคา — อาจจำกัดคำขอหรือไม่มีข้อมูล")
    if isinstance(batch.columns, pd.MultiIndex):
        return batch[ticker] if ticker in batch.columns.get_level_values(0) else batch.xs(ticker, axis=1, level=1)
    if count == 1:
        return batch
    raise ValueError("ไม่พบคอลัมน์ของหุ้น")


def fetch_daily_batch(tickers, cache, *, force=False, years=HISTORY_YEARS):
    if len(tickers) > SCAN_BATCH_SIZE:
        raise ValueError(f"โหลดได้ไม่เกิน {SCAN_BATCH_SIZE} ตัวต่อชุด")
    rows = {r["Ticker"]: r for r in asset_directory_rows(tickers).to_dict("records")}
    groups, stored, errors = {}, {}, []
    stats = {"reused": 0, "incremental": 0, "initial": 0, "failed": 0}
    for ticker in tickers:
        old, meta = cache.history(ticker)
        stored[ticker] = (old, meta)
        if not force and old is not None and checked_today(meta) and meta.get("years", 0) >= years:
            try:
                rows[ticker] = scan_snapshot_row(ticker, old, meta["fetched_at"])
                rows[ticker]["History_Years_Loaded"] = meta.get("years", 0)
                stats["reused"] += 1
                continue
            except (ValueError, KeyError):
                pass
        request = history_request(old, meta, years)
        groups.setdefault(tuple(request.items()), []).append(ticker)
    for key, symbols in groups.items():
        kwargs = dict(key)
        try:
            with _PROVIDER_LOCK:
                batch = yf.download(symbols, interval="1d", group_by="ticker", auto_adjust=True,
                                    threads=DOWNLOAD_THREADS, progress=False, timeout=DOWNLOAD_TIMEOUT_SECONDS, **kwargs)
            for ticker in symbols:
                try:
                    old, meta = stored[ticker]
                    fresh = _extract_batch(batch, ticker, len(symbols))
                    merged, adjusted = merge_daily_history(old, fresh)
                    if adjusted and "start" in kwargs:
                        with _PROVIDER_LOCK:
                            full = yf.download([ticker], period=f"{max(years, int(meta.get('years', 2)))}y", interval="1d",
                                               auto_adjust=True, group_by="ticker", threads=False, progress=False,
                                               timeout=DOWNLOAD_TIMEOUT_SECONDS)
                        merged = normalize_history(_extract_batch(full, ticker, 1))
                    elif "period" in kwargs:
                        # A full response is authoritative; do not retain old adjusted rows.
                        merged = normalize_history(fresh)
                    stamp = datetime.now(timezone.utc).isoformat()
                    row = scan_snapshot_row(ticker, merged, stamp)
                    row["History_Years_Loaded"] = max(years, int(meta.get("years", years)))
                    full_stamp = stamp if "period" in kwargs or adjusted else meta.get("full_refreshed_at", meta.get("fetched_at", stamp))
                    cache.save_history(ticker, merged, stamp, years=max(years, int(meta.get("years", years))), full_refreshed_at=full_stamp)
                    rows[ticker] = row
                    stats["incremental" if "start" in kwargs and not adjusted else "initial"] += 1
                except Exception as exc:
                    rows[ticker]["Data_Status"] = "โหลดไม่สำเร็จ"
                    errors.append(f"{ticker}: {str(exc)[:240]}")
                    stats["failed"] += 1
        except Exception as exc:
            for ticker in symbols:
                rows[ticker]["Data_Status"] = "โหลดไม่สำเร็จ"
                stats["failed"] += 1
            errors.append(str(exc)[:400])
    result = pd.DataFrame(rows.values()) if rows else asset_directory_rows(())
    cache.save_quotes(result)
    return result, errors, stats


class BackgroundUpdates:
    """One provider queue per server; Streamlit only reads saved results."""
    def __init__(self, cache):
        self.cache = cache
        self.lock = threading.RLock()
        self.thread = None
        self.priority = deque()
        self.metadata_queue = deque()
        self.pending = set()
        self.queue = deque()
        self.scan_running = False
        self.cooldown_until = 0.0
        self.current = ""
        self.total = self.done = self.success = self.failed = self.reused = self.incremental = self.initial = 0
        self.started = 0.0
        self.message = "พร้อมใช้ข้อมูลที่มี — ยังไม่เริ่มโหลดทั้งชุด"
        self.errors = []
        self.revision = 0

    def state(self):
        with self.lock:
            return {k: getattr(self, k) for k in ("scan_running", "cooldown_until", "current", "total", "done", "success", "failed", "reused", "incremental", "initial", "started", "message", "revision")} | {
                "remaining": len(self.queue), "busy": bool(self.current or self.priority or self.metadata_queue or self.scan_running), "errors": self.errors[-12:]}

    def _ensure_thread(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, name="dashboard-data-updates", daemon=True)
            self.thread.start()

    def request(self, ticker, kind="history", interval="1d"):
        job = (kind, ticker, interval)
        with self.lock:
            if time.time() < self.cooldown_until:
                return False
            if job not in self.pending:
                (self.metadata_queue if kind == "industry" else self.priority).append(job)
                self.pending.add(job)
            self._ensure_thread()
            return True

    def start_scan(self, tickers):
        with self.lock:
            if time.time() < self.cooldown_until or self.scan_running or self.current.startswith("สแกน "):
                return False
            self.queue = deque(dict.fromkeys(tickers))
            self.total = len(self.queue)
            self.done = self.success = self.failed = self.reused = self.incremental = self.initial = 0
            self.started = time.monotonic()
            self.scan_running = bool(self.queue)
            self.message = "กำลังโหลดเบื้องหลัง ใช้หน้า dashboard ต่อได้"
            self._ensure_thread()
            return True

    def stop(self):
        with self.lock:
            self.scan_running = False
            self.message = "หยุดหลังชุดที่กำลังโหลด ข้อมูลที่สำเร็จบันทึกแล้ว"

    def _job(self, kind, ticker, interval):
        if kind == "history" and interval == "1d":
            rows, errors, stats = fetch_daily_batch((ticker,), self.cache, force=True, years=5)
            if errors:
                raise ValueError("; ".join(errors))
        elif kind == "history":
            with _PROVIDER_LOCK:
                f = yf.Ticker(ticker).history(period="1mo", interval=interval, auto_adjust=True,
                                              actions=False, prepost=False, timeout=DOWNLOAD_TIMEOUT_SECONDS)
            self.cache.save_history(ticker, f, datetime.now(timezone.utc).isoformat(), interval=interval)
        elif kind in ("info", "industry"):
            if kind == "industry":
                cached, meta = self.cache.get(f"info:{ticker}")
                try:
                    recent = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(meta["fetched_at"])).total_seconds() < 30 * 86400
                except (KeyError, ValueError, TypeError):
                    recent = False
                if cached and recent:
                    self.cache.save_classification(ticker, cached)
                    return
            with _PROVIDER_LOCK:
                info = yf.Ticker(ticker).get_info()
            if not isinstance(info, dict) or not info:
                raise ValueError("ไม่มีข้อมูลพื้นฐานตอบกลับ")
            stamp = datetime.now(timezone.utc).isoformat()
            info = json.loads(pd.Series(info).to_json(double_precision=15))
            self.cache.put(f"info:{ticker}", {**info, "_Fetched_At_UTC": stamp}, {"fetched_at": stamp})
            self.cache.save_classification(ticker, {**info, "_Fetched_At_UTC": stamp})
        elif kind == "dividends":
            with _PROVIDER_LOCK:
                result = _fetch_dividends(ticker)
            if result["error"]:
                raise ValueError(result["error"])
            data = result.pop("data").copy()
            data["Ex_Date"] = data.Ex_Date.dt.strftime("%Y-%m-%d")
            self.cache.put(f"dividends:{ticker}", {**result, "records": data.to_dict("records")}, {"fetched_at": result["fetched_at"]})

    def _run(self):
        while True:
            with self.lock:
                if time.time() < self.cooldown_until:
                    self.scan_running = False
                    self.priority.clear()
                    self.metadata_queue.clear()
                    self.pending.clear()
                    self.thread = None
                    return
                if self.priority:
                    job = self.priority.popleft()
                    group = None
                    self.current = f"{job[1]} — {job[0]}"
                elif self.metadata_queue:
                    job = self.metadata_queue.popleft()
                    group = None
                    self.current = f"{job[1]} — อุตสาหกรรม"
                elif self.scan_running and self.queue:
                    if time.monotonic() - self.started >= SCAN_TIME_BUDGET_SECONDS:
                        self.scan_running = False
                        self.message = "ครบงบเวลาประมาณ 10 นาที — ยังไม่ครบทุกตัว กดเริ่มต่อเพื่อโหลดส่วนที่เหลือ"
                        self.thread = None
                        return
                    group = tuple(self.queue.popleft() for _ in range(min(SCAN_BATCH_SIZE, len(self.queue))))
                    job = None
                    self.current = f"สแกน {len(group)} ตัว: {group[0]} – {group[-1]}"
                else:
                    self.scan_running = False
                    self.current = ""
                    self.thread = None
                    return
            stats = {}
            try:
                if job:
                    self._job(*job)
                else:
                    rows, errors, stats = fetch_daily_batch(group, self.cache)
                    ok = int(rows.Data_Status.eq("โหลดสำเร็จ").sum())
                    with self.lock:
                        self.done += len(group)
                        self.success += ok
                        self.failed += stats["failed"]
                        self.reused += stats["reused"]
                        self.incremental += stats["incremental"]
                        self.initial += stats["initial"]
                        self.errors.extend(errors)
                        if ok * 2 < len(group):
                            self.cooldown_until = time.time() + SCAN_COOLDOWN_SECONDS
                            self.scan_running = False
                            self.message = "Yahoo ตอบกลับไม่ครบครึ่งชุด พัก 5 นาทีและใช้ข้อมูลเดิมต่อ"
                        elif not self.queue:
                            self.scan_running = False
                            self.message = f"จบรอบ: สำเร็จ {self.success:,} / {self.total:,} ตัว · ไม่สำเร็จ {self.failed:,} ตัว"
            except Exception as exc:
                with self.lock:
                    message = str(exc)[:400]
                    self.errors.append(f"{self.current}: {message}")
                    self.message = "โหลดใหม่ไม่สำเร็จ ข้อมูลเดิมและเวลาเดิมยังอยู่"
                    if any(s in message.lower() for s in ("429", "too many", "rate limit", "จำกัดคำขอ")):
                        self.cooldown_until = time.time() + SCAN_COOLDOWN_SECONDS
                        self.scan_running = False
            finally:
                with self.lock:
                    if job:
                        self.pending.discard(job)
                    self.current = ""
                    self.revision += 1
            # Only a short pause between actual network batches; never blocks the UI.
            if (group and stats.get("initial", 0) + stats.get("incremental", 0)) or (job and job[0] == "industry"):
                time.sleep(SCAN_INTERVAL_SECONDS)


@st.cache_resource
def get_updater(_version=APP_VERSION):
    return BackgroundUpdates(get_data_cache())


def load_watchlist_batch(tickers):
    rows, errors, _ = fetch_daily_batch(tickers, get_data_cache())
    stamps = rows.loc[rows.Data_Status.eq("โหลดสำเร็จ"), "Data_Time"]
    return rows, max(stamps) if not stamps.empty else "", errors


load_watchlist_batch.clear = lambda *args: None  # The persistent history must survive refresh.


def render_scan_controls(csv_frame):
    cache, worker = get_data_cache(), get_updater()
    state = worker.state()
    universe = select_universe(csv_frame)
    # Migrate the previous session's successful summaries without inventing history.
    if "quote_records" in st.session_state and not st.session_state.get("instant_migrated"):
        previous = st.session_state.quote_records
        if previous:
            cache.save_quotes(pd.DataFrame(previous.values()))
        st.session_state.instant_migrated = True
    st.session_state.quote_records = cache.quotes()
    st.session_state.scan_attempted = list(st.session_state.quote_records)
    st.session_state.scan_running = state["scan_running"]
    st.info("ใช้ข้อมูลจาก CSV และข้อมูลที่บันทึกไว้ได้ทันที เลือกหุ้นแล้วกด ‘โหลด/อัปเดตหุ้นที่เลือก’ เพื่อดึงข้อมูลใหม่เฉพาะตัว โดยไม่ต้องรอครบ 4,900 ตัว")
    if cache.error:
        st.warning("บันทึกประวัติลงดิสก์ไม่ได้ — ใช้หน่วยความจำชั่วคราวและ CSV ต่อได้: " + cache.error)
    with st.expander(f"อัปเดตทั้งชุดเบื้องหลัง — Common Stock {COMMON_STOCK_LIMIT:,} + ETF {ETF_LIMIT:,}", expanded=state["scan_running"]):
        st.caption(f"รายชื่อ ณ {CATALOG_AS_OF} · [Nasdaq]({CATALOG_SOURCE}) · ไม่ใช่อันดับความน่าซื้อ")
        a, b = st.columns(2)
        scope = a.selectbox("ชุดที่จะสแกน", ["ทั้งหมด", "Common Stock", "ETF"], key="scan_scope", disabled=state["scan_running"])
        mode = b.selectbox("รูปแบบการสแกน", ["อัปเดตส่วนที่ขาด / เริ่มต่อ", "ลองใหม่ตัวที่โหลดไม่ได้"], key="incremental_scan_mode", disabled=state["scan_running"])
        scoped = [t for t in universe if scope == "ทั้งหมด" or (scope == "ETF") == (t in ETF_NAMES)]
        if mode == "ลองใหม่ตัวที่โหลดไม่ได้":
            scoped = [t for t in scoped if "ไม่สำเร็จ" in str(st.session_state.quote_records.get(t, {}).get("Data_Status", ""))]
        a, b, c = st.columns(3)
        scan_busy = state["scan_running"] or state["current"].startswith("สแกน ")
        start = a.button("เริ่ม / ทำต่อ สูงสุดประมาณ 10 นาที", key="scan_start", disabled=scan_busy)
        small = b.button(f"โหลดชุดถัดไป {SCAN_BATCH_SIZE} ตัว", key="scan_next", disabled=scan_busy)
        stop = c.button("หยุดสแกน", key="scan_stop", disabled=not state["scan_running"])
        if stop:
            worker.stop()
        if start or small:
            # Skip successful histories checked this market day; failed refreshes remain retryable.
            saved = cache.quotes()
            pending = [t for t in scoped if not summary_is_current(saved.get(t, {}))]
            if not pending:
                st.success("ไม่มีรายการค้างในชุดนี้ ข้อมูลรายวันตรวจแล้ววันนี้ — อัปเดตราคาระหว่างวันผ่านหุ้นที่เลือก")
            elif not worker.start_scan(pending if start else pending[:SCAN_BATCH_SIZE]):
                st.warning("ยังเริ่มไม่ได้: มีงานสแกนอยู่ หรือแหล่งข้อมูลกำลังพักถึง " + thai_time(worker.state()["cooldown_until"]))
        state = worker.state()
        if state["total"]:
            st.progress(min(1.0, state["done"] / state["total"]), text=f"ตรวจแล้ว {state['done']:,}/{state['total']:,} · สำเร็จ {state['success']:,} · ไม่สำเร็จ {state['failed']:,} · ค้าง {state['remaining']:,}")
            st.caption(f"ใช้ประวัติเดิม {state['reused']:,} · โหลดช่วงใหม่ {state['incremental']:,} · โหลดประวัติเต็ม {state['initial']:,}")
        st.caption(state["message"])
        if state["cooldown_until"] > time.time():
            st.warning("พักการเรียก Yahoo ถึง " + thai_time(state["cooldown_until"]) + " — ตารางเดิมยังใช้งานได้")
        if state["errors"]:
            with st.expander("รายการที่ยังโหลดไม่ได้"):
                st.text("\n".join(state["errors"]))
        st.caption("เพื่อคำนวณผลตอบแทน 1 / 2 / 3 ปี ระบบขอประวัติย้อนหลัง 5 ปีครั้งแรก หรือเมื่อประวัติเดิมมีเพียง 2 ปี จากนั้นโหลดเฉพาะช่วงที่เพิ่มมาและตรวจราคาปรับแล้วก่อนรวมข้อมูล")
        st.caption("งบ 10 นาทีเป็นเวลาต่อรอบและจะจบคำขอที่กำลังทำก่อนหยุด ไม่ใช่การรับประกันว่าราคาครบ 4,900 ตัวภายใน 10 นาที งานทำต่อได้ขณะปิดแท็บหากเซิร์ฟเวอร์ยังทำงาน")
        st.caption("บันทึกอัตโนมัติใน dashboard_cache.sqlite3 ข้าง app.py บนเครื่องที่รันแอป; หากใช้โฮสต์ที่ล้างดิสก์เมื่อรีสตาร์ท ประวัตินี้อาจหาย เก็บ CSV เดิมไว้เสมอ")
    return universe


def asset_is_etf(ticker, row, info):
    return info.get("quoteType")=="ETF" or ticker in ETF_NAMES or "ETF" in str(row.get("Asset_Type","")).upper()


def _fetch_dividends(ticker):
    try:
        # An explicit history request distinguishes missing data from zero dividends.
        f=yf.Ticker(ticker).history(period="max",interval="1d",actions=True,auto_adjust=False,timeout=20)
        if f is None or f.empty or "Dividends" not in f:
            raise ValueError("แหล่งข้อมูลไม่ได้ส่งประวัติปันผลกลับมา")
        cash=pd.to_numeric(f.Dividends,errors="coerce")
        if cash.notna().sum()==0:
            raise ValueError("คอลัมน์ปันผลไม่มีค่าที่ตรวจสอบได้ จึงยังสรุปว่าไม่มีปันผลไม่ได้")
        cash=cash.loc[cash.notna() & cash.gt(0)]
        dates=pd.DatetimeIndex(cash.index)
        if dates.tz is not None:
            dates=dates.tz_localize(None)
        dividends=pd.DataFrame({"Ex_Date":dates.normalize(),"Dividend_Per_Share":cash.to_numpy()})
        dividends=dividends.groupby("Ex_Date",as_index=False).Dividend_Per_Share.sum().sort_values("Ex_Date")
        return {"data":dividends,"fetched_at":datetime.now(timezone.utc).isoformat(),"error":None,
                "coverage_start":str(f.index[0].date()),"coverage_end":str(f.index[-1].date())}
    except Exception as exc:
        return {"data":None,"fetched_at":"","error":str(exc),"coverage_start":"","coverage_end":""}


def load_dividend_history(ticker):
    stored, _ = get_data_cache().get(f"dividends:{ticker}")
    if not stored:
        return {"data": None, "fetched_at": "", "error": "ยังไม่มีประวัติปันผล กดโหลด/อัปเดตหุ้นที่เลือก", "coverage_start": "", "coverage_end": ""}
    data = pd.DataFrame(stored.get("records", []), columns=["Ex_Date", "Dividend_Per_Share"])
    data["Ex_Date"] = pd.to_datetime(data.Ex_Date)
    return {**stored, "data": data}


load_dividend_history.clear = lambda *args: None


def dividend_summary(result, price=None, now=None):
    if result.get("error") or result.get("data") is None:
        return {"total":None,"count":None,"yield":None,"last_date":None,"last_amount":None}
    today=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if today.tzinfo is not None:
        today=today.tz_convert("UTC").tz_localize(None)
    today=today.normalize()
    data=result["data"].loc[result["data"].Ex_Date.le(today)]
    ttm=data.loc[data.Ex_Date.gt(today-pd.DateOffset(years=1))]
    last=data.iloc[-1] if not data.empty else None
    value=float(ttm.Dividend_Per_Share.sum())
    return {"total":value,"count":len(ttm),"yield":value/price*100 if price and price>0 else None,
            "last_date":None if last is None else last.Ex_Date.strftime("%d/%m/%Y"),
            "last_amount":None if last is None else float(last.Dividend_Per_Share)}


def render_dividends(ticker, result, currency, price):
    st.subheader(f"ประวัติปันผล — {ticker}")
    if result.get("error"):
        st.warning(f"ยังโหลดประวัติปันผลไม่ได้: {result['error']}")
        return
    st.caption(f"ดึงสำเร็จล่าสุด {thai_time(result.get('fetched_at'))} · ข้อมูลครอบคลุม {result['coverage_start']} – {result['coverage_end']}")
    if result.get("coverage_start") and pd.Timestamp(result["coverage_start"])>pd.Timestamp.now(tz="UTC").tz_localize(None)-pd.DateOffset(years=1):
        st.info("ประวัติที่ผู้ให้ข้อมูลส่งกลับมาสั้นกว่า 12 เดือน ยอดและ Yield แสดงเฉพาะรายการที่มี ไม่ได้คูณประมาณให้เป็นรายปี")
    stats=dividend_summary(result,price)
    a,b,c,d=st.columns(4)
    a.metric(f"ปันผล 12 เดือน / หน่วย ({currency})",show_number(stats["total"],digits=4))
    b.metric("จำนวนครั้งใน 12 เดือน",str(stats["count"]))
    c.metric("Yield ย้อนหลัง 12 เดือน",show_number(stats["yield"],"%"))
    d.metric("Ex-dividend ล่าสุด",stats["last_date"] or "ไม่พบรายการ")
    years=st.radio("ช่วงประวัติปันผล",["1 ปี","3 ปี","5 ปี","10 ปี","ทั้งหมด"],index=2,horizontal=True,key="dividend_years")
    data=result["data"].copy()
    today=pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    data=data.loc[data.Ex_Date.le(today)]
    if years!="ทั้งหมด":
        data=data.loc[data.Ex_Date.gt(today-pd.DateOffset(years=int(years.split()[0])))]
    if data.empty:
        st.info("ไม่พบรายการปันผลในช่วงที่เลือกจากข้อมูลที่โหลดสำเร็จ")
    else:
        year=data.Ex_Date.dt.year
        yearly=data.assign(Year=year).groupby("Year").agg(Total=("Dividend_Per_Share","sum"),Payments=("Dividend_Per_Share","size")).reset_index()
        yearly["ช่วงข้อมูล"]=yearly.Year.map(lambda y:"สะสมปีนี้ (YTD)" if y==today.year else "ข้อมูลที่มีในช่วงเลือก")
        fig=go.Figure(go.Bar(x=yearly.Year.astype(str),y=yearly.Total,marker_color="#26a69a",hovertemplate="%{x}: %{y:.4f}<extra></extra>"))
        fig.update_layout(height=280,margin=dict(l=15,r=15,t=15,b=15),template="plotly_dark",yaxis_title=f"ปันผลต่อหน่วย ({currency})",xaxis_title="ปี (ปีปัจจุบันเป็น YTD)")
        st.plotly_chart(fig,**width_options(st.plotly_chart),key="dividend_chart")
        a,b=st.columns([1.4,1])
        displayed=data.sort_values("Ex_Date",ascending=False).rename(columns={"Ex_Date":"วันขึ้น XD / Ex-dividend","Dividend_Per_Share":f"ปันผลต่อหน่วย ({currency})"})
        a.dataframe(displayed,hide_index=True,**width_options(st.dataframe),height=300)
        b.dataframe(yearly.rename(columns={"Year":"ปี","Total":"รวมต่อหน่วย","Payments":"จำนวนครั้ง"}),hide_index=True,**width_options(st.dataframe),height=300)
        st.download_button("ดาวน์โหลดประวัติปันผล",data.to_csv(index=False).encode("utf-8-sig"),file_name=f"{ticker}_dividends.csv",mime="text/csv",key="download_dividends")
    st.caption("วันที่ในตารางเป็นวัน Ex-dividend ตามตลาด ไม่ใช่วันเงินเข้าบัญชี จำนวนเงินใช้ตามที่ผู้ให้ข้อมูลรายงาน อาจปรับตามการแตกหุ้น; การจ่ายของ ETF อาจมีองค์ประกอบอื่นนอกจากเงินปันผล และข้อมูลนี้ไม่ได้แยกภาษี/คืนทุน")


def decision_context(history, info, benchmark=None, now=None):
    ctx={"history":None,"metrics":{},"quote":number(info.get("regularMarketPrice")),"quote_time":number(info.get("regularMarketTime"))}
    if history is None or history.empty:
        return ctx
    f=completed_daily_history(history,now)
    if f.empty:
        return ctx
    ctx["history"],ctx["metrics"]=f,daily_snapshot(f)
    ctx["return_3m"]=snapshot_return(f,3)
    ctx["relative_3m"]=None
    if benchmark is not None and not benchmark.empty:
        try:
            b=completed_daily_history(benchmark,now)
            aligned=align_comparison({"asset":f,"benchmark":b},"3 เดือน")
            # Both histories must cover the intended period, not just a short overlap.
            if snapshot_return(f,3) is not None and snapshot_return(b,3) is not None:
                ctx["relative_3m"]=float(aligned.asset.iloc[-1]-aligned.benchmark.iloc[-1])
        except (ValueError,IndexError):
            pass
    return ctx


def criteria_score(ctx, info, is_etf):
    m=ctx["metrics"]
    c,e20,e50,sma=(number(m.get(k)) for k in ("Close","EMA20","EMA50","SMA200"))
    rsi,macd,signal,volume,atr=(number(m.get(k)) for k in ("RSI_14","MACD","MACD_Signal","Vol_Ratio","ATR"))
    rows=[]
    def add(group,name,current,ranges,earned,maximum,source="แท่งรายวันก่อนวันปัจจุบัน"):
        rows.append({"หมวด":group,"เกณฑ์":name,"ค่าปัจจุบัน":current,"ช่วง / คะแนน":ranges,
                     "ได้":earned,"เต็ม":maximum,"ผล":"ไม่มีข้อมูล" if earned is None else "เต็ม" if earned==maximum else "บางส่วน" if earned>0 else "ไม่ผ่าน","ข้อมูลอ้างอิง":source})
    trend=None if any(x is None for x in (c,e20,e50)) else c>e20>e50
    add("แนวโน้ม","ราคา > EMA20 > EMA50",f"{show_number(c)} > {show_number(e20)} > {show_number(e50)}","เรียงตามเงื่อนไข = 20; อื่น ๆ = 0",None if trend is None else 20 if trend else 0,20)
    add("แนวโน้ม","ราคา > SMA200",f"ราคา {show_number(c)} / SMA200 {show_number(sma)}","ราคาเหนือ SMA200 = 10; อื่น ๆ = 0",None if c is None or sma is None else 10 if c>sma else 0,10)
    add("โมเมนตัม","RSI 14",show_number(rsi),"45–65 = 10; 35–<45 หรือ >65–70 = 5; อื่น ๆ = 0",None if rsi is None else 10 if 45<=rsi<=65 else 5 if 35<=rsi<45 or 65<rsi<=70 else 0,10)
    add("โมเมนตัม","MACD > Signal",f"{show_number(macd,digits=4)} / {show_number(signal,digits=4)}","เหนือ Signal = 10; ต่ำกว่าหรือเท่ากัน = 0",None if macd is None or signal is None else 10 if macd>signal else 0,10)
    add("วอลุ่ม","Volume Ratio",show_number(volume,"x"),">=1.20 = 15; 1.00–<1.20 = 8; 0.80–<1.00 = 4; <0.80 = 0",None if volume is None else 15 if volume>=1.2 else 8 if volume>=1 else 4 if volume>=.8 else 0,15)
    atr_pct=atr/c*100 if atr is not None and c and c>0 else None
    add("ความผันผวน","ATR / ราคา",show_number(atr_pct,"%"),"<=3% = 15; >3–6% = 8; >6–10% = 3; >10% = 0",None if atr_pct is None else 15 if atr_pct<=3 else 8 if atr_pct<=6 else 3 if atr_pct<=10 else 0,15)
    if is_etf:
        relative,ret=ctx.get("relative_3m"),ctx.get("return_3m")
        add("ETF","ผลตอบแทน 3 เดือนเทียบ SPY",show_number(relative," จุดเปอร์เซ็นต์"),">=0 = 10; <0 = 0",None if relative is None else 10 if relative>=0 else 0,10,"ราคาปรับแล้ว วันที่ร่วมกัน")
        add("ETF","ผลตอบแทน 3 เดือน",show_number(ret,"%"),">=0% = 10; <0% = 0",None if ret is None else 10 if ret>=0 else 0,10,"ราคาปรับแล้ว")
    else:
        pe=number(info.get("forwardPE"))
        target=number(info.get("targetMeanPrice"))
        quote=ctx.get("quote") or c
        upside=(target/quote-1)*100 if target is not None and quote and quote>0 else None
        add("พื้นฐาน","Forward P/E",show_number(pe,"x"),">0–25 = 10; >25–40 = 5; <=0 หรือ >40 = 0",None if pe is None else 10 if 0<pe<=25 else 5 if 25<pe<=40 else 0,10,"Yahoo Finance; ไม่ใช่มูลค่ายุติธรรมรายอุตสาหกรรม")
        add("พื้นฐาน","Upside ราคาเป้าหมาย",show_number(upside,"%"),">=10% = 10; 5–<10% = 5; <5% = 0",None if upside is None else 10 if upside>=10 else 5 if upside>=5 else 0,10,"ราคาเป้าหมายเฉลี่ยนักวิเคราะห์")
    score=sum(r["ได้"] for r in rows if r["ได้"] is not None)
    coverage=sum(r["เต็ม"] for r in rows if r["ได้"] is not None)
    return {"rows":pd.DataFrame(rows),"score":score,"coverage":coverage,"upper":score+100-coverage,"trend":trend}


def build_entry_plan(ctx, info, scored, is_etf, min_rr=2.0, now=None):
    """Transparent long pullback setup. This is a heuristic, not a forecast."""
    result={"zone_low":None,"zone_high":None,"entry":None,"stop":None,"target":None,"rr":None,"blockers":[],"status":"ข้อมูลไม่พอ", "ready":False}
    f,m=ctx.get("history"),ctx.get("metrics",{})
    ema,atr=number(m.get("EMA20")),number(m.get("ATR"))
    if f is None or len(f)<60 or ema is None or atr is None or atr<=0:
        result["blockers"].append("ต้องมีประวัติอย่างน้อย 60 แท่ง พร้อม EMA20 และ ATR14")
        return result
    low,high=ema-.25*atr,ema+.25*atr
    support=float(f.Low.tail(20).min())
    resistance=float(f.High.tail(60).max())
    stop=min(support-.25*atr,low-1.5*atr)
    analyst=number(info.get("targetMeanPrice")) if not is_etf else None
    target=min(resistance,analyst) if analyst is not None and analyst>0 else resistance
    result.update(zone_low=low,zone_high=high,entry=high,stop=stop,target=target,support=support,resistance=resistance)
    blockers=result["blockers"]
    if low<=0 or stop<=0 or stop>=high or target<=high:
        blockers.append("ระดับราคา/Stop/เป้าหมายไม่รองรับแผนซื้อที่สมเหตุผล")
    else:
        result["rr"]=(target-high)/(high-stop)
    if result["rr"] is None or result["rr"]<min_rr:
        blockers.append(f"Reward/Risk ต้อง >= {min_rr:.1f} (ปัจจุบัน {show_number(result['rr'])})")
    if scored["coverage"]<100:
        blockers.append(f"ข้อมูลให้คะแนนยังไม่ครบ ({scored['coverage']}/100 คะแนนที่ประเมินได้)")
    if scored["score"]<80:
        blockers.append(f"คะแนนต้อง >=80/100 (ปัจจุบัน {scored['score']}/100)")
    if scored["trend"] is not True:
        blockers.append("แนวโน้มต้องเป็น ราคา > EMA20 > EMA50")
    nowstamp=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if nowstamp.tzinfo is None:
        nowstamp=nowstamp.tz_localize("UTC")
    last_date=f.index[-1].date()
    if (nowstamp.date()-last_date).days>7:
        blockers.append("แท่งราคาเก่าเกิน 7 วัน ต้องอัปเดตข้อมูลก่อน")
    quote,quote_time=ctx.get("quote"),ctx.get("quote_time")
    age=nowstamp.timestamp()-quote_time if quote_time is not None else None
    if age is None or not -60<=age<=900:
        blockers.append("ต้องยืนยันราคา quote ที่อัปเดตไม่เกิน 15 นาที")
    name=(str(info.get("shortName",""))+" "+str(info.get("longName",""))).lower()
    if is_etf and re.search(r"\b(2x|3x|inverse|leveraged|ultrapro|ultrashort)\b",name):
        blockers.append("ETF ทด/ผกผันอยู่นอกขอบเขตโมเดลนี้")
    if quote is None:
        blockers.append("ไม่มีราคา quote สำหรับยืนยันจุดเข้า")
    elif quote<low:
        blockers.append(f"ราคาต่ำกว่าโซน {low:.4f}; รอการยืนยันแนวรับใหม่")
    elif quote>high:
        blockers.append(f"รอราคาย่อลงสู่โซน {low:.4f}–{high:.4f}; ไม่ไล่ราคา")
    if not blockers:
        result.update(status="เข้าได้ตามเงื่อนไขของโมเดล",ready=True)
    elif scored["coverage"]<100:
        result["status"]="รอข้อมูลให้ครบ"
    elif scored["score"]<60 or scored["trend"] is False:
        result["status"]="ยังไม่ควรเข้าตามโมเดลนี้"
    else:
        result["status"]="รอจังหวะ / รอยืนยันเงื่อนไข"
    return result


def render_decision(ticker, ctx, info, scored, plan, is_etf, div_result, currency):
    st.subheader("เกณฑ์เข้าซื้อ — Trading Verdict (เต็ม 100)")
    a,b,c=st.columns(3)
    a.metric("คะแนนที่ได้",f"{scored['score']} / 100")
    b.metric("ความครบของข้อมูล",f"{scored['coverage']} / 100")
    c.metric("คะแนนต่ำสุด–สูงสุดที่เป็นไปได้",f"{scored['score']}–{scored['upper']}")
    st.dataframe(pd.DataFrame([
        {"ช่วงคะแนน":"80–100","ความหมาย":"ผ่านระดับคะแนนสำหรับพิจารณาเข้า ต้องผ่านเงื่อนไขราคา/ความเสี่ยงด้วย"},
        {"ช่วงคะแนน":"60–79","ความหมาย":"เฝ้าดู / รอจังหวะ ยังไม่ผ่านเกณฑ์เข้า"},
        {"ช่วงคะแนน":"40–59","ความหมาย":"ยังไม่ควรเข้าตามโมเดลนี้"},
        {"ช่วงคะแนน":"0–39","ความหมาย":"งดเข้าตามโมเดลนี้"}]),hide_index=True,**width_options(st.dataframe))
    st.caption(("โปรไฟล์ ETF: แทน P/E และราคาเป้าหมายด้วยผลตอบแทน 3 เดือนและความแข็งแกร่งเทียบ SPY" if is_etf else "โปรไฟล์หุ้น: รวมเงื่อนไขแนวโน้ม โมเมนตัม วอลุ่ม ความผันผวน P/E และราคาเป้าหมาย")+" · ข้อมูลที่ขาดไม่ถูกนับเป็นผ่าน และไม่มีการหารปรับให้คะแนนสูงขึ้น")
    st.dataframe(scored["rows"],hide_index=True,**width_options(st.dataframe),height=370,
                 column_config={"ช่วง / คะแนน":st.column_config.TextColumn(width="large")})
    bar=ctx.get("metrics",{}).get("Bar_Date","ไม่มีข้อมูล")
    st.caption(f"เกณฑ์เทคนิคใช้แท่งรายวันก่อนวันปัจจุบันตามตลาด ล่าสุด {bar} เพื่อไม่เทียบวอลุ่มระหว่างวันกับวอลุ่มเต็มวัน")
    st.subheader(f"แผนราคาเข้า — {ticker}")
    (st.success if plan["ready"] else st.warning)(plan["status"])
    m=ctx.get("metrics",{})
    trend_text="ยังไม่มีข้อมูลพอ" if scored["trend"] is None else "เรียงตัวเป็นขาขึ้นตามเกณฑ์" if scored["trend"] else "ยังไม่ผ่านการเรียงตัวขาขึ้น"
    st.write(f"**สรุปข้อมูลประกอบ:** ราคา quote {show_number(ctx.get('quote'),digits=4)} {currency}; แนวโน้ม {trend_text}; RSI {show_number(m.get('RSI_14'))}; MACD / Signal {show_number(m.get('MACD'),digits=4)} / {show_number(m.get('MACD_Signal'),digits=4)}; Volume Ratio {show_number(m.get('Vol_Ratio'),'x')}; ATR14 {show_number(m.get('ATR'),digits=4)} {currency}")
    if is_etf:
        st.write(f"**ผลตอบแทน ETF:** 3 เดือน {show_number(ctx.get('return_3m'),'%')} และต่างจาก SPY {show_number(ctx.get('relative_3m'),' จุดเปอร์เซ็นต์')} โดยใช้วันที่ร่วมกัน; เกณฑ์นี้วัดกลยุทธ์ตามแนวโน้ม ไม่ได้ตัดสินว่า ETF ตราสารหนี้หรือทองคำเหมาะกับพอร์ตหรือไม่")
    else:
        st.write(f"**พื้นฐาน:** Forward P/E {show_number(info.get('forwardPE'),'x')}; เป้าหมายเฉลี่ยนักวิเคราะห์ {show_number(info.get('targetMeanPrice'))} {currency}; Beta {show_number(info.get('beta'))} ใช้ประกอบความเสี่ยง โดยราคาเป้าหมายเป็นประมาณการ ไม่ใช่ราคาที่จะเกิดแน่นอน")
    if plan["entry"] is not None:
        a,b,c,d=st.columns(4)
        a.metric(f"โซนรอซื้อ ({currency})",f"{plan['zone_low']:,.4f}–{plan['zone_high']:,.4f}")
        b.metric("ราคาเข้าอ้างอิง",show_number(plan["entry"],digits=4))
        c.metric("Stop Loss",show_number(plan["stop"],digits=4))
        d.metric("เป้าทำกำไร / R:R",f"{show_number(plan['target'],digits=4)} / {show_number(plan['rr'])}")
        st.write("**ที่มาของราคา:** โซนซื้อ = EMA20 ± 0.25 ATR; ราคาเข้าอ้างอิง = ขอบบนของโซน; Stop = ค่าต่ำกว่าระหว่างแนวรับต่ำสุด 20 แท่งลบ 0.25 ATR กับขอบล่างโซนลบ 1.5 ATR")
        st.write("**เป้าหมาย:** แนวต้านสูงสุด 60 แท่ง"+(" โดยจำกัดไม่เกินราคาเป้าหมายนักวิเคราะห์เมื่อมีข้อมูล" if not is_etf else "")+"; R:R = (เป้าหมาย − ราคาเข้า) ÷ (ราคาเข้า − Stop)")
        if not plan["ready"]:
            st.caption("ตัวเลขนี้เป็นแผนรอเงื่อนไข ไม่ใช่สัญญาณให้ส่งคำสั่งซื้อทันที")
        if plan["stop"]>0 and plan["target"]>plan["entry"]:
            if st.button("นำราคาในแผนไปคำนวณจำนวนหุ้น",key="apply_entry_plan"):
                st.session_state[f"entry_{ticker}"]=float(plan["entry"])
                st.session_state[f"stop_{ticker}"]=float(plan["stop"])
    if plan["blockers"]:
        st.markdown("**เงื่อนไขที่ยังต้องรอ:**\n\n"+"\n".join("- "+reason for reason in plan["blockers"]))
    div=dividend_summary(div_result,ctx.get("quote"))
    st.write(f"**ปันผลประกอบการพิจารณา:** 12 เดือนย้อนหลัง {show_number(div['total'],digits=4)} {currency}/หน่วย; Yield {show_number(div['yield'],'%')}; ล่าสุด {div['last_date'] or 'ไม่มีข้อมูล'}")
    st.caption("ปันผลใช้ประกอบกระแสเงินสด ไม่เพิ่มคะแนนซื้ออัตโนมัติ และไม่ใช่การรับประกันการจ่ายครั้งต่อไป")
    st.caption("โมเดลนี้เป็นกติกาสำหรับซื้อเมื่อย่อในแนวโน้มขาขึ้น ยังไม่ผ่านการทดสอบย้อนหลัง ค่าคะแนน/ตัวคูณ ATR เป็นสมมติฐานของระบบ ไม่ใช่ความน่าจะเป็นกำไรหรือราคาที่รับประกัน")
    with st.expander("แหล่งอ้างอิงและขอบเขตของเกณฑ์"):
        st.markdown("[ATR และความผันผวน — Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr) · [ข้อมูลราคาและปันผล — yfinance](https://ranaroussi.github.io/yfinance/reference/index.html) · [ETF ทดและผกผัน — Investor.gov](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/sec)")
        st.write("แหล่งอ้างอิงอธิบายข้อมูลและอินดิเคเตอร์ ไม่ได้รับรองคะแนน 100 จุดหรือสูตรราคาเข้าของระบบนี้ กติกาเหมาะสำหรับเทียบสินทรัพย์ภายในกลยุทธ์เดียวกัน ไม่แทนการวิเคราะห์ข่าว ผลประกอบการ และความเหมาะสมกับพอร์ต")


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
    aliases = {
        "Industry": ["industry", "อุตสาหกรรม"],
        "Fund_Category": ["category", "fund_category", "หมวด ETF"],
        "Historical_Return": ["1y return (%)", "1y return%", "return_1y", "1y_return"],
        "Return_2Y": ["2y return (%)", "2y return%", "return_2y", "2y_return"],
        "Return_3Y": ["3y return (%)", "3y return%", "return_3y", "3y_return"],
    }
    for canonical, alternatives in aliases.items():
        if canonical not in frame:
            candidate = next((c for c in frame if c.casefold() in alternatives), None)
            if candidate is not None:
                frame = frame.rename(columns={candidate: canonical})
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
    if "Industry" not in frame:
        frame["Industry"] = None
    frame["Industry"] = frame.Industry.map(clean_industry)
    if "Fund_Category" in frame:
        etfs = frame.Asset_Type.str.upper().str.contains("ETF", regex=False) | frame.Ticker.isin(ETF_NAMES)
        frame.loc[etfs, "Industry"] = frame.loc[etfs, "Industry"].combine_first(frame.loc[etfs, "Fund_Category"].map(clean_industry))
    if "Industry_Source" not in frame:
        frame["Industry_Source"] = np.where(frame.Industry.notna(), "CSV", "")
    if "Industry_Time" not in frame:
        frame["Industry_Time"] = ""
    if "Status" not in frame:
        frame["Status"] = "ไม่มีข้อมูล"
    frame["Status"] = frame.Status.fillna("ไม่มีข้อมูล").astype(str).str.strip().str.upper()
    for col in WATCHLIST_NUMERIC_COLUMNS:
        if col not in frame:
            frame[col] = np.nan
        elif not pd.api.types.is_numeric_dtype(frame[col]):
            frame[col] = pd.to_numeric(
                frame[col].astype(str).str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False).str.replace("%", "", regex=False), errors="coerce")
        frame[col] = numeric_watchlist_series(frame[col])
    return frame.reset_index(drop=True)


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
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
        term=query.strip().upper()
        found=result.Ticker.str.contains(term,regex=False,na=False)
        if "Security_Name" in result:
            found=found | result.Security_Name.str.upper().str.contains(term,regex=False,na=False)
        if "Industry" in result:
            found=found | result.Industry.fillna("").str.upper().str.contains(term,regex=False,na=False)
        result = result.loc[found]
    for col, mask in [("Close", result.Close.between(low, high)),
                      ("RSI_14", result.RSI_14.between(*rsi_range)),
                      ("Historical_Return", result.Historical_Return.ge(min_return))]:
        if keep_missing:
            mask = mask | result[col].isna()
        result = result.loc[mask.reindex(result.index, fill_value=False)]
    return result


def load_fundamentals(ticker):
    result, _ = get_data_cache().get(f"info:{ticker}")
    if not result:
        raise ValueError("ยังไม่มีข้อมูลพื้นฐานที่บันทึกไว้ กดโหลด/อัปเดตหุ้นที่เลือก")
    return result


load_fundamentals.clear = lambda *args: None


def daily_snapshot(history):
    if history is None or history.empty:
        return {}
    f = normalize_history(history)
    close = f.Close
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    macd = close.ewm(span=12, adjust=False, min_periods=12).mean() - close.ewm(span=26, adjust=False, min_periods=26).mean()
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    rsi = wilder_rsi(close)
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
    return {"Close": number(close.iloc[-1]), "EMA20": number(ema20.iloc[-1]), "EMA50": number(ema50.iloc[-1]),
            "SMA200": number(sma200.iloc[-1]), "RSI_14": number(rsi.iloc[-1]), "MACD": number(macd.iloc[-1]),
            "MACD_Signal": number(signal.iloc[-1]), "ATR": atr, "Vol_Ratio": ratio,
            "Bar_Date": f.index[-1].strftime("%Y-%m-%d")}


def build_analysis(snapshot, selected_row, info):
    metrics, sources = {}, {}
    for col in NUMERIC_COLUMNS:
        fresh = number(snapshot.get(col))
        old = number(selected_row.get(col))
        metrics[col] = fresh if fresh is not None else old
        sources[col] = "กราฟรายวัน" if fresh is not None else str(selected_row.get("Data_Source") or "CSV") if old is not None else "—"
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

    pe_text = "ไม่มีประมาณการกำไร" if pe is None else "กำไรประมาณการไม่เป็นบวก" if pe <= 0 else "อยู่ในช่วง >0–25 เท่า (เกณฑ์เต็ม 10)" if pe <= 25 else "อยู่ในช่วง >25–40 เท่า (เกณฑ์ 5)" if pe <= 40 else "มากกว่า 40 เท่า (เกณฑ์ 0)"
    add("พื้นฐาน", "Forward P/E", show_number(pe, "x"), pe_text+"; ควรเทียบธุรกิจกลุ่มเดียวกัน", "Yahoo Finance")
    add("พื้นฐาน", "Trailing P/E", show_number(trailing_pe, "x"), "ราคาเทียบกำไรย้อนหลัง", "Yahoo Finance")
    add("พื้นฐาน", "Target Price", show_number(target), "ไม่มีราคาเป้าหมาย" if upside is None else f"ต่างจากราคาอ้างอิง {upside:+.2f}%", "นักวิเคราะห์ผ่าน Yahoo")
    add("พื้นฐาน", "Dividend Yield", show_number(dividend_pct, "%"), "อัตราปันผลย้อนหลังเทียบราคาอ้างอิง" if dividend_pct is not None else "ไม่มีข้อมูลปันผล", "Yahoo Finance")
    add("เทคนิค", "Trend / Screener", status, "สถานะของแหล่ง Watchlist; คะแนน 100 คำนวณจากข้อมูลใหม่ด้านล่าง", str(selected_row.get("Data_Source") or "CSV") if selected_row else "—")
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
    if f"entry_{ticker}" not in st.session_state:
        st.session_state[f"entry_{ticker}"]=float(entry_default)
    if f"stop_{ticker}" not in st.session_state:
        st.session_state[f"stop_{ticker}"]=float(stop_default)
    entry = a.number_input("ราคาเข้าซื้อ", min_value=0.0, step=.01, format="%.4f", key=f"entry_{ticker}")
    stop = b.number_input("Stop Loss", min_value=0.0, step=.01, format="%.4f", key=f"stop_{ticker}")
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
    if st.button("โหลด / อัปเดตข้อมูลคู่เปรียบเทียบ", key=f"{key}_load"):
        accepted = [get_updater().request(t, "history", "1d") for t in (first, second)]
        if all(accepted):
            st.info("กำลังโหลดคู่เปรียบเทียบเบื้องหลัง")
        else:
            st.warning("แหล่งข้อมูลกำลังพัก ลองใหม่หลังเวลาที่แสดงด้านบน")
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
    query = c.text_input("ค้นหา Ticker / บริษัท / อุตสาหกรรม", key="search_ticker", help="เช่น SCHD, Vanguard, Semiconductors หรือ Software ค้นจากข้อมูลที่บันทึกไว้")
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


RETURN_COLUMNS = ["Historical_Return", "Return_2Y", "Return_3Y"]
WATCHLIST_COLUMNS = ["Ticker", "Security_Name", "Industry", "Asset_Type", "Status", "Close", *RETURN_COLUMNS,
                     "Vol_Ratio", "RSI_14", "MACD", "Data_Source", "Data_Status", "Price_AsOf", "Data_Time"]


def return_cell_style(value):
    n = number(value)
    if n is None or n == 0:
        return ""
    return ("background-color: #143d2b; color: #7ee2a8; font-weight: 600" if n > 0 else
            "background-color: #4a2028; color: #ff9b9b; font-weight: 600")


def watchlist_column_config():
    config = {
        "Ticker": st.column_config.TextColumn("Ticker", help="สัญลักษณ์ซื้อขายของหุ้นหรือ ETF เช่น AAPL หรือ SPY"),
        "Security_Name": st.column_config.TextColumn("ชื่อบริษัท / ETF", help="ชื่อหลักทรัพย์จากทะเบียน Nasdaq ณ วันที่ระบุด้านบน", width="large"),
        "Industry": st.column_config.TextColumn("อุตสาหกรรม / หมวด ETF", help="หุ้น: อุตสาหกรรม (Industry) จาก CSV หรือ Yahoo Finance; ETF: หมวดกองทุน (Category) ซึ่งอาจลงทุนหลายอุตสาหกรรม เครื่องหมาย — คือยังไม่มีข้อมูล กดเติมอุตสาหกรรมหน้านี้เพื่อโหลด ข้อมูลนี้อัปเดตแยกจากเวลาราคา", width="medium"),
        "Asset_Type": st.column_config.TextColumn("ประเภท", help="Common Stock คือหุ้นสามัญ; ETF คือกองทุนที่ซื้อขายในตลาดหลักทรัพย์"),
        "Status": st.column_config.TextColumn("Status", help="สแกนใหม่: PASS เมื่อราคาปิด > EMA20 > EMA50; FAIL เมื่อไม่ครบเงื่อนไข; ถ้าข้อมูลไม่พอจะแจ้งไม่มีข้อมูล แถว CSV อาจใช้เกณฑ์เดิม สถานะนี้ไม่ใช่คำแนะนำซื้อหรือคะแนน 100 จุด"),
        "Close": st.column_config.NumberColumn("ราคา Watchlist", help="ราคาจาก CSV หรือราคาปิดรายวันปรับแล้วในสกุลของสินทรัพย์นั้น ดูวันที่ราคาและแหล่งข้อมูลประกอบ ไม่ใช่ราคาเรียลไทม์", format="%.2f"),
        "Vol_Ratio": st.column_config.NumberColumn("Vol Ratio", help="ปริมาณซื้อขายของแท่งรายวันล่าสุด ÷ ค่าเฉลี่ย 20 แท่งก่อนหน้า เช่น 1.50x หมายถึงมากกว่าค่าเฉลี่ย 50% ใช้แท่งก่อนวันปัจจุบันตามตลาด; CSV อาจใช้สูตรเดิม", format="%.2fx"),
        "RSI_14": st.column_config.NumberColumn("RSI (14)", help="Relative Strength Index แบบ Wilder ระยะ 14 แท่ง ช่วง 0–100 มากกว่า 70 คือเขตซื้อมาก ต่ำกว่า 30 คือเขตขายมาก ไม่ใช่สัญญาณซื้อขายโดยลำพัง", format="%.2f"),
        "MACD": st.column_config.NumberColumn("MACD", help="EMA12 − EMA26 ของราคาปิด หน่วยเดียวกับราคา ค่าบวกหมายถึงค่าเฉลี่ยระยะสั้นสูงกว่าระยะยาว การเทียบกับเส้น Signal ใช้ EMA9 ของ MACD", format="%.4f"),
        "Data_Source": st.column_config.TextColumn("แหล่งข้อมูล", help="ที่มาของราคาและตัวชี้วัดในแถว เช่น CSV หรือการสแกนรายวันจาก Yahoo Finance อุตสาหกรรมมีแหล่งข้อมูลแยกในไฟล์ดาวน์โหลด"),
        "Data_Status": st.column_config.TextColumn("สถานะข้อมูล", help="บอกว่าโหลดสำเร็จ ยังไม่โหลด หรือโหลดใหม่ไม่สำเร็จ หากโหลดใหม่ล้มเหลวจะคงราคาและเวลาที่เคยสำเร็จไว้"),
        "Price_AsOf": st.column_config.TextColumn("วันที่ราคา", help="วันที่แท่งราคาที่ใช้คำนวณ ตามปฏิทินตลาด ไม่ใช่วันที่เปิดหน้าเว็บ ใช้แท่งก่อนวันปัจจุบันตามตลาดเพื่อหลีกเลี่ยงปริมาณซื้อขายที่ยังไม่จบวัน"),
        "Data_Time": st.column_config.TextColumn("ดึงข้อมูลสำเร็จ (ไทย)", help="วันและเวลาที่ดึงราคาชุดนี้สำเร็จ แปลงเป็นเวลาไทย UTC+7 การเปิดหน้าใหม่ไม่เปลี่ยนเวลานี้ และไม่ใช่เวลาที่ราคาซื้อขายเกิดขึ้น"),
    }
    for years, col in zip((1, 2, 3), RETURN_COLUMNS):
        config[col] = st.column_config.NumberColumn(f"{years}Y Return (%)", format="%+.2f%%",
            help=f"ผลตอบแทนสะสม {years} ปี ไม่ใช่ผลตอบแทนเฉลี่ยต่อปี (CAGR): (ราคาปรับแล้วล่าสุด ÷ ราคาปรับแล้วของวันซื้อขายแรกตั้งแต่วันที่ย้อนหลัง {years} ปี − 1) × 100 ใช้แท่งรายวันก่อนวันนี้ตามตลาด สีเขียวคือบวก สีแดงคือลบ และ — คือประวัติไม่ครบช่วง ค่าจาก CSV อาจใช้วิธีคำนวณเดิม")
    return config


def render_watchlist_table(frame):
    columns = WATCHLIST_COLUMNS
    pages=max(1,math.ceil(len(frame)/100))
    if "watchlist_page" in st.session_state and st.session_state.watchlist_page>pages:
        st.session_state.watchlist_page=1
    page=st.number_input("หน้าตาราง (หน้าละ 100 ตัว)",min_value=1,max_value=pages,step=1,key="watchlist_page")
    start=(page-1)*100
    st.caption(f"แสดง {start+1 if len(frame) else 0:,}–{min(start+100,len(frame)):,} จาก {len(frame):,} ตัว · ดาวน์โหลดได้ครบทุกแถวที่ผ่านตัวกรอง")
    table = frame.iloc[start:start+100].reindex(columns=columns).copy()
    a, b = st.columns(2)
    fill_industry = a.button("เติมอุตสาหกรรมหน้านี้", key="fill_industry_page", disabled=table.empty,
                            help="ดึงเฉพาะรายการที่ยังไม่มีอุตสาหกรรมในหน้าปัจจุบัน สูงสุด 100 ตัว ทำเบื้องหลังและบันทึกใช้ซ้ำ")
    fill_returns = b.button("เติมผลตอบแทน 1 / 2 / 3 ปี หน้านี้", key="fill_returns_page", disabled=table.empty,
                           help="โหลดประวัติให้หุ้นในหน้านี้เบื้องหลัง ครั้งแรกต้องเติมประวัติให้ครอบคลุม 3 ปี การโหลดครั้งต่อไปใช้ข้อมูลที่เก็บไว้")
    if fill_industry:
        missing = table.loc[table.Industry.map(clean_industry).isna(), "Ticker"]
        queued = sum(get_updater().request(t, "industry") for t in missing)
        if queued:
            st.info(f"เข้าคิวเติมอุตสาหกรรม {queued} ตัวในหน้านี้ ข้อมูลจะขึ้นเองเมื่อสำเร็จ")
        elif len(missing):
            st.warning("แหล่งข้อมูลกำลังพัก ลองใหม่หลังเวลาพักที่แสดงด้านบน")
        else:
            st.info("หน้านี้มีข้อมูลอุตสาหกรรมหรือหมวด ETF ครบแล้ว")
    if fill_returns:
        indexed = frame.set_index("Ticker")
        pending = [t for t in table.Ticker if not summary_is_current(indexed.loc[t].to_dict())]
        if not pending:
            st.info("ประวัติหน้านี้ตรวจแล้ววันนี้ ช่อง — ที่เหลืออาจเป็นหุ้นหรือ ETF ที่มีประวัติไม่ถึงช่วงนั้น")
        elif get_updater().start_scan(pending):
            st.info(f"กำลังเติมประวัติและผลตอบแทน {len(pending)} ตัวในหน้านี้เบื้องหลัง")
        else:
            st.warning("มีงานสแกนอยู่ หรือแหล่งข้อมูลกำลังพัก ดูสถานะในส่วนอัปเดตทั้งชุด")
    table["Data_Time"] = table.Data_Time.map(lambda value: thai_time(value) if pd.notna(value) and value else "ไม่ระบุ")
    def rsi_style(value):
        n = number(value)
        return "" if n is None else "color: #ef5350" if n > 70 else "color: #26a69a" if n < 30 else ""
    styled = table.style.format({"Close":"{:,.2f}", **{c:"{:+.2f}%" for c in RETURN_COLUMNS}, "Vol_Ratio":"{:.2f}x", "RSI_14":"{:.2f}", "MACD":"{:.4f}"}, na_rep="—")
    styled = styled.map(rsi_style, subset=["RSI_14"]) if hasattr(styled,"map") else styled.applymap(rsi_style, subset=["RSI_14"])
    styled = styled.map(return_cell_style, subset=RETURN_COLUMNS) if hasattr(styled,"map") else styled.applymap(return_cell_style, subset=RETURN_COLUMNS)
    st.dataframe(styled, height=500, **width_options(st.dataframe), hide_index=True, column_config=watchlist_column_config())
    st.caption("ชี้เมาส์ที่หัวคอลัมน์เพื่อดูคำอธิบาย · ผลตอบแทนสะสม: เขียว = บวก / แดง = ลบ / — = ข้อมูลไม่พอ · เลื่อนตารางแนวนอนหรือขยายเต็มจอเพื่อดูทุกคอลัมน์")
    st.download_button("ดาวน์โหลดรายการที่กรองแล้ว", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="filtered_watchlist.csv", mime="text/csv", key="download_watchlist")


def main():
    st.set_page_config(page_title="Ultimate Trend Trading Terminal", page_icon="📈", layout="wide")
    render_revision = get_updater().state()["revision"]
    st.markdown("""<style>
    .block-container {padding-top:2rem;padding-bottom:3rem;max-width:1800px}
    [data-testid="stMetricValue"]{font-size:1.65rem}
    [data-testid="stDataFrame"]{border:1px solid #334155;border-radius:7px}
    </style>""", unsafe_allow_html=True)
    head,settings=st.columns([4,1])
    head.title("Ultimate Trend Trading Terminal")
    head.caption(f"รุ่น {APP_VERSION} · เปิดข้อมูลที่มีทันที · Common Stock 4,200 · ETF 700")
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh=False
    auto=settings.checkbox("อัปเดตหุ้นที่เลือกทุก 5 นาที",key="auto_refresh")
    refresh_selected = settings.button("อัปเดตหุ้นที่เลือก", key="refresh_all")
    st.caption(f"หน้าอัปเดตล่าสุด: {thai_time(datetime.now(timezone.utc))} · ราคาเป็นการดึงตามรอบและอาจล่าช้า ดูเวลาของราคาแยกด้านล่าง")
    original=pd.DataFrame(columns=["Ticker","Asset_Type","Status"]+NUMERIC_COLUMNS)
    source_label="ไม่ได้ใช้ CSV — ใช้รายชื่อที่ฝังอยู่ในแอป"
    csv_time="ไม่ทราบเวลาข้อมูลในไฟล์"
    with st.expander("ข้อมูล CSV เดิม / อัปโหลด Watchlist",expanded=False):
        upload=st.file_uploader("เลือก daily_watchlist.csv เดิม",type=["csv"],key="watchlist_upload")
        st.caption("อ่าน daily_watchlist.csv ข้าง app.py อัตโนมัติ ใช้ข้อมูลเดิมประกอบชุด 4,900 ตัว การเปลี่ยน app.py ไม่ได้เขียนทับ CSV")
    try:
        if upload is not None:
            original=parse_watchlist(upload.getvalue())
            source_label=f"ไฟล์ที่อัปโหลด: {upload.name}"
        elif WATCHLIST_FILE.exists():
            stat=WATCHLIST_FILE.stat()
            original=read_watchlist(str(WATCHLIST_FILE),stat.st_mtime_ns,stat.st_size)
            csv_time=thai_time(datetime.fromtimestamp(stat.st_mtime,timezone.utc))
            source_label=f"CSV แก้ไขไฟล์ล่าสุด {csv_time}"
    except Exception as exc:
        st.error(f"อ่าน CSV ไม่สำเร็จ: {exc} — ยังแสดงชุดรายชื่อ 4,900 ตัวได้")
    st.caption(source_label+" · เวลาแก้ไขไฟล์ไม่ใช่เวลาราคา")
    universe=render_scan_controls(original)
    frame,outside=build_universe_frame(original,st.session_state.quote_records,get_data_cache().classifications())
    c1,c2,c3,c4=st.columns(4)
    c1.metric("สินทรัพย์ทั้งหมด",f"{len(frame):,}")
    c2.metric("Common Stock",f"{int(frame.Asset_Type.eq('Common Stock').sum()):,}")
    c3.metric("ETF",f"{int(frame.Asset_Type.eq('ETF').sum()):,}")
    c4.metric("มีราคาใน Watchlist",f"{int(frame.Close.notna().sum()):,} / {len(frame):,}")
    stamps=[str(r.get("Data_Time")) for r in st.session_state.quote_records.values() if r.get("Data_Time")]
    scan_stamp=max(stamps) if stamps else ""
    st.caption(f"สแกนสำเร็จล่าสุด {thai_time(scan_stamp)} · PASS {int(frame.Status.eq('PASS').sum()):,} ตัว · ชุดสแกนใหม่ใช้ Close > EMA20 > EMA50; สถานะเดิมจาก CSV เก็บใน CSV_Screener_Status")
    st.caption("รายชื่อครบไม่ได้หมายความว่าราคาครบ ช่องว่างคือยังไม่มีราคาที่โหลดได้ เลือกหุ้นเพื่อวิเคราะห์ได้ทันที หรือใช้ปุ่มสแกนเพื่อเติมข้อมูลสำหรับตัวกรอง")
    if not outside.empty:
        with st.expander(f"รายการจาก CSV นอกชุด 4,900 ตัว ({len(outside):,} รายการ)"):
            st.caption("เก็บแสดงแยกเพื่อรักษาจำนวน Common Stock 4,200 และ ETF 700 รายการเหล่านี้ยังอยู่ในไฟล์ต้นฉบับ และพิมพ์ Ticker เพื่อวิเคราะห์ได้")
            st.dataframe(outside,hide_index=True,height=250,**width_options(st.dataframe))
            st.download_button("ดาวน์โหลดรายการนอกชุด",outside.to_csv(index=False).encode("utf-8-sig"),file_name="outside_universe.csv",mime="text/csv",key="outside_csv")
    filtered=render_filters(frame)
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
        ticker=normalize_symbol(ticker)
        valid_ticker = bool(re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}",ticker))
        matches = frame.loc[frame.Ticker.eq(ticker)]
        selected_row = matches.iloc[0].to_dict() if not matches.empty else {}
        info, history, snapshot, history_stamp = {}, None, {}, ""
        div_result={"data":None,"fetched_at":"","error":"ยังไม่มี Ticker ที่ถูกต้อง","coverage_start":"","coverage_end":""}
        if valid_ticker:
            requested = st.button("โหลด/อัปเดตหุ้นที่เลือก", key="load_selected", type="primary")
            last_request = st.session_state.get(f"requested_at_{ticker}", 0.0)
            if requested or refresh_selected or (auto and time.time() - last_request >= 300):
                worker = get_updater()
                accepted = worker.request(ticker, "history", "1d")
                if accepted:
                    worker.request(ticker, "info")
                    worker.request(ticker, "dividends")
                    if ticker in ETF_NAMES and ticker != "SPY":
                        worker.request("SPY", "history", "1d")
                    st.session_state[f"requested_at_{ticker}"] = time.time()
                    st.info(f"กำลังโหลด {ticker} เบื้องหลัง ข้อมูลใหม่จะขึ้นเองเมื่อสำเร็จ ใช้หน้าเว็บต่อได้")
                else:
                    st.warning("Yahoo กำลังพักถึง " + thai_time(worker.state()["cooldown_until"]) + " — แสดงข้อมูลเดิมต่อ")
            try:
                info = load_fundamentals(ticker)
            except Exception as exc:
                st.warning(f"ข้อมูลพื้นฐานยังโหลดไม่ได้: {exc}")
            try:
                history, history_stamp = load_chart_history(ticker,"1d")
                snapshot = daily_snapshot(completed_daily_history(history))
            except Exception as exc:
                st.warning(f"ราคาย้อนหลังยังโหลดไม่ได้ ใช้ค่าที่มีใน CSV: {exc}")
            with st.spinner("โหลดประวัติปันผล…"):
                div_result=load_dividend_history(ticker)
        else:
            st.info("กรุณาระบุ Ticker ให้ถูกต้อง")
        analysis, metrics, facts = build_analysis(snapshot, selected_row, info)
        is_etf=asset_is_etf(ticker,selected_row,info)
        if ticker in set(universe) and snapshot and history_stamp:
            try:
                known=scan_snapshot_row(ticker,history,history_stamp)
                known["History_Years_Loaded"] = get_data_cache().history(ticker)[1].get("years", 0)
                st.session_state.quote_records=remember_quotes(st.session_state.quote_records,pd.DataFrame([known]))
                st.session_state.scan_attempted=sorted(set(st.session_state.scan_attempted) | {ticker})
            except (ValueError,KeyError):
                pass
        currency = str(info.get("currency") or selected_row.get("Currency") or "สกุลราคาหุ้น")
        div_stats=dividend_summary(div_result,metrics["Quote"])
        facts["dividend_pct"]=div_stats["yield"]
        div_mask=analysis["ปัจจัย"].eq("Dividend Yield")
        analysis.loc[div_mask,"ค่าล่าสุด"]=show_number(div_stats["yield"],"%")
        analysis.loc[div_mask,"แหล่งข้อมูล"]="ประวัติปันผลที่โหลดสำเร็จ" if not div_result["error"] else "ไม่มีข้อมูล"
        analysis.loc[div_mask,"การแปลผล"]="ยอดปันผลต่อหน่วย 12 เดือน / ราคาอ้างอิง" if not div_result["error"] else "โหลดประวัติไม่ได้ ไม่ตีความว่าไม่มีปันผล"
        st.markdown(f"**{ticker or '—'} — {info.get('shortName') or info.get('longName') or selected_row.get('Security_Name') or ''}**")
        st.caption(f"Sector: {info.get('sector') or 'ไม่มีข้อมูล'} · Industry: {info.get('industry') or 'ไม่มีข้อมูล'}")
        c1,c2,c3 = st.columns(3)
        c1.metric(f"ราคาอ้างอิง ({currency})",show_number(metrics["Quote"]))
        c2.metric("Target Price",show_number(facts["target"]),
                  delta=f"{facts['upside']:+.2f}%" if facts["upside"] is not None else None)
        c3.metric("ขนาดสินทรัพย์กองทุน" if is_etf else "Market Cap",compact_number(info.get("totalAssets") if is_etf else info.get("marketCap")))
        c1,c2,c3 = st.columns(3)
        if is_etf:
            c1.metric("ประเภทสินทรัพย์","ETF")
        else:
            c1.metric("Forward P/E",show_number(facts["pe"],"x"),help="ราคาเทียบประมาณการกำไรต่อหุ้น")
        c2.metric("Dividend Yield (12 เดือน)",show_number(facts["dividend_pct"],"%"),help="รวมปันผลจากประวัติ 12 เดือน หารด้วยราคาอ้างอิง")
        c3.metric("Beta",show_number(facts["beta"]),help="ค่าความสัมพันธ์ของความเคลื่อนไหวกับตลาดจากผู้ให้ข้อมูล")
        if snapshot:
            st.caption(f"อินดิเคเตอร์ใช้แท่งก่อนวันปัจจุบันตามตลาด ล่าสุด {snapshot['Bar_Date']} · ราคา Watchlist อาจอัปเดตคนละเวลา ดูคอลัมน์แหล่งข้อมูล")
        st.caption(f"ราคาจากผู้ให้ข้อมูล ณ {thai_time(info.get('regularMarketTime'))}")
    with st.expander("เวลาอัปเดตข้อมูลล่าสุด — เวลาไทย (UTC+7)",expanded=True):
        st.dataframe(pd.DataFrame([
            {"ข้อมูล":"Quote / ข้อมูลพื้นฐานของ "+ticker,"ดึงสำเร็จล่าสุด (ไทย)":thai_time(info.get("_Fetched_At_UTC")),"เวลาที่ข้อมูลอ้างถึง":thai_time(info.get("regularMarketTime"))},
            {"ข้อมูล":"ราคาย้อนหลังรายวัน","ดึงสำเร็จล่าสุด (ไทย)":thai_time(history_stamp),"เวลาที่ข้อมูลอ้างถึง":"แท่งเทคนิคล่าสุด "+str(snapshot.get("Bar_Date","ไม่มีข้อมูล"))+" (วันที่ตลาด)"},
            {"ข้อมูล":"ประวัติปันผล","ดึงสำเร็จล่าสุด (ไทย)":thai_time(div_result.get("fetched_at")),"เวลาที่ข้อมูลอ้างถึง":str(div_result.get("coverage_start") or "—")+" ถึง "+str(div_result.get("coverage_end") or "—")},
            {"ข้อมูล":"สแกน Watchlist 4,900 ตัว","ดึงสำเร็จล่าสุด (ไทย)":thai_time(scan_stamp),"เวลาที่ข้อมูลอ้างถึง":"ดูวันที่ราคาแต่ละตัวใน Watchlist"},
            {"ข้อมูล":"CSV เดิม","ดึงสำเร็จล่าสุด (ไทย)":"ไม่ทราบเวลาสแกนจากไฟล์","เวลาที่ข้อมูลอ้างถึง":"เวลาแก้ไขไฟล์: "+csv_time}]),hide_index=True,**width_options(st.dataframe))
        st.caption("หน้านี้อ่านข้อมูลที่บันทึกไว้ทันที ปุ่มอัปเดตจะโหลดเฉพาะหุ้นที่เลือกเบื้องหลัง เวลาเปิดหน้าไม่ใช่เวลาราคา และข้อมูลจาก Yahoo อาจล่าช้า")
    st.divider()
    st.subheader("ตารางวิเคราะห์ 360° — พื้นฐาน เทคนิค และความเสี่ยง")
    st.dataframe(analysis, **width_options(st.dataframe), hide_index=True, height=500,
                 column_config={"การแปลผล":st.column_config.TextColumn(width="large"),
                                "แหล่งข้อมูล":st.column_config.TextColumn(help="ค่าแต่ละส่วนอาจอัปเดตคนละเวลา")})
    benchmark=None
    if is_etf and valid_ticker:
        try:
            benchmark=history if ticker=="SPY" else load_chart_history("SPY","1d")[0]
        except Exception as exc:
            st.warning(f"ยังโหลด SPY สำหรับประเมิน ETF ไม่ได้: {exc}")
    ctx=decision_context(history,info,benchmark)
    scored=criteria_score(ctx,info,is_etf)
    min_rr=st.number_input("Reward/Risk ขั้นต่ำสำหรับให้ผ่านแผนซื้อ",min_value=2.0,max_value=10.0,value=2.0,step=.5,key="minimum_rr",help="กำไรตามเป้าหมายต้องไม่น้อยกว่าความเสี่ยงตาม Stop กี่เท่า ยังไม่รวมค่าธรรมเนียม")
    entry_plan=build_entry_plan(ctx,info,scored,is_etf,min_rr)
    render_decision(ticker,ctx,info,scored,entry_plan,is_etf,div_result,currency)
    st.divider()
    render_position_sizer(ticker or "UNKNOWN", selected_row, metrics, currency)
    st.divider()
    render_dividends(ticker,div_result,currency,metrics["Quote"])
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

    update_state = get_updater().state()
    if not update_state["busy"] and update_state["revision"] != render_revision:
        # A job may finish after its data section was drawn; show that final result.
        st.rerun()
    if update_state["busy"]:
        st.caption("กำลังอัปเดตเบื้องหลัง: " + (update_state["current"] or "รอคิว") + " · ข้อมูลจะขึ้นเองเมื่อโหลดสำเร็จ")
    if update_state["busy"] or auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=2000 if update_state["busy"] else 300_000, key="background_data_poll")
        except ImportError:
            st.info("งานยังโหลดเบื้องหลังได้ กดแสดงผลล่าสุดเพื่อดูข้อมูล หรือเพิ่ม streamlit-autorefresh ใน requirements.txt")
    st.button("แสดงผลล่าสุดที่โหลดเสร็จ", key="show_saved_results")



if __name__ == "__main__":
    main()
