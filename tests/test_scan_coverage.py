"""Broader discovery must preserve evidence, bounded work and delivery limits."""
from copy import deepcopy
import base64
import gzip
from unittest.mock import patch

import pytest
import pandas as pd

import short_term_engine as engine
from short_term_context import pack_pool_rows, unpack_pool_rows
from short_term_service import scan, news_priority, chart_order
from short_term_report import report_rows, format_report
from test_short_term_engine import NOW, row, raw_quote, news, pool
from test_short_term_events import wdc_report


def expanded_pool(size):
    rows = [dict(row(), ticker='T' + str(i), company={'business_en': 'Company ' + str(i)},
                 daily_context={'sma20': 99.9, 'sma50': 96.2, 'sma200': 88.8}) for i in range(size)]
    return dict(model=engine.MODEL, pool_version=engine.POOL_VERSION, count=size,
                computed_at=NOW.isoformat(), context_version=2, **pack_pool_rows(rows))


def test_full_5000_pool_roundtrip_and_identity_validation():
    value = expanded_pool(5000)
    assert value['items'] == []
    restored = engine.validate_pool(value, NOW)
    assert len(restored) == 5000
    assert restored[-1]['ticker'] == 'T4999'
    assert restored[-1]['company']['business_en'] == 'Company 4999'
    assert restored[-1]['daily_context']['sma200'] == 88.8
    bad = deepcopy(value)
    bad['count'] = 4999
    with pytest.raises(ValueError): engine.validate_pool(bad, NOW)
    restored[-1]['ticker'] = 'T0'
    bad.update(pack_pool_rows(restored), count=5000)
    with pytest.raises(ValueError): engine.validate_pool(bad, NOW)


def test_build_pool_does_not_stop_at_old_1000_cap_and_counts_validated_rows():
    tickers = ['T' + str(i) for i in range(1002)] + ['THIN', 'FUND']
    dates = engine.calendar('2026-10-02').index
    dates = dates[dates.date < NOW.date()][-20:]
    frame = pd.DataFrame({'Open': 100., 'High': 103., 'Low': 99., 'Close': 101., 'Volume': 1_000_000.}, index=dates)
    class Cache:
        def quotes(self):
            return {t: {'Asset_Type': 'ETF' if t == 'FUND' else 'Common Stock',
                        'Close': 101., 'Dollar_Volume_20D': 101_000_000.} for t in tickers}
        def classifications(self): return {}
        def get(self, *args, **kwargs): return {'currency': 'USD'}, {}
        def history(self, ticker): return (frame.assign(Volume=1.) if ticker == 'THIN' else frame), {}
    with patch('short_term_context.company_context', return_value={}):
        value = engine.build_pool(Cache(), tickers, NOW)
    assert value['count'] == value['eligible_after_validation'] == 1002
    assert value['eligible_before_cap'] == 1003
    assert value['excluded_by_cap'] == 0
    assert value['catalog_common_stocks'] == 1003
    assert value['catalog_funds'] == 1
    assert len(engine.validate_pool(value, NOW)) == 1002


def test_compressed_pool_rejects_oversize_trailing_stream_and_mixed_rows():
    value = expanded_pool(1001)
    with patch('short_term_context.MAX_POOL_DECODE_BYTES', 500):
        with pytest.raises(ValueError): unpack_pool_rows(value)
    bad = deepcopy(value)
    bad['items_blob'] = base64.b64encode(base64.b64decode(value['items_blob']) + gzip.compress(b'[]')).decode()
    with pytest.raises(ValueError): unpack_pool_rows(bad)
    bad = dict(value, items=[row()])
    with pytest.raises(ValueError): unpack_pool_rows(bad)


def test_one_failed_quote_batch_keeps_other_results_and_actual_denominator():
    calls = []
    def quotes(symbols):
        calls.append(symbols)
        if len(calls) == 2:
            raise TimeoutError('one batch unavailable')
        return [raw_quote(t) for t in symbols]
    result = scan({'short_term_pool': expanded_pool(250)}, clock=lambda: NOW,
                  quote_fetcher=quotes, news_fetcher=lambda *a: {'items': []})
    assert result['counts']['universe'] == 250
    assert result['counts']['quote_attempted'] == 250
    assert result['counts']['fresh_quotes'] == 150
    assert result['counts']['quote_failed_batches'] == 1
    assert result['counts']['quote_unattempted'] == 0
    assert 'quote_batch_unavailable' in result['diagnostics']


def test_quote_deadline_and_rate_block_do_not_retry_or_claim_untouched_stocks():
    elapsed = [0.]
    calls = []
    def quotes(symbols):
        calls.append(symbols)
        elapsed[0] = 121.
        return [raw_quote(t) for t in symbols]
    result = scan({'short_term_pool': expanded_pool(250)}, clock=lambda: NOW,
                  monotonic=lambda: elapsed[0], quote_fetcher=quotes,
                  news_fetcher=lambda *a: {'items': []})
    assert len(calls) == 1
    assert result['counts']['quote_attempted'] == 100
    assert result['counts']['quote_unattempted'] == 150
    assert result['counts']['fresh_quotes'] == 100
    assert 'quote_scan_limit_reached' in result['diagnostics']
    calls.clear()
    def blocked(symbols):
        calls.append(symbols)
        raise RuntimeError('rate limit')
    result = scan({'short_term_pool': expanded_pool(250)}, clock=lambda: NOW,
                  quote_fetcher=blocked, news_fetcher=lambda *a: pytest.fail('No news after a block'))
    assert len(calls) == 1
    assert result['status'] == 'data_unavailable'
    assert result['counts']['quote_unattempted'] == 150
    assert 'provider_access_or_rate_blocked' in result['diagnostics']


def test_final_refresh_still_runs_after_news_budget_is_used():
    elapsed = [0.]
    calls = []
    def quotes(symbols):
        calls.append(symbols)
        return [raw_quote(t) for t in symbols]
    def slow_news(*args):
        elapsed[0] = 226.
        return news()
    with patch('thai_news_translation.enrich_prepared'):
        result = scan({'short_term_pool': pool()}, clock=lambda: NOW,
                      monotonic=lambda: elapsed[0], quote_fetcher=quotes, news_fetcher=slow_news,
                      chart_fetcher=lambda *a: pytest.fail('Chart budget must stay reserved'))
    assert len(calls) == 2
    assert result['counts']['charts_checked'] == 0
    assert result['events'][0]['metrics_available'] is False
    assert result['cards'] == []


@pytest.mark.parametrize('blocked_code', ['HTTP_403', 'HTTP_429', 'access_or_rate_blocked'])
def test_returned_news_block_stops_further_provider_requests(blocked_code):
    value = expanded_pool(30)
    news_calls = []
    quote_calls = []
    def quotes(symbols):
        quote_calls.append(symbols)
        return [raw_quote(t, regularMarketPrice=104.) for t in symbols]
    def blocked(*args):
        news_calls.append(args)
        return {'items': None, 'fallback_error': blocked_code}
    result = scan({'short_term_pool': value}, clock=lambda: NOW, quote_fetcher=quotes,
                  news_fetcher=blocked, chart_fetcher=lambda *a: pytest.fail('No chart after a block'))
    assert len(quote_calls) == len(news_calls) == 1
    assert result['status'] == 'data_unavailable'
    assert 'provider_access_or_rate_blocked' in result['diagnostics']


def test_rotating_news_tail_and_line_five_stock_limit():
    values = [(1000-i, {'ticker': 'T'+str(i)}, {'change_pct': (-1 if i % 2 else 1)*10}) for i in range(60)]
    first = news_priority(values, 0)
    second = news_priority(values, 1)
    assert len(first) == len(second) == 20
    assert first[:12] == second[:12]
    assert first[12:] != second[12:]
    assert len({v[1]['ticker'] for v in first}) == 20
    assert any(v[2]['change_pct'] < 0 for v in first)
    # A rotating news item must also eventually reach chart analysis, even if
    # every fixed-priority ticker has news in every round.
    selected = set()
    for slot in range(14):
        order = chart_order(20, slot)
        assert order[:6] == list(range(6))
        assert len(set(order)) == 20
        selected.update(order[:10])
    assert selected == set(range(20))
    report = wdc_report()
    event = report['events'][0]
    report['events'] = [dict(deepcopy(event), ticker='T'+str(i)) for i in range(20)]
    assert len(report_rows(report)) == 5
    assert '5) T4' in format_report(report)
    assert '6) T5' not in format_report(report)
