"""Thai screening controls; English cumulative-return tables and source values stay intact."""
from __future__ import annotations
import html
import json
import numpy as np
import pandas as pd
import streamlit as st
from return_periods import RETURN_FIELDS, RETURN_LABELS, RETURN_MODES, display_returns, labels_for_mode
from screening import (categorical_values, filter_frame, COMPANY_ONLY_FIELDS, FUND_ONLY_FIELDS,
                       COMPANY_ONLY_CATEGORIES, FUND_ONLY_CATEGORIES)

METRICS = {
    'Close':'Watchlist Price','Dollar_Volume_20D':'20-Day Average Price × Volume','Vol_Ratio':'Volume Ratio',
    'Size_Millions':'Market Cap / Fund Assets (millions, reported currency)',
    'Dividend_Yield':'Trailing Annual Dividend Yield (%)',
    'RSI_14':'RSI (14)','ATR_Pct':'ATR / Price (%)','Volatility_20D':'20-Day Annualized Volatility (%)',
    'Drawdown_52W':'Drawdown from 52-Week High (%)','Beta':'Beta (provider)',
    'Market_Cap_Millions':'Market Cap (millions, reported currency)',
    'Forward_PE':'Forward P/E','Trailing_PE':'Trailing P/E','Price_To_Book':'Price / Book',
    'Revenue_Growth':'Revenue Growth (%)','Profit_Margin':'Profit Margin (%)',
    'Operating_Margin':'Operating Margin (%)','ROE':'ROE (%)','ROA':'ROA (%)',
    'Debt_To_Equity':'Debt / Equity (times)','Current_Ratio':'Current Ratio',
    'Free_Cash_Flow':'Free Cash Flow (reported currency)',
    'Fund_Assets_Millions':'Fund Assets (millions, reported currency)',
}
METRIC_THAI = {
    'Close':'ราคาจากชุดรายวัน','Dollar_Volume_20D':'ราคา × ปริมาณเฉลี่ย 20 วัน',
    'Vol_Ratio':'ปริมาณเทียบค่าเฉลี่ย (เท่า)','Size_Millions':'ขนาดบริษัท / กองทุน (ล้านหน่วยสกุลเงิน)',
    'Dividend_Yield':'อัตราปันผลย้อนหลัง 1 ปี (%)','RSI_14':'RSI 14',
    'ATR_Pct':'ช่วงแกว่ง ATR / ราคา (%)','Volatility_20D':'ความผันผวน 20 วัน คิดต่อปี (%)',
    'Drawdown_52W':'ระยะจากจุดสูงสุด 52 สัปดาห์ (%)','Beta':'เบตาจากผู้ให้ข้อมูล',
    'Market_Cap_Millions':'มูลค่าตลาดบริษัท (ล้านหน่วยสกุลเงิน)',
    'Forward_PE':'P/E คาดการณ์ (เท่า)','Trailing_PE':'P/E ย้อนหลัง (เท่า)',
    'Price_To_Book':'ราคาต่อมูลค่าบัญชี P/B (เท่า)','Revenue_Growth':'การเติบโตรายได้ (%)',
    'Profit_Margin':'อัตรากำไรสุทธิ (%)','Operating_Margin':'อัตรากำไรดำเนินงาน (%)',
    'ROE':'ผลตอบแทนต่อส่วนผู้ถือหุ้น ROE (%)','ROA':'ผลตอบแทนต่อสินทรัพย์ ROA (%)',
    'Debt_To_Equity':'หนี้ต่อส่วนผู้ถือหุ้น D/E (เท่า)','Current_Ratio':'อัตราส่วนสภาพคล่อง (เท่า)',
    'Free_Cash_Flow':'กระแสเงินสดอิสระ (สกุลเงินในงบ)',
    'Fund_Assets_Millions':'สินทรัพย์กองทุน (ล้านหน่วยสกุลเงิน)',
}
CATEGORIES = {'Industry':'Industry / ETF Category','Sector':'Sector','Country':'Country',
              'Fund_Family':'Fund Family / Issuer','Exchange':'Exchange','Currency':'Currency',
              'Financial_Currency':'Financial Statement Currency'}
CATEGORY_THAI = {'Industry':'อุตสาหกรรม / หมวด ETF','Sector':'กลุ่มธุรกิจ','Country':'ประเทศ',
                 'Fund_Family':'บริษัทจัดการ / ผู้ออกกองทุน','Exchange':'ตลาดหลักทรัพย์',
                 'Currency':'สกุลเงินราคา / มูลค่าตลาด','Financial_Currency':'สกุลเงินในงบการเงิน'}
ASSET_THAI = {'All':'ทั้งหมด','Common Stock':'หุ้นบริษัท','ETF':'ETF'}
STATUS_THAI = {'All':'ทั้งหมด','PASS':'ผ่านเงื่อนไขแนวโน้ม (PASS)',
              'FAIL':'ไม่ผ่านเงื่อนไขแนวโน้ม (FAIL)','Insufficient Data':'ข้อมูลแนวโน้มไม่พอ'}
METRIC_GROUPS = {
    'screen_metrics_price':('ราคาและสภาพคล่อง',('Close','Dollar_Volume_20D','Vol_Ratio','Size_Millions','Dividend_Yield')),
    'screen_metrics_risk':('ความเสี่ยง',('RSI_14','ATR_Pct','Volatility_20D','Drawdown_52W','Beta')),
    'screen_metrics':('พื้นฐานบริษัท',tuple(f for f in METRICS if f in COMPANY_ONLY_FIELDS)),
    'screen_metrics_funds':('ข้อมูลกองทุน',('Fund_Assets_Millions',)),
}
PRESETS = {
    'custom':('กำหนดเอง','เลือกเกณฑ์ที่ต้องการ แล้วปรับค่าต่ำสุดหรือสูงสุดได้ทุกช่อง'),
    'trend':('แนวโน้มและโมเมนตัม','ราคา > SMA200 และ ราคา > EMA20 > EMA50; ผลตอบแทน 1 เดือน ≥ 0%; RSI 40–70; ตัดรายการที่ขาดข้อมูล'),
    'profit':('บริษัทที่รายได้ไม่หดตัวและมีกำไร','เฉพาะหุ้นบริษัท: รายได้เติบโต ≥ 0%, อัตรากำไรสุทธิ ≥ 10%, ROE ≥ 10%; ตัดรายการที่ขาดข้อมูล'),
    'funds':('ETF ที่มีผลตอบแทนย้อนหลังให้เปรียบเทียบ','เฉพาะ ETF: ต้องมีผลตอบแทน 1 ปีและ 5 ปี; ตัดรายการที่ประวัติไม่พอ โดยไม่กำหนดว่าต้องได้กำไร'),
}


def reset_filters():
    defaults={'screen_asset':'All','screen_status':'All','screen_return_mode':RETURN_MODES[0],
              'screen_sort':'Ticker','screen_descending':False,'screen_periods':[],
              'screen_required':[],'screen_price_age':4,'screen_profile_age':14,
              'stock_search':'','table_page':1,'screen_preset':'custom'}
    defaults.update({key:[] for key in METRIC_GROUPS})
    defaults.update({'screen_cat_'+field:[] for field in CATEGORIES})
    defaults.update({'screen_'+field:False for field in ('missing','fresh','profile_fresh','above_sma','bullish','favourites')})
    for field in (*RETURN_FIELDS,*METRICS):
        defaults['screen_min_'+field]=None
        defaults['screen_max_'+field]=None
    st.session_state.update(defaults)
    st.session_state['_filter_reset_version']=st.session_state.get('_filter_reset_version',0)+1


def apply_preset():
    preset=st.session_state.get('screen_preset','custom')
    if preset=='custom':return
    reset_filters()
    st.session_state['screen_preset']=preset
    if preset=='trend':
        st.session_state.update(screen_above_sma=True,screen_bullish=True,screen_periods=['Return_1M'],
            screen_min_Return_1M=0.,screen_metrics_risk=['RSI_14'],screen_min_RSI_14=40.,screen_max_RSI_14=70.)
    elif preset=='profit':
        st.session_state.update(screen_asset='Common Stock',screen_metrics=['Revenue_Growth','Profit_Margin','ROE'],
            screen_min_Revenue_Growth=0.,screen_min_Profit_Margin=10.,screen_min_ROE=10.)
    elif preset=='funds':
        st.session_state.update(screen_asset='ETF',screen_required=['Historical_Return','Return_5Y'])


def _migrate_controls():
    if st.session_state.get('_screen_group_layout')==1:return
    old=st.session_state.get('screen_metrics',[])
    for key,(_,fields) in METRIC_GROUPS.items():
        existing=st.session_state.get(key,[]) if key!='screen_metrics' else []
        st.session_state[key]=list(dict.fromkeys([v for v in (*existing,*old) if v in fields]))
    st.session_state['_screen_group_layout']=1


def _category(frame,field,container=st):
    options=categorical_values(frame,field)
    key='screen_cat_'+field
    if key in st.session_state:
        valid=[v for v in st.session_state[key] if v in options]
        if valid!=st.session_state[key]:st.session_state[key]=valid
    from screening import UNKNOWN
    return container.multiselect(CATEGORY_THAI[field],options,key=key,
        format_func=lambda value:'ไม่ได้รายงาน' if value==UNKNOWN else value,
        placeholder='ทั้งหมด · เลือกได้หลายรายการ',
        help='ภายในช่องเดียวกันเลือกอย่างใดอย่างหนึ่งได้ (OR) หากไม่เลือกจะไม่จำกัดช่องนี้')


def _ranges(frame,fields,labels,bounds):
    for field in fields:
        left,right=st.columns(2)
        bounds[field]=(left.number_input('ต่ำสุด '+labels[field],value=None,key='screen_min_'+field,placeholder='ไม่จำกัด'),
                       right.number_input('สูงสุด '+labels[field],value=None,key='screen_max_'+field,placeholder='ไม่จำกัด'))
        values=pd.to_numeric(frame.get(field,pd.Series(index=frame.index,dtype=float)),errors='coerce')
        count=int(np.isfinite(values).sum())
        st.caption(f'{labels[field]}: มีค่าตัวเลข {count:,} / {len(frame):,} รายการในขอบเขตที่เลือก · เว้นว่างทั้งคู่ = ยังไม่ใช้เกณฑ์นี้')


def _metric_group(frame,key,bounds):
    title,fields=METRIC_GROUPS[key]
    selected=st.multiselect('เลือกเกณฑ์'+title,list(fields),format_func=METRIC_THAI.get,key=key,
                            placeholder='เลือกเฉพาะเกณฑ์ที่ต้องการกำหนดช่วง')
    _ranges(frame,selected,METRIC_THAI,bounds)
    return selected


def filter_universe(frame):
    _migrate_controls()
    for field in RETURN_FIELDS:
        if field not in frame:frame=frame.assign(**{field:np.nan})
    preset_box,apply_box,reset_box=st.columns([3,1,1])
    preset=preset_box.selectbox('เริ่มจากชุดตัวกรอง',list(PRESETS),format_func=lambda key:PRESETS[key][0],key='screen_preset')
    apply_box.button('ใช้ชุดตัวกรอง',key='apply_screener_preset',on_click=apply_preset,disabled=preset=='custom')
    reset_box.button('ล้างตัวกรองทั้งหมด',on_click=reset_filters,key='reset_screener')
    st.caption(PRESETS[preset][1]+' · เป็นเงื่อนไขคัดกรองที่แก้ไขได้ ไม่ใช่คำแนะนำซื้อ')
    x,y=st.columns(2)
    asset=x.selectbox('ประเภทสินทรัพย์',list(ASSET_THAI),format_func=ASSET_THAI.get,key='screen_asset')
    status=y.selectbox('แนวโน้ม',list(STATUS_THAI),format_func=STATUS_THAI.get,key='screen_status')
    industry=_category(frame,'Industry')
    search_box,return_box=st.columns([3,2])
    query=search_box.text_input('ค้นหาสัญลักษณ์ / ชื่อบริษัท',key='stock_search',
        help='ถ้าตรงกับสัญลักษณ์หุ้นจะเลือกตัวนั้นก่อน ใช้ name:MSFT เพื่อค้นหาทุกชื่อที่มี MSFT').strip()
    mode=return_box.selectbox('รูปแบบผลตอบแทน',RETURN_MODES,key='screen_return_mode',
        help='ค่าเริ่มต้นเป็นผลตอบแทนสะสมจากราคาปรับแล้ว โหมด Annualized เปลี่ยนเฉพาะ 3 ปี / 5 ปี ทั้งการแสดงและการกรอง ไม่เปลี่ยนคะแนนซื้อขาย')
    work=display_returns(frame,mode)
    categories={'Industry':industry};bounds={}
    if asset!='All':categories['Asset_Type']=[asset]
    if status!='All':categories['Status']=['ไม่มีข้อมูล','ข้อมูลไม่พอ','INSUFFICIENT'] if status=='Insufficient Data' else [status]
    from screening import search_frame
    work=search_frame(work,query)
    scope=filter_frame(work,categories=categories)
    with st.expander('ตัวกรองขั้นสูง',expanded=False):
        st.caption('ต้องผ่านทุกเกณฑ์ที่เลือก (AND) · ภายในช่องเลือกหลายรายการ ผ่านรายการใดรายการหนึ่งได้ (OR) · ไม่เลือก / เว้นช่วงว่าง = ไม่จำกัด')
        returns,price,risk,company,details=st.tabs(['ผลตอบแทน','ราคา / ปันผล','ความเสี่ยง / แนวโน้ม','บริษัท / กองทุน','หมวดหมู่ / คุณภาพข้อมูล'])
        with returns:
            periods=st.multiselect('ช่วงผลตอบแทนที่ต้องการกรอง',list(RETURN_FIELDS),format_func=labels_for_mode(mode).get,key='screen_periods')
            _ranges(scope,periods,labels_for_mode(mode),bounds)
            required=st.multiselect('ต้องมีข้อมูลผลตอบแทนครบช่วงที่เลือก',list(RETURN_FIELDS),format_func=RETURN_LABELS.get,key='screen_required')
            st.caption('1 / 3 / 7 Days นับการเปลี่ยนแปลงระหว่างวันซื้อขาย ส่วน Month / Year ใช้วันซื้อขายก่อนหรือเท่ากับวันเริ่มช่วง ไม่ใช้จำนวนแท่งมาทดแทนประวัติหลายปี')
        with price:
            _metric_group(scope,'screen_metrics_price',bounds)
            st.caption('ราคาปรับแล้วจากชุดรายวัน ไม่ใช่ราคาเรียลไทม์ · ราคา × ปริมาณเป็นค่าประมาณสภาพคล่อง · อัตราปันผลใช้ trailingAnnualDividendYield ไม่ใช่อัตราปันผลคาดการณ์')
        with risk:
            _metric_group(scope,'screen_metrics_risk',bounds)
            lo,hi=st.columns(2)
            above=lo.checkbox('ราคาอยู่เหนือ SMA200',key='screen_above_sma')
            bullish=hi.checkbox('ราคา > EMA20 > EMA50',key='screen_bullish')
            st.caption('Drawdown ใช้ค่าติดลบ เช่น −20 ถึง 0 = ต่ำกว่าจุดสูงสุดไม่เกิน 20% · RSI และแนวโน้มไม่ใช่คำสั่งซื้อ')
        with company:
            st.caption('เกณฑ์พื้นฐานบริษัทใช้เฉพาะหุ้นบริษัท เมื่อเปิดเกณฑ์นี้ ETF จะไม่ผ่าน แม้เลือกให้รวมข้อมูลที่ขาด · P/E ของพอร์ต ETF มีความหมายต่างจาก P/E บริษัท')
            _metric_group(scope.loc[scope.Asset_Type.eq('Common Stock')],'screen_metrics',bounds)
            st.markdown('**ขนาดกองทุน**')
            _metric_group(scope.loc[scope.Asset_Type.eq('ETF')],'screen_metrics_funds',bounds)
            st.caption('ข้อมูลพื้นฐานมาจากโปรไฟล์ที่ผู้ให้ข้อมูลรายงาน ณ Profile As Of ไม่ใช่ทุกช่องจากงบล่าสุด · D/E แสดงเป็นเท่า · ควรเทียบธุรกิจเดียวกัน; อัตราส่วนสภาพคล่องทั่วไปไม่เหมาะกับธนาคาร')
        with details:
            cols=st.columns(2)
            for i,field in enumerate(f for f in CATEGORIES if f!='Industry'):
                categories[field]=_category(frame,field,cols[i%2])
            lo,hi=st.columns(2)
            fresh=lo.checkbox('จำกัดอายุข้อมูลราคา',key='screen_fresh')
            max_price_age=lo.number_input('อายุข้อมูลราคาสูงสุด (วันปฏิทิน)',min_value=0,max_value=3650,value=4,key='screen_price_age') if fresh else None
            profiles_fresh=hi.checkbox('จำกัดอายุข้อมูลพื้นฐาน',key='screen_profile_fresh')
            max_profile_age=hi.number_input('อายุข้อมูลพื้นฐานสูงสุด (วัน)',min_value=0,max_value=3650,value=14,key='screen_profile_age') if profiles_fresh else None
            favourites=st.checkbox('เฉพาะรายการโปรดในเซสชันนี้',key='screen_favourites')
            st.caption('อายุข้อมูลนับวันปฏิทิน รวมเสาร์–อาทิตย์และวันหยุด ตัวกรองวันที่ต้องมีวันที่จริงที่ไม่ใช่อนาคต')
        include_missing=st.checkbox('รวมรายการที่ไม่ได้รายงานค่าตัวเลขที่กำลังกรอง',value=False,key='screen_missing',
            help='ปกติรายการที่ขาดตัวเลขจะไม่ผ่าน หากเปิด รายการนั้นอาจผ่านโดยไม่ได้ยืนยันเกณฑ์ตัวเลขนั้น แต่ยังต้องผ่านประเภทสินทรัพย์ หมวดหมู่ วันที่ และข้อมูลที่กำหนดให้ต้องมี')
    active_bounds={field:pair for field,pair in bounds.items() if any(v is not None for v in pair)}
    company_active=bool(COMPANY_ONLY_FIELDS.intersection(active_bounds)) or any(categories.get(f) for f in COMPANY_ONLY_CATEGORIES)
    fund_active=bool(FUND_ONLY_FIELDS.intersection(active_bounds)) or any(categories.get(f) for f in FUND_ONLY_CATEGORIES)
    if company_active and (asset=='ETF' or fund_active):
        st.warning('เกณฑ์บริษัทใช้ร่วมกับประเภท ETF หรือเกณฑ์เฉพาะกองทุนไม่ได้ ผลลัพธ์จึงเป็นศูนย์ กรุณาเอาเกณฑ์บริษัท / กองทุนที่ไม่ต้องการออก หรือกดล้างตัวกรองทั้งหมด')
    if fund_active and asset=='Common Stock':
        st.warning('เกณฑ์สินทรัพย์กองทุนใช้กับหุ้นบริษัทไม่ได้ กรุณาเปลี่ยนประเภทสินทรัพย์หรือเอาเกณฑ์นี้ออก')
    money={'Close','Dollar_Volume_20D','Size_Millions','Market_Cap_Millions','Fund_Assets_Millions','Free_Cash_Flow'}
    if money.intersection(active_bounds):
        st.caption('เกณฑ์จำนวนเงินใช้สกุลที่รายงานโดยไม่แปลง FX เลือกสกุลเงินให้ตรงกันในแท็บหมวดหมู่; กระแสเงินสดใช้สกุลเงินในงบ ซึ่งอาจต่างจากสกุลราคา')
    applied={'Asset Type':asset,'Trend Status':status,'Return Display':mode,'Search Ticker / Company':query,
        'Reset Version':st.session_state.get('_filter_reset_version',0),
        'Return Periods to Filter':[labels_for_mode(mode)[f] for f in periods],
        'Include Missing Values':include_missing,'Require Available Return Periods':[RETURN_LABELS[f] for f in required],
        'Price Above SMA200':above,'Price > EMA20 > EMA50':bullish,'Session Favourites Only':favourites,
        'Company Filters Active':company_active,'Fund Filters Active':fund_active}
    applied.update({label:categories.get(field,[]) for field,label in CATEGORIES.items()})
    conditions=[]
    if asset!='All':conditions.append('ประเภท: '+ASSET_THAI[asset])
    if status!='All':conditions.append('แนวโน้ม: '+STATUS_THAI[status])
    if query:conditions.append('ค้นหา: '+query)
    for field,selected in categories.items():
        if field in CATEGORY_THAI and selected:conditions.append(CATEGORY_THAI[field]+': '+', '.join(selected))
    for field,(lower,upper) in bounds.items():
        label=labels_for_mode(mode).get(field,METRICS.get(field,field))
        applied['Minimum '+label]=lower;applied['Maximum '+label]=upper
        if field in active_bounds:
            display=labels_for_mode(mode).get(field,METRIC_THAI.get(field,field))
            limits=[]
            if lower is not None:limits.append('≥ '+f'{lower:g}')
            if upper is not None:limits.append('≤ '+f'{upper:g}')
            conditions.append(display+' '+' และ '.join(limits))
    for name,label,value in [('Price Age','อายุข้อมูลราคา',max_price_age),('Profile Age','อายุข้อมูลพื้นฐาน',max_profile_age)]:
        if value is not None:
            applied['Maximum '+name]=value;conditions.append(f'{label} ≤ {value} วัน')
    if required:conditions.append('ต้องมีผลตอบแทน: '+', '.join(RETURN_LABELS[f] for f in required))
    if above:conditions.append('ราคา > SMA200')
    if bullish:conditions.append('ราคา > EMA20 > EMA50')
    if favourites:conditions.append('เฉพาะรายการโปรด')
    if company_active:conditions.append('เกณฑ์บริษัท: รับเฉพาะหุ้นบริษัท')
    if fund_active:conditions.append('เกณฑ์กองทุน: รับเฉพาะ ETF')
    if active_bounds:conditions.append('ค่าตัวเลขที่ขาด: '+('รวมไว้โดยยังไม่ยืนยันเกณฑ์นั้น' if include_missing else 'ไม่ผ่านตัวกรอง'))
    summary=' · '.join(conditions) if conditions else 'ยังไม่จำกัดผลลัพธ์ แสดงทุกรายการ'
    st.markdown('<div class="screener-summary"><strong>ตัวกรองที่ใช้จริง</strong><br>'+html.escape(summary)+'</div>',unsafe_allow_html=True)
    try:
        work=filter_frame(work,categories=categories,bounds=bounds,max_price_age=max_price_age,
            max_profile_age=max_profile_age,include_missing=include_missing,require_returns=required,
            above_sma=above,bullish_ema=bullish,favourites=st.session_state.get('favourites',[]) if favourites else None)
    except ValueError as exc:
        message=str(exc)
        if ': maximum is below minimum' in message:
            field=message.split(':',1)[0];message='ค่าต่ำสุดต้องไม่มากกว่าค่าสูงสุด: '+labels_for_mode(mode).get(field,METRIC_THAI.get(field,field))
        st.warning(message)
        return None
    labels={**labels_for_mode(mode),**METRIC_THAI,'Ticker':'สัญลักษณ์','Industry':'อุตสาหกรรม / หมวด ETF'}
    x,y=st.columns([3,1])
    sort=x.selectbox('เรียงตาม',['Ticker','Industry',*RETURN_FIELDS,*METRICS],format_func=lambda field:labels.get(field,field),key='screen_sort')
    descending=y.checkbox('มากไปน้อย',value=False,key='screen_descending')
    if sort not in work:work[sort]=np.nan
    work=work.sort_values([sort,'Ticker'] if sort!='Ticker' else ['Ticker'],ascending=not descending,na_position='last',kind='stable')
    work.attrs['return_mode']=mode
    applied['Sort By']=sort;applied['Descending']=descending
    work.attrs['applied_filters']=applied
    encoded=html.escape(json.dumps(applied,ensure_ascii=False),quote=True)
    st.markdown(f'<output class="screener-ready" data-controls="{encoded}" data-count="{len(work)}">ผ่านตัวกรอง {len(work):,} / {len(frame):,} รายการ</output>',unsafe_allow_html=True)
    if work.empty:
        st.info('ไม่มีรายการผ่านทุกเกณฑ์ ลองลดจำนวนเงื่อนไข ขยายช่วงตัวเลข หรือใช้ปุ่มล้างตัวกรองทั้งหมดด้านบน')
    return work
