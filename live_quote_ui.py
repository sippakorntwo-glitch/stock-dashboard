"""Minute-price fragment; its updates do not rebuild the catalog or alter scores."""
from __future__ import annotations
import html
import os
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from live_quotes import QuoteService, polling_interval, quote_session

@st.cache_resource
def quote_service(version):
    return QuoteService()

def enabled():
    from chart_ranges import chart_requests_enabled
    return chart_requests_enabled() and os.environ.get('DASHBOARD_ALLOW_MINUTE_QUOTES','true').lower() in ('1','true')

@st.fragment(run_every=5)
def render_live_quote(ticker):
    # Ignore an old fragment invocation while a full-page stock switch is in flight.
    if st.session_state.get('selected_ticker',ticker) != ticker:
        return
    with st.container(key='minute_quote_panel', border=True):
        left, middle, right = st.columns([2,1.4,2])
        left.markdown('#### ราคาล่าสุดจากแท่ง 1 นาที')
        auto = middle.checkbox('อัปเดตราคาอัตโนมัติ',value=True,key='minute_price_auto',disabled=not enabled())
        # Keep every cadence visible: a timed rerun cannot dismiss an open menu
        # between the user's first click and their interval selection.
        interval = right.radio('รอบขอราคา',options=[30,60,120], horizontal=True,
                               format_func=lambda seconds:f'{seconds} วินาที',
                               key='minute_price_interval',disabled=not enabled(),
                               help='ใช้รอบนี้เมื่อช่วงเวลาซื้อขายที่แหล่งข้อมูลระบุยังเปิดอยู่ นอกช่วงนี้ลดความถี่อัตโนมัติ')
        service = quote_service(a.APP_VERSION)
        if auto and enabled():
            service.request(ticker,interval)
        value, attempt, busy = service.read(ticker,interval)
        now = pd.Timestamp.now(tz='UTC')
        session = quote_session(value,now)
        effective = polling_interval(now,value,interval)
        next_due = attempt.get('next_due',0)
        status = ('disabled' if not enabled() else 'paused' if not auto else 'updating' if busy
                  else attempt.get('status','scheduled'))
        messages = {'disabled':'ไม่ได้เปิดการขอราคาในสภาพแวดล้อมนี้',
                    'paused':'พักการอัปเดตราคา', 'updating':'กำลังตรวจราคาจากแหล่งข้อมูล',
                    'rate_limited':'แหล่งข้อมูลจำกัดคำขอ — พักชั่วคราว',
                    'budget':'ถึงเพดานคำขอร่วม — รอรอบที่อนุญาต',
                    'retry':'การตรวจครั้งล่าสุดไม่สำเร็จ — รอรอบลองใหม่',
                    'scheduled':'เปิดการอัปเดตราคาอัตโนมัติ'}
        due_text = (' · ตรวจได้อีกครั้ง '+a.thai_time(pd.Timestamp(next_due,unit='s',tz='UTC').isoformat())
                    if auto and next_due>now.timestamp() else '')
        st.markdown(f'<div class="quote-refresh-status" data-state="{status}" data-requested-seconds="{interval}" '
                    f'data-effective-seconds="{effective}" data-next-due="{next_due}" data-busy="{str(busy).lower()}" '
                    f'data-session="{session}">{html.escape(messages[status]+due_text)}</div>',unsafe_allow_html=True)
        if value:
            stamp = pd.Timestamp(value['bar_time'])
            age = max(0.0,(pd.Timestamp.now(tz='UTC')-stamp).total_seconds())
            recent = age <= 180
            label = 'อายุแท่งไม่เกิน 3 นาที' if recent else 'อายุแท่งเกิน 3 นาที'
            state = 'recent' if recent else 'stale'
            color = '#8ff0d0' if recent else '#ffce80'
            change = value.get('change_pct')
            delta = '—' if change is None else f'{change:+.2f}%'
            text = f'''<div class="minute-quote" data-ticker="{html.escape(ticker)}" data-state="{state}" data-price="{value['price']}" data-bar-time="{html.escape(value['bar_time'])}" data-fetched-at="{html.escape(value['fetched_at'])}">
              <div class="quote-symbol">{html.escape(ticker)} <span>{html.escape(value.get('currency') or 'ไม่ระบุสกุลเงิน')}</span></div>
              <div class="quote-price">{value['price']:,.4f}<span class="quote-delta">{delta}</span></div>
              <div style="color:{color}">{label} · อายุแท่ง {age/60:,.1f} นาที</div></div>'''
            st.markdown(text,unsafe_allow_html=True)
            st.caption('เวลาข้อมูลราคา 1 นาที: '+a.thai_time(value['bar_time'])+' · รับข้อมูล: '+a.thai_time(value['fetched_at']))
            st.caption('Yahoo Finance · รวม pre/post-market เมื่อมีข้อมูล · % เทียบ previous close ที่ผู้ให้ข้อมูลรายงาน')
        else:
            st.info('กำลังขอราคาของหุ้นที่เลือก โดยไม่หยุดการทำงานส่วนอื่น' if busy else 'ยังไม่มีราคา 1 นาทีที่ตรวจสอบได้ — ใช้ข้อมูลรายวันด้านล่างประกอบ')
        if attempt.get('error') and status not in ('paused','disabled'):
            st.warning(attempt['error'])
        session_labels = {'regular':'อยู่ในช่วงซื้อขายปกติที่แหล่งข้อมูลระบุ',
                          'pre':'อยู่ในช่วงก่อนเปิดตลาดที่แหล่งข้อมูลระบุ',
                          'post':'อยู่ในช่วงหลังปิดตลาดที่แหล่งข้อมูลระบุ',
                          'closed':'อยู่นอกช่วงซื้อขายที่แหล่งข้อมูลระบุ',
                          'unknown':'ยังไม่มีเวลาซื้อขายจากแหล่งข้อมูลที่ยืนยันช่วงปัจจุบันได้'}
        st.caption(session_labels[session]+' · รอบตรวจจริงอาจช้าลงเมื่อแหล่งข้อมูลจำกัดคำขอ')
        st.caption('เวลาแท่งบอกอายุราคา แม้เพิ่งตรวจซ้ำก็ไม่ได้ทำให้ราคาใหม่ขึ้น · ราคานี้อาจล่าช้าและไม่ใช่ราคาทุกธุรกรรมแบบเรียลไทม์')
        st.caption('อัปเดตเฉพาะการ์ดราคา ไม่เปลี่ยนหุ้นที่เลือก ตัวกรอง กราฟ หรือผลคำนวณจากแท่งรายวันที่ปิดแล้ว')
