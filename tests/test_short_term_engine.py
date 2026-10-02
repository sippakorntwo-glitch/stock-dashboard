import copy
from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd
import short_term_engine as e
from short_term_service import fresh_catalysts, scan

NOW = datetime(2026, 10, 2, 15, 16, tzinfo=timezone.utc)


def row():
    return dict(ticker='AAA', name='Acme', sector='Technology', industry='Hardware',
                currency='USD', asset_type='Common Stock', baseline_day='2026-10-01',
                average_shares_20d=2_000_000, average_dollars_20d=200_000_000,
                adr_20d=12., previous_close=100., previous_high=103.)


def raw_quote(ticker='AAA', **changes):
    value = dict(symbol=ticker, quoteType='EQUITY' if ticker != 'SPY' else 'ETF', currency='USD',
                 marketState='REGULAR', regularMarketPrice=104.05 if ticker == 'AAA' else 100.3,
                 regularMarketTime=NOW.timestamp() - 10, regularMarketPreviousClose=100.,
                 regularMarketVolume=630_000, bid=104.03, ask=104.06, exchangeDataDelayedBy=0)
    value.update(changes)
    return value


def bars(session='regular'):
    days = e.calendar('2026-10-02').index[-31:]
    frames = []
    for date in days:
        if date.date() > NOW.date():
            continue
        hour = '09:30' if session == 'regular' else '07:00'
        start = pd.Timestamp(str(date.date()) + ' ' + hour, tz=e.NY)
        values = []
        for i in range(21):
            close = 103 + i * .05
            values.append([close - .02, close + .08, close - .12, close,
                           30000 if date.date() == NOW.date() else 10000])
        frames.append(pd.DataFrame(values, index=pd.date_range(start, periods=21, freq='5min'),
                                   columns=['Open', 'High', 'Low', 'Close', 'Volume']))
    return pd.concat(frames)


def news(title='Acme reports second-quarter results', **changes):
    value = dict(title=title, publisher='Company release', link='https://example.com/results',
                 providerPublishTime=(NOW - timedelta(hours=1)).timestamp(), relatedTickers=['AAA'])
    value.update(changes)
    return {'items': [value]}


def pool():
    return {'model': e.MODEL, 'computed_at': NOW.isoformat(), 'items': [row()]}


class IntradayTests(unittest.TestCase):
    def test_real_session_calendar_early_close_and_next_trading_day(self):
        self.assertEqual(e.session_context(NOW)['next_day'], '2026-10-05')
        holiday = datetime(2026, 11, 26, 16, tzinfo=timezone.utc)
        self.assertEqual(e.session_context(holiday)['session'], 'closed')
        early = datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)
        self.assertEqual(e.session_context(early)['session'], 'closed')

    def test_rvol_is_matched_time_and_ignores_future_and_partial_bars(self):
        frame = bars()
        value, why = e.intraday_metrics(frame, NOW, 'regular')
        self.assertFalse(why)
        self.assertAlmostEqual(value['rvol'], 3.)
        self.assertEqual(value['session_volume'], 630000)
        partial = frame.tail(1).copy()
        partial.index = pd.DatetimeIndex([pd.Timestamp(NOW).tz_convert(e.NY).floor('5min')])
        partial['Volume'] = 1e9
        other, why = e.intraday_metrics(pd.concat([frame, partial]), NOW, 'regular')
        self.assertEqual(other['rvol'], value['rvol'])

    def test_missing_history_and_stale_or_bad_bars_block(self):
        frame = bars()
        short = frame.loc[frame.index.date >= datetime(2026, 10, 1).date()]
        self.assertEqual(e.intraday_metrics(short, NOW, 'regular')[1], 'insufficient_same_time_volume_history')
        self.assertEqual(e.intraday_metrics(frame, NOW + timedelta(minutes=20), 'regular')[1], 'stale_intraday_bars')
        frame.iloc[-1, frame.columns.get_loc('High')] = 1.
        self.assertEqual(e.intraday_metrics(frame, NOW, 'regular')[1], 'invalid_intraday_bars')

    def test_delayed_future_stale_currency_or_session_quotes_fail(self):
        for change in ({'exchangeDataDelayedBy': 15}, {'regularMarketTime': NOW.timestamp() + 1},
                       {'regularMarketTime': NOW.timestamp() - 181}, {'currency': 'CAD'},
                       {'marketState': 'PRE'}, {'symbol': 'BBB'}):
            self.assertIsNone(e.quote_observation(raw_quote(**change), 'AAA', NOW, 'regular'), change)
        quote = e.quote_observation(raw_quote(), 'AAA', NOW, 'regular')
        self.assertFalse(quote['spread_verified'])

    def test_premarket_never_borrows_regular_volume_or_timestamp(self):
        at = NOW.replace(hour=12)
        q = raw_quote(marketState='PRE', preMarketPrice=104., preMarketTime=at.timestamp() - 5,
                      regularMarketPrice=100., regularMarketTime=(at - timedelta(days=1)).timestamp(),
                      regularMarketVolume=999999999)
        observation = e.quote_observation(q, 'AAA', at, 'pre')
        self.assertEqual(observation['quote_time'], (at - timedelta(seconds=5)).isoformat())
        self.assertAlmostEqual(observation['change_pct'], 4.)
        self.assertIsNone(e.quote_observation(raw_quote(marketState='PRE'), 'AAA', at, 'pre'))
        metrics, why = e.intraday_metrics(bars('pre'), at, 'pre')
        self.assertFalse(why)
        self.assertLess(metrics['session_volume'], 999999999)

    def test_fresh_catalyst_is_not_old_news_generic_valuation_or_call_notice(self):
        good, why = fresh_catalysts(row(), news(), NOW)
        self.assertTrue(good)
        self.assertEqual(good[0]['direction'], 'unassessed')
        for item in (news('Acme schedules quarterly earnings conference call'),
                     news('Should you buy Acme after earnings?'),
                     news('Acme stock hits an all-time high'),
                     news(providerPublishTime=(NOW - timedelta(hours=37)).timestamp()),
                     news('Unrelated reports quarterly results', relatedTickers=['BBB'])):
            self.assertFalse(fresh_catalysts(row(), item, NOW)[0])
        self.assertEqual(fresh_catalysts(row(), {}, NOW)[1], 'news_feed_unavailable')

    def test_conditional_plan_accounts_for_costs_and_does_not_claim_executable_book(self):
        metrics, _ = e.intraday_metrics(bars(), NOW, 'regular')
        quote = e.quote_observation(raw_quote(), 'AAA', NOW, 'regular')
        articles, _ = fresh_catalysts(row(), news(), NOW)
        benchmark = e.quote_observation(raw_quote('SPY'), 'SPY', NOW, 'regular')
        plan, why = e.make_plan(row(), quote, metrics, articles, benchmark, NOW, 'regular')
        self.assertFalse(why)
        self.assertEqual(plan['status'], 'conditional_plan')
        self.assertGreaterEqual(plan['net_rr'], 2.)
        self.assertGreater(plan['cost_pct'], .3)
        self.assertFalse(plan['spread_verified'])
        too_narrow = dict(row(), adr_20d=1.)
        self.assertIn('insufficient_room_after_costs', e.make_plan(too_narrow, quote, metrics, articles, benchmark, NOW, 'regular')[1])
        self.assertIn('same_time_rvol_too_low', e.make_plan(row(), quote, dict(metrics, rvol=1.49), articles, benchmark, NOW, 'regular')[1])
        self.assertIn('outside_entry_zone_or_chasing', e.make_plan(row(), dict(quote, price=120.), metrics, articles, benchmark, NOW, 'regular')[1])

    def test_pool_rejects_etf_stale_or_low_liquidity_and_never_falls_back_to_top10(self):
        for changes in ({'asset_type': 'ETF'}, {'average_shares_20d': 43}, {'baseline_day': '2026-09-29'}):
            p = pool(); p['items'][0].update(changes)
            with self.assertRaises(ValueError): e.validate_pool(p, NOW)
        report = scan({'items': [row()]}, clock=lambda: NOW)
        self.assertEqual(report['status'], 'data_unavailable')
        self.assertFalse(report['cards'])

    def test_scan_refreshes_quotes_after_news_and_returns_fewer_than_five(self):
        calls = []
        def fetch(tickers):
            calls.append(tickers)
            return [raw_quote(t) for t in tickers]
        result = scan({'short_term_pool': pool()}, clock=lambda: NOW, quote_fetcher=fetch,
                      news_fetcher=lambda *args: news(), chart_fetcher=lambda _: bars())
        self.assertEqual(result['actual_count'], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['cards'][0]['status'], 'conditional_plan')

    def test_unavailable_news_never_becomes_no_bad_news_or_reused_daily_picks(self):
        result = scan({'short_term_pool': pool()}, clock=lambda: NOW,
                      quote_fetcher=lambda tickers: [raw_quote(t) for t in tickers],
                      news_fetcher=lambda *args: {'items': None}, chart_fetcher=lambda _: self.fail('Unexpected chart call'))
        self.assertEqual(result['actual_count'], 0)
        self.assertEqual(result['status'], 'data_unavailable')
        self.assertEqual(result['excluded']['news_feed_unavailable'], 1)

    def test_final_stale_quotes_do_not_reuse_first_batch(self):
        calls = []
        def fetch(tickers):
            calls.append(1)
            return [raw_quote(t, regularMarketTime=NOW.timestamp() - (5 if len(calls) == 1 else 1000)) for t in tickers]
        result = scan({'short_term_pool': pool()}, clock=lambda: NOW, quote_fetcher=fetch,
                      news_fetcher=lambda *args: news(), chart_fetcher=lambda _: bars())
        self.assertEqual(result['actual_count'], 0)
        self.assertEqual(result['excluded']['final_quote_not_fresh'], 1)


if __name__ == '__main__':
    unittest.main()
