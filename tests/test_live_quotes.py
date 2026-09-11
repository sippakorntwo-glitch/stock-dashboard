"""Isolated regressions; never call a live provider in these tests."""
import threading
import time
from collections import deque
import numpy as np
import pandas as pd
import pytest
from live_quotes import QuoteService, positive, polling_interval

@pytest.mark.parametrize('value',[None,True,False,0,-1,float('nan'),float('inf'),'bad'])
def test_bad_quote_prices_are_not_displayable(value):
    assert positive(value) is None

def test_quote_polling_windows_are_budgets_not_market_open_claims():
    assert polling_interval('2026-09-11T18:00:00Z') == 60
    assert polling_interval('2026-09-12T18:00:00Z') == 1800
    assert polling_interval('2026-09-11T05:00:00Z') == 1800

def test_single_worker_coalesces_requests_and_preserves_ttl(monkeypatch):
    now = pd.Timestamp('2026-09-11T18:00:00Z').timestamp()
    gate=threading.Event();calls=[]
    def fetch(ticker):
        calls.append(ticker);gate.wait(3)
        return {'ticker':ticker,'price':100.0,'bar_time':'2026-09-11T17:59:00Z'}
    service=QuoteService(fetch,lambda:now)
    assert service.request('AAPL')
    for _ in range(20):assert not service.request('AAPL')
    gate.set()
    deadline=time.time()+4
    while service.read('AAPL')[2] and time.time()<deadline:time.sleep(.01)
    assert calls == ['AAPL']
    assert service.read('AAPL')[0]['price'] == 100
    assert not service.request('AAPL')
    assert not service.request('../secrets')

def test_rate_limit_retains_last_good_and_opens_circuit(monkeypatch):
    monkeypatch.setattr('live_quotes.time.sleep',lambda _:None)
    def fail(_):raise RuntimeError('429 Too Many Requests')
    service=QuoteService(fail,lambda:10000)
    service.values['AAPL']={'ticker':'AAPL','price':101}
    service.pending.add('AAPL');service.jobs.append('AAPL');service._run()
    assert service.read('AAPL')[0]['price']==101
    assert service.cooldown_until==10900
    assert not service.request('MSFT')
    assert service.read('AAPL')[1]['error']

def test_hourly_ceiling_prevents_unbounded_new_ticker_requests():
    service=QuoteService(clock=lambda:10000)
    service.calls=deque([9999]*120)
    assert not service.request('QQQI')

def test_mismatched_response_cannot_replace_selected_symbol(monkeypatch):
    monkeypatch.setattr('live_quotes.time.sleep',lambda _:None)
    service=QuoteService(lambda _: {'ticker':'OTHER','price':500},lambda:10000)
    service.pending.add('QQQI');service.jobs.append('QQQI');service._run()
    assert service.read('QQQI')[0] is None
    assert service.read('QQQI')[1]['error']

def test_return_audit_survives_actual_cache_to_frame_to_annualized_display(tmp_path):
    import dashboard_runtime as a
    from return_periods import display_returns, RETURN_MODES
    c=np.linspace(100,200,1700)
    h=pd.DataFrame({'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':1000},index=pd.bdate_range(end='2026-09-09',periods=len(c)))
    cache=a.DashboardCache(tmp_path/'audit.sqlite3')
    cache.save_history('AAPL',h,'2026-09-10T10:00:00Z',years=6)
    saved=cache.quotes();assert isinstance(saved['AAPL']['Return_Observations'],dict)
    frame,_=a.build_universe_frame(pd.DataFrame({'Ticker':['AAPL']}),saved)
    row=frame.set_index('Ticker').loc['AAPL']
    assert isinstance(row['Return_Observations'],dict)
    displayed=display_returns(frame,RETURN_MODES[1]).set_index('Ticker').loc['AAPL']
    assert displayed.Return_5Y==pytest.approx(row['Return_Observations']['Return_5Y']['annualized'])

def test_recalculation_does_not_promote_source_days_partial_candle():
    import dashboard_runtime as a
    c=np.linspace(100,120,300)
    h=pd.DataFrame({'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':1000},index=pd.bdate_range(end='2026-09-09',periods=len(c)))
    row=a.scan_snapshot_row('AAPL',h,'2026-09-09T17:00:00Z')
    assert row['Price_AsOf']=='2026-09-08'

def test_theme_keeps_controls_visible_and_upload_budget():
    from pathlib import Path
    import tomllib
    from workspace_theme import CSS
    assert 'workspace-theme-v22' in CSS and 'focus-visible' in CSS
    assert 'display:none' not in CSS and 'visibility:hidden' not in CSS
    settings=tomllib.loads(Path('.streamlit/config.toml').read_text())
    assert settings['server']['maxUploadSize']==5
    assert settings['browser']['gatherUsageStats'] is False
