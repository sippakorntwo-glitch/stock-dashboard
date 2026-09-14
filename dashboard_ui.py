"""One-page workspace: click a stock in the table; research appears below it."""
from __future__ import annotations
import re
import time
import pandas as pd
import streamlit as st
import dashboard_runtime as a
from analytics import quality_counts
from dashboard_selection import set_selected, manual_ticker_key
from chart_ranges import get_chart_service
from ranking_board import render_board, consume_selection
from read_view import consistent_read, page_dependencies
from dashboard_views import (VIEWS, table, plot, original_watchlist, overview, filter_universe,
                             industry_summary, technical, fundamentals, risk, compare)


LAYOUT = 'single-page'


def _page_dependencies(ticker):
    is_etf = ticker in a.ETF_NAMES or st.session_state.get('_research_asset_kind') == (ticker, 'ETF')
    research = [] if is_etf else list(st.session_state.get('peer_selection_'+ticker, []))
    if is_etf:
        research.extend(st.session_state.get('etf_compare_symbols', [])[:3])
        benchmark = st.session_state.get('etf_benchmark_symbol')
        if benchmark:
            research.append(benchmark)
    return page_dependencies(ticker, st.session_state.get('comparison_symbols'), research)


@st.fragment(run_every=2)
def _poll_data(reader, rendered_revision, rendered_worker_revision, rendered_chart_revision=0, rendered_ticker=None, rendered_dependencies=None):
    """Refresh only for data used by this page, including pending comparisons."""
    ticker=st.session_state.get('selected_ticker')
    dependencies=_page_dependencies(ticker)
    if rendered_ticker is not None and ticker != rendered_ticker:
        return
    if rendered_dependencies is not None and dependencies != rendered_dependencies:
        return
    if reader:
        reader.select_page(dependencies)
        reader.refresh()
        state = reader.page_status(dependencies)
    else:
        state = {'busy': False, 'revision': 0}
    worker = a.get_updater().state()
    chart_state = get_chart_service().state()
    from chart_ranges import first_chart_load_finished
    from ui_stability import claim_refresh
    first_chart = first_chart_load_finished(st.session_state,chart_state['revision'],rendered_chart_revision)
    observed = (a.APP_VERSION,ticker,state.get('page_revision',state.get('view_revision',state['revision'])),worker['revision'],chart_state['revision'] if first_chart else None)
    rendered = (a.APP_VERSION,rendered_ticker or ticker,rendered_revision,rendered_worker_revision,rendered_chart_revision if first_chart else None)
    if claim_refresh(st.session_state,observed,rendered):
        if first_chart:st.session_state.pop('_chart_first_load_waiting',None)
        st.rerun()
    if state.get('error'):
        st.warning(state['error'])
    elif state['busy'] or worker['busy'] or chart_state['busy']:
        st.caption('กำลังอ่านข้อมูลที่เลือก ข้อมูลเดิมยังใช้งานได้ — แสดงผลให้อัตโนมัติเมื่อโหลดเสร็จ')
    else:
        st.caption('พร้อมใช้งาน · ตรวจชุดข้อมูลใหม่อัตโนมัติทุก 1 นาที')


def _manual_ticker(widget_key, selection_revision):
    # Queued browser state can belong to the input shown before a table/board
    # selection. Its callback runs before any fragment guard, so reject it here.
    if (selection_revision != st.session_state.get('_selection_revision', 0)
            or widget_key != manual_ticker_key(st.session_state)):
        return
    set_selected(st.session_state, a.normalize_symbol(st.session_state[widget_key]), reset_table=True)


def main():
    render_started = time.monotonic()
    st.set_page_config(page_title='Stock Research Workspace',page_icon='📊',layout='wide')
    from workspace_theme import apply_theme
    apply_theme()
    from research_workspace_ui import startup_before_widgets, render_sidebar
    startup_before_widgets()
    # Reserve timer/receipt positions before dynamic content or cache spinners.
    body=st.container(key='workspace_body')
    footer=st.container(key='workspace_footer')
    reader,error=a.get_remote_reader()
    base_cache=a.get_data_cache()
    consume_selection(base_cache)
    if 'selected_ticker' not in st.session_state:
        set_selected(st.session_state,'AAPL')
    ticker=st.session_state['selected_ticker']
    dependencies=_page_dependencies(ticker)
    if reader:
        reader.select_page(dependencies)
        reader.refresh()
    with consistent_read(base_cache,ticker,dependencies) as cache, body:
        state=cache.reader_state
        manifest,_=cache.get('remote:manifest',request_remote=False)
        manifest=manifest or {}
        rendered_generation=manifest.get('generation','')
        detail_marker,_=cache.get('remote:detail:'+ticker,request_remote=False)
        detail_marker=detail_marker or {}
        prepared_ready=not reader or not manifest or detail_marker.get('generation')==rendered_generation
        worker_revision=a.get_updater().state()['revision']
        chart_revision=get_chart_service().state()['revision']
        original=original_watchlist()
        frame,outside=a.build_universe_frame(original,cache.quotes(),cache.classifications())
        from screening import enrich_frame
        profiles,_=cache.get('remote:screener',request_remote=False)
        frame=enrich_frame(frame,profiles or {})
        st.sidebar.title('Stock Research')
        st.sidebar.caption('หน้าเดียว · คลิกหุ้นในตาราง แล้วดูกราฟและรายละเอียดด้านล่าง')
        input_key=manual_ticker_key(st.session_state)
        if input_key not in st.session_state:
            st.session_state[input_key]=ticker
        st.sidebar.text_input('Ticker สำหรับวิเคราะห์',key=input_key,on_change=_manual_ticker,
                              args=(input_key,st.session_state.get('_selection_revision',0)))
        ticker=st.session_state['selected_ticker']
        valid=bool(re.fullmatch(r'[A-Z0-9.^=/_-]{1,30}',ticker))
        favourites=st.session_state.setdefault('favourites',[])
        if st.sidebar.button('เพิ่ม / ลบรายการโปรด',disabled=not valid):
            if ticker in favourites: favourites.remove(ticker)
            elif len(favourites)<25: favourites.append(ticker)
        if favourites:
            st.sidebar.caption('รายการโปรด: '+', '.join(favourites))
            st.sidebar.download_button('บันทึกรายการโปรด',pd.DataFrame({'Ticker':favourites}).to_csv(index=False).encode('utf-8-sig'),'my_watchlist.csv','text/csv')
        st.sidebar.caption('บันทึกชุดวิเคราะห์เพื่อเก็บรายการโปรดไว้ใช้ครั้งหน้า หรือดาวน์โหลด CSV')
        if st.sidebar.button('ตรวจชุดข้อมูลใหม่',disabled=reader is None) and reader: reader.refresh(force=True)
        if a.live_enabled() and valid:
            if st.sidebar.button('ดึงหุ้นนี้จาก Yahoo'):
                for kind in ('history','info','dividends'): a.get_updater().request(ticker,kind,'1d')
        top_left, top_right = st.columns([2.6, 1.15], gap='large')
        with top_left:
            st.title('Stock Research Workspace')
            from workspace_theme import navigation
            navigation()
            st.caption('ข้อมูลเป็นรอบ ไม่ใช่ราคาสตรีมสด · รุ่นโปรแกรม '+a.APP_VERSION)
            counts=quality_counts(frame)
            for box,label,key in zip(st.columns(4),['รายการทั้งหมด','มีราคา','ราคาภายใน 4 วัน','มีราคาแต่ไม่ระบุวัน'],['total','priced','recent','unknown_time']): box.metric(label,f'{counts[key]:,}')
            if error: st.warning(error)
            if cache.error: st.warning('อ่านข้อมูลที่บันทึกไว้ไม่สำเร็จ')
            # Reader failures/recovery are displayed by the live status fragment,
            # so a recovered check never leaves a stale warning on this page.
            if not manifest: st.info('ยังไม่มีชุดข้อมูลอัตโนมัติ ใช้ข้อมูลที่มีอยู่ก่อนได้ แล้วกด “ตรวจชุดข้อมูลใหม่” อีกครั้งภายหลัง')
            else: st.caption('Snapshot เผยแพร่ '+a.thai_time(manifest.get('published_at')))
            etfs=int(frame.Asset_Type.eq('ETF').sum())
            st.caption(f'ทะเบียน {len(frame)-etfs:,} หุ้น + {etfs:,} ETF / ETP · รายชื่อกองทุน ณ {a.thai_time(a.ETF_DIRECTORY_AS_OF)} · ธง ETF ของ Nasdaq อาจรวม ETN ควรตรวจชื่อผลิตภัณฑ์ · จำนวนรายชื่อไม่ใช่ความครบของข้อมูล')
            if a.ETF_DIRECTORY_CONFLICTS:
                st.caption(f'{len(a.ETF_DIRECTORY_CONFLICTS)} symbol-type conflicts retained for review; no automatic stock reclassification.')
            with st.container(key='overview_controls'):
                work=filter_universe(frame)
        with top_right:
            # The board has its own timed fragment and timestamped publication;
            # do not retain a page's temporary read transaction in that callback.
            render_board(base_cache)
        with st.container(key='research_overview'):
            if work is not None:
                overview(frame, selectable=True, prepared=work)
            else:
                st.session_state.pop('_active_table_key',None)
        st.divider()
        st.header('วิเคราะห์หุ้นที่เลือก',anchor='selected-stock')
        if not valid:
            st.warning('กรุณากรอก Ticker ให้ถูกต้อง หรือคลิกเลือกหุ้นจากตาราง')
        elif not prepared_ready:
            st.info('กำลังอ่านข้อมูลของหุ้นที่เลือกให้ตรงกับชุดข้อมูลนี้ จะแสดงให้อัตโนมัติเมื่อพร้อม')
        else:
            if reader: reader.request(ticker)
            history,meta=cache.history(ticker)
            info,profile_meta=cache.get('info:'+ticker); info=dict(info or {})
            dividend_history,_=cache.get('dividends:'+ticker)
            info['_ProfileFetchedAt']=profile_meta.get('fetched_at') or info.get('_Fetched_At_UTC')
            info['_DividendHistory']=dividend_history
            statements,_=cache.get('financials:'+ticker)
            if statements:
                info['_FinancialStatements']=statements
            selected=frame.loc[frame.Ticker.eq(ticker)]
            row=selected.iloc[0].to_dict() if not selected.empty else {}
            st.subheader(f"{ticker} · {info.get('shortName') or row.get('Security_Name') or ''}")
            from workspace_theme import selected_context
            selected_context(ticker, row.get('Price_AsOf'), (statements or {}).get('fetched_at'))
            st.caption(f"วันที่ราคา Watchlist: {row.get('Price_AsOf') or 'ไม่ระบุ'} | ประวัติดึงสำเร็จ {a.thai_time(meta.get('fetched_at'))} | quote ณ {a.thai_time(info.get('regularMarketTime'))}")
            if detail_marker.get('retained_newer_local'):
                st.caption('บางรายการมีข้อมูลที่ตรวจได้ใหม่กว่าชุดเผยแพร่ จึงใช้ข้อมูลใหม่นั้นพร้อมเวลาแหล่งข้อมูลเดิม')
            from live_quote_ui import render_live_quote
            render_live_quote(ticker)
            mode = st.radio('มุมมองการวิเคราะห์', ['ภาพรวม','ลงทุนระยะยาว','จังหวะซื้อขาย'],
                            horizontal=True, key='research_mode',
                            help='ปรับลำดับและการเปิดรายละเอียด ทุกหัวข้อยังอยู่ในหน้าเดียว')
            is_etf = a.asset_is_etf(ticker,row,info)
            st.session_state['_research_asset_kind'] = (ticker, 'ETF' if is_etf else 'company')
            from research_summary import render_research_summary
            from research_updates import render_research_updates
            from research_workspace_ui import render_stock_notes
            render_research_summary(ticker,info,row,statements,is_etf=is_etf)
            render_research_updates(ticker,info,row,statements,cache)
            render_stock_notes(ticker, metrics=row)
            # Stable section identities keep chart state through mode/quote changes.
            sections = (['fundamentals','comparison','risk','technical'] if mode=='ลงทุนระยะยาว'
                        else ['technical','risk','fundamentals','comparison'] if mode=='จังหวะซื้อขาย'
                        else ['technical','fundamentals','comparison','risk'])
            for section in sections:
                with st.container(key='research_'+section):
                    if section=='technical':
                        st.header('กราฟและแผนซื้อ',anchor='technicals')
                        with st.expander('เปิดกราฟและแผนซื้อขาย', expanded=mode!='ลงทุนระยะยาว'):
                            technical(ticker,history,info,row)
                    elif section=='fundamentals':
                        st.header('พื้นฐานและปันผล',anchor='fundamentals')
                        with st.expander('เปิดรายละเอียดพื้นฐานและปันผล', expanded=mode=='ลงทุนระยะยาว'):
                            fundamentals(ticker,history,info,row,frame=frame)
                        if not is_etf:
                            st.subheader('จำลองราคาและสมมติฐาน',anchor='valuation')
                            with st.expander('เปิดสถานการณ์ราคา', expanded=False):
                                from valuation_ui import render_valuation
                                render_valuation(ticker,info,row,bundle=statements)
                    elif section=='risk':
                        st.header('ความเสี่ยง',anchor='risk')
                        with st.expander('เปิดรายละเอียดความเสี่ยง', expanded=mode=='จังหวะซื้อขาย'):
                            risk(ticker,history)
                    else:
                        st.header('เปรียบเทียบหลายตัว',anchor='comparison')
                        if not is_etf:
                            with st.expander('เปิดตารางคู่แข่ง', expanded=mode=='ลงทุนระยะยาว'):
                                from peer_analysis_ui import render_peer_analysis
                                render_peer_analysis(ticker,frame,cache,info=info)
                        with st.expander('เปิดผลตอบแทนและความสัมพันธ์', expanded=False):
                            compare(ticker,frame)
        st.divider()
        if work is not None:
            industry_summary(work)
        if not outside.empty:
            with st.expander(f'CSV นอกชุดหลัก ({len(outside):,} ตัว)'): table(outside)
        # compare() can prune a symbol removed from the catalog. Keep exactly
        # the displayed dependencies, using counters from this same WAL view.
        dependencies=_page_dependencies(ticker)
        revision=cache.page_revision(dependencies)
        with st.sidebar:
            render_sidebar()
    with footer:
        _poll_data(reader,revision,worker_revision,chart_revision,ticker,dependencies)
        st.caption('เพื่อการศึกษาวิจัย ไม่ใช่คำแนะนำลงทุนเฉพาะบุคคล คะแนนเป็นกติกาของระบบ ไม่ใช่โอกาสกำไรหรือผลทดสอบย้อนหลัง')
        from ui_stability import page_receipt
        st.markdown(page_receipt(a.APP_VERSION,ticker,st.session_state.get('stock_search',''),
                                time.monotonic()-render_started,
                                generation=rendered_generation),unsafe_allow_html=True)
