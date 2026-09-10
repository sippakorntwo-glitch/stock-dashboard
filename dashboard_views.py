"""Thai research workspace. Views are rendered on demand, not all at once."""
from __future__ import annotations
import math
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import dashboard_runtime as a
from analytics import clean_close, risk_metrics, comparison, beta_to_benchmark, quality_counts
VIEWS = ['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว','สถานะข้อมูล']


def table(frame, **kwargs):
    st.dataframe(frame, hide_index=True, **a.width_options(st.dataframe), **kwargs)


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


def overview(frame):
    work = frame.copy()
    for field in a.EXTRA_NUMERIC:
        if field not in work: work[field] = np.nan
    x,y,z = st.columns([1,1,2])
    asset = x.selectbox('ประเภท', ['ทั้งหมด','Common Stock','ETF'])
    status = y.selectbox('สถานะ', ['ทั้งหมด','PASS','FAIL'])
    query = z.text_input('ค้นหา Ticker / บริษัท / อุตสาหกรรม').strip()
    if asset != 'ทั้งหมด': work = work.loc[work.Asset_Type.eq(asset)]
    if status != 'ทั้งหมด': work = work.loc[work.Status.eq(status)]
    if query:
        mask = pd.Series(False,index=work.index)
        for field in ['Ticker','Security_Name','Industry']:
            mask |= work[field].fillna('').astype(str).str.contains(query,case=False,regex=False)
        work = work.loc[mask]
    with st.expander('ตัวกรองราคา / ผลตอบแทน / คุณภาพข้อมูล'):
        x,y,z = st.columns(3)
        low = x.number_input('ราคาขั้นต่ำ',min_value=0.0,value=0.0)
        high = x.number_input('ราคาสูงสุด',min_value=0.0,value=max(5000.0,a.number(frame.Close.max()) or 0.0))
        rsi = y.slider('RSI 14',0,100,(0,100))
        fresh = y.checkbox('ราคาไม่เกิน 4 วันปฏิทินและระบุวันที่')
        minimum = z.number_input('ผลตอบแทน 1 ปีขั้นต่ำ (%)',value=-100.0)
        keep = z.checkbox('แสดงแถวที่ข้อมูลยังไม่ครบ',value=True)
        favourites = st.checkbox('เฉพาะรายการโปรดในเซสชันนี้')
    if high < low:
        st.warning('ราคาสูงสุดต้องไม่น้อยกว่าราคาขั้นต่ำ'); return
    for field in ['Close','RSI_14','Historical_Return']:
        s = work[field]
        valid = s.between(low,high) if field=='Close' else s.between(*rsi) if field=='RSI_14' else s.ge(minimum)
        work = work.loc[valid | s.isna() if keep else valid]
    if fresh:
        dates = pd.to_datetime(work.Price_AsOf,errors='coerce',utc=True).dt.tz_localize(None)
        age = (pd.Timestamp.now(tz='America/New_York').tz_localize(None).normalize()-dates.dt.normalize()).dt.days
        work = work.loc[age.between(0,4)]
    if favourites: work = work.loc[work.Ticker.isin(st.session_state.get('favourites',[]))]
    x,y = st.columns([3,1])
    sort = x.selectbox('เรียงตาม',['Ticker','Historical_Return','Return_3M','Return_2Y','Return_3Y','RSI_14','ATR_Pct','Volatility_20D','Dollar_Volume_20D'])
    descending = y.checkbox('มากไปน้อย',value=sort!='Ticker')
    work = work.sort_values(sort,ascending=not descending,na_position='last')
    pages = max(1,math.ceil(len(work)/100))
    if st.session_state.get('table_page',1)>pages: st.session_state.table_page=1
    page = st.number_input('หน้าตาราง — หน้าละ 100 ตัว',min_value=1,max_value=pages,step=1,key='table_page')
    fields = ['Ticker','Security_Name','Industry','Asset_Type','Status','Close','Return_1D','Return_3M','Historical_Return','Return_2Y','Return_3Y','RSI_14','ATR_Pct','Volatility_20D','Dollar_Volume_20D','Price_AsOf','Data_Status']
    shown = work.iloc[(page-1)*100:page*100].reindex(columns=fields)
    styled = shown.style.format(precision=2,na_rep='—').map(a.return_cell_style,subset=['Return_1D','Return_3M','Historical_Return','Return_2Y','Return_3Y'])
    config = a.watchlist_column_config()
    for field,label in {'Return_1D':'1D (%)','Return_3M':'3M (%)','ATR_Pct':'ATR / ราคา (%)','Volatility_20D':'Volatility 20D ต่อปี (%)'}.items():
        config[field]=st.column_config.NumberColumn(label,format='%.2f')
    config['Dollar_Volume_20D']=st.column_config.NumberColumn('ราคา × Volume เฉลี่ย 20D',format='%.0f',help='ค่าประมาณจากราคาปรับแล้ว ไม่ใช่มูลค่าซื้อขายจริงจากตลาด')
    st.dataframe(styled,hide_index=True,height=520,column_config=config,**a.width_options(st.dataframe))
    st.caption(f'ผ่านตัวกรอง {len(work):,} ตัว · ช่อง — คือไม่มีข้อมูล ไม่ใช่ศูนย์ · PASS เป็นสถานะแนวโน้ม ไม่ใช่คำสั่งซื้อ')
    st.download_button('ดาวน์โหลดผลกรองครบทุกแถว',work.to_csv(index=False).encode('utf-8-sig'),'filtered_watchlist.csv','text/csv')
    st.subheader('ความแข็งแกร่งแยกอุตสาหกรรม / หมวด ETF')
    grouped=work.groupby(['Asset_Type','Industry'],dropna=True).agg(observations=('Return_3M','count'),median_return_3m=('Return_3M','median')).reset_index()
    grouped=grouped.loc[grouped.observations.ge(3)].sort_values('median_return_3m',ascending=False).head(20)
    if grouped.empty: st.info('ยังมีอุตสาหกรรมและผลตอบแทน 3 เดือนไม่พอสำหรับสรุปกลุ่ม')
    else: table(grouped,height=300)
    st.caption('มัธยฐานเฉพาะรายการที่ผ่านตัวกรองและมีข้อมูลอย่างน้อย 3 ตัวต่อกลุ่ม ไม่ใช่ผลตอบแทนดัชนีหรือภาพรวมตลาดทั้งหมด')


def technical(ticker,daily_history,info,row):
    periods=['1 เดือน','3 เดือน','6 เดือน','1 ปี','2 ปี','3 ปี']
    if a.live_enabled(): periods=['1 วัน','5 วัน','7 วัน']+periods
    period=st.radio('ช่วงเวลาแสดงกราฟ',periods,horizontal=True)
    interval='5m' if period=='1 วัน' else '15m' if period in ('5 วัน','7 วัน') else '1d'
    chart_history,meta=a.get_data_cache().history(ticker,interval)
    if interval!='1d' and st.button('ดึงกราฟระหว่างวันจาก Yahoo'):
        a.get_updater().request(ticker,'history',interval)
    if chart_history is None:
        st.info('ยังไม่มีประวัติสำหรับกราฟที่เลือก ชุดอัตโนมัติจะเติมประวัติรายวัน')
    else:
        try:
            payload=a.build_payload(chart_history,ticker,period,interval,meta.get('fetched_at',''))
            html=a.build_chart_html(payload)
            if hasattr(st,'iframe'): st.iframe(html,height=900)
            else: components.html(html,height=900,scrolling=False)
        except Exception as exc: st.warning(f'แสดงกราฟไม่ได้ ({type(exc).__name__})')
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
    with st.expander('ตารางวิเคราะห์ 360° และแหล่งข้อมูล'):
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
    records=[]
    for label,key,pct in fields:
        raw=info.get(key); n=a.number(raw)
        value=a.show_number(n*100,'%') if pct and n is not None else a.show_number(n) if n is not None else raw if isinstance(raw,str) else 'ไม่มีข้อมูล'
        records.append({'มิติ':label,'ค่า':value,'ฟิลด์ต้นทาง':key})
    table(pd.DataFrame(records),height=480)
    st.caption('อัตราการเติบโตและอัตรากำไรเป็นค่าที่แหล่งข้อมูลรายงาน ช่วงอ้างอิงอาจต่างกัน ตัวเลขมูลค่าและกระแสเงินสดใช้สกุลที่ผู้ให้ข้อมูลระบุ ไม่ใช่มูลค่ายุติธรรมอัตโนมัติ')
    if info.get('longBusinessSummary'):
        with st.expander('ธุรกิจ / กลยุทธ์กองทุน'): st.write(info['longBusinessSummary'])
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
    years=st.radio('ช่วงตัวอย่างความเสี่ยง',['1 ปี','3 ปี','5 ปี','ทั้งหมด'],horizontal=True)
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
    chosen=st.multiselect('เลือก 2–6 ตัว',symbols,default=list(dict.fromkeys([ticker,'SPY'])),max_selections=6)
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
    if not result['correlation'].empty:
        st.subheader('Correlation ของผลตอบแทนรายวัน')
        st.dataframe(result['correlation'].style.format('{:.2f}',na_rep='—'),**a.width_options(st.dataframe))
    st.caption('Correlation ใช้อย่างน้อย 20 จุดผลตอบแทน; Beta อย่างน้อย 60 จุด คำนวณจากวันที่ร่วมกัน ไม่ใช่ Beta จากหน้าข้อมูลบริษัท และอดีตไม่รับประกันความสัมพันธ์ในอนาคต')
    st.download_button('ดาวน์โหลดชุดราคาเปรียบเทียบ',result['prices'].to_csv().encode('utf-8-sig'),'comparison_prices.csv','text/csv')


def health(reader,frame,cache):
    state=reader.status() if reader else {'manifest':{},'error':'ยังไม่มีแหล่งข้อมูล'}
    manifest=state.get('manifest',{})
    st.subheader('สถานะข้อมูลและระบบ')
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
    st.link_button('เปิด GitHub Actions','https://github.com/sippakorntwo-glitch/stock-dashboard/actions')


def main():
    st.set_page_config(page_title='Stock Research Workspace',page_icon='📊',layout='wide')
    st.markdown('''<style>.block-container{padding-top:1.5rem;max-width:1700px}
    [data-testid="stMetric"]{border:1px solid #26384b;border-radius:12px;padding:14px;background:#101c2b}
    [data-testid="stMetricValue"]{font-size:1.65rem}</style>''',unsafe_allow_html=True)
    reader,error=a.get_remote_reader()
    if reader: reader.refresh()
    revision=reader.status()['revision'] if reader else 0
    cache=a.get_data_cache()
    original=original_watchlist()
    frame,outside=a.build_universe_frame(original,cache.quotes(),cache.classifications())
    st.sidebar.title('Stock Research')
    view=st.sidebar.radio('มุมมอง',VIEWS)
    ticker=a.normalize_symbol(st.sidebar.text_input('Ticker สำหรับวิเคราะห์',value='AAPL'))
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
    st.title('Stock Research Workspace')
    st.caption('แนวโน้ม • พื้นฐาน • ปันผล • ความเสี่ยง • เปรียบเทียบ | ข้อมูลเป็นรอบ ไม่ใช่ราคาสตรีมสด')
    counts=quality_counts(frame)
    for box,label,key in zip(st.columns(4),['รายการทั้งหมด','มีราคา','ราคาภายใน 4 วัน','มีราคาแต่ไม่ระบุวัน'],['total','priced','recent','unknown_time']): box.metric(label,f'{counts[key]:,}')
    if error: st.warning(error)
    state=reader.status() if reader else {'manifest':{}}
    if state.get('error'): st.warning(state['error'])
    if not state.get('manifest'): st.info('ยังไม่มีชุดข้อมูลอัตโนมัติ ใช้ CSV/ข้อมูลเดิมก่อน เจ้าของระบบเริ่ม Actions → Update market data (free) → bootstrap')
    else: st.caption('Snapshot เผยแพร่ '+a.thai_time(state['manifest'].get('published_at')))
    if view==VIEWS[0]:
        overview(frame)
        if not outside.empty:
            with st.expander(f'CSV นอกชุดหลัก ({len(outside):,} ตัว)'): table(outside)
    elif view==VIEWS[-1]: health(reader,frame,cache)
    elif not valid: st.warning('กรุณากรอก Ticker ให้ถูกต้อง')
    else:
        history,meta=cache.history(ticker)
        info,_=cache.get('info:'+ticker); info=info or {}
        selected=frame.loc[frame.Ticker.eq(ticker)]
        row=selected.iloc[0].to_dict() if not selected.empty else {}
        st.subheader(f"{ticker} · {info.get('shortName') or row.get('Security_Name') or ''}")
        st.caption(f"วันที่ราคา Watchlist: {row.get('Price_AsOf') or 'ไม่ระบุ'} | ประวัติดึงสำเร็จ {a.thai_time(meta.get('fetched_at'))} | quote ณ {a.thai_time(info.get('regularMarketTime'))}")
        if view==VIEWS[1]: technical(ticker,history,info,row)
        elif view==VIEWS[2]: fundamentals(ticker,history,info,row)
        elif view==VIEWS[3]: risk(ticker,history)
        elif view==VIEWS[4]: compare(ticker,frame)
    end=reader.status() if reader else {'busy':False,'revision':0}
    if reader and not end['busy'] and end['revision']!=revision: st.rerun()
    worker=a.get_updater().state()
    if worker['busy'] or end['busy']: st.caption('กำลังอ่านหรืออัปเดตข้อมูลที่เลือก ข้อมูลเดิมยังใช้งานได้')
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=3000 if worker['busy'] or end['busy'] else 300_000,key='research_refresh')
    st.caption('เพื่อการศึกษาวิจัย ไม่ใช่คำแนะนำลงทุนเฉพาะบุคคล คะแนนเป็นกติกาของระบบ ไม่ใช่โอกาสกำไรหรือผลทดสอบย้อนหลัง')
