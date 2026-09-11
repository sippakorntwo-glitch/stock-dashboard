"""Reusable research sections for the single-page workspace."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import dashboard_runtime as a
from analytics import clean_close, risk_metrics, comparison, beta_to_benchmark, quality_counts
from dashboard_selection import table_key, apply_table_selection
from dashboard_help import help_table, column_help
from chart_ranges import PAGE_SIZE, page_slice, render_chart
from return_periods import (RETURN_FIELDS, RETURN_LABELS, RETURN_CAPTION, TABLE_FIELDS,
                            return_column_config, export_watchlist)
VIEWS = ['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว','สถานะข้อมูล']


def table(frame, **kwargs):
    return help_table(frame, **kwargs)


def plot(fig, key, height=420):
    fig.update_layout(template='plotly_dark', height=height, margin=dict(l=15,r=15,t=30,b=20),
                      hovermode='x unified', legend=dict(orientation='h',y=1.1))
    st.plotly_chart(fig, key=key, **a.width_options(st.plotly_chart), config={'displaylogo':False})


def original_watchlist():
    original = pd.DataFrame(columns=['Ticker','Asset_Type','Status'])
    with st.sidebar.expander('อัปโหลด Watchlist / CSV'):
        upload = st.file_uploader('CSV ที่มี Ticker หรือ Symbol', type=['csv'])
        st.caption('ไฟล์อัปโหลดใช้เฉพาะเซสชันนี้ ไม่เผยแพร่กลับ GitHub')
    try:
        if upload is not None:
            return a.parse_watchlist(upload.getvalue())
        if a.WATCHLIST_FILE.exists():
            stat = a.WATCHLIST_FILE.stat()
            return a.read_watchlist(str(a.WATCHLIST_FILE),stat.st_mtime_ns,stat.st_size)
        saved,_ = a.get_data_cache().get('remote:watchlist', request_remote=False)
        return a.parse_watchlist(saved.encode()) if saved else original
    except Exception as exc:
        st.warning(f'อ่าน CSV ไม่สำเร็จ ({type(exc).__name__}) — ใช้ทะเบียนรายชื่อและข้อมูลที่บันทึกไว้')
        return original


def filter_universe(frame):
    from filters_ui import filter_universe as advanced_filter
    return advanced_filter(frame)



def overview(frame, selectable=False, prepared=None):
    work = filter_universe(frame) if prepared is None else prepared
    if work is None:
        return None
    pages = max(1,math.ceil(len(work)/PAGE_SIZE))
    if st.session_state.get('table_page',1)>pages: st.session_state.table_page=1
    page = st.number_input('หน้าตาราง — หน้าละ 500 ตัว',min_value=1,max_value=pages,step=1,key='table_page')
    fields = list(TABLE_FIELDS)
    shown = page_slice(work,page).reindex(columns=fields)
    from quality_views import industry_display, snapshot_quality, placeholder_options
    shown = industry_display(shown, snapshot_quality(a.get_data_cache()))
    styled = shown.style.format(precision=2,na_rep='—').map(a.return_cell_style,subset=list(RETURN_FIELDS))
    config = a.watchlist_column_config()
    for field,label in {'ATR_Pct':'ATR / ราคา (%)','Volatility_20D':'Volatility 20D ต่อปี (%)'}.items():
        config[field]=st.column_config.NumberColumn(label,format='%.2f')
    config['Dollar_Volume_20D']=st.column_config.NumberColumn('ราคา × Volume เฉลี่ย 20D',format='%.0f',help='ค่าประมาณจากราคาปรับแล้ว ไม่ใช่มูลค่าซื้อขายจริงจากตลาด')
    from return_periods import EXPORT_LABELS
    mode = work.attrs.get('return_mode', 'Cumulative (Adjusted Close)')
    for field,label in EXPORT_LABELS.items():
        if field in config and isinstance(config[field],dict):
            config[field] = {**config[field], 'label':label}
        elif field in fields:
            config[field] = st.column_config.Column(label)
    config.update(return_column_config(mode))
    config = column_help(fields,config)
    st.caption(f'แสดง {len(shown):,} ตัวในหน้านี้ · หน้า {page:,} / {pages:,}')
    options = {}
    if selectable:
        tickers = tuple(shown.Ticker.astype(str))
        key = table_key(tickers, st.session_state.get('_table_epoch',0))
        # Capture the visible order BEFORE any filter, sort, page or data rerun.
        def on_select():
            apply_table_selection(st.session_state,key,tickers)
        options = dict(key=key,on_select=on_select,selection_mode=['single-row','single-cell'])
        st.caption('คลิกชื่อหุ้นหรือช่องใดก็ได้ในแถว เพื่อแสดงกราฟและข้อมูลทั้งหมดด้านล่าง')
        if len(tickers)==1: st.caption('หุ้นในผลค้นหา: '+tickers[0])
    with st.container(key='stock_picker_table'):
        st.dataframe(styled,hide_index=True,height=520,row_height=36,column_config=config,**options,**placeholder_options(),**a.width_options(st.dataframe))
    st.caption(f'ผ่านตัวกรอง {len(work):,} ตัว · ช่อง — คือไม่มีข้อมูล ไม่ใช่ศูนย์ · PASS เป็นสถานะแนวโน้ม ไม่ใช่คำสั่งซื้อ')
    if selectable:
        st.caption('หุ้นที่เลือก: '+st.session_state.get('selected_ticker','AAPL'))
        st.markdown('[↓ ไปยังกราฟและรายละเอียดด้านล่าง](#selected-stock)')
    st.caption(RETURN_CAPTION)
    st.download_button('ดาวน์โหลดผลกรองครบทุกแถว',export_watchlist(work).to_csv(index=False).encode('utf-8-sig'),'filtered_watchlist.csv','text/csv',on_click='ignore')
    return work


def industry_summary(work):
    st.subheader('ความแข็งแกร่งแยกอุตสาหกรรม / หมวด ETF')
    grouped=work.groupby(['Asset_Type','Industry'],dropna=True).agg(observations=('Return_3M','count'),median_return_3m=('Return_3M','median')).reset_index()
    grouped=grouped.loc[grouped.observations.ge(3)].sort_values('median_return_3m',ascending=False).head(20)
    if grouped.empty: st.info('ยังมีอุตสาหกรรมและผลตอบแทน 3 เดือนไม่พอสำหรับสรุปกลุ่ม')
    else: table(grouped,height=300)
    st.caption('มัธยฐานเฉพาะรายการที่ผ่านตัวกรองและมีข้อมูลอย่างน้อย 3 ตัวต่อกลุ่ม ไม่ใช่ผลตอบแทนดัชนีหรือภาพรวมตลาดทั้งหมด')


def technical(ticker,daily_history,info,row):
    from return_audit_ui import render_return_audit
    render_return_audit(ticker,daily_history,row)
    render_chart(ticker,daily_history)
    # Daily criteria must NEVER be calculated from the selected intraday chart.
    is_etf=a.asset_is_etf(ticker,row,info)
    benchmark,_=a.get_data_cache().history('SPY') if is_etf else (None,{})
    ctx=a.decision_context(daily_history,info,benchmark)
    scored=a.criteria_score(ctx,info,is_etf)
    rr=st.number_input('Reward/Risk ขั้นต่ำ',min_value=2.0,max_value=10.0,value=2.0,step=.5)
    plan=a.build_entry_plan(ctx,info,scored,is_etf,rr)
    currency=str(info.get('currency') or 'สกุลสินทรัพย์')
    div=a.load_dividend_history(ticker)
    a.render_decision(ticker,ctx,info,scored,plan,is_etf,div,currency)
    analysis,metrics,_=a.build_analysis(ctx.get('metrics',{}),row,info)
    with st.expander('ตารางวิเคราะห์ 360° และแหล่งข้อมูล',expanded=True):
        table(analysis,height=450)
    a.render_position_sizer(ticker,row,metrics,currency)
    st.caption('ราคาชุดรายวันอาจไม่ผ่านเกณฑ์ quote อายุไม่เกิน 15 นาที ระบบจึงคงสถานะรอยืนยัน ไม่ลดเกณฑ์เพื่อให้เกิดสัญญาณซื้อ')


def fundamentals(ticker,history,info,row):
    st.subheader('ธุรกิจ • มูลค่า • กำไร • กระแสเงินสด')
    st.caption('ข้อมูลพื้นฐานดึงสำเร็จ '+a.thai_time(info.get('_Fetched_At_UTC'))+' — ไม่ใช่วันที่ของงบการเงินทุกช่อง')
    etf=a.asset_is_etf(ticker,row,info)
    fields=[('อุตสาหกรรม','industry',False),('Sector','sector',False),('ประเทศ','country',False),('Market cap','marketCap',False),
            ('Forward P/E','forwardPE',False),('Trailing P/E','trailingPE',False),('Price / Book','priceToBook',False),('EV / EBITDA','enterpriseToEbitda',False),
            ('Revenue growth','revenueGrowth',True),('Earnings growth','earningsGrowth',True),('Profit margin','profitMargins',True),('Operating margin','operatingMargins',True),
            ('Return on equity','returnOnEquity',True),('Return on assets','returnOnAssets',True),('Operating cash flow','operatingCashflow',False),('Free cash flow','freeCashflow',False),
            ('เงินสดรวม','totalCash',False),('หนี้รวม','totalDebt',False),('เป้าหมายเฉลี่ยนักวิเคราะห์','targetMeanPrice',False),('จำนวนนักวิเคราะห์','numberOfAnalystOpinions',False)]
    if etf: fields=[('หมวดกองทุน','category',False),('กลุ่มกองทุน','fundFamily',False),('สินทรัพย์กองทุน','totalAssets',False),('NAV ต่อหน่วย','navPrice',False),('Beta 3Y จากแหล่งข้อมูล','beta3Year',False)]
    from quality_views import profile_value, profile_field_state, profile_unit
    records=[]
    for label,key,pct in fields:
        raw=info.get(key); n=a.number(raw)
        value=a.show_number(n*100,'%') if pct and n is not None else a.show_number(n) if n is not None else profile_value(raw,info)
        records.append({'มิติ':label,'ค่า':value,'หน่วย': '%' if pct else profile_unit(info,key),'สถานะข้อมูล':profile_field_state(info,key),'ฟิลด์ต้นทาง':key})
    table(pd.DataFrame(records),height=480)
    st.caption('อัตราการเติบโตและอัตรากำไรเป็นค่าที่แหล่งข้อมูลรายงาน ช่วงอ้างอิงอาจต่างกัน ตัวเลขมูลค่าและกระแสเงินสดใช้สกุลที่ผู้ให้ข้อมูลระบุ ไม่ใช่มูลค่ายุติธรรมอัตโนมัติ')
    if info.get('longBusinessSummary'):
        with st.expander('ธุรกิจ / กลยุทธ์กองทุน',expanded=True): st.write(info['longBusinessSummary'])
    result=a.load_dividend_history(ticker)
    # Prefer a dated daily price over a potentially week-old info quote for yield.
    price=a.number(row.get('Close'))
    if price is None and history is not None:
        completed=a.completed_daily_history(history)
        price=a.number(completed.Close.iloc[-1]) if not completed.empty else None
    if price is None: price=a.number(info.get('regularMarketPrice'))
    end=pd.to_datetime(result.get('coverage_end'),errors='coerce',utc=True)
    stale=pd.notna(end) and (pd.Timestamp.now(tz='UTC')-end).days>35
    if stale:
        st.warning('ประวัติปันผลสิ้นสุดเกิน 35 วัน ยังไม่ยืนยันยอดหรือ Yield ปัจจุบัน แสดงประวัติที่มีเพื่ออ้างอิงเท่านั้น')
        if result.get('data') is not None: table(result['data'],height=300)
    else:
        a.render_dividends(ticker,result,str(info.get('currency') or 'สกุลสินทรัพย์'),price)
    st.caption(f'ราคาอ้างอิงสำหรับ Yield: {a.show_number(price)}; ตรวจวันที่ราคาและช่วงประวัติปันผลประกอบ')


def risk(ticker,history):
    if history is None: st.info('ยังไม่มีประวัติราคาให้คำนวณความเสี่ยง'); return
    close=clean_close(a.completed_daily_history(history))
    years=st.radio('ช่วงตัวอย่างความเสี่ยง',['1 ปี','3 ปี','5 ปี','ทั้งหมด'],horizontal=True,key='risk_period')
    if close.empty: st.info('ยังไม่มีแท่งรายวันที่ใช้คำนวณได้'); return
    if years!='ทั้งหมด': close=close.loc[close.index>=close.index[-1]-pd.DateOffset(years=int(years.split()[0]))]
    stats=risk_metrics(close.to_frame('Close'))
    for box,label,key in zip(st.columns(4),['ผลตอบแทนสะสม','CAGR','Volatility ต่อปี','Maximum drawdown'],['return_pct','cagr_pct','volatility_pct','max_drawdown_pct']):
        box.metric(label,a.show_number(stats[key],'%'))
    st.caption(f"ข้อมูลจริง {stats['start'] or '—'} ถึง {stats['end'] or '—'} · {stats['observations']:,} แท่ง ไม่รับรองว่าครบช่วงที่เลือก")
    dd=(close/close.cummax()-1)*100
    plot(go.Figure(go.Scatter(x=dd.index,y=dd,fill='tozeroy',name='Drawdown (%)')),'drawdown')
    changes=close.pct_change(fill_method=None).dropna()*100
    plot(go.Figure(go.Histogram(x=changes,nbinsx=40,name='Daily returns (%)')),'daily_distribution',300)
    st.write(f"ดีที่สุดต่อวัน {a.show_number(stats['best_day_pct'],'%')} · แย่ที่สุดต่อวัน {a.show_number(stats['worst_day_pct'],'%')}")
    st.caption('Volatility = ส่วนเบี่ยงเบนมาตรฐานผลตอบแทนรายวัน × √252; CAGR ใช้จำนวนวันปฏิทินจริงและไม่แสดงเมื่อข้อมูลสั้นกว่า 1 ปี; Drawdown วัดภายในช่วงตัวอย่าง ไม่ใช่ขีดจำกัดความเสียหายในอนาคต')


def compare(ticker,frame):
    symbols=list(dict.fromkeys([ticker,'SPY','QQQ','MSFT',*frame.Ticker.tolist()]))
    defaults=[ticker,'SPY' if ticker!='SPY' else 'QQQ']
    # Keep custom choices through refreshes; a new selected ticker resets them in the callback.
    if 'comparison_symbols' not in st.session_state:
        st.session_state['comparison_symbols']=defaults
    st.session_state['comparison_symbols']=[s for s in st.session_state['comparison_symbols'] if s in symbols][:6]
    chosen=st.multiselect('เลือก 2–6 ตัว',symbols,max_selections=6,key='comparison_symbols')
    period=st.selectbox('ช่วงเปรียบเทียบ',['3 เดือน','6 เดือน','1 ปี','3 ปี'],index=2)
    months=int(period.split()[0])*(12 if 'ปี' in period else 1)
    histories={}
    for symbol in chosen:
        h,_=a.get_data_cache().history(symbol)
        if h is None: st.info(f'{symbol}: ยังไม่มีประวัติที่อ่านได้')
        else: histories[symbol]=a.completed_daily_history(h)
    if len(histories)!=len(chosen) or len(chosen)<2:
        st.caption('ต้องมีข้อมูลครบทุกตัวที่เลือกก่อน ไม่ตัดหุ้นที่ไม่มีข้อมูลออกเงียบ ๆ'); return
    try: result=comparison(histories,months)
    except ValueError as exc: st.warning(str(exc)); return
    if not result['full_window']: st.warning('ประวัติร่วมกันสั้นกว่าช่วงที่เลือก ใช้เฉพาะวันที่มีจริง')
    normalized=result['normalized']; fig=go.Figure()
    for symbol in normalized: fig.add_trace(go.Scatter(x=normalized.index,y=normalized[symbol],name=symbol))
    plot(fig,'multi_performance')
    st.caption(f'เริ่มที่ 0% วันที่ {normalized.index[0]:%Y-%m-%d} ถึง {normalized.index[-1]:%Y-%m-%d} · ไม่มีการเติมราคาในวันว่างหรือแปลงสกุลเงิน')
    rows=[]
    for symbol in result['prices']:
        stats=risk_metrics(result['prices'][[symbol]].rename(columns={symbol:'Close'}))
        rows.append({'Ticker':symbol,'Return (%)':stats['return_pct'],'Volatility (%)':stats['volatility_pct'],'Max drawdown (%)':stats['max_drawdown_pct'],
                     'Beta vs SPY':beta_to_benchmark(result['prices'],symbol) if 'SPY' in result['prices'] else None})
    table(pd.DataFrame(rows))
    if 'SPY' not in result['prices']:st.caption('Beta vs SPY: ต้องเลือก SPY ในชุดเปรียบเทียบก่อน จึงมี benchmark ให้คำนวณ ไม่ใช่ค่า Beta เท่ากับศูนย์')
    if not result['correlation'].empty:
        st.subheader('Correlation ของผลตอบแทนรายวัน')
        help_table(result['correlation'].style.format('{:.2f}',na_rep='—'),hide_index=False,correlation=True)
    st.caption('Correlation ใช้อย่างน้อย 20 จุดผลตอบแทน; Beta อย่างน้อย 60 จุด คำนวณจากวันที่ร่วมกัน ไม่ใช่ Beta จากหน้าข้อมูลบริษัท และอดีตไม่รับประกันความสัมพันธ์ในอนาคต')
    st.download_button('ดาวน์โหลดชุดราคาเปรียบเทียบ',result['prices'].to_csv().encode('utf-8-sig'),'comparison_prices.csv','text/csv')


def health(reader,frame,cache):
    state=reader.status() if reader else {'manifest':{},'error':'ยังไม่มีแหล่งข้อมูล'}
    manifest=state.get('manifest',{})
    st.subheader('สถานะข้อมูลและระบบ',anchor='system-status')
    st.write('รุ่นโปรแกรม',a.APP_VERSION)
    st.write('ชุดข้อมูล',manifest.get('generation','ยังไม่เผยแพร่'))
    st.write('เผยแพร่สำเร็จ',a.thai_time(manifest.get('published_at')))
    if manifest.get('coverage'): table(pd.DataFrame([{'ข้อมูล':k,'จำนวน':v} for k,v in manifest['coverage'].items()]))
    report=manifest.get('report',{})
    st.write('รอบเก็บข้อมูล',{k:v for k,v in report.items() if k!='errors'})
    if report.get('errors'):
        with st.expander('รายการที่ต้องตรวจเพิ่ม'): st.text('\n'.join(map(str,report['errors'])))
    if cache.error: st.warning('Local cache มีข้อผิดพลาด: '+cache.error)
    table(pd.DataFrame([quality_counts(frame)]))
    st.caption('workflow สีเขียวหมายถึงบันทึกความคืบหน้าสำเร็จ ไม่ใช่ทุกตัวมีราคาล่าสุด; recent ใช้ 4 วันปฏิทิน ไม่ใช่ปฏิทินวันทำการตลาดสหรัฐ วันหยุดยาวอาจถูกจัดว่าเก่า')
    from quality_views import render_quality_report
    render_quality_report(cache,frame)
    st.link_button('เปิด GitHub Actions','https://github.com/sippakorntwo-glitch/stock-dashboard/actions')


def main():
    # Keep the historical import entrypoint without a second navigation implementation.
    from dashboard_ui import main as single_page_main
    single_page_main()
