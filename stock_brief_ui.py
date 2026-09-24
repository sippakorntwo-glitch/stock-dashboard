"""Selected-stock quotes and sourced news beside the existing chart analysis."""
from __future__ import annotations

from html import escape
import math
import os
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from chart_commentary import summarize_chart
from market_pulse_ui import literal_text, display_number
from stock_brief_service import StockBriefService
from stock_news_analysis import analyze_stock_news

TITLE = 'ราคาและข่าวประกอบการวิเคราะห์'


def price_text(value):
    value = a.number(value)
    if value is None:
        return '—'
    digits = 2 if abs(value) >= 1 or value == 0 else min(8, max(4, -int(math.floor(math.log10(abs(value))))+2))
    return f'{value:,.{digits}f}'


@st.cache_resource(max_entries=1, show_spinner=False)
def brief_service(version):
    return StockBriefService()


def enabled():
    from chart_ranges import chart_requests_enabled
    return (chart_requests_enabled()
            and os.environ.get('DASHBOARD_ALLOW_STOCK_BRIEF', 'true').lower() in ('1', 'true'))


def quote_freshness(quote, now=None):
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    try:
        stamp = pd.Timestamp(quote.get('quote_time'))
        if pd.isna(stamp) or stamp.tzinfo is None or now.tzinfo is None:
            return 'unknown', 'ยืนยันเวลาราคาไม่ได้'
        age = (now-stamp).total_seconds()
        if age < 0:
            return 'unknown', 'เวลาราคาอยู่ในอนาคต ต้องตรวจต้นทาง'
        delay = a.number(quote.get('delay_minutes'))
        if age > 180 or (delay is not None and delay > 3):
            return 'stale', 'ราคาอ้างอิงเก่า / ราคาล่าช้า'
        return 'recent', 'อายุราคาไม่เกิน 3 นาที'
    except (TypeError, ValueError, OverflowError):
        return 'unknown', 'ยืนยันเวลาราคาไม่ได้'


def render_quote(quote, kind):
    default = 'ตลาดปกติ' if kind == 'regular' else 'ก่อนเปิด / หลังปิดตลาด'
    label = {'pre':'ก่อนเปิดตลาด (Pre-market)', 'post':'หลังปิดตลาด (After-hours)'}.get(
        (quote or {}).get('session'), default)
    st.markdown('**'+label+'**')
    if not quote:
        st.caption('ยังไม่มีราคาช่วงนี้ที่ตรวจสอบได้')
        return
    state, freshness = quote_freshness(quote)
    currency = quote.get('currency') or 'ไม่ระบุสกุลเงิน'
    change = a.number(quote.get('change_pct'))
    st.metric(label+' · '+literal_text(currency), price_text(quote.get('price')),
              display_number(change, '%', signed=True) if change is not None else None,
              help=('การเปลี่ยนแปลงเทียบราคาปิดตลาดปกติครั้งก่อน'
                    if kind == 'regular' else 'การเปลี่ยนแปลงเทียบราคาปิดตลาดปกติที่อ้างอิงช่วงนอกเวลา'))
    st.caption('เวลาราคาต้นทาง: '+a.thai_time(quote.get('quote_time'))+' · '+freshness)
    if change is None:
        st.caption('ยังไม่มีราคาปิดอ้างอิงที่ใช้คำนวณการเปลี่ยนแปลง')
    delay = a.number(quote.get('delay_minutes'))
    st.caption('ต้นทางระบุหน่วง '+display_number(delay)+' นาที' if delay is not None
               else 'ต้นทางไม่ระบุระยะหน่วง')
    if quote.get('previous_close') is not None:
        st.caption(('ราคาปิดครั้งก่อน: ' if kind == 'regular' else 'ราคาปิดตลาดปกติที่ใช้เทียบ: ')
                   +price_text(quote['previous_close'])+' '+literal_text(currency))
    if quote.get('change_abs') is not None:
        st.caption('เปลี่ยนแปลง '+display_number(quote['change_abs'], signed=True)+' '+literal_text(currency))
    if kind == 'extended' and quote.get('basis_time'):
        st.caption('เวลาราคาตลาดปกติที่ใช้เทียบ: '+a.thai_time(quote['basis_time']))
    st.markdown('<span class="brief-quote" data-kind="'+kind+'" data-state="'+state
                +'" data-ticker="'+escape(str(quote.get('ticker') or ''), quote=True)
                +'" data-quote-time="'+escape(str(quote.get('quote_time') or ''), quote=True)
                +'" data-session="'+escape(str(quote.get('session') or ''), quote=True)+'"></span>',
                unsafe_allow_html=True)


def chart_context(payload):
    """A short bridge to the chart above, without another duplicate indicator table."""
    data = summarize_chart(payload)
    if not data.get('available'):
        return 'ข้อมูลกราฟยังไม่พอสำหรับอ่านประกอบข่าว'
    interval = 'รายวัน' if data['interval'] == '1d' else '5 นาที'
    trend = {'uptrend':'แนวโน้มตาม EMA เอนขึ้น', 'downtrend':'แนวโน้มตาม EMA เอนลง',
             'mixed':'EMA ยังให้สัญญาณผสม', 'insufficient':'ข้อมูล EMA ยังไม่ครบ'}[data['trend']]
    parts = [f'กราฟ {interval} ช่วง {data["period"]}: {trend}']
    rsi = data['metrics'].get('rsi')
    if rsi is not None:
        parts.append('RSI14 '+display_number(rsi)+(' อยู่โซนสูง ควรตรวจการพักตัว' if rsi>70
                     else ' อยู่โซนต่ำ ยังต้องรอการยืนยันการฟื้น' if rsi<30 else ''))
    levels = data.get('levels', {})
    if levels.get('support') is not None:
        parts.append('ติดตามการปิดแท่งเทียบกรอบ '+display_number(levels['support'])
                     +'–'+display_number(levels['resistance'])+' ที่แสดงเป็นเส้นบนกราฟ')
    if data.get('bar_state') != 'closed':
        parts.append('แท่งล่าสุดยังไม่ยืนยันปิด')
    return ' · '.join(parts)


def render_article(article, index):
    with st.container(border=True):
        st.link_button(str(index)+'. '+literal_text(article['title']), article['url'], width='stretch')
        st.caption(literal_text(article['publisher'])+' · เผยแพร่ '+a.thai_time(article['published_at']))
        article_type = 'บทความความเห็น / บทวิเคราะห์' if article.get('article_type') == 'opinion' else 'รายการข่าวจากต้นทาง'
        st.caption(article_type+' · '+str(article.get('category_label') or 'ยังไม่จำแนกประเด็น'))
        if article.get('topic'):
            st.write(literal_text(article['topic']))
        excerpt = article.get('source_excerpt')
        if excerpt:
            st.caption('ข้อความย่อจากต้นทาง (คงภาษาต้นฉบับ):')
            st.write(literal_text(excerpt))
        else:
            st.caption('ต้นทางไม่ได้ส่งเนื้อหาย่อ จึงแสดงเฉพาะหัวข้อและประเด็นที่ตรวจพบ')
        for factor in article.get('impact_factors', []):
            st.write('• '+literal_text(factor))
        st.caption('ผลต่อราคา: ยังไม่ยืนยันจากข้อมูลข่าวที่มี · อ่านบทความต้นทางประกอบ')


def render_stock_brief(payload, *, info=None, is_etf=False):
    ticker = payload.get('ticker', '')
    if st.session_state.get('selected_ticker', ticker) != ticker:
        return
    active = enabled()
    state = {'ticker':ticker, 'regular':None, 'extended':None, 'news':None,
             'status':'disabled', 'busy':False, 'error':''}
    if active:
        service = brief_service(a.APP_VERSION)
        service.request(ticker)
        state = service.read(ticker)
    status = state.get('status', 'waiting')
    report = analyze_stock_news(state.get('news'), ticker, is_etf=is_etf)
    with st.container(border=True, key='stock_brief_panel'):
        st.subheader(TITLE+' · '+ticker)
        st.markdown('<div class="stock-brief-receipt" data-ticker="'+escape(ticker, quote=True)
                    +'" data-state="'+escape(status, quote=True)+'" data-quote-seconds="60"'
                    +' data-news-seconds="300" data-chart-period="'+escape(str(payload.get('period', '')), quote=True)
                    +'" data-news-checked-at="'+escape(str(report.get('checked_at') or ''), quote=True)
                    +'" data-rendered-at="'+pd.Timestamp.now(tz='UTC').isoformat()+'"></div>',
                    unsafe_allow_html=True)
        st.caption('ตรวจราคาประมาณทุก 1 นาที · ข่าวประมาณทุก 5 นาที · ใช้เวลาที่ต้นทางรายงานของแต่ละรายการ')
        if state.get('busy'):
            st.caption('กำลังตรวจราคาและข่าวของ '+ticker+' · ใช้งานส่วนอื่นต่อได้')
        elif not active:
            st.caption('ยังไม่เปิดแหล่งราคาและข่าวในสภาพแวดล้อมนี้')
        elif status in ('waiting', 'queued', 'budget'):
            st.caption('รอรอบตรวจข้อมูล')
        if state.get('error'):
            st.caption(state['error'])
        columns = st.columns(2)
        for column, kind in zip(columns, ('regular', 'extended')):
            with column:
                render_quote(state.get(kind), kind)
        if state.get('quote_checked_at'):
            st.caption('ตรวจชุดราคาสำเร็จ: '+a.thai_time(state['quote_checked_at']))
        st.caption('ราคา quote เป็นราคาต้นทาง ส่วนเส้นแนวรับ–แนวต้านใช้ชุดราคาบนกราฟซึ่งอาจปรับสิทธิ์ย้อนหลัง ฐานราคาและเวลาจึงอาจต่างกัน')
        st.markdown('**อ่านข่าวคู่กับกราฟ**')
        st.write(chart_context(payload))
        st.caption('ใช้ EMA20/EMA50, SMA200 และ RSI ของกราฟด้านบน โดยนับตามขนาดแท่งที่เลือก')
        if is_etf:
            st.caption('หลักทรัพย์นี้เป็นกองทุน: พิจารณาการถือครอง นโยบายกระจายเงิน และค่าใช้จ่ายกองทุนประกอบข่าว')
        st.markdown('**ข่าวและประเด็นที่ควรตรวจ**')
        recent, week = report.get('recent_items', []), report.get('week_items', [])
        articles = [*recent, *week]
        st.caption(f'จากรายการที่ต้นทางส่งมา: ภายใน 24 ชั่วโมง {len(recent)} รายการ · เก่ากว่า 24 ชั่วโมงถึง 7 วัน {len(week)} รายการ')
        if report.get('state') == 'stale':
            st.caption('ผลการตรวจข่าวเก่าแล้ว แสดงวันเผยแพร่เดิมและรอตรวจรอบใหม่')
        if not articles:
            st.info('ยังไม่มีข่าวในช่วง 7 วันที่ตรวจวันเผยแพร่และแหล่งที่มาได้สำหรับหุ้นนี้')
        for index, article in enumerate(articles[:3], 1):
            render_article(article, index)
        if len(articles)>3:
            with st.expander('ข่าวเพิ่มเติม · '+str(len(articles)-3)+' รายการ'):
                for index, article in enumerate(articles[3:], 4):
                    render_article(article, index)
        if report.get('checked_at'):
            st.caption('ตรวจข่าวสำเร็จ: '+a.thai_time(report['checked_at']))
        with st.expander('แหล่งข้อมูลและวิธีอ่านบทวิเคราะห์'):
            st.write('Yahoo Finance ส่งรายการที่เชื่อมโยงกับสัญลักษณ์หุ้น ซึ่งอาจมีข่าวตลาดกว้างหรือบทความความเห็นรวมอยู่ด้วย ประเด็นและปัจจัยผลกระทบเป็นคำอธิบายตามกติกา ต้องตรวจข้อเท็จจริงในบทความก่อนนำไปใช้')
            st.write('แสดงเนื้อหาย่อเฉพาะเมื่อผู้ให้ข้อมูลส่งมา พร้อมลิงก์และวันเผยแพร่ การตรวจซ้ำไม่เปลี่ยนวันข่าวและไม่ทำให้ราคาเก่ากลายเป็นราคาสด')
            st.caption('รอบจริงอาจช้าลงตามคิวหรือข้อจำกัดต้นทาง บทวิเคราะห์นี้ไม่เพิ่มคะแนนหรือยืนยันจุดซื้อจากหัวข้อข่าวเพียงอย่างเดียว')
    return state, report
