import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

import line_alerts as a
from ranking_policy import entry_checks, POLICY

NOW = datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc)
RECIPIENT = 'U' + 'a' * 32


def board(tickers=('AAA',)):
    rows = []
    for ticker in tickers:
        row = dict(ticker=ticker, asset_type='ETF', score=90, coverage=100,
                   qualified=True, ready_at_calculation=True, quote=100.,
                   quote_time=(NOW-timedelta(minutes=2)).timestamp(),
                   zone_low=99., zone_high=101., stop=95., target=112.,
                   info_fetched_at=NOW.isoformat(),
                   info=dict(bid=99.95, ask=100.05, category='Broad market', totalAssets=1000000))
        row['entry_audit'] = entry_checks(row, NOW)
        rows.append(row)
    return dict(schema=1, model=a.MODEL, computed_at=NOW.isoformat(), entry_policy=POLICY, items=rows)


class Store:
    def __init__(self):
        self.value = {'schema': 1, 'recipients': {}}
        self.writes = 0
        self.fail_at = None

    def read(self):
        return copy.deepcopy(self.value)

    def write(self, value):
        self.writes += 1
        if self.writes == self.fail_at:
            raise a.AlertError('Simulated durable state failure')
        self.value = copy.deepcopy(value)


class Client:
    def __init__(self, store):
        self.store, self.sent = store, []
        self.quota, self.fail = True, False

    def verify(self):
        pass

    def available(self):
        return self.quota

    def push(self, pending):
        stored = list(self.store.value['recipients'].values())[0]['pending']
        assert pending == stored, 'Never send before durable reservation'
        self.sent.append(copy.deepcopy(pending))
        if self.fail:
            raise a.AlertError('Simulated uncertain send')


class EligibilityTests(unittest.TestCase):
    def test_valid_uses_existing_complete_entry_policy(self):
        self.assertEqual(len(a.eligible(board(), NOW)), 1)

    def test_stale_or_future_payload_never_alerts(self):
        for minutes in (-36, 1):
            p = board(); p['computed_at'] = (NOW+timedelta(minutes=minutes)).isoformat()
            self.assertEqual(a.eligible(p, NOW), [])

    def test_invalid_schema_and_duplicate_symbols_rejected(self):
        for p in (dict(board(), schema=99), board(('AAA', 'AAA'))):
            with self.assertRaises(a.AlertError): a.eligible(p, NOW)

    def test_stale_future_naive_missing_quote_blocked(self):
        for value in ((NOW-timedelta(minutes=16)).timestamp(), (NOW+timedelta(seconds=1)).timestamp(),
                      '2026-09-29T17:00:00', None):
            p=board(); p['items'][0]['quote_time']=value
            self.assertEqual(a.eligible(p, NOW), [])

    def test_score_coverage_zone_rr_and_spread_rechecked(self):
        for changes in ({'score':79}, {'coverage':99}, {'zone_high':99}, {'target':108},
                        {'qualified':False}, {'ready_at_calculation':False},
                        {'info':dict(bid=99,ask=102,category='ETF',totalAssets=1000000)}):
            p=board(); p['items'][0].update(changes)
            self.assertEqual(a.eligible(p, NOW), [], changes)

    def test_boolean_score_rejected(self):
        p=board(); p['items'][0]['score']=True
        with self.assertRaises(a.AlertError): a.eligible(p, NOW)

    def test_weekend_does_not_alert(self):
        self.assertEqual(a.eligible(board(), NOW+timedelta(days=4)), [])

    def test_message_has_source_time_actual_rr_and_limits(self):
        text=a.format_alert(board(tuple('A'+str(i) for i in range(10)))['items'], NOW)
        self.assertIn('R:R ที่ราคานี้ 2.40',text)
        self.assertIn('เวลา',text)
        self.assertLess(len(text.encode('utf-16-le'))//2,4900)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(); self.client=Client(self.store)

    def run_delivery(self,p=None,now=NOW,mode='scan'):
        return a.deliver(board() if p is None else p,self.store,self.client,RECIPIENT,now,mode)

    def test_batch_once_daily_and_new_symbol_still_alerts(self):
        self.assertEqual(self.run_delivery(board(('AAA','BBB')))['messages'],1)
        self.assertEqual(self.run_delivery(board(('AAA','BBB')))['messages'],0)
        self.assertEqual(self.run_delivery(board(('AAA','BBB','CCC')))['messages'],1)
        self.assertNotIn('AAA ·',self.client.sent[-1]['text'])

    def test_watch_only_never_sends(self):
        p=board();p['items'][0]['ready_at_calculation']=False
        self.assertEqual(self.run_delivery(p)['messages'],0)
        self.assertEqual(self.client.sent,[])

    def test_quota_exhausted_does_not_mark_sent(self):
        self.client.quota=False
        self.assertEqual(self.run_delivery()['status'],'quota_exhausted')
        self.assertEqual(self.client.sent,[])
        self.client.quota=True
        self.assertEqual(self.run_delivery()['messages'],1)

    def test_failed_reservation_never_sends(self):
        self.store.fail_at=1
        with self.assertRaises(a.AlertError):self.run_delivery()
        self.assertEqual(self.client.sent,[])

    def test_uncertain_send_reuses_identical_body_and_key(self):
        self.client.fail=True
        with self.assertRaises(a.AlertError):self.run_delivery()
        first=copy.deepcopy(self.client.sent[0]); self.client.fail=False
        p=board();p['items'][0]['quote']=100.1
        result=self.run_delivery(p, NOW+timedelta(seconds=5))
        self.assertEqual(self.client.sent[-1],first)
        self.assertEqual(result['messages'],1)
        self.assertEqual(self.run_delivery()['messages'],0)

    def test_accepted_then_state_write_failure_reuses_retry_key(self):
        self.store.fail_at=2
        with self.assertRaises(a.AlertError):self.run_delivery()
        first=self.client.sent[0]
        self.store.fail_at=None
        self.run_delivery()
        self.assertEqual(self.client.sent[-1],first)

    def test_expired_pending_never_sends_stale_or_duplicates(self):
        self.client.fail=True
        with self.assertRaises(a.AlertError):self.run_delivery()
        self.client.fail=False
        result=self.run_delivery(now=NOW+timedelta(minutes=20))
        self.assertEqual(len(self.client.sent),1)
        self.assertEqual(result['expired_pending'],1)
        self.assertEqual(result['messages'],0)

    def test_setup_test_only_once_and_no_private_identifiers_in_state(self):
        self.assertEqual(self.run_delivery(mode='test')['messages'],1)
        self.assertEqual(self.run_delivery(mode='test')['messages'],0)
        self.assertNotIn(RECIPIENT,json.dumps(self.store.value))
        self.assertNotIn('Bearer',json.dumps(self.store.value))


class RichReportTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(); self.client=Client(self.store)
        self.calls=[]

    def builder(self, payload, tickers, now, mode):
        self.calls.append((tickers,mode))
        return {'stocks':5, 'messages':[
            {'type':'image','originalContentUrl':'https://raw.githubusercontent.com/sippakorntwo-glitch/stock-dashboard/'+'a'*40+'/briefing.png',
             'previewImageUrl':'https://raw.githubusercontent.com/sippakorntwo-glitch/stock-dashboard/'+'a'*40+'/briefing-preview.png'},
            {'type':'text','text':'Five-stock report with dated sources'}]}

    def test_scan_caps_new_signals_at_five_and_leaves_remaining_for_next_run(self):
        p=board(tuple('A'+str(i) for i in range(7)))
        a.deliver(p,self.store,self.client,RECIPIENT,NOW,message_builder=self.builder)
        a.deliver(p,self.store,self.client,RECIPIENT,NOW,message_builder=self.builder)
        self.assertEqual([len(c[0]) for c in self.calls],[5,2])

    def test_no_signal_does_not_build_or_publish_a_report(self):
        p=board();p['items'][0]['ready_at_calculation']=False
        a.deliver(p,self.store,self.client,RECIPIENT,NOW,message_builder=self.builder)
        self.assertEqual(self.calls,[])

    def test_preview_works_for_watchlist_but_is_permanently_once(self):
        p=board();p['items'][0]['ready_at_calculation']=False
        for now in (NOW,NOW+timedelta(days=40)):
            a.deliver(p,self.store,self.client,RECIPIENT,now,'preview',self.builder)
        self.assertEqual(len(self.client.sent),1)
        self.assertEqual(self.calls,[([], 'preview')])

    def test_retry_keeps_exact_text_and_immutable_image(self):
        self.client.fail=True
        with self.assertRaises(a.AlertError):
            a.deliver(board(),self.store,self.client,RECIPIENT,NOW,message_builder=self.builder)
        first=copy.deepcopy(self.client.sent[0]); self.client.fail=False
        a.deliver(board(),self.store,self.client,RECIPIENT,NOW+timedelta(seconds=1),message_builder=self.builder)
        self.assertEqual(self.client.sent[-1],first)
        self.assertEqual(len(self.calls),1)

    def test_expiry_during_news_and_image_build_does_not_reserve_or_send(self):
        with self.assertRaises(a.AlertError):
            a.deliver(board(),self.store,self.client,RECIPIENT,NOW,message_builder=self.builder,
                      clock=lambda:NOW+timedelta(minutes=20))
        self.assertEqual(self.store.writes,0)
        self.assertEqual(self.client.sent,[])

    def test_image_url_cannot_change_to_mutable_or_external_host(self):
        for url in ('https://example.com/briefing.png',
                    'https://raw.githubusercontent.com/sippakorntwo-glitch/stock-dashboard/main/briefing.png'):
            with self.assertRaises(a.AlertError):
                a.validate_messages([{'type':'image','originalContentUrl':url,'previewImageUrl':url}])

    def test_text_split_preserves_emoji_and_source_links_under_line_limit(self):
        from stock_alert_report import text_chunks
        source='https://example.com/verified-news'
        parts=text_chunks(('บทวิเคราะห์ 📈'*700)+'\n\n'+source)
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=4400 for p in parts))
        self.assertIn(source,parts[-1])
        self.assertEqual(sum(p.count('📈') for p in parts),700)

    def test_current_price_refresh_never_upgrades_saved_readiness(self):
        from stock_alert_report import refresh_report_quotes
        p=board();p['items'][0]['ready_at_calculation']=False
        raw=[{'symbol':'AAA','regularMarketPrice':101.,'regularMarketTime':NOW.timestamp(),
              'marketState':'REGULAR','currency':'USD'}]
        self.assertEqual(refresh_report_quotes(p,['AAA'],lambda _:raw,NOW),1)
        self.assertEqual(p['items'][0]['quote'],101.)
        self.assertFalse(p['items'][0]['ready_at_calculation'])
        self.assertEqual(a.eligible(p,NOW),[])

    def test_bad_refresh_preserves_original_price_and_source_time(self):
        from stock_alert_report import refresh_report_quotes
        for extra in ({'currency':'EUR'},{'marketState':'PRE'},
                      {'regularMarketTime':(NOW+timedelta(seconds=1)).timestamp()},
                      {'regularMarketTime':(NOW-timedelta(minutes=30)).timestamp()}):
            p=board(); original=copy.deepcopy(p)
            raw=[dict(symbol='AAA',regularMarketPrice=101.,regularMarketTime=NOW.timestamp(),
                      marketState='REGULAR',currency='USD')]
            raw[0].update(extra)
            self.assertEqual(refresh_report_quotes(p,['AAA'],lambda _:raw,NOW),0)
            self.assertEqual(p,original)


class HTTPClientTests(unittest.TestCase):
    def pending(self):
        return dict(text='test',retry_key='00000000-0000-4000-a000-000000000000',
                    expires_at=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())

    def test_only_documented_409_means_accepted(self):
        client=a.LineClient('test-only-token',RECIPIENT,None)
        with patch.object(client,'call',return_value=(409,{'x-line-accepted-request-id':'accepted'},{})):
            client.push(self.pending())
        with patch.object(client,'call',return_value=(409,{},{})):
            with self.assertRaises(a.AlertError):client.push(self.pending())

    def test_expired_request_never_reaches_network(self):
        client=a.LineClient('test-only-token',RECIPIENT,None)
        pending=self.pending();pending['expires_at']=NOW.isoformat()
        with patch.object(client,'call') as call:
            with self.assertRaises(a.AlertError):client.push(pending)
            call.assert_not_called()

    def test_wrong_bot_and_unreachable_recipient_blocked(self):
        client=a.LineClient('test-only-token',RECIPIENT,None)
        with patch.object(client,'call',return_value=(200,{}, {'basicId':'@wrong'})):
            with self.assertRaises(a.AlertError):client.verify()
        with patch.object(client,'call',side_effect=[(200,{}, {'basicId':a.EXPECTED_BOT}),(404,{}, {})]):
            with self.assertRaises(a.AlertError):client.verify()


if __name__=='__main__':unittest.main()
