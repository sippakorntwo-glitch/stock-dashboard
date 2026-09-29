import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import urllib.error
import sys
import threading
from types import SimpleNamespace

from ranking_policy import POLICY, entry_checks
from stock_alert_briefing import (MODEL, build_briefing, fetch_company_news,
                                  format_briefing_text, select_rows, fetch_alert_news,
                                  fetch_news_rss, parse_news_rss, NewsFeedError,
                                  MAX_RSS_BYTES, _NoNewsRedirect)

NOW = datetime(2026, 9, 29, 18, 40, tzinfo=timezone.utc)


def row(ticker='ACME', asset_type='Common Stock', ready=True):
    value = {
        'ticker': ticker, 'name': ticker + ' Industries Inc.', 'asset_type': asset_type,
        'score': 90, 'coverage': 100, 'qualified': True, 'ready_at_calculation': ready,
        'quote': 10, 'quote_time': (NOW - timedelta(minutes=1)).isoformat(),
        'zone_low': 9.9, 'zone_high': 10.1, 'stop': 9, 'target': 13,
        'info_fetched_at': NOW.isoformat(),
        'info': {'currency': 'USD', 'financialCurrency': 'USD', 'bid': 9.99, 'ask': 10.01,
                 'sector': 'Industrials', 'industry': 'Tools', 'trailingEps': 2,
                 'profitMargins': 0.1, 'operatingCashflow': 30_000_000,
                 'freeCashflow': 20_000_000, 'revenueGrowth': 0.2,
                 'totalDebt': 40_000_000, 'totalCash': 30_000_000,
                 'earningsTimestamp': (NOW + timedelta(days=25)).timestamp(),
                 'category': 'Broad Market', 'totalAssets': 200_000_000},
    }
    value['entry_audit'] = entry_checks(value, NOW)
    return value


def payload(rows=None):
    return {'schema': 1, 'model': MODEL, 'entry_policy': POLICY,
            'computed_at': NOW.isoformat(), 'items': rows if rows is not None else [row()]}


def article(title='ACME Industries announces quarterly results', days=1, **extra):
    return {'content': {'title': title, 'provider': {'displayName': 'Company IR'},
                        'canonicalUrl': {'url': 'https://example.com/news/' + str(days)},
                        'pubDate': (NOW - timedelta(days=days)).isoformat(), **extra}}


def reviewed(**extra):
    return {'title': 'ACME Industries updates investors', 'publisher': 'ACME Industries',
            'url': 'https://example.com/ir', 'published_at': '2026-09-08',
            'date_precision': 'day', 'reviewed_at': NOW.isoformat(),
            'summary_th': 'บริษัทเผยยอดขายเติบโต', 'company_relevance': 'ผู้ผลิตเครื่องมือ',
            'positive_th': 'มุมมอง: ยอดขายเพิ่มอาจช่วยกำไร', 'negative_th': 'ยังไม่ทราบกำไรสุทธิ', **extra}


class SelectionTests(unittest.TestCase):
    def test_prefer_equities_but_include_triggering_etf(self):
        board = payload([row('ETFONE', 'ETF'), row('A'), row('B'), row('ETFTWO', 'ETF'), row('C')])
        self.assertEqual([x['ticker'] for x in select_rows(board, limit=3)], ['A', 'B', 'C'])
        self.assertEqual([x['ticker'] for x in select_rows(board, ['ETFTWO'], limit=3)], ['ETFTWO', 'A', 'B'])

    def test_actual_count_is_honest(self):
        report = build_briefing(payload(), NOW, lambda ticker: [])
        self.assertEqual((report['requested_count'], report['actual_count']), (5, 1))

    def test_duplicate_tickers_and_boolean_scores_rejected(self):
        for rows in ([row(), row()], [dict(row(), score=True)]):
            with self.assertRaises(ValueError):
                select_rows(payload(rows))

    def test_stale_future_and_unzoned_snapshot_rejected_before_fetch(self):
        for value in ((NOW - timedelta(minutes=36)).isoformat(),
                      (NOW + timedelta(seconds=1)).isoformat(), '2026-09-29T18:40:00'):
            board = payload()
            board['computed_at'] = value
            with self.assertRaises(ValueError):
                build_briefing(board, NOW, lambda ticker: self.fail('must not fetch'))


class EntryExplanationTests(unittest.TestCase):
    def test_status_requires_saved_ready_and_current_checklist(self):
        good, watch = row('GOOD'), row('WATCH', ready=False)
        report = build_briefing(payload([good, watch]), NOW, lambda ticker: [])
        self.assertEqual([c['status'] for c in report['cards']], ['entry', 'watch'])
        self.assertEqual(report['cards'][0]['rr'], 3)
        self.assertIn('รอการยืนยัน', report['cards'][1]['next_step'])

    def test_stale_quote_becomes_watch_and_keeps_source_time(self):
        value = row()
        value['quote_time'] = (NOW - timedelta(minutes=16)).isoformat()
        card = build_briefing(payload([value]), NOW, lambda ticker: [])['cards'][0]
        self.assertEqual(card['status'], 'watch')
        self.assertFalse(card['quote_fresh'])
        self.assertEqual(card['quote_time'], value['quote_time'])
        self.assertIn('15 นาที', card['situation'])

    def test_outside_zone_and_invalid_stop_do_not_offer_entry(self):
        value = row()
        value.update(quote=11, stop=12)
        card = build_briefing(payload([value]), NOW, lambda ticker: [])['cards'][0]
        self.assertEqual(card['status'], 'watch')
        self.assertIsNone(card['rr'])
        self.assertIn('สูงกว่าโซน', card['situation'])

    def test_missing_or_stale_financials_are_unknown_not_positive(self):
        value = row()
        value['info_fetched_at'] = (NOW - timedelta(days=8)).isoformat()
        card = build_briefing(payload([value]), NOW, lambda ticker: [])['cards'][0]
        self.assertEqual(card['positive_factors'], [])
        self.assertIn('เกิน 7 วัน', card['risk_factors'][0])

    def test_reit_is_explicit_and_existing_sector_blocker_remains(self):
        value = row()
        value['info'].update(industry='REIT - Hotel & Motel', sector='Real Estate')
        card = build_briefing(payload([value]), NOW, lambda ticker: [])['cards'][0]
        self.assertEqual(card['asset_type'], 'REIT')
        self.assertEqual(card['status'], 'watch')
        self.assertIn('ธุรกิจในขอบเขตเกณฑ์กระแสเงินสด', card['blockers'])


class NewsEvidenceTests(unittest.TestCase):
    def test_related_current_story_retains_exact_publisher_url_time(self):
        raw = article()
        news = fetch_company_news(row(), NOW, lambda ticker: [raw])
        self.assertEqual(news['state'], 'available')
        story = news['items'][0]
        self.assertEqual(story['publisher'], 'Company IR')
        self.assertEqual(story['published_at'], raw['content']['pubDate'])
        self.assertEqual(story['direction'], 'unassessed')
        self.assertEqual((story['positive_th'], story['negative_th']), ('', ''))
        self.assertIn('สูงกว่าคาด', story['context'])

    def test_unrelated_future_unsafe_and_old_stories_not_shown(self):
        unsafe = article()
        unsafe['content']['canonicalUrl']['url'] = 'http://example.com/insecure'
        articles = [article('Different company earnings'), article(days=-1), article(days=31), unsafe]
        news = fetch_company_news(row(), NOW, lambda ticker: articles)
        self.assertEqual(news['items'], [])
        self.assertNotIn('ไม่มีข่าวร้าย', news['note'].replace('ยังสรุปว่าไม่มีข่าวร้ายไม่ได้', ''))

    def test_bare_word_ticker_is_not_company_relevance(self):
        value = row('GAP')
        value['name'] = 'Gap, Inc.'
        news = fetch_company_news(value, NOW, lambda ticker: [article('A gap in market earnings expectations')])
        self.assertEqual(news['items'], [])

    def test_capitalized_ambiguous_company_word_needs_identity_evidence(self):
        value = row('GAP')
        value['name'] = 'Gap, Inc.'
        for title in ('Gap Between Bond Yields Widens', 'INFO On This Week\'s Economy'):
            if title.startswith('INFO'):
                value = row('INFO')
                value['name'] = 'INFO Inc.'
            news = fetch_company_news(value, NOW, lambda ticker: [article(title)])
            self.assertEqual(news['items'], [])
        value = row('GAP')
        value['name'] = 'Gap Inc.'
        news = fetch_company_news(value, NOW, lambda ticker: [article('Gap Inc. announces quarterly results')])
        self.assertEqual(len(news['items']), 1)
        news = fetch_company_news(value, NOW, lambda ticker: [article('Old Navy opens stores', relatedTickers=['GAP'])])
        self.assertEqual(len(news['items']), 1)

    def test_old_context_label_and_recent_preference(self):
        old = article(days=20)
        news = fetch_company_news(row(), NOW, lambda ticker: [old])
        self.assertIn('บริบทเก่า', news['items'][0]['age_label'])
        news = fetch_company_news(row(), NOW, lambda ticker: [old, article(days=2)])
        self.assertEqual(len(news['items']), 1)
        self.assertEqual(news['items'][0]['age_label'], 'ข่าวใน 7 วัน')

    def test_failure_does_not_mean_empty_or_no_bad_news(self):
        def fail(ticker):
            raise RuntimeError('secret-in-provider-error')
        news = fetch_company_news(row(), NOW, fail)
        self.assertEqual(news['state'], 'unavailable')
        self.assertIn('ดึงข่าวไม่ได้', news['note'])
        self.assertNotIn('secret', str(news))
        self.assertEqual(fetch_company_news(row(), NOW, lambda ticker: [])['state'], 'empty')

    def test_same_url_deduplicated_and_relevant_sixth_item_survives(self):
        raw = [article('Different company update') for _ in range(5)] + [article(), article()]
        news = fetch_company_news(row(), NOW, lambda ticker: raw)
        self.assertEqual(len(news['items']), 1)

    def test_day_precision_reviewed_source_with_specific_effects(self):
        news = fetch_company_news(row(), NOW, lambda ticker: [], {'ACME': [reviewed()]})
        item = news['items'][0]
        self.assertEqual(item['date_precision'], 'day')
        self.assertEqual(item['evidence_type'], 'reviewed_source')
        self.assertEqual(item['summary_th'], 'บริษัทเผยยอดขายเติบโต')
        self.assertIn('บริบทเก่า', item['age_label'])

    def test_failed_live_feed_with_curated_fallback_is_explicit(self):
        def fail(ticker):
            raise ValueError('network failed')
        news = fetch_company_news(row(), NOW, fail, {'ACME': [reviewed()]})
        self.assertEqual((news['state'], news['feed_status']), ('available', 'unavailable'))
        self.assertIn('ฟีดข่าวรอบนี้ดึงไม่ได้', news['note'])
        self.assertNotIn('ไม่พบข่าว', news['note'])

    def test_reviewed_date_visible_and_failed_feed_not_hidden_in_text(self):
        def fail(ticker):
            raise ValueError('network failed')
        report = build_briefing(payload(), NOW, fail, verified_news={'ACME': [reviewed()]})
        text = format_briefing_text(report)
        self.assertIn('ตรวจข่าว 30/09 01:40 น. ไทย', text)
        self.assertIn('ฟีดข่าวรอบนี้ดึงไม่ได้', text)

    def test_curated_evidence_requires_review_time_and_provenance(self):
        invalid = [reviewed(reviewed_at=(NOW + timedelta(hours=1)).isoformat()),
                   reviewed(company_relevance=''), reviewed(url='file:///tmp/report'),
                   reviewed(reviewed_at=(NOW - timedelta(days=8)).isoformat())]
        news = fetch_company_news(row(), NOW, lambda ticker: [], {'ACME': invalid})
        self.assertEqual(news['items'], [])

    def test_no_generic_disclaimer_and_beginner_explanations_present(self):
        report = build_briefing(payload(), NOW, lambda ticker: [],
                                verified_news={'ACME': [reviewed()]})
        text = format_briefing_text(report)
        self.assertNotIn('ไม่รับประกัน', text)
        for required in ('ด้านบวกของข่าว', 'ด้านลบ/จุดติดตาม', 'R:R =', 'จำนวนหุ้น =', 'https://example.com/ir'):
            self.assertIn(required, text)


def rss_item(title='ACME Industries quarterly results', pubdate='Tue, 29 Sep 2026 17:00:00 GMT',
             link='https://example.com/news', source='Company IR'):
    return (f'<rss version="2.0"><channel><title>Stock news</title><item><title>{title}</title>'
            f'<link>{link}</link><pubDate>{pubdate}</pubDate><source>{source}</source>'
            '</item></channel></rss>').encode()


class RSSFallbackTests(unittest.TestCase):
    def test_rss_source_datetime_kept_without_fabricated_related_ticker(self):
        values = parse_news_rss(rss_item(), 'ACME', NOW)
        self.assertEqual(values[0]['providerPublishTime'], '2026-09-29T17:00:00+00:00')
        self.assertEqual(values[0]['publisher'], 'Company IR')
        self.assertNotIn('relatedTickers', values[0])
        self.assertEqual(values[0]['association'], 'rss-request-context')
        news = fetch_company_news(row(), NOW, lambda ticker: values)
        self.assertEqual(len(news['items']), 1)

    def test_rss_ambiguous_generic_title_still_fails_company_identity(self):
        value = row('GAP')
        value['name'] = 'Gap Inc.'
        values = parse_news_rss(rss_item(title='Gap Between Bond Yields Widens'), 'GAP', NOW)
        news = fetch_company_news(value, NOW, lambda ticker: values)
        self.assertEqual(news['items'], [])

    def test_rss_future_unzoned_unsafe_links_and_invalid_dates_rejected(self):
        for xml in (rss_item(pubdate='Wed, 30 Sep 2026 17:00:00 GMT'),
                    rss_item(pubdate='Tue, 29 Sep 2026 17:00:00'),
                    rss_item(pubdate='not a date'), rss_item(link='http://example.com/news'),
                    rss_item(link='https://user:password@example.com/news')):
            with self.assertRaises(NewsFeedError):
                parse_news_rss(xml, 'ACME', NOW)

    def test_rss_invalid_xml_html_dtd_and_size_fail_closed(self):
        for xml in (b'<rss', b'<html><body>Login</body></html>',
                    b'<!DOCTYPE rss [<!ENTITY e SYSTEM "file:///etc/passwd">]><rss><channel/></rss>',
                    b'<rss><channel/></rss>'.decode().encode('utf-16'),
                    b' ' * (MAX_RSS_BYTES + 1)):
            with self.assertRaises(NewsFeedError):
                parse_news_rss(xml, 'ACME', NOW)
        self.assertEqual(parse_news_rss(b'<rss><channel/></rss>', 'ACME', NOW), [])

    def test_empty_primary_is_success_and_does_not_call_fallback(self):
        result = fetch_alert_news('ACME', NOW, lambda ticker: [], lambda *args: self.fail('not needed'))
        self.assertEqual((result['source'], result['items']), ('yahoo_primary', []))

    def test_primary_timeout_uses_rss_with_safe_diagnostics(self):
        def timeout(ticker):
            raise TimeoutError('private-api-key-and-token-must-not-leak')
        result = fetch_alert_news('ACME', NOW, timeout, lambda ticker, now: parse_news_rss(rss_item(), ticker, now))
        self.assertEqual(result['source'], 'yahoo_rss')
        self.assertEqual(result['primary_error'], 'TimeoutError')
        self.assertNotIn('private-api-key', str(result))

    def test_access_denials_rate_limits_and_explicit_botblock_never_fallback(self):
        errors = [urllib.error.HTTPError('https://example.com', status, 'denied', None, None)
                  for status in (401, 403, 407, 429)]
        errors.append(ValueError('Captcha: bot detection'))
        for error in errors:
            def fail(ticker):
                raise error
            result = fetch_alert_news('ACME', NOW, fail, lambda *args: self.fail('must not bypass block'))
            self.assertIsNone(result['items'])
            self.assertEqual(result['fallback_error'], 'not_attempted_access_or_rate_blocked')

    def test_fallback_failure_sanitized_and_no_third_attempt(self):
        def primary(ticker):
            raise ValueError('raw response private value')
        def fallback(ticker, now):
            raise NewsFeedError('invalid_rss_xml')
        result = fetch_alert_news('ACME', NOW, primary, fallback)
        self.assertEqual(result['primary_error'], 'ValueError')
        self.assertEqual(result['fallback_error'], 'invalid_rss_xml')
        self.assertIsNone(result['items'])

    def test_rss_request_uses_fixed_https_host_bounded_read_and_no_redirect(self):
        calls = {}
        class Response:
            status = 200
            headers = {}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return 'https://finance.yahoo.com/rss/headline?s=ACME'
            def read(self, count):
                calls['read_limit'] = count
                return rss_item()
        class Opener:
            def open(self, request, timeout):
                calls['url'] = request.full_url
                calls['timeout'] = timeout
                calls['headers'] = dict(request.header_items())
                return Response()
        with patch('stock_alert_briefing.urllib.request.build_opener', return_value=Opener()):
            result = fetch_news_rss('ACME', NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(calls['url'], 'https://finance.yahoo.com/rss/headline?s=ACME')
        self.assertEqual(calls['timeout'], 10)
        self.assertEqual(calls['read_limit'], MAX_RSS_BYTES + 1)
        self.assertNotIn('Authorization', calls['headers'])
        self.assertNotIn('Cookie', calls['headers'])
        self.assertIsNone(_NoNewsRedirect().redirect_request(None, None, None, None, None, None))


class PrimaryNewsBlockTests(unittest.TestCase):
    def _provider_call(self, body, payload, json_must_not_run=False):
        from market_pulse_service import fetch_news
        class Response:
            content = body
            def raise_for_status(self):
                pass
            def json(self):
                if json_must_not_run:
                    raise AssertionError('challenge must be detected before JSON parse')
                return payload
        provider = SimpleNamespace(post=lambda *args, **kwargs: Response())
        modules = {'yfinance.data': SimpleNamespace(YfData=lambda: provider),
                   'dashboard_runtime': SimpleNamespace(core=SimpleNamespace(_PROVIDER_LOCK=threading.RLock()))}
        with patch.dict(sys.modules, modules):
            return fetch_news('ACME')

    def test_http200_unauthorized_and_rate_envelopes_preserve_denial(self):
        from market_pulse_service import NewsProviderBlocked
        for value, code in (({'error': {'code': 'Unauthorized', 'description': 'private-cookie'}}, 401),
                            ({'errors': [{'message': 'Too Many Requests'}]}, 429),
                            ({'data': {'errors': [{'code': 'Forbidden'}]}}, 403)):
            with self.assertRaises(NewsProviderBlocked) as caught:
                self._provider_call(b'{"error":true}', value)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('private-cookie', str(caught.exception))
            result = fetch_alert_news('ACME', NOW,
                lambda ticker: self._provider_call(b'{"error":true}', value),
                lambda *args: self.fail('must not bypass HTTP 200 denial'))
            self.assertEqual(result['fallback_error'], 'not_attempted_access_or_rate_blocked')

    def test_http200_captcha_stops_before_json_decode_and_no_rss_attempt(self):
        from market_pulse_service import NewsProviderBlocked
        body = b'<html><body>Verify you are human. CAPTCHA secret-session</body></html>'
        with self.assertRaises(NewsProviderBlocked) as caught:
            self._provider_call(body, None, json_must_not_run=True)
        self.assertEqual(caught.exception.code, 403)
        self.assertNotIn('secret-session', str(caught.exception))

    def test_normal_article_word_and_generic_envelope_do_not_fake_denial(self):
        article_data = {'content': {'title': 'ACME wins lawsuit over access denied claim'}}
        envelope = {'data': {'tickerStream': {'stream': [article_data]}}}
        self.assertEqual(self._provider_call(b'{"data":{}}', envelope), [article_data])
        with self.assertRaisesRegex(ValueError, 'Invalid news envelope'):
            self._provider_call(b'{"errors":[]}', {'errors': ['Upstream temporarily unavailable']})


if __name__ == '__main__':
    unittest.main()
