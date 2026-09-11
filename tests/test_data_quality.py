"""Data completeness regressions. All fixture data is test-only; no providers."""
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
import pytest
from data_quality import (present,industry_value,checked_universe,history_shape,missing_metric,
                          metadata_due,metadata_jobs,make_quality,prepare_cached_metadata)


def test_zero_is_data_but_nan_and_placeholders_are_not():
    assert present(0) and present(0.0) and present(-3)
    for value in [None,float('nan'),float('inf'),'None','null','nan','n/a','',True]:assert not present(value)


def test_industry_does_not_guess_sector_or_company_name():
    assert industry_value({'sector':'Technology','shortName':'Some Bank'}) is None
    assert industry_value({'industryDisp':'Biotechnology'})=='Biotechnology'
    assert industry_value({'industry':'Software','category':'Large Blend'},True)=='Large Blend'
    assert industry_value({'industry':'Software'},True) is None


def test_snapshot_universe_is_exact_and_rejects_duplicates():
    assert checked_universe({'universe':['AAPL','BRK-B']})==('AAPL','BRK-B')
    for value in [[],['AAPL','AAPL'],['<script>'],None]:
        with pytest.raises(ValueError):checked_universe({'universe':value})


def test_short_history_is_not_a_failed_request():
    s={'valid':True,'bars':50,'first':'2026-07-01','last':'2026-09-10'}
    assert missing_metric('SMA200',{},s)=='short_history'
    assert missing_metric('Historical_Return',{},s)=='short_history'
    assert missing_metric('Vol_Ratio',{},s)=='missing_inputs'
    assert missing_metric('Return_1D',{'Return_1D':0},s)=='available'
    assert not history_shape(None)['valid']


def test_partial_profiles_recheck_labels_after_one_day_not_week():
    now=pd.Timestamp('2026-09-11T14:00:00Z').timestamp()
    meta={'info:A':{'fetched_at':'2026-09-09T14:00:00Z','classification_available':False}}
    assert metadata_due('info','A',meta,now)
    meta['info:A']['fetched_at']='2026-09-11T13:00:00Z'
    assert not metadata_due('info','A',meta,now)
    meta['attempt:info:A']={'success':False,'retry_after':'2026-09-12T14:00:00Z'}
    assert not metadata_due('info','A',meta,now)


def test_fair_queue_does_not_starve_etfs_or_dividends():
    jobs=metadata_jobs(['A','B','C','SPY','QQQ'],{},['SPY','QQQ'],time.time())
    assert jobs[:4]==[('info','A'),('info','SPY'),('dividends','A'),('dividends','SPY')]
    assert len(jobs)==10 and len(set(jobs))==10


def test_recover_labels_on_info_put_and_never_roll_back(tmp_path):
    import dashboard_runtime as a
    cache=a.DashboardCache(tmp_path/'cache.sqlite3')
    stamp='2026-09-11T12:00:00Z'
    cache.put('info:AEON',{'industry':'Biotechnology'},{'fetched_at':stamp})
    assert cache.classifications()['AEON']['Industry']=='Biotechnology'
    cache.put('info:AEON',{'industry':'Wrong older value'},{'fetched_at':'2026-09-10T12:00:00Z'})
    assert cache.classifications()['AEON']['Industry']=='Biotechnology'
    assert cache.get('info:AEON',request_remote=False)[0]['industry']=='Biotechnology'
    cache.put('info:AEON',{'currency':'USD'},{'fetched_at':'2026-09-11T13:00:00Z'})
    assert cache.classifications()['AEON']['Industry']=='Biotechnology'
    assert cache.classifications()['AEON']['Industry_Time']==stamp


def test_quality_distinguishes_no_dividends_from_unchecked(tmp_path):
    import dashboard_runtime as a
    cache=a.DashboardCache(tmp_path/'cache.sqlite3')
    cache.put('info:AAPL',{'industry':'Consumer Electronics','currency':'USD','earningsGrowth':0},{'fetched_at':'2026-09-11T00:00:00Z'})
    cache.put('dividends:AAPL',{'records':[],'error':None,'coverage_start':'2020-01-01','coverage_end':'2026-09-10'},{'fetched_at':'2026-09-11T00:00:00Z'})
    q=make_quality(cache,['AAPL','SPY'],etfs=['SPY'])
    assert q['symbols']['AAPL']['dividend_state']=='no_payments'
    assert q['symbols']['SPY']['dividend_state']=='pending'
    assert q['columns']['stock.earningsGrowth']['available']==1
    assert q['columns']['etf.navPrice']['pending']==1
    assert q['counts']['industry']==1 and q['counts']['info']==1
    assert 'earningsGrowth' not in q['symbols']['AAPL']['missing_info_fields']
    assert all(sum(v.values()) in (1,2) for v in q['columns'].values())


def test_default_catalog_equals_deployed_csv():
    import dashboard_runtime as a
    canonical=a.parse_watchlist(a.WATCHLIST_FILE.read_bytes())
    assert a.select_universe(pd.DataFrame(columns=['Ticker']))==a.select_universe(canonical)


def test_quality_metadata_round_trip_without_provider(tmp_path):
    import dashboard_runtime as a
    import data_sync
    cache=a.DashboardCache(tmp_path/'cache.sqlite3')
    q={'version':1,'counts':{'universe':2},'symbols':{'AAPL':{'industry_state':'pending'}}}
    data_sync.apply_summary(cache,{'schema':1,'universe':['AAPL','SPY'],'quotes':{},'classifications':{},'quality':q})
    assert cache.get('remote:quality',request_remote=False)[0]==q
    assert cache.get('remote:universe',request_remote=False)[0]==['AAPL','SPY']


def test_ui_placeholders_do_not_pollute_original_industry():
    from quality_views import industry_display,profile_field_state,profile_value
    f=pd.DataFrame({'Ticker':['A','B'],'Industry':[None,'Technology']})
    before=f.copy(deep=True)
    q={'symbols':{'A':{'industry_state':'not_reported'}}}
    display=industry_display(f,q)
    assert display.Industry.iloc[0]=='แหล่งข้อมูลไม่รายงาน'
    # Pandas 3 stores absent strings as NaN, not Python None. Assert semantics
    # and exact source-frame preservation rather than implementation identity.
    assert pd.isna(f.Industry.iloc[0]) and display.Industry.iloc[1]=='Technology'
    pd.testing.assert_frame_equal(f,before)
    assert profile_field_state({'earningsGrowth':0},'earningsGrowth')=='มีข้อมูล'
    assert profile_value(None,{})=='รอโหลดข้อมูลพื้นฐาน'


def test_ranking_uses_verified_membership_not_empty_csv():
    source=Path('ranking_job.py').read_text()
    assert 'checked_universe(summary)' in source
    assert 'a.select_universe(pd.DataFrame(columns=' not in source


def test_quality_counts_do_not_claim_every_fundamental_available(tmp_path):
    import dashboard_runtime as a
    cache=a.DashboardCache(tmp_path/'cache.sqlite3')
    cache.put('info:AAPL',{'industry':'Consumer Electronics'},{'fetched_at':'2026-09-11T00:00:00Z'})
    q=make_quality(cache,['AAPL'])
    assert q['counts']['info']==1
    assert q['columns']['stock.forwardPE']=={'not_reported':1}
    assert q['columns']['stock.industry']=={'available':1}
