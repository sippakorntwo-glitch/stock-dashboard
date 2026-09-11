"""Fixtures only. No live network or invented production observations."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from screening import filter_frame,enrich_frame,categorical_values,profile_rows,UNKNOWN
from return_periods import period_observation,display_returns,RETURN_MODES,RETURN_FIELDS


def fixture():
    return pd.DataFrame([
        {'Ticker':'A','Asset_Type':'Common Stock','Industry':'Software','Country':'US','Close':100.,'RSI_14':55.,'EMA20':95.,'EMA50':90.,'SMA200':80.,'Return_1D':0.,'Return_5Y':30.,'Price_AsOf':'2026-09-10','Profile_AsOf':'2026-09-09T12:00:00Z'},
        {'Ticker':'B','Asset_Type':'Common Stock','Industry':'Biotechnology','Country':'US','Close':20.,'RSI_14':70.,'EMA20':22.,'EMA50':25.,'SMA200':30.,'Return_1D':2.,'Return_5Y':np.nan,'Price_AsOf':'2026-09-10','Profile_AsOf':'2026-08-01T12:00:00Z'},
        {'Ticker':'QQQI','Asset_Type':'ETF','Industry':'Derivative Income','Country':None,'Close':50.,'RSI_14':50.,'EMA20':48.,'EMA50':47.,'SMA200':45.,'Return_1D':-1.,'Return_5Y':np.nan,'Price_AsOf':'2026-09-09','Profile_AsOf':'2026-09-09T12:00:00Z'},
        {'Ticker':'N','Asset_Type':'ETF','Industry':None,'Country':None,'Close':np.nan,'RSI_14':np.nan,'Return_1D':np.nan,'Return_5Y':np.nan,'Price_AsOf':None,'Profile_AsOf':None},
    ])


def test_category_or_numeric_and_no_mutation():
    f=fixture();before=f.copy(deep=True)
    r=filter_frame(f,categories={'Industry':['Software','Biotechnology'],'Country':['US']},bounds={'RSI_14':(40,60),'Close':(50,None)})
    assert r.Ticker.tolist()==['A']
    pd.testing.assert_frame_equal(f,before)


def test_unknown_is_explicit_and_numeric_zero_is_valid():
    f=fixture()
    assert filter_frame(f,categories={'Industry':[UNKNOWN]}).Ticker.tolist()==['N']
    assert filter_frame(f,bounds={'Return_1D':(0,0)}).Ticker.tolist()==['A']
    assert filter_frame(f,bounds={'Return_1D':(0,0)},include_missing=True).Ticker.tolist()==['A','N']
    assert UNKNOWN in categorical_values(f,'Industry')


def test_required_history_never_bypassed_by_include_missing():
    assert filter_frame(fixture(),require_returns=['Return_5Y'],include_missing=True).Ticker.tolist()==['A']
    assert filter_frame(fixture(),above_sma=True,bullish_ema=True).Ticker.tolist()==['A','QQQI']
    with pytest.raises(ValueError):filter_frame(fixture(),bounds={'Close':(100,10)})


def test_age_uses_price_date_without_utc_previous_day_shift():
    f=fixture()
    assert filter_frame(f,max_price_age=0,now='2026-09-10T22:00:00Z').Ticker.tolist()==['A','B']
    assert filter_frame(f,max_price_age=1,max_profile_age=3,now='2026-09-10T22:00:00Z').Ticker.tolist()==['A','QQQI']
    assert filter_frame(f,favourites=['QQQI']).Ticker.tolist()==['QQQI']


def test_calendar_previous_close_weekends_and_long_gaps():
    close=pd.Series([100.,120.,150.],index=pd.to_datetime(['2025-08-29','2025-09-02','2026-08-31']))
    o=period_observation(close,months=12)
    assert o['requested_start']=='2025-08-31' and o['start']=='2025-08-29'
    assert o['value']==pytest.approx(50.)
    bad=pd.Series([100.,150.],index=pd.to_datetime(['2025-07-01','2026-08-31']))
    assert period_observation(bad,months=12)['state']=='missing_inputs'


def test_annualized_is_display_only_and_requires_actual_ledger():
    f=pd.DataFrame([{'Ticker':'A','Return_3Y':72.8,'Return_5Y':100.,'Return_1D':2.,
        'Return_Observations':{'Return_3Y':{'annualized':20.},'Return_5Y':{'annualized':14.8698355}}}])
    before=f.copy(deep=True);r=display_returns(f,RETURN_MODES[1])
    assert r.Return_3Y.iloc[0]==20. and r.Return_1D.iloc[0]==2.
    pd.testing.assert_frame_equal(f,before)
    assert pd.isna(display_returns(f.drop(columns=['Return_Observations']),RETURN_MODES[1]).Return_3Y.iloc[0])


def test_compact_fields_keep_source_dates_and_unconverted_units(tmp_path):
    import dashboard_runtime as a
    c=a.DashboardCache(tmp_path/'profile.sqlite3')
    c.put('info:QQQI',{'fundFamily':'NEOS','currency':'USD','totalAssets':14000000000.,'profitMargins':0.}, {'fetched_at':'2026-09-10T12:00:00Z'})
    profiles=profile_rows(c,['QQQI','A'])
    assert profiles['QQQI']['Profit_Margin']==0. and profiles['QQQI']['Profile_AsOf']=='2026-09-10T12:00:00Z'
    out=enrich_frame(fixture(),profiles).set_index('Ticker')
    assert out.loc['QQQI','Size_Millions']==14000. and out.loc['QQQI','Fund_Family']=='NEOS'
    assert pd.isna(out.loc['A','Size_Millions'])


def test_expanded_official_catalog_preserves_stocks_and_adds_qqqi():
    import dashboard_runtime as a
    from catalog_extension import load_directory
    directory=load_directory()
    assert len(directory['funds'])>=5000 and 'QQQI' in directory['funds']
    u=a.select_universe();assert len(u)==len(set(u))==a.COMMON_STOCK_LIMIT+a.ETF_LIMIT
    assert a.COMMON_STOCK_LIMIT==4200 and a.ETF_LIMIT>=5000 and 'QQQI' in u
    assert 'QQQI' in a.ETF_NAMES and 'QQQI' not in a.STOCK_NAMES
    assert set(a.DEFAULT_ETFS)==set(a.ETF_NAMES)


def test_new_source_ledger_and_screener_summary_round_trip(tmp_path):
    import dashboard_runtime as a
    import update_data as collector
    from data_sync import DirectoryStore,apply_summary,read_checked
    import gzip
    c=a.DashboardCache(tmp_path/'c.sqlite3')
    idx=pd.bdate_range(end='2026-09-10',periods=1700);v=np.linspace(100,200,len(idx))
    h=pd.DataFrame({'Open':v,'High':v+1,'Low':v-1,'Close':v,'Volume':1000.},index=idx)
    c.save_history('AAPL',h,'2026-09-11T01:00:00Z',years=6)
    c.put('info:AAPL',{'industry':'Consumer Electronics','sector':'Technology','currency':'USD'}, {'fetched_at':'2026-09-11T00:00:00Z'})
    store=DirectoryStore(tmp_path/'data');m=collector.publish_snapshot(store,c,('AAPL',),{})
    s=json.loads(gzip.decompress(read_checked(store,m['summary'])))
    assert len(s['quotes']['AAPL']['Return_Observations'])==8
    assert s['screener']['AAPL']['Sector']=='Technology' and m['catalog_fingerprint']
    local=a.DashboardCache(tmp_path/'l.sqlite3');apply_summary(local,s)
    assert local.get('remote:screener',request_remote=False)[0]['AAPL']['Currency']=='USD'
