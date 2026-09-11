"""Pagination, glossary, real-period boundaries and isolated provider tests."""
import time
import numpy as np
import pandas as pd
import pytest
from chart_ranges import ChartHistoryService,PERIODS,PAGE_SIZE,page_slice,covers_years,range_payload
from dashboard_help import field_help,column_help,table_html
import dashboard_runtime as a


def prices(index):
    c=np.linspace(100,120,len(index))
    return pd.DataFrame({'Open':c,'High':c+2,'Low':c-2,'Close':c,'Volume':1000},index=index)


def test_500_pagination_preserves_all_rows_and_order():
    f=pd.DataFrame({'Ticker':[f'T{i}' for i in range(4900)]})
    assert PAGE_SIZE==500
    pages=[page_slice(f,p) for p in range(1,11)]
    assert [len(x) for x in pages]==[500]*9+[400]
    pd.testing.assert_frame_equal(pd.concat(pages),f)
    assert page_slice(f.iloc[::-1],2).iloc[0].Ticker=='T4399'
    assert page_slice(f.iloc[:0],1).empty


@pytest.mark.parametrize('period',['1 วัน','3 วัน','5 ปี','10 ปี'])
def test_requested_periods_present(period):assert period in PERIODS


@pytest.mark.parametrize('days',[1,3])
def test_intraday_counts_exchange_sessions_not_calendar_days(days):
    dates=['2026-03-05','2026-03-06','2026-03-09','2026-03-10']
    idx=pd.DatetimeIndex([t for date in dates for t in pd.date_range(date+' 09:30',periods=78,freq='5min',tz='America/New_York')])
    p=range_payload(prices(idx),'TEST',f'{days} วัน','5m')
    assert p['visibleStart']==(4-days)*78
    assert p['interval']=='5m' and p['intraday'] and p['full_window']
    assert p['timezone']=='America/New_York'
    assert p['records'][p['visibleStart']]['time']==int(idx[(4-days)*78].timestamp())


def test_naive_intraday_timezone_is_not_invented():
    with pytest.raises(ValueError):range_payload(prices(pd.date_range('2026-01-01',periods=10,freq='5min')),'TEST','3 วัน','5m')


@pytest.mark.parametrize('years',[5,10])
def test_long_window_and_ipo_coverage_are_honest(years):
    f=prices(pd.bdate_range('2014-01-01','2026-09-10'))
    p=range_payload(f,'TEST',f'{years} ปี','1d')
    assert p['full_window'] and not p['intraday']
    assert p['visibleStart']==int(f.index.searchsorted(f.index[-1]-pd.DateOffset(years=years)))
    ipo=f.iloc[-200:];p=range_payload(ipo,'IPO',f'{years} ปี','1d')
    assert not p['full_window'] and len(p['records'])==200
    assert not covers_years(ipo,years)


def test_tooltips_cover_criteria_and_preserve_column_configs():
    for name in ['ราคา > EMA20 > EMA50','ราคา > SMA200','RSI 14','MACD > Signal','Volume Ratio','ATR / ราคา','Forward P/E','Upside ราคาเป้าหมาย']:
        assert 'ค่าจากชุดข้อมูลที่แสดง' not in field_help(name)
    old={'Close':{'label':'Price','type_config':{'type':'number','format':'%.2f'}},'Ticker':{'help':'existing'}}
    conf=column_help(['Ticker','Close','Return_1D','Return_3M','Volatility_20D'],old)
    assert conf['Close']['type_config']==old['Close']['type_config']
    assert 'help' not in old['Close']
    assert conf['Ticker']['help']=='existing'
    assert all(conf[k].get('help') for k in conf)


def test_html_tooltips_escape_untrusted_values():
    f=pd.DataFrame({'เกณฑ์':['Forward P/E','<script>alert(1)</script>'],'ค่าปัจจุบัน':[20,None]})
    html=table_html(f)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'title=' in html and 'tabindex="0"' in html and '<details' in html
    assert '—' in html and 'กำไร' in html


def test_chart_fetch_isolated_from_scoring_and_reuses_data(tmp_path,monkeypatch):
    cache=a.DashboardCache(tmp_path/'chart.sqlite3');svc=ChartHistoryService(cache);calls=[]
    intra=prices(pd.date_range('2026-03-10 09:30',periods=78,freq='5min',tz='America/New_York'))
    class Provider:
        def history(self,**kwargs):calls.append(kwargs);return intra
    monkeypatch.setattr(a.yf,'Ticker',lambda ticker:Provider())
    svc._fetch('AAPL','5m');restored,meta=svc.read('AAPL','5m')
    assert str(restored.index.tz)=='America/New_York' and restored.index[0]==intra.index[0]
    assert not cache.quotes() and cache.history('AAPL')[0] is None
    assert calls[0]['prepost'] is False and calls[0]['interval']=='5m'
    cache.put('chart:attempt:5m:AAPL',{}, {'next_due':time.time()+900})
    assert svc.request('AAPL','5m')=='' and len(calls)==1


def test_failure_preserves_old_chart_and_backs_off(tmp_path,monkeypatch):
    cache=a.DashboardCache(tmp_path/'failure.sqlite3');svc=ChartHistoryService(cache)
    f=prices(pd.date_range('2026-01-02 09:30',periods=5,freq='5min',tz='America/New_York'))
    cache.put('chart:history:5m:AAPL',f.to_json(orient='split',date_format='iso'),{'timezone':'America/New_York','fetched_at':'2026-01-02T15:00:00Z'})
    def fail(*args):raise RuntimeError('429 rate limit')
    monkeypatch.setattr(svc,'_fetch',fail);monkeypatch.setattr('chart_ranges.time.sleep',lambda seconds:None)
    svc.jobs.extend([('AAPL','5m'),('MSFT','5m')]);svc.pending.update(svc.jobs);svc._run()
    old,meta=svc.read('AAPL','5m')
    assert len(old)==5 and meta['fetched_at']=='2026-01-02T15:00:00Z'
    assert svc.cooldown_until>time.time() and not svc.pending
    assert 'พัก' in svc.request('MSFT','5m')


def test_global_hourly_request_cap(tmp_path):
    svc=ChartHistoryService(a.DashboardCache(tmp_path/'rate.sqlite3'));svc.calls.extend([time.time()]*60)
    assert '60' in svc.request('AAPL','5m') and not svc.pending


def test_long_history_fetch_warmup_and_no_summary_mutation(tmp_path,monkeypatch):
    svc=ChartHistoryService(a.DashboardCache(tmp_path/'long.sqlite3'));calls=[]
    class Provider:
        def history(self,**kwargs):calls.append(kwargs);return prices(pd.bdate_range('2015-01-01','2026-01-02'))
    monkeypatch.setattr(a.yf,'Ticker',lambda ticker:Provider())
    svc._fetch('SPY','long')
    assert 'start' in calls[0] and calls[0]['interval']=='1d'
    f,meta=svc.read('SPY','long')
    assert meta['requested_years']==11 and covers_years(f,10) and not svc.cache.quotes()


def test_chart_range_resize_guard_and_long_zoom():
    assert 'minBarSpacing:.05' in a.core.HTML
    assert 'dataset.rangeFrom' in a.core.HTML
    assert 'const r=chart.timeScale().getVisibleLogicalRange();chart.resize' in a.core.HTML


def test_500_rows_and_four_ranges_without_network(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from unittest.mock import patch
    import chart_ranges
    import dashboard_ui
    cache=a.DashboardCache(tmp_path/'app.sqlite3')
    daily=prices(pd.bdate_range('2014-01-01','2026-09-10'))
    intra=prices(pd.DatetimeIndex([t for d in pd.bdate_range('2026-09-04',periods=5) for t in pd.date_range(str(d.date())+' 09:30',periods=78,freq='5min',tz='America/New_York')]))
    for ticker in ['AAPL','SPY']:
        cache.save_history(ticker,daily,'2026-09-10T20:01:00Z')
        cache.put('chart:history:5m:'+ticker,intra.to_json(orient='split',date_format='iso'),{'timezone':'America/New_York'})
    svc=ChartHistoryService(cache)
    monkeypatch.setattr(chart_ranges,'get_chart_service',lambda:svc)
    monkeypatch.setattr(dashboard_ui,'get_chart_service',lambda:svc)
    monkeypatch.setenv('DASHBOARD_ALLOW_CHART_REQUESTS','false')
    class Reader:
        def refresh(self,force=False):pass
        def request(self,ticker):pass
        def status(self):return {'busy':False,'revision':0,'manifest':{}}
    with patch.object(a,'get_data_cache',return_value=cache),patch.object(a.core,'get_data_cache',return_value=cache),patch.object(a,'get_remote_reader',return_value=(Reader(),'')),patch.object(a,'get_updater',return_value=a.ReadOnlyUpdater()),patch.object(a.yf,'Ticker',side_effect=AssertionError('no network')):
        at=AppTest.from_string('from dashboard_ui import main\nmain()',default_timeout=40).run()
        assert not at.exception,str(at.exception)
        assert len(at.dataframe[0].value)==500
        for period in ['1 วัน','3 วัน','5 ปี','10 ปี']:
            at.radio(key='chart_period').set_value(period).run()
            assert not at.exception,str(at.exception)
            assert not any('ยังไม่มีประวัติจริงสำหรับช่วงที่เลือก' in item.value for item in at.info)
        assert len(at.sidebar.radio)==0
