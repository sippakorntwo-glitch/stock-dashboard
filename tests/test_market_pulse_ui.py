"""Real Streamlit renders for the Top 10 overlay; no provider is contacted."""
from copy import deepcopy
import os

import pandas as pd
import pytest

from market_pulse import normalize_news, normalize_quotes

pytestmark = pytest.mark.skipif(
    os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1',
    reason='Requires actual Streamlit AppTest',
)


SCRIPT = '''
import streamlit as st
from market_pulse_ui import render_pulse_header, render_pulse_method
from ranking_board import pick_buttons, split_entries
payload = st.session_state['_pulse_fixture_payload']
state = render_pulse_header(payload)
entries, watch = split_entries(payload)
st.caption('Entry fixture count: '+str(len(entries)))
pick_buttons(entries, True, payload=payload, pulse=state)
pick_buttons(watch, False, payload=payload, pulse=state)
render_pulse_method()
st.text_input('Independent search', key='_pulse_independent_search')
'''


class CachedService:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.requests = []
        self.reads = 0

    def request(self, symbols, *, news_symbols):
        self.requests.append((list(symbols), list(news_symbols)))
        return True

    def read(self):
        self.reads += 1
        return deepcopy(self.state)


def fixtures():
    now = pd.Timestamp.now(tz='UTC')
    observed = now-pd.Timedelta(seconds=30)
    row = {'ticker':'TEST', 'name':'UNIT TEST FIXTURE', 'score':100, 'coverage':100,
           'qualified':True, 'ready_at_calculation':False, 'stop':100, 'target':112,
           'rsi':55, 'reasons':[], 'blockers':['Strict entry policy not passed']}
    payload = {'computed_at':now.isoformat(), 'items':[row]}
    raw = [{'symbol':ticker, 'marketState':'REGULAR', 'currency':'USD',
            'regularMarketPrice':103 if ticker == 'TEST' else 101,
            'regularMarketPreviousClose':100, 'regularMarketTime':observed.timestamp(),
            'regularMarketVolume':1800, 'averageDailyVolume3Month':1000,
            'exchangeDataDelayedBy':0} for ticker in ('TEST', 'SPY', 'QQQ')]
    quotes = normalize_quotes(raw, ['TEST', 'SPY', 'QQQ'], now)
    news = normalize_news([{'content':{
        'title':'Fixture company releases update', 'provider':{'displayName':'Fixture News'},
        'canonicalUrl':{'url':'https://news.example.com/fixture-company'},
        'pubDate':(now-pd.Timedelta(hours=1)).isoformat(),
    }}], 'TEST', now-pd.Timedelta(seconds=10))
    state = {'quotes':quotes, 'news':{'TEST':news}, 'quote_status':{}, 'news_status':{},
             'status':'ready', 'busy':False, 'checked_at':now.isoformat(), 'error':''}
    return payload, state


def run_app(monkeypatch, payload, state, *, active=True):
    from streamlit.testing.v1 import AppTest
    import market_pulse_ui as ui
    monkeypatch.setenv('DASHBOARD_ALLOW_CHART_REQUESTS', 'true')
    monkeypatch.setenv('DASHBOARD_ALLOW_MARKET_PULSE', 'true' if active else 'false')
    service = CachedService(state)
    monkeypatch.setattr(ui, 'pulse_service', lambda version:service)
    # A wiring regression must fail the test rather than contacting a provider.
    monkeypatch.setattr(ui.a.yf, 'Ticker', lambda *args, **kwargs:pytest.fail('Unexpected live provider'))
    at = AppTest.from_string(SCRIPT, default_timeout=8)
    at.session_state['_pulse_fixture_payload'] = deepcopy(payload)
    at.run()
    assert not at.exception, str(at.exception)
    return at, service


def candidate_markup(at):
    return next(element.value for element in at.markdown
                if 'class="ranking-pulse-candidate"' in element.value)


def status_markup(at):
    return next(element.value for element in at.markdown
                if 'class="ranking-pulse-status"' in element.value)


def captions(at):
    return [element.value for element in at.caption]


def test_real_overlay_uses_source_clocks_and_keeps_strong_momentum_separate_from_entry(monkeypatch):
    import dashboard_runtime as a
    payload, state = fixtures()
    original = deepcopy((payload, state))
    at, service = run_app(monkeypatch, payload, state)
    assert service.requests == [(['TEST', 'SPY', 'QQQ'], ['TEST'])]
    assert 'data-refresh-seconds="30"' in status_markup(at)
    markup = candidate_markup(at)
    assert 'data-state="strong"' in markup and 'data-entry-independent="true"' in markup
    assert 'data-quote-time="'+state['quotes']['TEST']['quote_time']+'"' in markup
    assert 'Entry fixture count: 0' in captions(at)
    assert 'เฝ้าดู ไม่ใช่จุดซื้อ' in at.button(key='ranking_pick_TEST').label
    assert '100/100' in at.button(key='ranking_pick_TEST').label
    assert any(text.startswith('ราคาต้นทาง: '+a.thai_time(state['quotes']['TEST']['quote_time'])) for text in captions(at))
    assert 'ตรวจชุดราคาสำเร็จ: '+a.thai_time(state['checked_at']) in captions(at)
    assert 'ตรวจข่าวสำเร็จ: '+a.thai_time(state['news']['TEST']['checked_at']) in captions(at)
    article = state['news']['TEST']['items'][0]
    assert article['publisher']+' · เผยแพร่ '+a.thai_time(article['published_at']) in captions(at)
    links = at.get('link_button')
    assert len(links) == 1 and links[0].proto.url == article['url']
    assert (payload, state) == original


def test_pause_stops_new_requests_and_retains_prices_and_independent_filter(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state)
    at.checkbox(key='ranking_pulse_auto').uncheck().run()
    assert not at.exception, str(at.exception)
    assert len(service.requests) == 1 and service.reads == 2
    assert 'data-state="paused"' in status_markup(at)
    assert 'data-quote-time="'+state['quotes']['TEST']['quote_time']+'"' in candidate_markup(at)
    at.text_input(key='_pulse_independent_search').set_value('KEEP-MY-FILTER').run()
    at.button(key='ranking_pick_TEST').click().run()
    assert not at.exception, str(at.exception)
    assert len(service.requests) == 1
    assert at.session_state['selected_ticker'] == 'TEST'
    assert at.text_input(key='_pulse_independent_search').value == 'KEEP-MY-FILTER'
    assert at.checkbox(key='ranking_pulse_auto').value is False


@pytest.mark.parametrize('kind', ['stale', 'future', 'delayed'])
def test_stale_future_and_declared_delayed_quotes_are_visible_without_live_strength_claims(monkeypatch, kind):
    import dashboard_runtime as a
    payload, state = fixtures()
    now = pd.Timestamp.now(tz='UTC')
    for quote in state['quotes'].values():
        if kind == 'stale':
            quote['quote_time'] = (now-pd.Timedelta(minutes=10)).isoformat()
        elif kind == 'future':
            quote['quote_time'] = (now+pd.Timedelta(seconds=30)).isoformat()
        else:
            quote['delay_minutes'] = 15
    at, _ = run_app(monkeypatch, payload, state)
    assert 'data-state="unknown"' in candidate_markup(at)
    assert any(text.startswith('ราคาต้นทาง: '+a.thai_time(state['quotes']['TEST']['quote_time'])) for text in captions(at))
    reference = next(text for text in captions(at) if text.startswith('ตลาดอ้างอิง:'))
    if kind != 'delayed':
        assert 'อายุราคาไม่เกิน 3 นาที' not in reference
    else:
        assert 'ต้นทางระบุหน่วง 15.00 นาที' in reference
    assert 'เฝ้าดู ไม่ใช่จุดซื้อ' in at.button(key='ranking_pick_TEST').label
    if kind == 'delayed':
        assert any('ล่าช้า 15 นาที' in text for text in captions(at))


def test_missing_volume_and_news_stay_unknown_not_zero_or_positive(monkeypatch):
    payload, state = fixtures()
    state['quotes']['TEST']['volume'] = None
    state['quotes']['TEST']['average_volume'] = None
    state['news'] = {}
    at, _ = run_app(monkeypatch, payload, state)
    assert 'data-state="unknown"' in candidate_markup(at)
    volume = next(text for text in captions(at) if 'ปริมาณเทียบค่าเฉลี่ยเต็มวัน:' in text)
    assert 'ปริมาณเทียบค่าเฉลี่ยเต็มวัน: —' in volume and '0.00 เท่า' not in volume
    assert not at.get('link_button')
    assert any('ยังไม่มีข่าวที่อ่านและตรวจวันเผยแพร่ได้' in text for text in captions(at))
    assert not any('ข่าวที่ต้นทางเชื่อมโยงใน 24 ชั่วโมง:' in text for text in captions(at))


def test_disabled_source_never_requests_service_or_displays_fixture_as_live(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state, active=False)
    assert not service.requests and service.reads == 0
    assert at.checkbox(key='ranking_pulse_auto').disabled
    assert 'data-state="disabled"' in status_markup(at)
    assert 'data-state="unknown"' in candidate_markup(at)
    assert 'ยังไม่มีราคาล่าสุดที่ตรวจสอบได้ของ TEST' in captions(at)


def test_failed_refresh_preserves_visible_source_time_and_announces_backoff(monkeypatch):
    import dashboard_runtime as a
    payload, state = fixtures()
    state.update(status='rate_limited', error='ผู้ให้ข้อมูลจำกัดคำขอ — คงข้อมูลเดิมไว้',
                 next_due=(pd.Timestamp.now(tz='UTC')+pd.Timedelta(minutes=15)).timestamp())
    at, _ = run_app(monkeypatch, payload, state)
    assert 'data-state="rate_limited"' in status_markup(at)
    assert state['error'] in captions(at)
    assert any(text.startswith('ตรวจได้อีกครั้ง:') for text in captions(at))
    assert any(text.startswith('ราคาต้นทาง: '+a.thai_time(state['quotes']['TEST']['quote_time'])) for text in captions(at))
    assert 'data-quote-time="'+state['quotes']['TEST']['quote_time']+'"' in candidate_markup(at)
