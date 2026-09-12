"""English advanced screener. No market-data calls when changing filters."""
from __future__ import annotations
import html
import json
import pandas as pd
import numpy as np
import streamlit as st
from return_periods import RETURN_FIELDS,RETURN_LABELS,RETURN_MODES,display_returns,labels_for_mode
from screening import categorical_values,filter_frame

METRICS={
 'Close':'Watchlist Price','RSI_14':'RSI (14)','ATR_Pct':'ATR / Price (%)',
 'Volatility_20D':'20-Day Annualized Volatility (%)','Drawdown_52W':'Drawdown from 52-Week High (%)',
 'Dollar_Volume_20D':'20-Day Average Price × Volume','Vol_Ratio':'Volume Ratio',
 'Size_Millions':'Market Cap / Fund Assets (millions, reported currency)',
 'Forward_PE':'Forward P/E','Price_To_Book':'Price / Book','Revenue_Growth':'Revenue Growth (%)',
 'Profit_Margin':'Profit Margin (%)','ROE':'ROE (%)','Free_Cash_Flow':'Free Cash Flow (reported currency)',
 'Beta':'Beta (provider)',
}
CATEGORIES={'Industry':'Industry / ETF Category','Sector':'Sector','Country':'Country',
            'Fund_Family':'Fund Family / Issuer','Exchange':'Exchange','Currency':'Currency'}


def reset_filters():
    # Deleting a widget key can reconnect it to its old browser value on the
    # next event. Write every default in this callback so both sides reset.
    defaults={'screen_asset':'All','screen_status':'All','screen_return_mode':RETURN_MODES[0],
              'screen_sort':'Ticker','screen_descending':False,'screen_periods':[],
              'screen_metrics':[],'screen_required':[],'screen_price_age':4,
              'screen_profile_age':14,'stock_search':'','table_page':1}
    for field in CATEGORIES:
        defaults['screen_cat_'+field]=[]
    for field in ('missing','fresh','profile_fresh','above_sma','bullish','favourites'):
        defaults['screen_'+field]=False
    for field in (*RETURN_FIELDS,*METRICS):
        defaults['screen_min_'+field]=None
        defaults['screen_max_'+field]=None
    st.session_state.update(defaults)
    st.session_state['_filter_reset_version']=st.session_state.get('_filter_reset_version',0)+1


def filter_universe(frame):
    for field in RETURN_FIELDS:
        if field not in frame:frame=frame.assign(**{field:np.nan})
    x,y=st.columns(2)
    asset=x.selectbox('Asset Type',['All','Common Stock','ETF'],key='screen_asset')
    status=y.selectbox('Trend Status',['All','PASS','FAIL','Insufficient Data'],key='screen_status')
    # Keep this dropdown outside Advanced Filters and preserve its existing key.
    options=categorical_values(frame,'Industry')
    key='screen_cat_Industry'
    if key in st.session_state:
        valid=[v for v in st.session_state[key] if v in options]
        if valid!=st.session_state[key]:st.session_state[key]=valid
    industry=st.multiselect('Industry / ETF Category',options,key=key,
        placeholder='All industries / ETF categories',
        help='Select one or more industries or ETF categories. Empty means all. Choices come from the published catalog, not guessed labels.')
    search_box,return_box=st.columns([3,2])
    query=search_box.text_input('Search Ticker / Company',key='stock_search', help='Exact ticker matches take priority. Use name:MSFT to find every fund or company name containing MSFT.').strip()
    mode=return_box.selectbox('Return Display',RETURN_MODES,key='screen_return_mode',
        help='Adjusted-close cumulative returns by default. Annualized mode changes only the 3Y/5Y display and filters, not trading scores. Neither mode is a live quote, price-only return, or official fund NAV return.')
    work=display_returns(frame,mode)
    categories={'Industry':industry};bounds={};required=[]
    if asset!='All':categories['Asset_Type']=[asset]
    if status!='All':categories['Status']=['ไม่มีข้อมูล','ข้อมูลไม่พอ','INSUFFICIENT'] if status=='Insufficient Data' else [status]
    from screening import search_frame
    work=search_frame(work,query)
    with st.expander('Advanced Filters',expanded=False):
        st.caption('AND between filters; OR within each multi-select. Blank limits mean no restriction. Missing values never become zero.')
        cols=st.columns(2)
        for i,(field,label) in enumerate((item for item in CATEGORIES.items() if item[0]!='Industry')):
            options=categorical_values(frame,field)
            key='screen_cat_'+field
            if key in st.session_state:
                valid=[v for v in st.session_state[key] if v in options]
                if valid!=st.session_state[key]:st.session_state[key]=valid
            categories[field]=cols[i%2].multiselect(label,options,key=key)
        st.markdown('**Return Filters**')
        labels=labels_for_mode(mode)
        periods=st.multiselect('Return Periods to Filter',list(RETURN_FIELDS),format_func=lambda f:labels[f],key='screen_periods')
        for field in periods:
            lo,hi=st.columns(2)
            bounds[field]=(lo.number_input('Minimum '+labels[field],value=None,key='screen_min_'+field,placeholder='No minimum'),
                           hi.number_input('Maximum '+labels[field],value=None,key='screen_max_'+field,placeholder='No maximum'))
        st.markdown('**Price, Liquidity, Risk and Fundamentals**')
        chosen=st.multiselect('Metrics to Filter',list(METRICS),format_func=METRICS.get,key='screen_metrics')
        for field in chosen:
            lo,hi=st.columns(2)
            bounds[field]=(lo.number_input('Minimum '+METRICS[field],value=None,key='screen_min_'+field,placeholder='No minimum'),
                           hi.number_input('Maximum '+METRICS[field],value=None,key='screen_max_'+field,placeholder='No maximum'))
        st.caption('Fund Assets applies to ETFs; Market Cap applies to companies. No FX conversion. Fundamental fields keep their own Profile As Of date; fund-only/company-only fields can be unavailable.')
        include_missing=st.checkbox('Include Missing Values in Active Numeric Filters',value=False,key='screen_missing')
        st.markdown('**Data Quality and Technical Conditions**')
        lo,hi=st.columns(2)
        fresh=lo.checkbox('Limit Price Age',key='screen_fresh')
        max_price_age=lo.number_input('Maximum Price Age (calendar days)',min_value=0,max_value=3650,value=4,key='screen_price_age') if fresh else None
        profiles_fresh=hi.checkbox('Limit Profile Age',key='screen_profile_fresh')
        max_profile_age=hi.number_input('Maximum Profile Age (days)',min_value=0,max_value=3650,value=14,key='screen_profile_age') if profiles_fresh else None
        required=st.multiselect('Require Available Return Periods',list(RETURN_FIELDS),format_func=lambda f:RETURN_LABELS[f],key='screen_required')
        above=lo.checkbox('Price Above SMA200',key='screen_above_sma')
        bullish=hi.checkbox('Price > EMA20 > EMA50',key='screen_bullish')
        favourites=st.checkbox('Session Favourites Only',key='screen_favourites')
        st.caption('Age uses calendar days, not an exchange holiday calendar. Active categorical, date, availability and trend conditions always require actual matching data.')
        st.button('Reset Filters',on_click=reset_filters,key='reset_screener')
    try:
        work=filter_frame(work,categories=categories,bounds=bounds,max_price_age=max_price_age,
            max_profile_age=max_profile_age,include_missing=include_missing,require_returns=required,
            above_sma=above,bullish_ema=bullish,favourites=st.session_state.get('favourites',[]) if favourites else None)
    except ValueError as exc:
        st.warning(str(exc));return None
    labels={**labels_for_mode(mode),**METRICS,'Ticker':'Ticker','Industry':'Industry / ETF Category'}
    x,y=st.columns([3,1])
    sort=x.selectbox('Sort By',['Ticker','Industry',*RETURN_FIELDS,*METRICS],format_func=lambda f:labels.get(f,f),key='screen_sort')
    descending=y.checkbox('Descending',value=False,key='screen_descending')
    if sort not in work:work[sort]=np.nan
    work=work.sort_values([sort,'Ticker'] if sort!='Ticker' else ['Ticker'],ascending=not descending,na_position='last',kind='stable')
    work.attrs['return_mode']=mode
    applied={'Asset Type':asset,'Trend Status':status,'Return Display':mode,
             'Search Ticker / Company':query,
             'Reset Version':st.session_state.get('_filter_reset_version',0),
             'Return Periods to Filter':[labels_for_mode(mode)[f] for f in periods]}
    applied.update({label:categories.get(field,[]) for field,label in CATEGORIES.items()})
    for field,(lower,upper) in bounds.items():
        label=labels_for_mode(mode).get(field,METRICS.get(field,field))
        applied['Minimum '+label]=lower
        applied['Maximum '+label]=upper
    work.attrs['applied_filters']=applied
    encoded=html.escape(json.dumps(applied,ensure_ascii=False),quote=True)
    description=html.escape(f'Applied: {asset} · {len(work):,} results · {mode}')
    st.markdown(f'<output class="screener-ready" data-controls="{encoded}" data-count="{len(work)}">{description}</output>',unsafe_allow_html=True)
    st.caption(f'{len(work):,} matching securities / {len(frame):,} catalog members. Return basis: {mode}.')
    return work
