"""Selected-stock briefing renders real Streamlit widgets without network calls."""
from copy import deepcopy
import json
import os

import pandas as pd
import pytest

from stock_news_analysis import normalize_stock_news

pytestmark = pytest.mark.skipif(
    os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1',
    reason='Requires actual Streamlit AppTest',
)

SCRIPT = '''
import streamlit as st
from stock_brief_ui import render_stock_brief
payload = st.session_state['_brief_payload']
render_stock_brief(payload, info={'quoteType':'ETF' if st.session_state['_brief_etf'] else 'EQUITY'},
                   is_etf=st.session_state['_brief_etf'])
st.text_input('Independent chart search', key='_brief_search')
'''


class CachedBrief:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.requests = []
        self.reads = []

    def request(self, ticker):
        self.requests.append(ticker)
        return True

    def read(self, ticker):
        self.reads.append(ticker)
        return deepcopy(self.state)


def fixtures():
    now = pd.Timestamp.now(tz='UTC')
    records = []
    for index in range(230):
        close = 100.0 + index
        day = (now.normalize()-pd.Timedelta(days=230-index)).date().isoformat()
        records.append({'time':day, 'open':close-.5, 'high':close+2, 'low':close-2,
                        'close':close, 'volume':1000, 'ema20':close-4 if index>=19 else None,
                        'ema50':close-8 if index>=49 else None, 'sma200':close-20 if index>=199 else None,
                        'rsi':60, 'macd':2., 'signal':1., 'hist':1.})
    payload = {'ticker':'SCHD', 'period':'1 ปี', 'interval':'1d', 'timezone':'UTC', 'precision':2,
               'visibleStart':160, 'records':records, 'fetchedAt':now.isoformat(), 'demo':False,
               'full_window':True}
    regular = {'ticker':'SCHD', 'price':33.28, 'change_pct':-.58, 'change_abs':-.19, 'previous_close':33.47,
               'quote_time':(now-pd.Timedelta(minutes=30)).isoformat(),
               'session':'regular', 'market_state':'POST', 'currency':'USD', 'delay_minutes':0}
    extended = {'ticker':'SCHD', 'price':33.29, 'change_pct':(33.29/33.28-1)*100, 'change_abs':.01, 'previous_close':33.28,
                'basis_time':regular['quote_time'],
                'quote_time':(now-pd.Timedelta(seconds=20)).isoformat(),
                'session':'post', 'market_state':'POST', 'currency':'USD', 'delay_minutes':0}
    news = normalize_stock_news([{'content':{
        'title':'Should You Invest in SCHD for Dividend Income?', 'provider':{'displayName':'Fixture News'},
        'canonicalUrl':{'url':'https://news.example.com/fund-reading'},
        'pubDate':(now-pd.Timedelta(hours=1)).isoformat(),
        'summary':'The author discusses fund distributions and portfolio holdings.'}}, {'content':{
        'title':'Fund announces holdings update', 'provider':{'displayName':'Fixture News'},
        'canonicalUrl':{'url':'https://news.example.com/fund-holdings'},
        'pubDate':(now-pd.Timedelta(days=2)).isoformat(),
    }}], 'SCHD', now-pd.Timedelta(seconds=10))
    state = {'ticker':'SCHD', 'regular':regular, 'extended':extended, 'news':news,
             'status':'ready', 'busy':False, 'error':'', 'quote_checked_at':now.isoformat()}
    return payload, state


def run_app(monkeypatch, payload, state, *, active=True, is_etf=True, selected='SCHD'):
    from streamlit.testing.v1 import AppTest
    import stock_brief_ui as ui
    monkeypatch.setenv('DASHBOARD_ALLOW_CHART_REQUESTS', 'true')
    monkeypatch.setenv('DASHBOARD_ALLOW_STOCK_BRIEF', 'true' if active else 'false')
    service = CachedBrief(state)
    monkeypatch.setattr(ui, 'brief_service', lambda version:service)
    monkeypatch.setattr(ui.a.yf, 'Ticker', lambda *args, **kwargs:pytest.fail('Unexpected live provider'))
    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.session_state['_brief_payload'] = deepcopy(payload)
    at.session_state['_brief_etf'] = is_etf
    at.session_state['selected_ticker'] = selected
    at.session_state['chart_period'] = '1 ปี'
    at.session_state['_chart_indicator_preference'] = {'rsi':True, 'ema20':False}
    at.run()
    assert not at.exception, str(at.exception)
    return at, service


def captions(at):
    return [value.value for value in at.caption]


def receipt(at):
    return next(value.value for value in at.markdown if 'class="stock-brief-receipt"' in value.value)


def quotes(at):
    return [value.value for value in at.markdown if 'class="brief-quote"' in value.value]


def test_regular_extended_prices_and_changes_have_separate_source_clocks_and_bases(monkeypatch):
    import dashboard_runtime as a
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state)
    assert service.requests == service.reads == ['SCHD']
    assert [metric.value for metric in at.metric] == ['33.28', '33.29']
    assert [metric.delta for metric in at.metric] == ['-0.58%', '+0.03%']
    assert 'ตลาดปกติ · USD' == at.metric[0].label
    assert 'หลังปิดตลาด (After-hours) · USD' == at.metric[1].label
    assert 'ครั้งก่อน' in at.metric[0].help and 'นอกเวลา' in at.metric[1].help
    assert 'ราคาปิดครั้งก่อน: 33.47 USD' in captions(at)
    assert 'ราคาปิดตลาดปกติที่ใช้เทียบ: 33.28 USD' in captions(at)
    assert 'เปลี่ยนแปลง -0.19 USD' in captions(at) and 'เปลี่ยนแปลง +0.01 USD' in captions(at)
    assert 'เวลาราคาตลาดปกติที่ใช้เทียบ: '+a.thai_time(state['extended']['basis_time']) in captions(at)
    for quote, markup in zip((state['regular'], state['extended']), quotes(at)):
        assert 'data-quote-time="'+quote['quote_time']+'"' in markup
        assert any(value.startswith('เวลาราคาต้นทาง: '+a.thai_time(quote['quote_time'])) for value in captions(at))
    assert 'data-state="stale"' in quotes(at)[0]
    assert 'data-state="recent"' in quotes(at)[1]
    assert 'data-chart-period="1 ปี"' in receipt(at)
    assert 'data-quote-seconds="60"' in receipt(at) and 'data-news-seconds="300"' in receipt(at)


def test_sources_excerpt_and_conditional_etf_context_never_claim_confirmed_positive_news(monkeypatch):
    import dashboard_runtime as a
    payload, state = fixtures()
    original = deepcopy((payload, state))
    at, _ = run_app(monkeypatch, payload, state)
    article = state['news']['items'][0]
    assert 'ตรวจข่าวสำเร็จ: '+a.thai_time(state['news']['checked_at']) in captions(at)
    assert 'Fixture News · เผยแพร่ '+a.thai_time(article['published_at']) in captions(at)
    text = '\n'.join(value.value for value in at.markdown)
    assert 'The author discusses fund distributions and portfolio holdings' in text
    assert 'เงินจ่ายต่อหน่วย' in text and 'ผู้จัดการกองทุน' in text
    assert any('บทความความเห็น / บทวิเคราะห์' in value for value in captions(at))
    assert any('ยังไม่ยืนยันจากข้อมูลข่าวที่มี' in value for value in captions(at))
    assert any('ภายใน 24 ชั่วโมง 1 รายการ · เก่ากว่า 24 ชั่วโมงถึง 7 วัน 1 รายการ' in value for value in captions(at))
    links = at.get('link_button')
    assert [value.proto.url for value in links] == [value['url'] for value in state['news']['items']]
    assert not any(value in text for value in ('22.89%', 'เชิงบวก (หนุนราคา)', '9%'))
    assert (payload, state) == original


def test_receipts_keep_original_times_through_ui_rerun_and_do_not_mutate_chart(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state)
    before = json.dumps(at.session_state['_brief_payload'], sort_keys=True)
    source_quotes = quotes(at)
    at.text_input(key='_brief_search').set_value('KEEP-THIS-FILTER').run()
    assert not at.exception, str(at.exception)
    assert service.requests == ['SCHD', 'SCHD']
    assert quotes(at) == source_quotes
    assert at.text_input(key='_brief_search').value == 'KEEP-THIS-FILTER'
    assert at.session_state['chart_period'] == '1 ปี'
    assert at.session_state['_chart_indicator_preference'] == {'rsi':True, 'ema20':False}
    assert json.dumps(at.session_state['_brief_payload'], sort_keys=True) == before
    assert state['news']['checked_at'] in receipt(at)


@pytest.mark.parametrize('kind', ['stale', 'future', 'delayed', 'missing_time'])
def test_problem_quote_clocks_are_visible_without_promoting_to_recent(monkeypatch, kind):
    payload, state = fixtures()
    now = pd.Timestamp.now(tz='UTC')
    if kind == 'stale':
        state['extended']['quote_time'] = (now-pd.Timedelta(minutes=20)).isoformat()
    elif kind == 'future':
        state['extended']['quote_time'] = (now+pd.Timedelta(minutes=10)).isoformat()
    elif kind == 'delayed':
        state['extended']['delay_minutes'] = 15
    else:
        state['extended']['quote_time'] = None
    at, _ = run_app(monkeypatch, payload, state)
    assert 'data-state="recent"' not in quotes(at)[1]
    assert at.metric[1].value == '33.29'
    assert any('ล่าช้า' in value or 'ยืนยันเวลา' in value or 'อนาคต' in value for value in captions(at))
    if kind == 'delayed':
        assert 'ต้นทางระบุหน่วง 15.00 นาที' in captions(at)


def test_stale_feed_keeps_publication_date_and_does_not_synthesize_missing_summary(monkeypatch):
    payload, state = fixtures()
    state['news']['checked_at'] = (pd.Timestamp.now(tz='UTC')-pd.Timedelta(minutes=20)).isoformat()
    for article in state['news']['items']:
        article['source_excerpt'] = ''
        article['body_state'] = 'missing'
    at, _ = run_app(monkeypatch, payload, state)
    assert any('ผลการตรวจข่าวเก่าแล้ว' in value for value in captions(at))
    assert sum('ต้นทางไม่ได้ส่งเนื้อหาย่อ' in value for value in captions(at)) == 2
    assert not any('ข้อความย่อจากต้นทาง' in value for value in captions(at))


def test_missing_quotes_and_news_render_missing_not_zero_or_old_other_ticker(monkeypatch):
    payload, state = fixtures()
    state.update(regular=None, extended=None, news=None, status='waiting')
    at, _ = run_app(monkeypatch, payload, state)
    assert not at.metric and not at.get('link_button') and not quotes(at)
    assert sum('ยังไม่มีราคาช่วงนี้ที่ตรวจสอบได้' in value for value in captions(at)) == 2
    assert len(at.info) == 1 and 'ยังไม่มีข่าวในช่วง 7 วัน' in at.info[0].value


def test_disabled_source_does_not_read_or_display_fixture_as_current(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state, active=False)
    assert not service.requests and not service.reads
    assert not at.metric and not at.get('link_button')
    assert 'data-state="disabled"' in receipt(at)


def test_selected_ticker_change_suppresses_old_chart_brief_before_request(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state, selected='OTHER')
    assert not service.requests and not service.reads and not at.metric
    assert not any('stock-brief-receipt' in value.value for value in at.markdown)


def test_switching_ticker_and_period_replaces_receipt_quotes_and_news(monkeypatch):
    payload, state = fixtures()
    at, service = run_app(monkeypatch, payload, state)
    other_payload = deepcopy(payload)
    other_payload.update(ticker='OTHER', period='3 ปี')
    other_state = deepcopy(state)
    other_state.update(ticker='OTHER', news=None)
    other_state['regular'].update(ticker='OTHER', price=44.12)
    other_state['extended'] = None
    service.state = other_state
    at.session_state['_brief_payload'] = other_payload
    at.session_state['selected_ticker'] = 'OTHER'
    at.session_state['chart_period'] = '3 ปี'
    at.run()
    assert not at.exception, str(at.exception)
    assert service.requests == service.reads == ['SCHD', 'OTHER']
    assert 'data-ticker="OTHER"' in receipt(at) and 'data-chart-period="3 ปี"' in receipt(at)
    assert len(at.metric) == 1 and at.metric[0].value == '44.12'
    assert not at.get('link_button')
    assert all('data-ticker="OTHER"' in markup for markup in quotes(at))


def test_provider_currency_and_excerpt_are_markdown_literals(monkeypatch):
    payload, state = fixtures()
    state['regular']['currency'] = '**USD**'
    state['news']['items'][0]['source_excerpt'] = '**No instructions** and `plain text`'
    at, _ = run_app(monkeypatch, payload, state)
    assert at.metric[0].label.endswith(r'\*\*USD\*\*')
    assert any(r'\*\*No instructions\*\* and \`plain text\`' in value.value for value in at.markdown)


def test_small_prices_are_visible_at_useful_precision_instead_of_rounding_to_zero(monkeypatch):
    payload, state = fixtures()
    state['regular']['price'] = .000042
    state['regular']['previous_close'] = .000041
    at, _ = run_app(monkeypatch, payload, state)
    assert float(at.metric[0].value) == pytest.approx(.000042)
    assert any('0.000041' in value for value in captions(at))


def test_partial_backoff_keeps_sources_and_does_not_block_independent_input(monkeypatch):
    payload, state = fixtures()
    state.update(status='rate_limited', error='ต้นทางจำกัดคำขอ กำลังรอรอบถัดไป', busy=False)
    at, service = run_app(monkeypatch, payload, state)
    at.text_input(key='_brief_search').set_value('UNBLOCKED').run()
    assert not at.exception and at.text_input(key='_brief_search').value == 'UNBLOCKED'
    assert 'data-state="rate_limited"' in receipt(at)
    assert state['error'] in captions(at)
    assert len(at.metric) == 2 and len(at.get('link_button')) == 2
    assert len(service.requests) == 2
