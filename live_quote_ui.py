"""Minute-price fragment; its updates do not rebuild the catalog or alter scores."""
from __future__ import annotations
import html
import os
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from live_quotes import QuoteService

@st.cache_resource
def quote_service(version):
    return QuoteService()

def enabled():
    from chart_ranges import chart_requests_enabled
    return chart_requests_enabled() and os.environ.get('DASHBOARD_ALLOW_MINUTE_QUOTES','true').lower() in ('1','true')

@st.fragment(run_every=15)
def render_live_quote(ticker):
    # Ignore an old fragment invocation while a full-page stock switch is in flight.
    if st.session_state.get('selected_ticker',ticker) != ticker:
        return
    with st.container(key='minute_quote_panel', border=True):
        left, right = st.columns([3,1])
        left.markdown('#### ราคาล่าสุด · Minute Price')
        auto = right.checkbox('Auto-refresh price',value=True,key='minute_price_auto',disabled=not enabled())
        service = quote_service(a.APP_VERSION)
        if auto and enabled():
            service.request(ticker)
        value, attempt, busy = service.read(ticker)
        if value:
            stamp = pd.Timestamp(value['bar_time'])
            age = max(0.0,(pd.Timestamp.now(tz='UTC')-stamp).total_seconds())
            recent = age <= 180
            label = 'แท่งล่าสุดไม่เกิน 3 นาที' if recent else 'ข้อมูลเก่า / นอกเวลาซื้อขาย'
            state = 'recent' if recent else 'stale'
            color = '#8ff0d0' if recent else '#ffce80'
            change = value.get('change_pct')
            delta = '—' if change is None else f'{change:+.2f}%'
            text = f'''<div class="minute-quote" data-ticker="{html.escape(ticker)}" data-state="{state}" data-price="{value['price']}" data-bar-time="{html.escape(value['bar_time'])}">
              <div class="quote-symbol">{html.escape(ticker)} <span>{html.escape(value['currency'])}</span></div>
              <div class="quote-price">{value['price']:,.4f}<span class="quote-delta">{delta}</span></div>
              <div style="color:{color}">{label} · อายุแท่ง {age/60:,.1f} นาที</div></div>'''
            st.markdown(text,unsafe_allow_html=True)
            st.caption('เวลาเริ่มแท่ง 1 นาที: '+a.thai_time(value['bar_time'])+' · รับข้อมูล: '+a.thai_time(value['fetched_at']))
            st.caption('Yahoo Finance · รวม pre/post-market เมื่อมีข้อมูล · % เทียบ previous close ที่ผู้ให้ข้อมูลรายงาน')
        else:
            st.info('กำลังขอราคาของหุ้นที่เลือก โดยไม่หยุดการทำงานส่วนอื่น' if busy else 'ยังไม่มีราคา 1 นาทีที่ตรวจสอบได้ — ใช้ข้อมูลรายวันด้านล่างประกอบ')
        if attempt.get('error'):
            st.warning(attempt['error'])
        st.caption('ขอข้อมูลประมาณทุก 60 วินาทีในช่วง 04:00–20:00 นิวยอร์กวันจันทร์–ศุกร์; นอกช่วงนี้พัก 30 นาที ไม่ใช่การยืนยันว่าตลาดเปิดในวันหยุด · ผู้ให้ข้อมูลอาจล่าช้า ไม่ใช่ tick-by-tick real-time')
        st.caption('ราคาการ์ดนี้แยกจาก Watchlist Price / ผลตอบแทนรายวัน / คะแนนซื้อ จึงไม่เอาแท่งที่ยังไม่ปิดไปแทนค่ารายวัน')
