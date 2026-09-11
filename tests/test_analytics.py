import math
import numpy as np
import pandas as pd
import pytest
from analytics import risk_metrics,period_return,extended_snapshot,comparison,beta_to_benchmark,quality_counts
import dashboard_runtime as runtime

def frame(prices,end='2026-09-09'):
    c=np.asarray(prices,dtype=float)
    return pd.DataFrame({'Close':c,'Open':c,'High':c+1,'Low':c-1,'Volume':1000.},index=pd.bdate_range(end=end,periods=len(c)))

def test_reference_drawdown():
    r=risk_metrics(frame([100,120,90,110]))
    assert r['max_drawdown_pct']==pytest.approx(-25)
    assert r['return_pct']==pytest.approx(10)
    assert r['cagr_pct'] is None and r['volatility_pct'] is None

def test_cagr_and_volatility():
    f=frame(np.geomspace(100,120,400));r=risk_metrics(f);days=(f.index[-1]-f.index[0]).days
    assert r['cagr_pct']==pytest.approx((1.2**(365.25/days)-1)*100)
    assert r['volatility_pct']<1e-10

def test_short_history_missing_not_zero():
    f=frame([100,101,102]);assert period_return(f.Close,36) is None
    assert extended_snapshot(f)['Drawdown_52W'] is None

def test_shared_dates_no_forward_fill():
    f=frame([100,101,105,102,110]);g=f.drop(f.index[2]);r=comparison({'A':f,'B':g},12)
    assert len(r['prices'])==4 and not r['full_window'] and r['correlation'].empty

def test_beta_minimum_sample_and_variance():
    f=frame(np.linspace(100,180,100));p=pd.DataFrame({'A':f.Close,'SPY':f.Close})
    assert beta_to_benchmark(p,'A')==pytest.approx(1)
    p['SPY']=100;assert beta_to_benchmark(p,'A') is None

def test_quality_unknown_future_and_old():
    f=pd.DataFrame({'Close':[100,100,100,100,None],'Price_AsOf':['2026-09-09','','2026-08-01','2026-10-01','']})
    assert quality_counts(f,now='2026-09-10')=={'total':5,'priced':4,'recent':1,'unknown_time':1,'old_or_future':2}

def test_new_missing_indicator_clears_csv(tmp_path):
    cache=runtime.DashboardCache(tmp_path/'test.sqlite3')
    row=runtime.scan_snapshot_row('AAPL',frame([100,101,102]),'2026-09-10T10:00:00Z')
    cache.save_quotes(pd.DataFrame([row]))
    csv=runtime.parse_watchlist(b'Ticker,RSI_14,Close\nAAPL,75,90\n')
    f,_=runtime.build_universe_frame(csv,cache.quotes())
    assert pd.isna(f.set_index('Ticker').loc['AAPL','RSI_14'])

def test_empty_industry_preserves_previous(tmp_path):
    cache=runtime.DashboardCache(tmp_path/'test.sqlite3')
    cache.save_classification('AAPL',{'industry':'Technology','_Fetched_At_UTC':'2026-09-09T00:00:00Z'})
    cache.save_classification('AAPL',{'industry':None,'_Fetched_At_UTC':'2026-09-10T00:00:00Z'})
    assert cache.classifications()['AAPL']['Industry']=='Technology'

def test_readonly_worker(monkeypatch):
    monkeypatch.setattr(runtime,'get_remote_reader',lambda:(None,''))
    worker=runtime.ReadOnlyUpdater();assert not worker.request('AAPL')
    assert not worker.start_scan(['AAPL']) and not worker.state()['busy']

def test_snapshot_extended_fields():
    row=runtime.scan_snapshot_row('AAPL',frame(np.linspace(100,200,400)),'2026-09-10T10:00:00Z')
    for key in ['Return_1D','Return_3M','Volatility_20D','Dollar_Volume_20D','Drawdown_52W','ATR_Pct']:
        assert math.isfinite(row[key])
    assert row['Price_AsOf']=='2026-09-09' and row['Metric_Calc_Version']==runtime.METRIC_VERSION


def test_new_metric_version_requires_backfill(tmp_path):
    from update_data import history_missing
    cache=runtime.DashboardCache(tmp_path/'migration.sqlite3')
    cache.save_history('AAPL',frame(np.linspace(100,200,400)),'2026-09-10T00:00:00Z',years=runtime.HISTORY_YEARS)
    row=cache.quotes()['AAPL']
    assert not history_missing(row)
    row.pop('Metric_Calc_Version')
    assert history_missing(row)


def test_bootstrap_detects_old_metric_version():
    from update_data import pending_bootstrap
    row = {"History_Years_Loaded": runtime.HISTORY_YEARS, "Return_Calc_Version": runtime.RETURN_CALC_VERSION,
           "Close": 123.45, "Metric_Calc_Version": runtime.METRIC_VERSION}
    metadata = {"info:AAPL": {}, "dividends:AAPL": {}}
    assert pending_bootstrap(("AAPL",), {"AAPL": row}, metadata) == (0, None)
    row.pop("Metric_Calc_Version")
    pending, due = pending_bootstrap(("AAPL",), {"AAPL": row}, metadata)
    assert pending == 1 and due == 0


def test_history_missing_uses_shared_metric_version(monkeypatch):
    from update_data import history_missing
    row = {"History_Years_Loaded": runtime.HISTORY_YEARS, "Return_Calc_Version": runtime.RETURN_CALC_VERSION,
           "Close": 123.45, "Metric_Calc_Version": runtime.METRIC_VERSION}
    assert not history_missing(row)
    monkeypatch.setattr(runtime, "METRIC_VERSION", runtime.METRIC_VERSION + 1)
    assert history_missing(row)
