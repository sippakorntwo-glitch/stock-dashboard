"""Auditable DAILY adjusted-close returns, never unlabeled live price growth.

Day horizons count completed session changes. Calendar horizons use the last
observed close ON OR BEFORE the calendar boundary (previous trading close).
Missing/invalid endpoints remain unavailable. Annualization is display-only.
"""
from __future__ import annotations
import math
import pandas as pd

RETURN_METHOD_VERSION = 3
RETURN_SPECS = (
    ('Return_1D', '1 Day', 1, None),
    ('Return_3D', '3 Days', 3, None),
    ('Return_7D', '7 Days', 7, None),
    ('Return_1M', '1 Month', None, 1),
    ('Return_6M', '6 Months', None, 6),
    ('Historical_Return', '1 Year', None, 12),
    ('Return_3Y', '3 Years', None, 36),
    ('Return_5Y', '5 Years', None, 60),
)
RETURN_FIELDS = tuple(item[0] for item in RETURN_SPECS)
RETURN_LABELS = {field: period + ' (%)' for field, period, _, _ in RETURN_SPECS}
RETURN_MODES = ('Cumulative (Adjusted Close)', 'Annualized (3Y / 5Y only)')
RETURN_CAPTION = (
    'Adjusted-close returns, not live quotes or revenue growth. '
    '1 / 3 / 7 Days count completed trading-session changes, not calendar days. '
    'Month / Year baselines use the last trading close on or before the calendar start date. '
    'Cumulative return = (end adjusted close / start adjusted close - 1) × 100. '
    'Adjusted prices reflect provider dividend/split adjustments; they are not official fund NAV returns. '
    'Fund websites may show month-end, annualized or price-only results instead. '
    'See Price As Of and Return Calculation Details before comparing. '
    'Investor fees, taxes and currency conversion are excluded. — means unavailable, not zero.'
)
EXPORT_LABELS = {
    'Ticker':'Ticker','Security_Name':'Company / ETF','Industry':'Industry / ETF Category',
    'Asset_Type':'Asset Type','Status':'Trend Status','Close':'Watchlist Price',
    'Price_AsOf':'Price As Of',**RETURN_LABELS,'RSI_14':'RSI (14)','ATR_Pct':'ATR / Price (%)',
    'Volatility_20D':'20-Day Volatility (%)','Dollar_Volume_20D':'20-Day Average Price × Volume',
    'Data_Status':'Data Status',
}
TABLE_FIELDS = ('Ticker','Security_Name','Industry','Asset_Type','Status','Close',
                'Price_AsOf',*RETURN_FIELDS,'RSI_14','ATR_Pct','Volatility_20D',
                'Dollar_Volume_20D','Data_Status')


def positive_price(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) and n>0 else None
    except (TypeError,ValueError,OverflowError):return None


def daily_closes(history):
    if history is None or history.empty or 'Close' not in history:return pd.Series(dtype=float)
    close=pd.to_numeric(history['Close'],errors='coerce').copy()
    close.index=pd.DatetimeIndex(pd.to_datetime(close.index)).tz_localize(None).normalize()
    close=close.loc[close.index.notna()]
    return close.loc[~close.index.duplicated(keep='last')].sort_index().astype(float)


def period_observation(close,*,sessions=None,months=None):
    if (sessions is None)==(months is None):raise ValueError('Specify exactly one of sessions or months')
    amount=sessions if sessions is not None else months
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<1:raise ValueError('Period must be a positive integer')
    result={'value':None,'annualized':None,'start':None,'end':None,'requested_start':None,
            'start_price':None,'end_price':None,'state':'short_history',
            'basis':'adjusted-close','method_version':RETURN_METHOD_VERSION}
    if close.empty:return result
    result.update(end=close.index[-1].date().isoformat(),end_price=positive_price(close.iloc[-1]))
    if sessions is not None:
        if len(close)<=sessions:return result
        first=len(close)-sessions-1
    else:
        cutoff=close.index[-1]-pd.DateOffset(months=months)
        result['requested_start']=cutoff.date().isoformat()
        first=int(close.index.searchsorted(cutoff,side='right'))-1
        if first<0 or first>=len(close)-1:return result
        if (cutoff-close.index[first]).days>7:
            result['state']='missing_inputs';return result
    result.update(start=close.index[first].date().isoformat(),start_price=positive_price(close.iloc[first]))
    if result['start_price'] is None or result['end_price'] is None:
        result['state']='missing_inputs';return result
    value=(result['end_price']/result['start_price']-1)*100
    if not math.isfinite(value):result['state']='missing_inputs';return result
    result.update(value=float(value),state='available')
    # Standard period annualization: do not annualize 1/3/7-day or sub-year changes.
    if months is not None and months>=12:
        result['annualized']=float(((result['end_price']/result['start_price'])**(12/months)-1)*100)
    return result


def return_observations(history):
    close=daily_closes(history)
    return {f:period_observation(close,sessions=d,months=m) for f,_,d,m in RETURN_SPECS}


def table_returns(history):
    return {f:obs['value'] for f,obs in return_observations(history).items()}


def labels_for_mode(mode=RETURN_MODES[0]):
    labels=dict(RETURN_LABELS)
    if mode==RETURN_MODES[1]:
        for field,label,_,months in RETURN_SPECS:
            if months and months>12:labels[field]=label+' (Annualized %)'
    return labels


def display_returns(frame,mode=RETURN_MODES[0]):
    if mode not in RETURN_MODES:raise ValueError('Unknown return display')
    result=frame.copy()
    if mode==RETURN_MODES[1]:
        for field in ('Return_3Y','Return_5Y'):
            # Never convert a legacy/unknown calculation without its verified dates.
            result[field]=result.apply(lambda r: (r.get('Return_Observations') or {}).get(field,{}).get('annualized')
                if isinstance(r.get('Return_Observations'),dict) else None,axis=1)
            result[field]=pd.to_numeric(result[field],errors='coerce')
    result.attrs['return_mode']=mode
    return result


def return_help(field,mode=RETURN_MODES[0]):
    field=str(field).removeprefix('price.')
    spec=next((s for s in RETURN_SPECS if s[0]==field),None)
    if spec is None:return None
    _,label,days,months=spec
    start=(f'the close {days} completed trading session(s) earlier' if days else
           f'the last close ON OR BEFORE {months} calendar month(s) earlier (prior close on weekends/holidays)')
    annualized=mode==RETURN_MODES[1] and months and months>12
    return (f'{label}: '+ ('annualized adjusted return: ((end/start)^(12/months)-1) × 100. ' if annualized else
            'cumulative adjusted return: (end/start-1) × 100. ')+
            f'Start is {start}. End is Price As Of, not now. Adjusted Close is not NAV or price-only return. '
            'No pre-inception estimates. Invalid/missing endpoints are —, never 0%.')


def return_column_config(mode=RETURN_MODES[0]):
    import streamlit as st
    labels=labels_for_mode(mode)
    return {f:st.column_config.NumberColumn(labels[f],format='%+.2f%%',help=return_help(f,mode)) for f in RETURN_FIELDS}


def export_watchlist(frame):
    mode=frame.attrs.get('return_mode',RETURN_MODES[0]);labels={**EXPORT_LABELS,**labels_for_mode(mode)}
    result=frame.reindex(columns=TABLE_FIELDS).rename(columns=labels)
    result['Return Basis']='Yahoo adjusted close; completed daily sessions; prior calendar-boundary close'
    result['Return Display']=mode
    return result
