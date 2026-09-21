"""Concurrency, data retention and provider budgets; no external requests."""
from collections import deque
from datetime import datetime, timezone
import threading
from types import SimpleNamespace

import pytest

import market_pulse_service as service_module
from market_pulse_service import PulseService, MAX_CACHE_SYMBOLS


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 21, 15, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds=30):
        self.now += seconds


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def quotes(symbols, now, price=100):
    return {'quoteResponse': {'result': [
        {'symbol': symbol, 'regularMarketPrice': price, 'regularMarketTime': now - 1,
         'regularMarketPreviousClose': 95, 'marketState': 'REGULAR', 'currency': 'USD'}
        for symbol in symbols
    ]}}


def news(now, title='Company publishes results'):
    return [{'id': 'article', 'content': {
        'title': title, 'pubDate': iso(now - 60),
        'provider': {'displayName': 'Issuer newsroom'},
        'canonicalUrl': {'url': 'https://example.com/results'},
    }}]


def finish(service):
    service.thread.join(timeout=4)
    assert not service.thread.is_alive(), 'background worker did not finish'
    return service.read()


def test_one_background_batch_coalesces_reruns_without_blocking_reader():
    clock = Clock()
    entered, release = threading.Event(), threading.Event()
    caller = threading.get_ident()
    calls = []

    def fetch(symbols):
        calls.append((symbols, threading.get_ident()))
        entered.set()
        assert release.wait(3)
        return quotes(symbols, clock())

    service = PulseService(fetch, lambda _: [], clock)
    assert service.request(['AAPL', 'SPY', 'QQQ'], news_symbols=[])
    assert entered.wait(1)
    for _ in range(20):
        assert service.read()['busy']
        assert not service.request(['AAPL', 'SPY', 'QQQ'])
    release.set()
    result = finish(service)
    assert calls == [(('AAPL', 'SPY', 'QQQ'), calls[0][1])]
    assert calls[0][1] != caller
    assert set(result['quotes']) == {'AAPL', 'SPY', 'QQQ'}
    assert result['status'] == 'ready'
    assert not service.request(['AAPL'])
    clock.advance()
    assert service.request(['AAPL'], [])
    finish(service)
    assert len(calls) == 2


@pytest.mark.parametrize('symbols,news_symbols', [
    ([], []), ('AAPL', []), (['../secret'], []), (['aapl'], []),
    ([f'A{i}' for i in range(13)], []), (['AAPL'], ['MSFT']),
    (['AAPL'], 'AAPL'), (['AAPL', None], []),
])
def test_invalid_or_oversized_requests_never_call_provider(symbols, news_symbols):
    def forbidden(_):
        raise AssertionError('unexpected network operation')
    service = PulseService(forbidden, forbidden, Clock())
    assert not service.request(symbols, news_symbols)
    assert not service.calls


def test_news_rotates_fairly_with_one_request_each_round_and_five_minute_ttl():
    clock = Clock()
    called = []
    service = PulseService(lambda symbols: quotes(symbols, clock()),
                           lambda ticker: called.append(ticker) or news(clock()), clock)
    for index in range(10):
        assert service.request(['AAPL', 'MSFT', 'SPY', 'QQQ'], ['MSFT', 'AAPL'])
        finish(service)
        clock.advance()
    assert called == ['MSFT', 'AAPL']
    assert service.request(['AAPL', 'MSFT', 'SPY', 'QQQ'], ['AAPL', 'MSFT'])
    finish(service)
    assert called == ['MSFT', 'AAPL', 'MSFT']
    assert len(service.quote_calls) == 11
    assert len(service.news_calls) == 3


def test_partial_quote_response_keeps_old_source_time_without_zero_values():
    clock = Clock()
    response = quotes(['AAPL', 'SPY'], clock())
    service = PulseService(lambda _: response, lambda _: [], clock)
    assert service.request(['AAPL', 'SPY'], [])
    before = finish(service)
    clock.advance()
    response = quotes(['AAPL'], clock(), 105)
    assert service.request(['AAPL', 'SPY'], [])
    after = finish(service)
    assert after['quotes']['SPY'] == before['quotes']['SPY']
    assert after['quotes']['AAPL']['price'] == 105
    assert after['quote_status']['SPY']['state'] == 'kept'
    assert after['status'] == 'partial'


def test_regressed_quote_response_never_replaces_more_recent_source_observation():
    clock = Clock()
    response = quotes(['AAPL'], clock())
    service = PulseService(lambda _: response, lambda _: [], clock)
    assert service.request(['AAPL'], [])
    before = finish(service)
    clock.advance()
    response = quotes(['AAPL'], clock() - 120, 1)
    assert service.request(['AAPL'], [])
    after = finish(service)
    assert after['quotes'] == before['quotes']
    assert after['checked_at'] == before['checked_at']
    assert after['status'] == 'error'


def test_429_cooldown_respects_retry_after_and_skips_news():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: [], clock)
    assert service.request(['AAPL'], [])
    before = finish(service)
    clock.advance()
    news_calls = []

    def limited(_):
        exc = RuntimeError('private provider payload with token=SECRET')
        exc.response = SimpleNamespace(status_code=429, headers={'Retry-After': '1800'})
        raise exc

    service.quote_fetcher = limited
    service.news_fetcher = lambda ticker: news_calls.append(ticker)
    assert service.request(['AAPL'])
    after = finish(service)
    assert after['quotes'] == before['quotes']
    assert after['checked_at'] == before['checked_at']
    assert after['cooldown_until'] == clock() + 1800
    assert after['status'] == 'rate_limited'
    assert 'SECRET' not in repr(after)
    assert not news_calls
    clock.advance(300)
    assert not service.request(['AAPL'])


def test_news_error_retains_successful_check_time_and_articles():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: news(clock()), clock)
    assert service.request(['AAPL'])
    before = finish(service)
    clock.advance(300)

    def fail(_):
        raise RuntimeError('401 Unauthorized secret-token')

    service.news_fetcher = fail
    assert service.request(['AAPL'])
    after = finish(service)
    assert after['news'] == before['news']
    assert after['news_status']['AAPL']['state'] == 'error'
    assert after['status'] == 'partial'
    assert 'secret-token' not in repr(after)


def test_news_regression_preserves_article_publication_time_but_records_successful_check():
    clock = Clock()
    response = news(clock())
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: response, clock)
    assert service.request(['AAPL'])
    before = finish(service)
    clock.advance(300)
    response = news(clock() - 600, 'Older article')
    assert service.request(['AAPL'])
    after = finish(service)
    assert after['news']['AAPL']['items'] == before['news']['AAPL']['items']
    assert after['news']['AAPL']['checked_at'] == iso(clock())
    assert after['news_status']['AAPL']['state'] == 'kept'


def test_valid_empty_news_has_successful_check_but_no_invented_article_time():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: [], clock)
    assert service.request(['AAPL'])
    result = finish(service)
    assert result['news']['AAPL']['state'] == 'empty'
    assert result['news']['AAPL']['checked_at'] == iso(clock())
    assert result['news']['AAPL']['items'] == []
    assert 'published_at' not in result['news']['AAPL']


def test_malformed_news_preserves_last_good_data():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: news(clock()), clock)
    assert service.request(['AAPL'])
    before = finish(service)
    clock.advance(300)
    service.news_fetcher = lambda _: {'error': 'bad response'}
    assert service.request(['AAPL'])
    after = finish(service)
    assert after['news'] == before['news']
    assert after['news_status']['AAPL']['state'] == 'error'


@pytest.mark.parametrize('budget_name,count', [('calls', 240), ('quote_calls', 120)])
def test_request_limits_are_shared_across_changing_tickers(budget_name, count):
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: [], clock)
    setattr(service, budget_name, deque([clock() - 10] * count))
    assert not service.request(['AAPL'])
    assert not service.request(['MSFT'])
    assert service.read()['status'] == 'budget'
    clock.advance(3590)
    assert service.request(['MSFT'], [])
    assert finish(service)['quotes']['MSFT']['price'] == 100


def test_news_budget_does_not_block_quote_and_is_visible():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: [], clock)
    service.news_calls = deque([clock() - 10] * 120)
    assert service.request(['AAPL'])
    result = finish(service)
    assert result['quotes']['AAPL']['price'] == 100
    assert result['news_status']['AAPL']['state'] == 'budget'
    assert not result['news']


def test_cache_is_bounded_and_reader_cannot_mutate_worker_state():
    clock = Clock()
    service = PulseService(lambda symbols: quotes(symbols, clock()), lambda _: [], clock)
    for index in range(MAX_CACHE_SYMBOLS + 2):
        symbol = f'X{index}'
        assert service.request([symbol], [])
        finish(service)
        clock.advance()
    result = service.read()
    assert len(result['quotes']) == MAX_CACHE_SYMBOLS
    assert len(result['quote_status']) == MAX_CACHE_SYMBOLS
    assert 'X0' not in result['quotes']
    result['quotes']['X65']['price'] = 1
    assert service.read()['quotes']['X65']['price'] == 100


def test_default_fetchers_use_normal_authentication_and_uncached_validated_news(monkeypatch):
    import sys
    import yfinance.data
    calls = []
    news_calls = []

    class Response:
        def raise_for_status(self):
            news_calls.append('status checked')

        def json(self):
            return {'data': {'tickerStream': {'stream': []}}}

    class Data:
        def get_raw_json(self, url, params, timeout):
            calls.append((url, params, timeout))
            return {'quoteResponse': {'result': []}}

        def post(self, url, body, timeout):
            news_calls.append((url, body, timeout))
            return Response()

    runtime = SimpleNamespace(core=SimpleNamespace(_PROVIDER_LOCK=threading.RLock()))
    monkeypatch.setitem(sys.modules, 'dashboard_runtime', runtime)
    monkeypatch.setattr(yfinance.data, 'YfData', Data)
    service_module.fetch_quotes(('AAPL', 'SPY', 'QQQ'))
    service_module.fetch_news('AAPL')
    service_module.fetch_news('AAPL')
    assert calls == [(service_module.QUOTE_URL,
                      {'symbols': 'AAPL,SPY,QQQ', 'formatted': 'false'}, 10)]
    expected = (service_module.NEWS_URL,
                {'serviceConfig': {'snippetCount': 5, 's': ['AAPL']}}, 10)
    assert news_calls == [expected, 'status checked', expected, 'status checked']


@pytest.mark.parametrize('payload', [None, [], {}, {'data': {}},
    {'data': {'tickerStream': {'stream': None}}},
    {'errors': ['unavailable'], 'data': {'tickerStream': {'stream': []}}},
])
def test_news_adapter_never_turns_malformed_provider_response_into_empty_success(monkeypatch, payload):
    import sys
    import yfinance.data
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    data = SimpleNamespace(post=lambda *args, **kwargs: response)
    runtime = SimpleNamespace(core=SimpleNamespace(_PROVIDER_LOCK=threading.RLock()))
    monkeypatch.setitem(sys.modules, 'dashboard_runtime', runtime)
    monkeypatch.setattr(yfinance.data, 'YfData', lambda: data)
    with pytest.raises(ValueError):
        service_module.fetch_news('AAPL')


def test_news_http_error_raises_before_body_is_treated_as_empty(monkeypatch):
    import sys
    import yfinance.data

    def fail():
        raise RuntimeError('429')

    response = SimpleNamespace(raise_for_status=fail,
                               json=lambda: {'data': {'tickerStream': {'stream': []}}})
    runtime = SimpleNamespace(core=SimpleNamespace(_PROVIDER_LOCK=threading.RLock()))
    monkeypatch.setitem(sys.modules, 'dashboard_runtime', runtime)
    monkeypatch.setattr(yfinance.data, 'YfData', lambda: SimpleNamespace(post=lambda *a, **kw: response))
    with pytest.raises(RuntimeError):
        service_module.fetch_news('AAPL')
