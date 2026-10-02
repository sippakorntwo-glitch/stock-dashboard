from copy import deepcopy
from datetime import timedelta
import unittest

import short_term_engine as e
from short_term_service import scan, fresh_catalysts, movement_priority
from short_term_report import format_report, notice_ids
from market_event_news import story_id
from market_event_monitor import deliver_urgent
from test_short_term_engine import NOW, row, raw_quote, pool, news, bars
from test_line_alerts import Store, RECIPIENT
from test_line_alert_schedule import ScheduledClient


def wdc_report():
    item = dict(row(), ticker='WDC', name='Western Digital', industry='Computer Hardware')
    source = dict(pool(), items=[item])
    frame = bars()
    frame[['Open', 'High', 'Low', 'Close']] *= 88 / 104
    def quotes(tickers):
        return [raw_quote(t, regularMarketPrice=88.05 if t == 'WDC' else 100.3) for t in tickers]
    headline = 'Seagate and Western Digital shares fall on Toshiba HDD expansion'
    return scan({'short_term_pool': source}, clock=lambda: NOW, quote_fetcher=quotes,
                news_fetcher=lambda *args: news(headline, relatedTickers=['WDC', 'STX']),
                chart_fetcher=lambda _: frame)


class EventDiscoveryTests(unittest.TestCase):
    def test_low_price_commissions_are_per_share_and_not_flat_point_three_percent(self):
        self.assertAlmostEqual(e.trade_cost_rate(10), .0061)
        self.assertAlmostEqual(e.trade_cost_rate(5), .0071)
        self.assertGreater(e.trade_cost_rate(2), .013)
        self.assertGreater(e.trade_cost_rate(1), .023)
        with self.assertRaises(ValueError): e.trade_cost_rate(0)

    def test_stock_below_ten_can_produce_a_plan_with_price_specific_cost(self):
        frame = bars(); frame[['Open', 'High', 'Low', 'Close']] /= 20
        frame.Volume *= 20
        metrics, why = e.intraday_metrics(frame, NOW, 'regular')
        small = dict(row(), previous_close=5., previous_high=5.15, adr_20d=2.)
        quote = e.quote_observation(raw_quote(regularMarketPrice=5.21, regularMarketPreviousClose=5.), 'AAA', NOW, 'regular')
        articles, _ = fresh_catalysts(small, news(), NOW)
        benchmark = e.quote_observation(raw_quote('SPY'), 'SPY', NOW, 'regular')
        plan, reasons = e.make_plan(small, quote, metrics, articles, benchmark, NOW, 'regular')
        self.assertNotIn('not_eligible_common_stock', reasons)
        self.assertIsNotNone(plan, reasons)
        self.assertGreater(plan['cost_pct'], .68)

    def test_competitor_capacity_news_is_relevant_without_ticker_in_title(self):
        for ticker in ('WDC', 'STX'):
            company = dict(row(), ticker=ticker, name='Different legal name')
            items, _ = fresh_catalysts(company, news('Toshiba plans to double HDD production capacity', relatedTickers=[]), NOW)
            self.assertEqual(items[0]['industry_impact']['impact_type'], 'competitor_supply')
        company = dict(row(), ticker='WDC', name='Western Digital')
        self.assertFalse(fresh_catalysts(company, news('Toshiba expands nuclear production capacity', relatedTickers=[]), NOW)[0])

    def test_negative_mover_is_discovered_but_not_bought_just_because_it_fell(self):
        report = wdc_report()
        self.assertEqual(report['actual_count'], 0)
        self.assertEqual(report['status'], 'events_watch')
        event = report['events'][0]
        self.assertEqual(event['ticker'], 'WDC')
        self.assertLess(event['change_pct'], -10)
        self.assertTrue(event['urgent'])
        self.assertEqual(event['status'], 'recovery_watch')
        self.assertIn('recovery_not_confirmed', event['reasons'])
        self.assertIn('1) WDC', format_report(report))
        self.assertIn('สถานะ: รอฟื้นตัว', format_report(report))

    def test_balanced_scan_keeps_losers_even_when_gainers_dominate_scores(self):
        values = [(10000 + i, dict(row(), ticker='UP' + str(i)), {'change_pct': 20}) for i in range(20)]
        values += [(1, dict(row(), ticker='WDC'), {'change_pct': -12})]
        chosen = movement_priority(values)
        self.assertEqual(len(chosen), 10)
        self.assertIn('WDC', [v[1]['ticker'] for v in chosen])

    def test_same_competitor_event_across_publishers_has_one_notice(self):
        event = wdc_report()['events'][0]
        first = event['news'][0]
        second = dict(first, url='https://example.com/another-publisher')
        self.assertEqual(story_id('WDC', first), story_id('WDC', second))
        self.assertNotEqual(story_id('STX', first), story_id('WDC', first))

    def test_supply_shortage_counterpoint_is_not_lost_in_generic_competition_explanation(self):
        from market_event_news import industry_impact
        impact = industry_impact('Analysts say Toshiba HDD expansion may not ease global supply shortage', 'WDC')
        self.assertIn('อาจยังไม่แก้ภาวะขาดแคลน', impact['counterpoint_th'])
        self.assertIn('อาจเพิ่มการแข่งขัน', impact['impact_th'])


class UrgentDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(); self.client = ScheduledClient(self.store)
        self.report = wdc_report()

    def builder(self, payload, now, report):
        return {'model': e.MODEL, 'stocks': len(report['cards']), 'events': len(report['events']),
                'messages': [{'type': 'text', 'text': 'Event test'}],
                'expires_at': (now + timedelta(minutes=2)).isoformat(), 'notice_ids': notice_ids(report)}

    def send(self, report=None, clock=None):
        return deliver_urgent(report or self.report, {}, self.store, self.client, RECIPIENT, NOW,
                              self.builder, clock or (lambda: NOW))

    def test_new_negative_event_sends_once_without_a_buy_plan(self):
        self.assertEqual(self.send()['messages'], 1)
        self.assertEqual(self.send()['messages'], 0)
        self.assertEqual(len(self.client.sent), 1)
        bucket = next(iter(self.store.value['recipients'].values()))
        self.assertEqual(bucket['event_budget']['used'], 1)
        self.assertEqual(bucket['quota_ledger']['conservative_used'], 1)

    def test_requested_new_format_can_show_seen_news_once_within_existing_budget(self):
        self.send()
        result = deliver_urgent(self.report, {}, self.store, self.client, RECIPIENT, NOW,
                                self.builder, lambda: NOW, presentation='format-unit-test')
        self.assertEqual(result['messages'], 1)
        again = deliver_urgent(self.report, {}, self.store, self.client, RECIPIENT, NOW,
                               self.builder, lambda: NOW, presentation='format-unit-test')
        self.assertEqual(again['status'], 'presentation_already_sent')
        bucket = next(iter(self.store.value['recipients'].values()))
        self.assertEqual(bucket['quota_ledger']['conservative_used'], 2)

    def test_two_additional_pushes_daily_and_overall_quota_are_hard_limits(self):
        self.send()
        report = deepcopy(self.report); report['events'][0]['event_id'] = 'other-story'
        self.assertEqual(self.send(report)['messages'], 1)
        report['events'][0]['event_id'] = 'third-story'
        self.assertEqual(self.send(report)['status'], 'event_budget_reached')
        self.assertEqual(len(self.client.sent), 2)
        self.store = Store(); self.client = ScheduledClient(self.store, used=300)
        self.assertEqual(self.send()['messages'], 0)

    def test_uncertain_push_resumes_existing_body_and_charges_budget_once(self):
        import line_alerts
        from line_alert_schedule import deliver_scheduled
        self.client.fail = True
        with self.assertRaises(line_alerts.AlertError): self.send()
        self.client.fail = False
        original = deepcopy(self.client.sent[0])
        result = deliver_scheduled({}, self.store, self.client, RECIPIENT, NOW, None, lambda: NOW)
        self.assertEqual(result['messages'], 1)
        self.assertEqual(self.client.sent[-1], original)
        self.assertEqual(next(iter(self.store.value['recipients'].values()))['event_budget']['used'], 1)

    def test_expiry_or_failed_durable_write_prevents_push(self):
        import line_alerts
        with self.assertRaises(line_alerts.AlertError):
            self.send(clock=lambda: NOW + timedelta(minutes=3))
        self.assertFalse(self.client.sent)
        self.store.fail_at = 1
        with self.assertRaises(line_alerts.AlertError): self.send()
        self.assertFalse(self.client.sent)


if __name__ == '__main__':
    unittest.main()
