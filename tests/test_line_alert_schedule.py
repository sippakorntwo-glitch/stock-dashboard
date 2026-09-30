import copy
from datetime import datetime, timedelta, timezone
import unittest

import line_alerts as alerts
import line_alert_schedule as schedule
from stock_alert_report import refresh_report_quotes
from stock_alert_briefing import build_briefing, format_briefing_text
from test_line_alerts import board, Store, Client, RECIPIENT

UTC = timezone.utc
REGULAR = datetime(2026, 10, 1, 13, 46, tzinfo=UTC)
PRE = datetime(2026, 10, 1, 13, 16, tzinfo=UTC)


def five_board(now):
    payload = board(('AAA', 'BBB', 'CCC', 'DDD', 'EEE'))
    payload['computed_at'] = now.isoformat()
    for row in payload['items']:
        row.update(quote_time=(now - timedelta(minutes=1)).isoformat(), info_fetched_at=now.isoformat())
    return payload


class ScheduledClient(Client):
    def __init__(self, store, used=0):
        super().__init__(store)
        self.used = used
        self.limit = 300

    def quota_snapshot(self):
        return {'type': 'limited', 'limit': self.limit, 'used': self.used,
                'remaining': max(0, self.limit - self.used)}


def bundle(payload, tickers, now, mode):
    return {'stocks': 5, 'messages': [{'type': 'text', 'text': 'test scheduled report'}],
            'expires_at': (now + timedelta(minutes=2)).isoformat()}


class CalendarTests(unittest.TestCase):
    def test_allocates_all_300_in_full_months_including_short_and_holiday_months(self):
        for period in ('2026-09', '2026-10', '2026-11', '2026-12', '2027-02'):
            plan, unused = schedule.allocation(period, 300)
            self.assertEqual(sum(map(len, plan.values())), 300, period)
            self.assertEqual(unused, 0, period)
            self.assertEqual(len({slot['id'] for day in plan.values() for slot in day}), 300)

    def test_holidays_have_no_slots_and_early_close_is_respected(self):
        slots = schedule.month_slots('2026-11')
        self.assertFalse(any(s['trading_date'] == '2026-11-26' for s in slots))
        early = [s for s in slots if s['trading_date'] == '2026-11-27']
        self.assertEqual(len(early), 12)
        self.assertEqual(early[-1]['expires_at'], '2026-11-27T18:00:00+00:00')
        self.assertIsNone(schedule.current_slot(datetime(2026, 11, 27, 18, 16, tzinfo=UTC)))

    def test_dst_changes_thai_time_automatically(self):
        summer = next(s for s in schedule.month_slots('2026-10') if s['trading_date'] == '2026-10-30')
        winter = next(s for s in schedule.month_slots('2026-11') if s['trading_date'] == '2026-11-02')
        self.assertEqual(schedule._time(summer['start']).astimezone(schedule.THAI).strftime('%H:%M'), '18:15')
        self.assertEqual(schedule._time(winter['start']).astimezone(schedule.THAI).strftime('%H:%M'), '19:15')

    def test_full_day_keeps_last_pre_round_and_has_roughly_30_percent_pre(self):
        plan, _ = schedule.allocation('2026-10', 300)
        day = plan['2026-10-01']
        pre = [s for s in day if s['session'] == 'pre']
        self.assertEqual(len(day), 14)
        self.assertEqual(len(pre), 4)
        self.assertEqual(pre[-1]['start'], '2026-10-01T13:15:00+00:00')

    def test_mid_month_or_last_day_never_produces_catchup_bursts(self):
        plan, unused = schedule.allocation('2026-09', 297, '2026-09-30')
        self.assertGreater(unused, 250)
        self.assertLessEqual(sum(map(len, plan.values())), 18)
        self.assertIsNone(schedule.current_slot(datetime(2026, 10, 1, 13, 31, tzinfo=UTC)))

    def test_budget_adapts_to_other_oa_consumption(self):
        high, _ = schedule.allocation('2026-10', 250, '2026-10-15')
        low, _ = schedule.allocation('2026-10', 50, '2026-10-15')
        self.assertGreater(sum(map(len, high.values())), sum(map(len, low.values())))
        self.assertEqual(sum(map(len, low.values())), 50)

    def test_quota_ledger_covers_approximate_api_lag_and_month_reset(self):
        bucket = {}
        quota = {'type': 'limited', 'limit': 300, 'used': 299}
        self.assertEqual(schedule.quota_remaining(bucket, quota, REGULAR), 1)
        bucket['quota_ledger']['conservative_used'] += 1
        self.assertEqual(schedule.quota_remaining(bucket, quota, REGULAR), 0)
        later = datetime(2026, 11, 2, 14, 16, tzinfo=UTC)
        self.assertEqual(schedule.quota_remaining(bucket, dict(quota, used=0), later), 300)

    def test_zero_quota_summary_and_high_quota_capacity_are_explicit(self):
        summary = schedule.schedule_summary({'type': 'limited', 'limit': 0, 'used': 0}, REGULAR)
        self.assertEqual(summary['next_month_planned'], 0)
        plan, unused = schedule.allocation('2026-10', 15000)
        self.assertGreater(unused, 14000)


class ScheduledDeliveryTests(unittest.TestCase):
    def send(self, store, client, now=REGULAR, payload=None, builder=bundle, clock=None):
        return alerts.deliver(payload or five_board(now), store, client, RECIPIENT, now,
                              'scheduled', builder, clock=clock)

    def test_five_watch_stocks_can_be_scheduled_without_manufacturing_buy_flags(self):
        store = Store(); client = ScheduledClient(store)
        payload = five_board(REGULAR)
        for row in payload['items']:
            row['ready_at_calculation'] = False
        result = self.send(store, client, payload=payload)
        self.assertEqual(result['messages'], 1)
        self.assertEqual(result['stocks'], 5)
        self.assertTrue(all(not row['ready_at_calculation'] for row in payload['items']))

    def test_same_slot_deduplicates_but_next_planned_slot_sends(self):
        store = Store(); client = ScheduledClient(store)
        self.send(store, client)
        self.assertEqual(self.send(store, client)['messages'], 0)
        next_round = REGULAR + timedelta(minutes=30)
        self.assertEqual(self.send(store, client, next_round)['messages'], 1)
        self.assertEqual(len(client.sent), 2)

    def test_uncertain_response_retries_same_body_and_quota_charge_once(self):
        store = Store(); client = ScheduledClient(store); client.fail = True
        with self.assertRaises(alerts.AlertError): self.send(store, client)
        reserved = copy.deepcopy(client.sent[0])
        client.fail = False
        result = self.send(store, client)
        self.assertEqual(result['messages'], 1)
        self.assertEqual(client.sent[1], reserved)
        self.assertEqual(next(iter(store.value['recipients'].values()))['quota_ledger']['conservative_used'], 1)

    def test_stale_board_or_exhausted_quota_never_sends(self):
        store = Store(); client = ScheduledClient(store)
        payload = five_board(REGULAR - timedelta(minutes=36))
        self.assertEqual(self.send(store, client, payload=payload)['messages'], 0)
        client.used = client.limit
        self.assertEqual(self.send(store, client)['messages'], 0)
        self.assertFalse(client.sent)

    def test_recheck_deadline_after_report_preparation(self):
        store = Store(); client = ScheduledClient(store)
        with self.assertRaises(alerts.AlertError):
            self.send(store, client, clock=lambda: REGULAR + timedelta(minutes=16))
        self.assertFalse(client.sent)

    def test_pending_expiry_is_suppressed_without_replacement_push(self):
        store = Store(); client = ScheduledClient(store); client.fail = True
        with self.assertRaises(alerts.AlertError): self.send(store, client)
        client.fail = False
        result = self.send(store, client, REGULAR + timedelta(minutes=30))
        self.assertEqual(result['status'], 'expired_pending')
        self.assertEqual(len(client.sent), 1)

    def test_failed_state_reservation_never_pushes(self):
        store = Store(); client = ScheduledClient(store); store.fail_at = 2
        with self.assertRaises(alerts.AlertError): self.send(store, client)
        self.assertFalse(client.sent)


class PreMarketTests(unittest.TestCase):
    def raw(self, **changes):
        raw = {'symbol': 'AAA', 'currency': 'USD', 'marketState': 'PRE',
               'regularMarketPrice': 98., 'regularMarketTime': int((PRE - timedelta(hours=18)).timestamp()),
               'regularMarketPreviousClose': 97., 'preMarketPrice': 100.,
               'preMarketTime': int((PRE - timedelta(minutes=1)).timestamp())}
        raw.update(changes)
        return [raw]

    def test_pre_price_has_own_timestamp_and_does_not_upgrade_regular_audit(self):
        payload = five_board(PRE); payload['report_session'] = 'pre'
        row = payload['items'][0]; row['ready_at_calculation'] = False
        original = copy.deepcopy(row['entry_audit'])
        self.assertEqual(refresh_report_quotes(payload, ['AAA'], lambda _: self.raw(), PRE, pre_market=True), 1)
        self.assertEqual(row['quote_session'], 'pre')
        self.assertEqual(row['quote'], 100.)
        self.assertEqual(row['entry_audit'], original)
        self.assertFalse(row['ready_at_calculation'])
        briefing = build_briefing(payload, PRE, news_fetcher=lambda _: [])
        card = briefing['cards'][0]
        self.assertEqual(card['status'], 'pre_candidate')
        self.assertFalse(card['pre_market_audit']['liquidity_confirmed'])
        self.assertEqual(briefing['entry_count'], 0)
        self.assertIn('ราคา Pre-market', format_briefing_text(briefing))

    def test_post_or_stale_future_wrong_currency_cannot_become_pre_price(self):
        for changes in ({'marketState': 'POST'}, {'preMarketTime': int((PRE - timedelta(minutes=16)).timestamp())},
                        {'preMarketTime': int((PRE + timedelta(seconds=1)).timestamp())}, {'currency': 'EUR'}):
            payload = five_board(PRE)
            refresh_report_quotes(payload, ['AAA'], lambda _: self.raw(**changes), PRE, pre_market=True)
            self.assertEqual(payload['items'][0]['quote_session'], 'regular', changes)

    def test_missing_pre_quote_is_labeled_and_old_bid_ask_never_confirms_liquidity(self):
        payload = five_board(PRE); payload['report_session'] = 'pre'
        briefing = build_briefing(payload, PRE, news_fetcher=lambda _: [])
        card = briefing['cards'][0]
        self.assertFalse(card['quote_fresh'])
        self.assertEqual(card['status'], 'watch')
        self.assertIn('ยังไม่มีราคา Pre-market', card['situation'])

    def test_unqualified_stock_is_not_promoted_to_pre_candidate(self):
        payload = five_board(PRE); payload['report_session'] = 'pre'
        payload['items'][0]['qualified'] = False
        refresh_report_quotes(payload, ['AAA'], lambda _: self.raw(), PRE, pre_market=True)
        card = build_briefing(payload, PRE, news_fetcher=lambda _: [])['cards'][0]
        self.assertEqual(card['status'], 'watch')


if __name__ == '__main__':
    unittest.main()
