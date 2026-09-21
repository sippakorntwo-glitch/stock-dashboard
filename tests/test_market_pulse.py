"""Observable market/news evidence must not invent buy signals or fresh data."""
from copy import deepcopy

import pandas as pd
import pytest

from market_pulse import normalize_quotes, normalize_news, assess_pulse

NOW = '2026-09-21T14:30:00Z'
QUOTE_AT = '2026-09-21T14:29:40Z'


def raw_quote(ticker='TEST', **changes):
    row = {'symbol':ticker, 'marketState':'REGULAR', 'regularMarketPrice':103,
           'regularMarketPreviousClose':100, 'regularMarketTime':pd.Timestamp(QUOTE_AT).timestamp(),
           'regularMarketVolume':1800, 'averageDailyVolume3Month':1000, 'currency':'USD',
           'exchangeDataDelayedBy':0}
    row.update(changes)
    return row


def quote(ticker='TEST', **changes):
    return normalize_quotes([raw_quote(ticker, **changes)], [ticker], NOW)[ticker]


def base_row():
    return {'ticker':'TEST', 'score':100, 'coverage':100, 'qualified':True,
            'ready_at_calculation':False, 'stop':100, 'target':112, 'rsi':55}


def news_item(title='Company files trading update', **changes):
    content = {'title':title, 'provider':{'displayName':'Example News'},
               'canonicalUrl':{'url':'https://news.example.com/company-update'},
               'pubDate':'2026-09-21T13:45:00Z'}
    content.update(changes)
    return {'content':content}


def assessment(stock=None, spy=None, news=None, row=None, **changes):
    return assess_pulse(base_row() if row is None else row,
                        quote() if stock is None else stock,
                        {'SPY':quote('SPY', regularMarketPrice=101)} if spy is None else {'SPY':spy},
                        news, now=NOW, snapshot_at=changes.get('snapshot_at', NOW))


def test_quotes_bind_requested_symbols_and_keep_source_time_separate_from_download():
    raw = {'quoteResponse':{'result':[raw_quote(), raw_quote('OTHER'), raw_quote('test')]}}
    original = deepcopy(raw)
    result = normalize_quotes(raw, ['TEST'], NOW)
    assert set(result) == {'TEST'} and raw == original
    value = result['TEST']
    assert pd.Timestamp(value['quote_time']) == pd.Timestamp(QUOTE_AT)
    assert pd.Timestamp(value['fetched_at']) == pd.Timestamp(NOW)
    assert value['change_pct'] == pytest.approx(3)
    assert value['volume_session'] == 'regular'
    assert value['average_volume_basis'] == 'ค่าเฉลี่ยเต็มวัน 3 เดือน'


@pytest.mark.parametrize('changes', [
    {'regularMarketTime':None}, {'regularMarketTime':'2026-09-21T14:29:40'},
    {'regularMarketTime':pd.Timestamp(NOW).timestamp()+1},
    {'regularMarketPrice':float('nan')}, {'regularMarketPrice':True},
    {'regularMarketPrice':-1},
])
def test_invalid_or_future_source_quotes_cannot_become_live(changes):
    assert normalize_quotes([raw_quote(**changes)], ['TEST'], NOW) == {}


def test_duplicate_provider_symbols_and_malformed_batch_do_not_silently_choose_data():
    assert normalize_quotes([raw_quote(), raw_quote(regularMarketPrice=105)], ['TEST'], NOW) == {}
    assert normalize_quotes({'quoteResponse':{'error':'provider error'}}, ['TEST'], NOW) == {}
    assert normalize_quotes([raw_quote()], ['TEST'], '2026-09-21') == {}


@pytest.mark.parametrize('session,prefix', [('PRE','pre'), ('POST','post')])
def test_extended_session_price_and_change_use_current_regular_close_without_borrowing_volume(session, prefix):
    raw = raw_quote(marketState=session, regularMarketPrice=102)
    raw.update({prefix+'MarketPrice':105, prefix+'MarketTime':pd.Timestamp(QUOTE_AT).timestamp()})
    value = normalize_quotes([raw], ['TEST'], NOW)['TEST']
    assert value['price'] == 105 and value['session'] == prefix
    assert value['change_pct'] == pytest.approx((105/102-1)*100)
    assert value['volume_session'] == 'regular'
    pulse = assessment(stock=value)
    assert pulse['state'] == 'unknown' and pulse['metrics']['volume_ratio'] is None
    assert normalize_quotes([raw_quote(marketState=session)], ['TEST'], NOW) == {}


def test_volume_fallback_is_explicit_and_zero_volume_is_known_zero():
    value = quote(averageDailyVolume3Month=None, averageDailyVolume10Day=500, regularMarketVolume=0)
    assert value['average_volume'] == 500 and '10 วัน' in value['average_volume_basis']
    pulse = assessment(stock=value)
    assert pulse['metrics']['volume_ratio'] == 0 and pulse['state'] == 'watch'


def test_all_three_fresh_evidence_criteria_can_be_strong_without_promoting_entry_or_claiming_probability():
    row, stock = base_row(), quote()
    original = deepcopy(row)
    pulse = assessment(stock=stock, row=row)
    assert pulse['state'] == 'strong'
    assert pulse['metrics']['met_count'] == pulse['metrics']['known_count'] == 3
    assert pulse['metrics']['relative_spy_pp'] == pytest.approx(2)
    assert pulse['metrics']['volume_ratio'] == pytest.approx(1.8)
    assert pulse['metrics']['current_rr'] == pytest.approx(3)
    assert row == original and not row['ready_at_calculation']
    assert 'probability' not in pulse and 'ready_at_calculation' not in pulse
    assert pulse['news_context']['state'] == 'unavailable'


@pytest.mark.parametrize('change', [
    {'quote_time':'2026-09-21T14:26:59Z'}, {'quote_time':'2026-09-21T14:30:01Z'},
    {'quote_time':None}, {'quote_time':'2026-09-21T14:29:40'},
    {'market_state':'CLOSED'}, {'market_state':'UNKNOWN'}, {'ticker':'OTHER'}, {'currency':''},
])
def test_stale_future_closed_mismatched_and_unknown_quotes_block_assessment(change):
    value = {**quote(), **change}
    pulse = assessment(stock=value)
    assert pulse['state'] == 'unknown'
    assert pulse['metrics']['change_pct'] is None and pulse['metrics']['current_rr'] is None


@pytest.mark.parametrize('change', [
    {'quote_time':'2026-09-21T14:27:01Z'},  # Both recent, but >120 s apart.
    {'currency':'CAD'}, {'ticker':'QQQ'}, {'change_pct':None},
    {'session':'pre','market_state':'PRE'}, {'market_state':'CLOSED'},
])
def test_incomparable_benchmark_cannot_imply_outperformance(change):
    spy = {**quote('SPY', regularMarketPrice=101), **change}
    pulse = assessment(spy=spy)
    assert pulse['state'] == 'unknown' and pulse['metrics']['relative_spy_pp'] is None


@pytest.mark.parametrize('change', [
    {'volume':None}, {'volume':float('nan')}, {'volume':-1},
    {'average_volume':None}, {'average_volume':0}, {'volume_session':'post'},
])
def test_unknown_volume_is_not_awarded_or_interpreted_as_zero(change):
    pulse = assessment(stock={**quote(), **change})
    assert pulse['state'] == 'unknown'
    assert pulse['metrics']['volume_ratio'] is None
    assert pulse['metrics']['known_count'] == 2


def test_known_weak_evidence_is_watch_and_plan_requires_valid_fresh_snapshot():
    assert assessment(stock=quote(regularMarketPrice=101))['state'] == 'watch'
    assert assessment(snapshot_at='2026-09-21T13:54:59Z')['metrics']['current_rr'] is None
    assert assessment(snapshot_at=None)['metrics']['current_rr'] is None
    assert assessment(row={**base_row(), 'target':102})['metrics']['current_rr'] is None
    assert assessment(row={**base_row(), 'stop':104})['metrics']['current_rr'] is None
    assert assessment(stock=quote(currency='CAD'))['metrics']['current_rr'] is None


def test_news_metadata_is_safe_deduplicated_sorted_bounded_and_not_mutated():
    raw = [news_item('Latest '+('word '*90)), news_item('Duplicate'),
           news_item('Older', pubDate='2026-09-20T12:00:00Z', canonicalUrl={'url':'https://news.example.com/older'})]
    original = deepcopy(raw)
    result = normalize_news(raw, 'TEST', NOW)
    assert result['state'] == 'available' and len(result['items']) == 2
    assert len(result['items'][0]['title']) <= 240
    assert result['association'] == 'provider-linked' and raw == original
    pulse = assessment(news=result)
    assert pulse['news_context']['recent_count'] == 1
    assert 'ผู้ให้ข้อมูลเชื่อมโยง' in pulse['news_context']['note']


@pytest.mark.parametrize('changes', [
    {'pubDate':'2026-09-21T14:30:01Z'}, {'pubDate':'2026-09-21T14:00:00'},
    {'pubDate':None}, {'provider':None}, {'title':''},
    {'canonicalUrl':{'url':'javascript:alert(1)'}},
    {'canonicalUrl':{'url':'https://user:secret@example.com/story'}},
    {'canonicalUrl':{'url':'https://example.com:444/story'}},
    {'canonicalUrl':{'url':'https://127.0.0.1/story'}},
    {'canonicalUrl':{'url':'https://service.internal/story'}},
    {'relatedTickers':['OTHER']},
])
def test_unverified_news_cannot_become_a_recent_company_headline(changes):
    result = normalize_news([news_item(**changes)], 'TEST', NOW)
    assert result['state'] == 'unavailable' and result['items'] == []


def test_headline_language_and_missing_news_never_change_momentum_or_entry():
    rising = normalize_news([news_item('Shares rocket after major success')], 'TEST', NOW)
    falling = normalize_news([news_item('Shares crash after major failure')], 'TEST', NOW)
    results = [assessment(news=value) for value in [rising, falling, None]]
    assert all(result['state'] == 'strong' for result in results)
    assert all(result['metrics'] == results[0]['metrics'] for result in results)
    weak = assessment(stock=quote(regularMarketPrice=101), news=rising)
    assert weak['state'] == 'watch'


def test_empty_failed_old_and_other_ticker_news_are_distinct_and_never_refreshed_by_calculation():
    empty = normalize_news([], 'TEST', NOW)
    failed = normalize_news(None, 'TEST', NOW)
    old = normalize_news([news_item()], 'TEST', '2026-09-21T14:00:00Z')
    other = normalize_news([news_item()], 'OTHER', NOW)
    assert assessment(news=empty)['news_context']['state'] == 'empty'
    assert assessment(news=failed)['news_context']['state'] == 'unavailable'
    pulse = assessment(news=old)
    assert pulse['news_context']['state'] == 'stale'
    assert pd.Timestamp(pulse['news_context']['checked_at']) == pd.Timestamp(old['checked_at'])
    assert assessment(news=other)['news_context']['state'] == 'unavailable'


def test_invalid_assessment_clock_and_absent_data_return_unknown_without_exception():
    pulse = assess_pulse({}, None, None, None, now='invalid', snapshot_at=NOW)
    assert pulse['state'] == 'unknown' and pulse['calculated_at'] is None
    assert pulse['metrics']['known_count'] == 0


def test_declared_delayed_feed_cannot_be_strong_despite_new_looking_quote_timestamp():
    pulse = assessment(stock=quote(exchangeDataDelayedBy=15))
    assert pulse['state'] == 'unknown' and pulse['metrics']['known_count'] == 0
    assert any('ล่าช้า 15 นาที' in caution for caution in pulse['cautions'])
    assert assessment(spy=quote('SPY', exchangeDataDelayedBy=15))['metrics']['relative_spy_pp'] is None
    assert assessment(stock=quote(exchangeDataDelayedBy=None))['state'] == 'strong'


def test_thresholds_accept_float_noise_but_do_not_round_up_near_misses():
    stock = {**quote(), 'change_pct':2-5e-15, 'volume':1500}
    spy = {**quote('SPY'), 'change_pct':1}
    assert assessment(stock=stock, spy=spy)['state'] == 'strong'
    assert assessment(stock={**stock, 'change_pct':1.999}, spy=spy)['state'] == 'watch'
    assert assessment(stock={**stock, 'volume':1499.99}, spy=spy)['state'] == 'watch'


def test_nonfinite_derived_values_cannot_pass_criteria_or_become_plan_ratios():
    stock = {**quote(), 'volume':1e308, 'average_volume':1e-308}
    pulse = assessment(stock=stock)
    assert pulse['state'] == 'unknown' and pulse['metrics']['volume_ratio'] is None
    stock = {**quote(), 'change_pct':1e308}
    spy = {**quote('SPY'), 'change_pct':-1e308}
    pulse = assessment(stock=stock, spy=spy)
    assert pulse['metrics']['relative_spy_pp'] is None and pulse['state'] == 'unknown'
    tiny_price = {**quote(), 'price':2e-308}
    pulse = assessment(stock=tiny_price, row={**base_row(), 'stop':1e-308, 'target':1e308})
    assert pulse['metrics']['current_rr'] is None
    assert quote(regularMarketPreviousClose=1e-308, regularMarketPrice=1e308)['change_pct'] is None
