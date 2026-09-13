"""Deterministic source/session/budget boundaries; no live requests."""
from collections import deque
import os
from types import SimpleNamespace
import pandas as pd
import pytest
from live_quotes import QuoteService, polling_interval, quote_session, session_periods

NOW = pd.Timestamp('2026-09-11T14:00:00Z').timestamp()

def observation(ticker='AAPL', when='2026-09-11T14:00:00Z', price=100):
    return {'ticker':ticker,'price':price,'bar_time':when,'currency':'USD',
            'fetched_at':when, 'session_periods':{'regular':{
                'start':'2026-09-11T13:30:00Z','end':'2026-09-11T20:00:00Z'}}}

def run_once(service,ticker='AAPL'):
    service.pending.add(ticker);service.jobs.append(ticker);service._run()

def test_fast_cadence_requires_provider_session_and_early_close_is_respected():
    value=observation()
    assert polling_interval('2026-09-11T14:00:00Z',value,30)==30
    assert polling_interval('2026-09-11T14:00:00Z',value,120)==120
    value['session_periods']['regular']['end']='2026-09-11T17:00:00Z'
    assert quote_session(value,'2026-09-11T17:01:00Z')=='closed'
    assert polling_interval('2026-09-11T17:01:00Z',value,30)==1800
    # A future session on a holiday never becomes active from weekday arithmetic.
    value['session_periods']['regular']={'start':'2026-09-08T13:30:00Z','end':'2026-09-08T20:00:00Z'}
    assert quote_session(value,'2026-09-07T15:00:00Z')=='closed'
    assert polling_interval('2026-09-07T15:00:00Z',value)==1800

def test_next_session_due_does_not_move_backwards_with_each_read():
    clock=[pd.Timestamp('2026-09-11T07:50:00Z').timestamp()]
    service=QuoteService(clock=lambda:clock[0])
    value=observation(when='2026-09-10T19:59:00Z')
    value['session_periods']['pre']={'start':'2026-09-11T08:00:00Z','end':'2026-09-11T13:30:00Z'}
    service.values['AAPL']=value
    service.attempts['AAPL']={'attempted_at':clock[0],'error':'','next_due':clock[0]+600}
    expected=clock[0]+600
    assert service.read('AAPL')[1]['next_due']==expected
    clock[0]+=300
    assert service.read('AAPL')[1]['next_due']==expected
    assert not service.request('AAPL')

def test_stale_success_cannot_replace_newer_quote_and_same_bar_may_update(monkeypatch):
    monkeypatch.setattr('live_quotes.time.sleep',lambda _:None)
    service=QuoteService(lambda _:observation(when='2026-09-11T13:59:00Z',price=1),lambda:NOW)
    service.values['AAPL']=observation(price=100)
    run_once(service)
    assert service.values['AAPL']['price']==100
    assert service.values['AAPL']['fetched_at']=='2026-09-11T14:00:00Z'
    assert service.read('AAPL')[1]['status']=='retry'
    service.fetcher=lambda _:observation(price=101)
    run_once(service)
    assert service.values['AAPL']['price']==101
    assert service.read('AAPL')[1]['error']==''

@pytest.mark.parametrize('when',['2026-09-11T14:00:00','2026-09-12T14:00:00Z',None])
def test_bad_or_future_source_timestamp_retains_last_good(monkeypatch,when):
    monkeypatch.setattr('live_quotes.time.sleep',lambda _:None)
    service=QuoteService(lambda _:observation(when=when,price=1),lambda:NOW)
    service.values['AAPL']=observation()
    run_once(service)
    assert service.values['AAPL']['price']==100
    assert service.read('AAPL')[1]['error']

def test_rate_limit_delay_is_honored_across_symbols_and_faster_controls(monkeypatch):
    monkeypatch.setattr('live_quotes.time.sleep',lambda _:None)
    exc=RuntimeError('429 Too Many Requests')
    exc.response=SimpleNamespace(headers={'Retry-After':'7200'})
    def fail(_):raise exc
    service=QuoteService(fail,lambda:NOW)
    run_once(service)
    assert service.cooldown_until==NOW+7200
    assert not service.request('AAPL',30) and not service.request('MSFT',30)
    assert service.read('MSFT')[1]['status']=='rate_limited'
    assert service.read('MSFT')[1]['next_due']==NOW+7200

def test_budget_pause_is_visible_and_expires_without_bypassing_limit():
    clock=[NOW]
    service=QuoteService(clock=lambda:clock[0]);service.calls=deque([NOW-3590]*120)
    assert not service.request('AAPL')
    assert service.read('AAPL')[1]['status']=='budget'
    assert service.read('AAPL')[1]['next_due']==NOW+10
    clock[0]+=11
    assert service.read('AAPL')[1]['status']=='scheduled'

def test_metadata_epoch_is_normalized_without_naive_or_invalid_windows():
    result=session_periods({'currentTradingPeriod':{
        'regular':{'start':NOW,'end':NOW+3600},
        'pre':{'start':'2026-09-11T07:00:00','end':'2026-09-11T08:00:00'},
        'post':{'start':NOW+10,'end':NOW}}})
    assert list(result)==['regular']
    assert result['regular']['start']=='2026-09-11T14:00:00+00:00'


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1', reason='Requires real Streamlit')
def test_visible_cadence_controls_preserve_requested_interval_and_pause(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import live_quote_ui

    class QuoteFixture:
        def __init__(self):
            self.requests=[]
        def request(self,ticker,interval):
            self.requests.append((ticker,interval))
        def read(self,ticker,interval):
            return observation(ticker), {'status':'scheduled','next_due':0}, False

    service=QuoteFixture()
    monkeypatch.setattr(live_quote_ui,'quote_service',lambda _:service)
    monkeypatch.setattr(live_quote_ui,'enabled',lambda:True)
    app=AppTest.from_string('''
import streamlit as st
from live_quote_ui import render_live_quote
st.session_state.setdefault('selected_ticker','AAPL')
render_live_quote('AAPL')
''').run()

    def status():
        assert not app.exception,str(app.exception)
        return next(item.value for item in app.markdown if 'quote-refresh-status' in item.value)

    interval=app.radio(key='minute_price_interval')
    assert interval.label=='รอบขอราคา' and interval.options==['30 วินาที','60 วินาที','120 วินาที']
    assert not app.selectbox and interval.value==30
    assert service.requests==[('AAPL',30)]
    app.radio(key='minute_price_interval').set_value(60).run()
    assert 'data-requested-seconds="60"' in status() and service.requests[-1]==('AAPL',60)
    app.checkbox(key='minute_price_auto').uncheck().run()
    assert 'data-state="paused"' in status()
    paused_requests=list(service.requests)
    app.radio(key='minute_price_interval').set_value(30).run()
    assert 'data-requested-seconds="30"' in status() and 'data-state="paused"' in status()
    assert service.requests==paused_requests
    app.checkbox(key='minute_price_auto').check().run()
    assert 'data-state="scheduled"' in status() and service.requests[-1]==('AAPL',30)
    assert len(service.requests)==len(paused_requests)+1
    assert app.session_state['selected_ticker']=='AAPL'
