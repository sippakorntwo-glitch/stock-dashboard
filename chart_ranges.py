"""Bounded selected-stock chart history, isolated from screening/valuation.
One provider request at a time, 60/hour/server, bounded queue, TTL and backoff.
No credentials, remote writes, synthetic prices or bulk scans.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
from io import StringIO
import os
import re
import threading
import time
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import dashboard_runtime as a

PERIODS=['1 วัน','3 วัน','5 วัน','7 วัน','1 เดือน','3 เดือน','6 เดือน','1 ปี','2 ปี','3 ปี','5 ปี','10 ปี']
PAGE_SIZE=500


def page_slice(frame,page,size=PAGE_SIZE):
    if page<1 or size<1:raise ValueError('page/size must be positive')
    return frame.iloc[(page-1)*size:page*size]


def chart_requests_enabled():
    try:secret=st.secrets.get('DASHBOARD_ALLOW_CHART_REQUESTS',True)
    except (FileNotFoundError,KeyError):secret=True
    return str(os.environ.get('DASHBOARD_ALLOW_CHART_REQUESTS',secret)).lower() in ('true','1')


def covers_years(frame,years):
    if frame is None or frame.empty:return False
    idx=pd.DatetimeIndex(frame.index)
    return idx[0]<=idx[-1]-pd.DateOffset(years=years)


class ChartHistoryService:
    def __init__(self,cache):
        self.cache=cache
        self.lock=threading.RLock()
        self.jobs=deque()
        self.pending=set()
        self.calls=deque()
        self.thread=None
        self.cooldown_until=0.0
        self.revision=0

    def state(self):
        with self.lock:return {'busy':bool(self.pending),'revision':self.revision}

    def read(self,ticker,kind):
        raw,meta=self.cache.get(f'chart:history:{kind}:{ticker}',request_remote=False)
        if raw is None:return None,{}
        try:
            frame=pd.read_json(StringIO(raw),orient='split')
            idx=pd.DatetimeIndex(pd.to_datetime(frame.index,utc=True)).tz_convert(meta.get('timezone','UTC'))
            frame.index=idx.tz_localize(None).normalize() if kind=='long' else idx
            return a.normalize_history(frame),meta
        except (TypeError,ValueError,KeyError):return None,{}

    def request(self,ticker,kind):
        if kind not in ('5m','long') or not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}',ticker):
            return 'สัญลักษณ์หรือช่วงกราฟไม่รองรับ'
        now=time.time()
        _,attempt=self.cache.get(f'chart:attempt:{kind}:{ticker}',request_remote=False)
        if now<float(attempt.get('next_due',0)):return attempt.get('error','')
        with self.lock:
            if now<self.cooldown_until:return 'แหล่งข้อมูลกำลังพักหลังจำกัดคำขอ ใช้ข้อมูลเดิมที่มี'
            job=(ticker,kind)
            if job in self.pending:return 'กำลังโหลดประวัติกราฟที่เลือก'
            while self.calls and self.calls[0]<now-3600:self.calls.popleft()
            if len(self.calls)+len(self.pending)>=60:return 'ถึงขีดจำกัด 60 คำขอกราฟต่อชั่วโมงของเซิร์ฟเวอร์ ใช้ข้อมูลที่มีไปก่อน'
            if len(self.pending)>=8:return 'คิวกราฟเต็มชั่วคราว ใช้ข้อมูลที่มีและลองใหม่ภายหลัง'
            self.jobs.append(job);self.pending.add(job)
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._run,name='selected-chart-history',daemon=True)
                self.thread.start()
        return 'กำลังโหลดประวัติกราฟที่เลือก'

    def _fetch(self,ticker,kind):
        kwargs=dict(interval='5m' if kind=='5m' else '1d',auto_adjust=True,actions=False,prepost=False,timeout=20,raise_errors=True)
        if kind=='5m':kwargs['period']='1mo'
        else:kwargs['start']=(pd.Timestamp.now(tz='UTC')-pd.DateOffset(years=11)).date().isoformat()
        with a.core._PROVIDER_LOCK:
            frame=a.yf.Ticker(ticker).history(**kwargs)
        frame=a.normalize_history(frame)
        if kind=='5m' and frame.index.tz is None:raise ValueError('Intraday history has no exchange timezone')
        meta={'fetched_at':datetime.now(timezone.utc).isoformat(),'timezone':str(frame.index.tz or 'UTC'),
              'interval':kwargs['interval'],'requested_years':11 if kind=='long' else None,
              'source':'Yahoo Finance','adjusted':True,'last_bar':str(frame.index[-1])}
        self.cache.put(f'chart:history:{kind}:{ticker}',frame.to_json(orient='split',date_format='iso',double_precision=15),meta)
        # Never store chart-only observations as screening history or quotes.
        with self.cache._lock:
            if not self.cache.error:
                with self.cache.connect() as db:
                    keys=[r[0] for r in db.execute("SELECT key FROM objects WHERE key LIKE 'chart:history:%' ORDER BY json_extract(metadata,'$.fetched_at') DESC")]
                    db.executemany('DELETE FROM objects WHERE key=?',[(k,) for k in keys[128:]])

    def _run(self):
        while True:
            with self.lock:
                if not self.jobs:
                    self.thread=None
                    return
                ticker,kind=self.jobs.popleft()
                self.calls.append(time.time())
            error='';ttl=900 if kind=='5m' else 86400
            try:self._fetch(ticker,kind)
            except Exception as exc:
                limited=any(word in str(exc).lower() for word in ('429','rate limit','too many')) or 'RateLimit' in type(exc).__name__
                ttl=3600 if limited else 300
                error='ผู้ให้ข้อมูลจำกัดคำขอ พัก 1 ชั่วโมงและคงกราฟเดิมไว้' if limited else f'โหลดช่วงกราฟไม่สำเร็จ ({type(exc).__name__}) คงข้อมูลเดิมไว้; ลองใหม่หลัง 5 นาที'
                if limited:
                    with self.lock:
                        self.cooldown_until=time.time()+ttl
                        self.jobs.clear();self.pending.clear()
            finally:
                self.cache.put(f'chart:attempt:{kind}:{ticker}',{}, {'next_due':time.time()+ttl,'error':error})
                with self.lock:self.pending.discard((ticker,kind));self.revision+=1
            time.sleep(2)


@st.cache_resource
def _service(version,cache_path):return ChartHistoryService(a.get_data_cache(version))


def get_chart_service():return _service(a.APP_VERSION,a._cache_path())


def range_payload(frame,ticker,period,interval,fetched_at=''):
    payload=a.build_payload(frame,ticker,period,interval,fetched_at)
    records=payload['records'];start=payload['visibleStart']
    payload['range_first']=records[min(start,len(records)-1)]['time']
    payload['range_last']=records[-1]['time']
    if interval=='5m':
        sessions=pd.DatetimeIndex(frame.index).normalize().unique()
        payload['full_window']=len(sessions)>=int(period.split()[0])
    else:
        count,unit=period.split()
        offset=pd.DateOffset(months=int(count)) if unit=='เดือน' else pd.DateOffset(years=int(count))
        payload['full_window']=frame.index[0]<=frame.index[-1]-offset
    return payload


def render_chart(ticker,daily_history):
    period=st.radio('ช่วงเวลาแสดงกราฟ',PERIODS,index=PERIODS.index('1 ปี'),horizontal=True,key='chart_period',
        help='ช่วงย้อนหลัง ไม่ใช่ขนาดแท่ง: 1/3/5/7 วันใช้ 5 นาทีและนับวันซื้อขายล่าสุดที่มีข้อมูล; เดือน/ปีใช้แท่งรายวัน')
    short=period.endswith('วัน');long=period in ('5 ปี','10 ปี')
    service=get_chart_service()
    history,meta=a.get_data_cache().history(ticker,'5m' if short else '1d')
    kind='5m' if short else 'long';message=''
    if short or long:
        extra,extra_meta=service.read(ticker,kind)
        if extra is not None and (short or not covers_years(history,int(period.split()[0]))):history,meta=extra,extra_meta
        need=short or not covers_years(history,int(period.split()[0]))
        if extra is not None and long:need=True
        if need:
            if chart_requests_enabled():message=service.request(ticker,kind)
            elif history is None:message='เจ้าของระบบปิดการดึงกราฟเพิ่มเติม จึงยังไม่มีข้อมูลช่วงนี้'
    if message:
        (st.warning if any(word in message for word in ('ไม่สำเร็จ','จำกัด','พัก','เต็ม','ปิด')) else st.info)(message)
    if short:
        st.caption('1 วัน / 3 วัน = 1 / 3 วันซื้อขายล่าสุดที่มีข้อมูล ไม่ใช่ 24 / 72 ชั่วโมง · แท่ง 5 นาที เฉพาะเวลาตลาดปกติ · แคชอย่างน้อย 15 นาที ไม่ใช่ราคาสตรีมสด')
    elif long:
        st.caption('5 ปี / 10 ปีใช้แท่งรายวัน ดึงประวัติเฉพาะหุ้นที่เลือกเมื่อจำเป็นและเก็บแคช 24 ชั่วโมง; หุ้นเข้าตลาดใหม่อาจมีไม่ครบช่วง')
    if history is None or history.empty:
        st.info('ยังไม่มีประวัติจริงสำหรับช่วงที่เลือก ไม่ใช้แท่งรายวันแทนแท่งระหว่างวัน และไม่เติมราคาจำลอง')
        return
    try:
        payload=range_payload(history,ticker,period,'5m' if short else '1d',meta.get('fetched_at',''))
        if not payload['full_window']:st.warning('ประวัติที่มีสั้นกว่าช่วงที่เลือก แสดงเฉพาะข้อมูลจริงที่มี ไม่ถือว่าครบช่วง')
        first=history.index[min(payload['visibleStart'],len(history)-1)];last=history.index[-1]
        st.caption(f'ช่วงข้อมูลที่แสดงจริง: {first:%Y-%m-%d} ถึง {last:%Y-%m-%d} · ดึงสำเร็จ {a.thai_time(meta.get("fetched_at"))}')
        if short and (pd.Timestamp.now(tz=last.tz).date()-last.date()).days>4:st.warning('แท่งระหว่างวันล่าสุดเกิน 4 วันปฏิทิน อาจเป็นวันหยุดหรือข้อมูลเก่า ไม่ใช่ราคา ณ ขณะนี้')
        html=a.build_chart_html(payload)
        if hasattr(st,'iframe'):st.iframe(html,height=900)
        else:components.html(html,height=900,scrolling=False)
    except (ValueError,TypeError,KeyError) as exc:st.warning(f'แสดงกราฟไม่ได้ ({type(exc).__name__}) ไม่เปลี่ยนข้อมูลให้คะแนนรายวัน')
