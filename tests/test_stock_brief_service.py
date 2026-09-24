"""Selected briefing: source clocks, independent data streams and bounded work."""
from collections import deque
from datetime import datetime, timezone
import threading
from types import SimpleNamespace

import pytest

from stock_brief_service import (
    StockBriefService, normalize_brief_quotes, MAX_CACHE_SYMBOLS, MAX_PENDING_SYMBOLS,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 24, 20, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds=60):
        self.now += seconds


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def quotes(ticker, now, **changes):
    row = {'symbol': ticker, 'currency': 'USD', 'marketState': 'POST',
           'regularMarketPrice': 100, 'regularMarketTime': now - 120,
           'regularMarketPreviousClose': 95,
           'postMarketPrice': 101, 'postMarketTime': now - 1}
    row.update(changes)
    return {'quoteResponse': {'result': [row], 'error': None}}


def news(now, title='Company results', count=1):
    return [{'content': {'title': f'{title} {index}', 'pubDate': iso(now - 60 - index),
                         'provider': {'displayName': 'Issuer newsroom'},
                         'canonicalUrl': {'url': f'https://example.com/results/{index}'},
                         'summary': 'Revenue increased compared with the previous year.'}}
            for index in range(count)]


def finish(service, ticker='AAPL'):
    service.thread.join(timeout=4)
    assert not service.thread.is_alive()
    return service.read(ticker)


def test_regular_and_extended_keep_distinct_prices_times_and_change_bases():
    clock = Clock()
    result = normalize_brief_quotes(quotes('AAPL', clock()), 'AAPL', iso(clock()))
    regular, extended = result['regular'], result['extended']
    assert (regular['price'], extended['price']) == (100, 101)
    assert regular['session'] == 'regular' and extended['session'] == 'post'
    assert regular['quote_time'] == iso(clock() - 120)
    assert extended['quote_time'] == iso(clock() - 1)
    assert regular['change_pct'] == pytest.approx(100 / 95 * 100 - 100)
    assert extended['change_pct'] == pytest.approx(1)
    assert regular['change_basis'] == 'previous regular close'
    assert extended['change_basis'] == 'latest regular close'
    assert extended['basis_time'] == regular['quote_time']
    assert not regular['is_current_session'] and extended['is_current_session']


def test_no_previous_close_never_uses_unverifiable_reported_change():
    clock = Clock()
    result = normalize_brief_quotes(quotes('AAPL', clock(), regularMarketPreviousClose=None,
                                          regularMarketChangePercent=99), 'AAPL', iso(clock()))
    assert result['regular']['change_pct'] is None
    assert result['regular']['change_abs'] is None
    assert result['extended']['change_pct'] == pytest.approx(1)


def test_overflowing_change_is_missing_instead_of_infinite():
    clock = Clock()
    result = normalize_brief_quotes(quotes('AAPL', clock(), regularMarketPreviousClose=1e-308),
                                    'AAPL', iso(clock()))
    assert result['regular']['change_pct'] is None
    assert result['regular']['change_abs'] == 100


def test_premarket_and_prior_postmarket_choose_latest_actual_source_observation():
    clock = Clock()
    result = normalize_brief_quotes(quotes('AAPL', clock(), marketState='PRE',
                                          preMarketPrice=102, preMarketTime=clock()-0.5), 'AAPL', iso(clock()))
    assert result['extended']['session'] == 'pre'
    assert result['extended']['price'] == 102
    assert result['extended']['is_current_session']


@pytest.mark.parametrize('changes', [
    {'postMarketTime': None}, {'postMarketTime': '2026-09-24T20:00:00'},
    {'postMarketTime': float('inf')}, {'postMarketTime': True},
    {'postMarketPrice': 0}, {'postMarketPrice': float('nan')},
    {'postMarketPrice': True},
])
def test_invalid_extended_observation_is_missing_and_regular_is_not_relabelled(changes):
    clock = Clock()
    result = normalize_brief_quotes(quotes('AAPL', clock(), **changes), 'AAPL', iso(clock()))
    assert result['regular']['price'] == 100
    assert result['extended'] is None


def test_future_and_earlier_extended_times_never_mix_with_latest_regular_basis():
    clock = Clock()
    for time in (clock() + 1, clock() - 120, clock() - 121):
        result = normalize_brief_quotes(quotes('AAPL', clock(), postMarketTime=time), 'AAPL', iso(clock()))
        assert result['extended'] is None


@pytest.mark.parametrize('changes', [
    {'currency': None}, {'currency': 'USD / EUR'}, {'currency': ''},
    {'regularMarketPrice': 0}, {'regularMarketPrice': True},
    {'regularMarketTime': None}, {'regularMarketTime': '2026-09-24T20:00:00'},
])
def test_invalid_regular_or_currency_rejects_incoherent_extended_change(changes):
    clock = Clock()
    assert normalize_brief_quotes(quotes('AAPL', clock(), **changes), 'AAPL', iso(clock())) == {'regular': None, 'extended': None}


def test_wrong_ticker_duplicate_and_error_envelopes_are_rejected():
    clock = Clock()
    good = quotes('AAPL', clock())
    duplicated = {'quoteResponse': {'result': good['quoteResponse']['result'] * 2}}
    errored = dict(good, error='Unauthorized')
    for raw in (quotes('MSFT', clock()), duplicated, errored, None, {}, {'quoteResponse': []}):
        assert normalize_brief_quotes(raw, 'AAPL', iso(clock())) == {'regular': None, 'extended': None}


def test_explicit_provider_delay_and_closed_session_never_label_current_quote():
    clock = Clock()
    delayed = normalize_brief_quotes(quotes('AAPL', clock(), exchangeDataDelayedBy=15), 'AAPL', iso(clock()))
    assert delayed['extended']['freshness'] == 'stale'
    assert not delayed['extended']['is_current_session']
    closed = normalize_brief_quotes(quotes('AAPL', clock(), marketState='CLOSED'), 'AAPL', iso(clock()))
    assert closed['extended']['freshness'] == 'recent'
    assert not closed['extended']['is_current_session']


def test_one_background_worker_nonblocking_reads_and_bounded_pending_queue():
    clock = Clock()
    entered, release = threading.Event(), threading.Event()
    caller, calls = threading.get_ident(), []

    def fetch(symbols):
        calls.append((symbols, threading.get_ident()))
        entered.set()
        assert release.wait(3)
        return quotes(symbols[0], clock())

    service = StockBriefService(fetch, lambda _: [], clock)
    assert service.request('AAPL') and entered.wait(1)
    assert service.read('AAPL')['busy']
    for index in range(50):
        assert not service.request(f'S{index}')
        service.read(f'S{index}')
    assert len(service.pending) <= MAX_PENDING_SYMBOLS
    assert len(service.cache) <= MAX_CACHE_SYMBOLS
    assert len(calls) == 1
    release.set()
    finish(service)
    assert calls[0][1] != caller


@pytest.mark.parametrize('ticker', [None, '', '../secret', 'aapl', [], 123])
def test_invalid_request_never_starts_work(ticker):
    service = StockBriefService(lambda _: pytest.fail('quote called'), lambda _: pytest.fail('news called'), Clock())
    assert not service.request(ticker)
    assert not service.cache


def test_news_uses_ten_available_articles_and_independent_five_minute_ttl():
    clock = Clock()
    quote_calls, news_calls = [], []
    service = StockBriefService(lambda symbols: quote_calls.append(symbols) or quotes(symbols[0], clock()),
                                lambda ticker: news_calls.append(ticker) or news(clock(), count=10), clock)
    for index in range(6):
        assert service.request('AAPL')
        result = finish(service)
        assert len(result['news']['items']) == 10
        clock.advance()
    assert len(quote_calls) == 6
    assert len(news_calls) == 2
    assert result['quote_checked_at'] == iso(clock() - 60)
    assert result['news_checked_at'] == iso(clock() - 60)


def test_global_spacing_applies_across_symbols_and_news_can_run_while_quote_not_due():
    clock = Clock()
    quotes_called, news_called = [], []
    service = StockBriefService(lambda symbols: quotes_called.append(symbols[0]) or quotes(symbols[0], clock()),
                                lambda ticker: news_called.append(ticker) or [], clock)
    assert service.request('AAPL')
    finish(service)
    assert not service.request('MSFT')
    clock.advance(60)
    assert service.request('MSFT')
    finish(service, 'MSFT')
    assert quotes_called == ['AAPL', 'MSFT']
    assert news_called == ['AAPL']
    clock.advance(240)
    # A quote-specific backoff must not block an independently eligible news read.
    service.cache['MSFT']['quote_due'] = clock() + 300
    assert service.request('MSFT')
    finish(service, 'MSFT')
    assert news_called == ['AAPL', 'MSFT']
    assert quotes_called == ['AAPL', 'MSFT']


def test_hourly_budget_and_expiry_are_independent_of_user_switching():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: [], clock)
    # Spacing already bounds normal use; exercise explicit rolling window gate.
    service.quote_calls = deque([clock() - 3599 + i for i in range(60)])
    service.news_calls = deque([clock() - 3599 + i for i in range(12)])
    assert not service.request('AAPL')
    assert service.read('AAPL')['next_due'] == clock() + 1
    clock.advance(1)
    assert service.request('AAPL')
    result = finish(service)
    assert result['status'] == 'ready'
    assert len(service.quote_calls) == 60 and len(service.news_calls) == 12


def test_quote_failure_does_not_block_news_or_expose_private_exception():
    clock = Clock()

    def fail(_):
        raise RuntimeError('401 secret-token')

    service = StockBriefService(fail, lambda _: news(clock()), clock)
    assert service.request('AAPL')
    result = finish(service)
    assert result['regular'] is None
    assert result['news']['state'] == 'available'
    assert result['status'] == 'partial'
    assert 'secret-token' not in repr(result)


def test_rate_limit_retains_data_and_respects_provider_retry_after_for_both_streams():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: news(clock()), clock)
    assert service.request('AAPL')
    before = finish(service)
    clock.advance(300)

    def limited(_):
        exc = RuntimeError('private payload')
        exc.response = SimpleNamespace(status_code=429, headers={'Retry-After': '1800'})
        raise exc

    service.quote_fetcher = limited
    service.news_fetcher = lambda _: pytest.fail('news must honor global cooldown')
    assert service.request('AAPL')
    after = finish(service)
    assert after['regular']['quote_time'] == before['regular']['quote_time']
    assert after['news'] == before['news']
    assert after['quote_checked_at'] == before['quote_checked_at']
    assert after['cooldown_until'] == clock() + 1800
    assert after['status'] == 'rate_limited'
    assert not service.request('MSFT')


def test_malformed_news_and_regressed_quotes_keep_original_observations():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: news(clock()), clock)
    assert service.request('AAPL')
    before = finish(service)
    clock.advance(300)
    service.quote_fetcher = lambda symbols: quotes(symbols[0], clock() - 900, regularMarketPrice=1)
    service.news_fetcher = lambda _: {'error': 'bad envelope'}
    assert service.request('AAPL')
    after = finish(service)
    assert after['regular']['quote_time'] == before['regular']['quote_time']
    assert after['regular']['price'] == before['regular']['price']
    assert after['news'] == before['news']
    assert after['news_checked_at'] == before['news_checked_at']
    assert after['quote_checked_at'] == before['quote_checked_at']


def test_news_regression_retains_article_dates_but_records_successful_check():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: news(clock()), clock)
    assert service.request('AAPL')
    before = finish(service)
    clock.advance(300)
    service.news_fetcher = lambda _: news(clock() - 900, title='Old article')
    assert service.request('AAPL')
    after = finish(service)
    assert after['news']['items'] == before['news']['items']
    assert after['news_checked_at'] == iso(clock())
    assert after['news_status']['state'] == 'kept'


def test_read_recalculates_age_and_returns_detached_copies_without_network():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: [], clock)
    assert service.request('AAPL')
    before = finish(service)
    assert before['extended']['freshness'] == 'recent'
    before['extended']['price'] = 999
    clock.advance(301)
    after = service.read('AAPL')
    assert after['extended']['price'] == 101
    assert after['extended']['freshness'] == 'stale'
    assert not after['extended']['is_current_session']
    assert len(service.quote_calls) == len(service.news_calls) == 1
    assert not service.read('MSFT')['regular']
    assert 'MSFT' not in service.cache


def test_later_regular_quote_does_not_rebase_retained_extended_observation():
    clock = Clock()
    service = StockBriefService(lambda symbols: quotes(symbols[0], clock()), lambda _: [], clock)
    assert service.request('AAPL')
    before = finish(service)
    clock.advance(60)
    service.quote_fetcher = lambda symbols: quotes(symbols[0], clock(), regularMarketPrice=105,
                                                    regularMarketTime=clock()-1,
                                                    postMarketTime=None, marketState='REGULAR')
    assert service.request('AAPL')
    after = finish(service)
    assert after['regular']['price'] == 105
    assert after['extended']['previous_close'] == 100
    assert after['extended']['change_pct'] == before['extended']['change_pct']
    assert after['extended']['basis_time'] == before['regular']['quote_time']
    assert not after['extended']['is_current_session']


def test_new_closed_metadata_suppresses_current_flag_on_retained_post_quote():
    clock = Clock()
    first = quotes('AAPL', clock())
    service = StockBriefService(lambda _: first, lambda _: [], clock)
    assert service.request('AAPL')
    before = finish(service)
    assert before['extended']['is_current_session']
    clock.advance(60)
    service.quote_fetcher = lambda _: quotes('AAPL', clock(), marketState='CLOSED',
                                             regularMarketTime=clock()-180,
                                             postMarketPrice=None, postMarketTime=None)
    assert service.request('AAPL')
    after = finish(service)
    assert after['regular']['market_state'] == 'CLOSED'
    assert after['extended']['freshness'] == 'recent'
    assert after['extended']['quote_time'] == before['extended']['quote_time']
    assert not after['extended']['is_current_session']


def test_new_extended_quote_with_regressed_regular_basis_is_rejected():
    clock = Clock()
    first = quotes('AAPL', clock(), regularMarketPrice=105,
                   regularMarketTime=clock()-2, postMarketPrice=106)
    service = StockBriefService(lambda _: first, lambda _: [], clock)
    assert service.request('AAPL')
    before = finish(service)
    clock.advance(60)
    service.quote_fetcher = lambda _: quotes('AAPL', clock(), regularMarketPrice=100,
                                             regularMarketTime=clock()-900, postMarketPrice=110)
    assert service.request('AAPL')
    after = finish(service)
    assert after['regular']['price'] == 105
    assert after['extended']['price'] == 106
    assert after['extended']['change_pct'] == before['extended']['change_pct']
    assert after['quote_checked_at'] == before['quote_checked_at']
    assert after['quote_status']['state'] == 'error'
