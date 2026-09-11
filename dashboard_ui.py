"""One-page workspace: click a stock in the table; research appears below it."""
from __future__ import annotations
import re
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from analytics import quality_counts
from dashboard_selection import set_selected
from chart_ranges import get_chart_service
from ranking_board import render_board, consume_selection
from dashboard_views import (VIEWS, table, plot, original_watchlist, overview, filter_universe,
                             industry_summary, technical, fundamentals, risk, compare, health)

LAYOUT = 'single-page'


@st.fragment(run_every=2)
def _poll_data(reader, rendered_revision, rendered_worker_revision, rendered_chart_revision=0):
    """Refresh the page only when a selected data load has actually changed."""
    if reader:
        reader.refresh()
        state = reader.status()
    else:
        state = {'busy': False, 'revision': 0}
    worker = a.get_updater().state()
    chart_state = get_chart_service().state()
    if state['revision'] != rendered_revision or worker['revision'] != rendered_worker_revision or chart_state['revision'] != rendered_chart_revision:
        st.rerun()
    if state['busy'] or worker['busy'] or chart_state['busy']:
        st.caption('กำลังอ่านข้อมูลที่เลือก ข้อมูลเดิมยังใช้งานได้ — แสดงผลให้อัตโนมัติเมื่อโหลดเสร็จ')
    else:
        st.caption('พร้อมใช้งาน · ตรวจชุดข้อมูลใหม่อัตโนมัติทุก 5 นาที')


def _manual_ticker():
    set_selected(st.session_state, a.normalize_symbol(st.session_state['ticker_input']), reset_table=True)


def main():
    st.set_page_config(page_title='Stock Research Workspace',page_icon='📊',layout='wide')
    st.markdown('''<style>.block-container{padding-top:2.5rem;max-width:1700px}
    [data-testid="stMetric"]{border:1px solid #26384b;border-radius:12px;padding:14px;background:#101c2b}
    [data-testid="stMetricValue"]{font-size:1.65rem}
    .st-key-ranking_board [data-testid="stVerticalBlock"]{gap:.25rem}
    .st-key-ranking_board [data-testid="stButton"] button{min-height:1.9rem;padding:.16rem .5rem}
    .st-key-ranking_board [data-testid="stButton"] p{font-size:.82rem}
    .st-key-ranking_board h3{font-size:1.15rem}</style>''',unsafe_allow_html=True)
    reader,error=a.get_remote_reader()
    if reader: reader.refresh()
    revision=reader.status()['revision'] if reader else 0
    worker_revision=a.get_updater().state()['revision']
    chart_revision=get_chart_service().state()['revision']
    cache=a.get_data_cache()
    consume_selection(cache)
    original=original_watchlist()
    frame,outside=a.build_universe_frame(original,cache.quotes(),cache.classifications())
    if 'selected_ticker' not in st.session_state:
        set_selected(st.session_state,'AAPL')
    st.sidebar.title('Stock Research')
    st.sidebar.caption('หน้าเดียว · คลิกหุ้นในตาราง แล้วดูกราฟและรายละเอียดด้านล่าง')
    st.sidebar.text_input('Ticker สำหรับวิเคราะห์',key='ticker_input',on_change=_manual_ticker)
    ticker=st.session_state['selected_ticker']
    valid=bool(re.fullmatch(r'[A-Z0-9.^=/_-]{1,30}',ticker))
    favourites=st.session_state.setdefault('favourites',[])
    if st.sidebar.button('เพิ่ม / ลบรายการโปรด',disabled=not valid):
        if ticker in favourites: favourites.remove(ticker)
        elif len(favourites)<25: favourites.append(ticker)
    if favourites:
        st.sidebar.caption('รายการโปรด: '+', '.join(favourites))
        st.sidebar.download_button('บันทึกรายการโปรด',pd.DataFrame({'Ticker':favourites}).to_csv(index=False).encode('utf-8-sig'),'my_watchlist.csv','text/csv')
    st.sidebar.caption('รายการโปรดเก็บเฉพาะเซสชัน ดาวน์โหลดเพื่อเก็บไว้ถาวร')
    if st.sidebar.button('ตรวจชุดข้อมูลใหม่',disabled=reader is None) and reader: reader.refresh(force=True)
    if a.live_enabled() and valid:
        if st.sidebar.button('ดึงหุ้นนี้จาก Yahoo'):
            for kind in ('history','info','dividends'): a.get_updater().request(ticker,kind,'1d')
    top_left, top_right = st.columns([2.6, 1.15], gap='large')
    with top_left:
        st.title('Stock Research Workspace')
        st.caption('หน้าเดียว: ตารางหุ้น → กราฟและแผนซื้อ → พื้นฐานและปันผล → ความเสี่ยง → เปรียบเทียบ → สถานะข้อมูล')
        st.caption('ข้อมูลเป็นรอบ ไม่ใช่ราคาสตรีมสด · รุ่นโปรแกรม '+a.APP_VERSION)
        counts=quality_counts(frame)
        for box,label,key in zip(st.columns(4),['รายการทั้งหมด','มีราคา','ราคาภายใน 4 วัน','มีราคาแต่ไม่ระบุวัน'],['total','priced','recent','unknown_time']): box.metric(label,f'{counts[key]:,}')
        if error: st.warning(error)
        state=reader.status() if reader else {'manifest':{}}
        if state.get('error'): st.warning(state['error'])
        if not state.get('manifest'): st.info('ยังไม่มีชุดข้อมูลอัตโนมัติ ใช้ CSV/ข้อมูลเดิมก่อน เจ้าของระบบเริ่ม Actions → Update market data (free) → bootstrap')
        else: st.caption('Snapshot เผยแพร่ '+a.thai_time(state['manifest'].get('published_at')))
        with st.container(key='overview_controls'):
            work=filter_universe(frame)
    with top_right:
        render_board(cache)
    with st.container(key='research_overview'):
        if work is not None:
            overview(frame, selectable=True, prepared=work)
    st.divider()
    st.header('วิเคราะห์หุ้นที่เลือก',anchor='selected-stock')
    if not valid:
        st.warning('กรุณากรอก Ticker ให้ถูกต้อง หรือคลิกเลือกหุ้นจากตาราง')
    else:
        if reader: reader.request(ticker)
        history,meta=cache.history(ticker)
        info,_=cache.get('info:'+ticker); info=info or {}
        selected=frame.loc[frame.Ticker.eq(ticker)]
        row=selected.iloc[0].to_dict() if not selected.empty else {}
        st.subheader(f"{ticker} · {info.get('shortName') or row.get('Security_Name') or ''}")
        st.caption(f"วันที่ราคา Watchlist: {row.get('Price_AsOf') or 'ไม่ระบุ'} | ประวัติดึงสำเร็จ {a.thai_time(meta.get('fetched_at'))} | quote ณ {a.thai_time(info.get('regularMarketTime'))}")
        # Render once per selected symbol, not once per row in the catalog.
        with st.container(key='research_technical'):
            st.header('กราฟและแผนซื้อ')
            technical(ticker,history,info,row)
        st.divider()
        with st.container(key='research_fundamentals'):
            st.header('พื้นฐานและปันผล')
            fundamentals(ticker,history,info,row)
        st.divider()
        with st.container(key='research_risk'):
            st.header('ความเสี่ยง')
            risk(ticker,history)
        st.divider()
        with st.container(key='research_comparison'):
            st.header('เปรียบเทียบหลายตัว')
            compare(ticker,frame)
    st.divider()
    if work is not None:
        industry_summary(work)
    if not outside.empty:
        with st.expander(f'CSV นอกชุดหลัก ({len(outside):,} ตัว)'): table(outside)
    with st.container(key='research_health'):
        health(reader,frame,cache)
    _poll_data(reader,revision,worker_revision,chart_revision)
    st.caption('เพื่อการศึกษาวิจัย ไม่ใช่คำแนะนำลงทุนเฉพาะบุคคล คะแนนเป็นกติกาของระบบ ไม่ใช่โอกาสกำไรหรือผลทดสอบย้อนหลัง')
