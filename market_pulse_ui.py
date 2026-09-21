"""Thirty-second Top 10 context; live observations never change entry eligibility."""
from __future__ import annotations

from html import escape
import os
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from market_pulse import assess_pulse
from market_pulse_service import PulseService

REFRESH_SECONDS = 30


@st.cache_resource(max_entries=1, show_spinner=False)
def pulse_service(version):
    return PulseService()


def enabled():
    from chart_ranges import chart_requests_enabled
    return (chart_requests_enabled()
            and os.environ.get('DASHBOARD_ALLOW_MARKET_PULSE', 'true').lower() in ('1', 'true'))


def display_number(value, suffix='', *, signed=False):
    value = a.number(value)
    if value is None:
        return '—'
    return (f'{value:+,.2f}' if signed else f'{value:,.2f}') + suffix


def quote_age(quote, now):
    try:
        stamp = pd.Timestamp(quote.get('quote_time'))
        if pd.isna(stamp) or stamp.tzinfo is None:
            return None
        return (now - stamp).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return None


def source_delay(quote):
    delay = a.number(quote.get('delay_minutes'))
    return (' · ต้นทางระบุหน่วง ' + display_number(delay) + ' นาที'
            if delay is not None else ' · ต้นทางไม่ระบุระยะหน่วง')


def render_pulse_header(payload):
    """Render immediately; all provider work is scheduled on one shared worker."""
    active = enabled()
    auto = st.checkbox('อัปเดตการประเมินทุก 30 วินาที', value=True,
                       key='ranking_pulse_auto', disabled=not active,
                       help='ตรวจราคาของกลุ่ม Top 10 และ SPY/QQQ แบบรวมทุก 30 วินาที ข่าวหมุนตรวจทีละหุ้นและเก็บผลประมาณ 5 นาทีต่อหุ้น รอบจริงอาจช้าลงเมื่อผู้ให้ข้อมูลจำกัดคำขอ')
    st.caption('ตลาดทุก 30 วินาที · ข่าวหมุนตรวจประมาณ 5 นาทีต่อหุ้น')
    empty = {'quotes': {}, 'news': {}, 'quote_status': {}, 'news_status': {},
             'status': 'disabled', 'busy': False, 'checked_at': None, 'error': ''}
    if active:
        service = pulse_service(a.APP_VERSION)
        tickers = [row['ticker'] for row in payload.get('items', [])]
        symbols = list(dict.fromkeys([*tickers, 'SPY', 'QQQ']))
        if auto:
            service.request(symbols, news_symbols=tickers)
        state = service.read()
    else:
        state = empty
    status = 'disabled' if not active else 'paused' if not auto else state.get('status', 'scheduled')
    now = pd.Timestamp.now(tz='UTC')
    status_text = {
        'disabled': 'ยังไม่เปิดแหล่งราคาและข่าวในสภาพแวดล้อมนี้',
        'paused': 'พักการตรวจตลาดและข่าว',
        'updating': 'กำลังตรวจตลาดและข่าว',
        'scheduled': 'เปิดรอบตรวจตลาดทุก 30 วินาที',
        'waiting': 'รอตรวจตลาดและข่าวรอบแรก',
        'refreshing': 'กำลังตรวจตลาดและข่าว',
        'ready': 'เปิดรอบตรวจตลาดทุก 30 วินาที',
        'rate_limited': 'ผู้ให้ข้อมูลจำกัดคำขอ — พักตามเวลาที่กำหนด',
        'budget': 'ถึงเพดานคำขอร่วม — รอรอบที่อนุญาต',
        'retry': 'ตรวจรอบล่าสุดไม่สำเร็จ — รอรอบลองใหม่',
        'error': 'ตรวจรอบล่าสุดไม่สำเร็จ — รอรอบลองใหม่',
        'partial': 'ข้อมูลล่าสุดยังมาไม่ครบ — ดูเวลาแต่ละหุ้นประกอบ',
    }.get(status, 'กำลังติดตามข้อมูลตลาด')
    if state.get('busy') and active and auto:
        status_text = 'กำลังตรวจตลาดและข่าว · ใช้งานส่วนอื่นต่อได้'
    receipt = ('<div class="ranking-pulse-status" data-state="' + escape(status, quote=True)
               + '" data-refresh-seconds="30" data-news-seconds="300" data-scope="published-top10"'
               + ' data-rendered-at="' + now.isoformat() + '" data-checked-at="'
               + escape(str(state.get('checked_at') or ''), quote=True) + '">'
               + escape(status_text) + '</div>')
    st.markdown(receipt, unsafe_allow_html=True)
    if state.get('error') and active and auto:
        st.caption(state['error'])
        if state.get('next_due'):
            st.caption('ตรวจได้อีกครั้ง: ' + a.thai_time(pd.Timestamp(state['next_due'], unit='s', tz='UTC').isoformat()))
    markets = []
    for ticker in ('SPY', 'QQQ'):
        quote = state.get('quotes', {}).get(ticker)
        if not quote:
            markets.append(ticker + ' รอข้อมูล')
            continue
        age = quote_age(quote, now)
        freshness = 'เวลาใช้ประเมินไม่ได้' if age is None or not 0 <= age <= 180 else 'อายุราคาไม่เกิน 3 นาที'
        session = {'regular': 'ตลาดปกติ', 'pre': 'ก่อนเปิด', 'post': 'หลังปิด'}.get(quote.get('session'), 'ไม่ทราบช่วงตลาด')
        markets.append(ticker + ' ' + display_number(quote.get('change_pct'), '%', signed=True)
                       + ' · ' + session + ' · ' + freshness + source_delay(quote))
    st.caption('ตลาดอ้างอิง: ' + ' | '.join(markets))
    if state.get('checked_at'):
        st.caption('ตรวจชุดราคาสำเร็จ: ' + a.thai_time(state['checked_at']))
    return state


def render_candidate_pulse(row, payload, state):
    ticker = row['ticker']
    quote = state.get('quotes', {}).get(ticker)
    news = state.get('news', {}).get(ticker)
    assessment = assess_pulse(row, quote, state.get('quotes', {}), news,
                              snapshot_at=payload.get('computed_at'))
    metrics = assessment.get('metrics', {})
    label = assessment['label']
    color = {'strong': '#8fe0c4', 'watch': '#f2cb84', 'unknown': '#b6c6d8'}.get(assessment['state'], '#b6c6d8')
    markup = ('<div class="ranking-pulse-candidate" data-ticker="' + escape(ticker, quote=True)
              + '" data-state="' + escape(assessment['state'], quote=True)
              + '" data-quote-time="' + escape(str((quote or {}).get('quote_time') or ''), quote=True)
              + '" data-news-checked-at="' + escape(str((news or {}).get('checked_at') or ''), quote=True)
              + '" data-entry-independent="true" style="font-size:13px;line-height:1.6;margin:3px 0 8px">'
              + '<strong style="color:' + color + '">' + escape(label) + '</strong></div>')
    st.markdown(markup, unsafe_allow_html=True)
    if quote:
        session = {'regular': 'ตลาดปกติ', 'pre': 'ก่อนเปิดตลาด', 'post': 'หลังปิดตลาด'}.get(quote.get('session'), 'ไม่ระบุช่วงตลาด')
        st.caption(display_number(quote.get('price')) + ' ' + str(quote.get('currency') or 'ไม่ระบุสกุลเงิน')
                   + ' · ' + display_number(quote.get('change_pct'), '%', signed=True) + ' · ' + session)
        st.caption('ราคาต้นทาง: ' + a.thai_time(quote.get('quote_time')) + source_delay(quote))
    else:
        st.caption('ยังไม่มีราคาล่าสุดที่ตรวจสอบได้ของ ' + ticker)
    context = assessment.get('news_context', {})
    if context.get('state') == 'available':
        st.caption('ข่าวที่ต้นทางเชื่อมโยงใน 24 ชั่วโมง: ' + str(context.get('recent_count', 0))
                   + ' รายการ · เปิดอ่านก่อนสรุปผลต่อราคา')
    elif context.get('state') == 'stale':
        st.caption('ข่าวที่มีเป็นข้อมูลเก่า · รอตรวจรอบใหม่')
    with st.expander('แรงส่งและข่าว · ' + ticker, expanded=False):
        st.caption('ประเมินแรงเก็งกำไรแยกจากคะแนน 100 จุดและสถานะผ่านเงื่อนไขซื้อ')
        for criterion in metrics.get('criteria', []):
            mark = '✓ ' if criterion.get('met') else 'รอข้อมูล: ' if not criterion.get('known') else 'ยังไม่ถึงเกณฑ์: '
            st.write(mark + criterion['label'])
            st.caption(criterion.get('detail') or '')
        st.caption('เทียบ SPY: ' + display_number(metrics.get('relative_spy_pp'), ' จุดเปอร์เซ็นต์', signed=True)
                   + ' · ปริมาณเทียบค่าเฉลี่ยเต็มวัน: ' + display_number(metrics.get('volume_ratio'), ' เท่า'))
        st.caption('R:R ตามแผนเดิมที่ราคาล่าสุด: ' + display_number(metrics.get('current_rr'), ' เท่า'))
        for reason in assessment.get('reasons', []):
            st.caption(reason)
        for caution in assessment.get('cautions', []):
            st.caption('ข้อควรตรวจ: ' + caution)
        st.markdown('**ข่าวที่ผู้ให้ข้อมูลเชื่อมโยงกับหุ้น**')
        st.caption(context.get('note') or 'หัวข้อข่าวอาจกล่าวถึงหลายบริษัท ต้องอ่านเนื้อหาต้นทางก่อนสรุปผลต่อหุ้น')
        news_status = state.get('news_status', {}).get(ticker, {})
        if isinstance(news_status, dict) and news_status.get('error'):
            st.caption(news_status['error'])
        articles = context.get('items') or []
        if not articles:
            st.caption('ยังไม่มีข่าวที่อ่านและตรวจวันเผยแพร่ได้ ไม่ได้หมายความว่าไม่มีเหตุการณ์ใหม่')
        for article in articles[:3]:
            # The pure normalizer validates HTTPS destinations. Streamlit escapes
            # button text, so a publisher headline cannot inject HTML or Markdown.
            st.link_button(article['title'], article['url'], width='stretch')
            st.caption(article['publisher'] + ' · เผยแพร่ ' + a.thai_time(article['published_at']))
        if context.get('checked_at'):
            st.caption('ตรวจข่าวสำเร็จ: ' + a.thai_time(context['checked_at']))
        st.caption('Yahoo Finance · รอบตรวจไม่ใช่อายุราคา ข่าวใหม่ขึ้นอยู่กับเวลาที่ต้นทางเผยแพร่')
    return assessment


def render_pulse_method():
    with st.expander('วิธีอ่านแรงส่งและรอบอัปเดต', expanded=False):
        st.write('แรงส่งเด่นใช้เกณฑ์ตัวอย่างร่วมกัน: ราคาเพิ่มอย่างน้อย 2% เทียบราคาปิดก่อนหน้า, ชนะ SPY อย่างน้อย 1 จุดเปอร์เซ็นต์ และปริมาณซื้อขายสะสมอย่างน้อย 1.5 เท่าของค่าเฉลี่ยเต็มวัน โดยต้องมีราคาในช่วงตลาดปกติที่อายุไม่เกิน 3 นาทีและเวลาเทียบตลาดตรงกัน')
        st.write('ปริมาณระหว่างวันเทียบค่าเฉลี่ยเต็มวันเป็นเพียงบริบท ไม่ใช่ RVOL ที่เทียบกับเวลาเดียวกัน ข่าวแสดงเพื่อให้อ่านประกอบ ไม่ถือว่าหัวข้อข่าวเป็นข่าวบวกหรือเป็นหลักฐานว่าราคาจะขึ้น')
        st.write('สแกนทั้งทะเบียนและแผนเดิมทุก 30 นาที; ตรวจตลาดและประเมินกลุ่ม Top 10 ทุก 30 วินาที; ข่าวหมุนตรวจประมาณทุก 5 นาทีต่อหุ้น รอบจริงอาจช้าลงตามคิว ข้อจำกัดแหล่งข้อมูล หรือตลาดปิด')
        st.caption('แรงส่งเด่นไม่ใช่โอกาสกำไรเป็นเปอร์เซ็นต์ และไม่เปลี่ยนหุ้นเฝ้าดูให้ผ่านเงื่อนไขซื้อ ราคาอาจล่าช้าและอาจกลับตัวได้')
