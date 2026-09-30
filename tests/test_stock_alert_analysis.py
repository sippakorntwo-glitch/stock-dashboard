"""Technical clock correctness and separation of news facts from interpretation."""
from datetime import datetime, timezone
import unittest

import pandas as pd

from stock_alert_analysis import daily_technicals, industry_labels, technical_analysis, news_analysis
from stock_alert_briefing import build_briefing, format_briefing_text
from stock_alert_report import text_chunks, refresh_report_quotes
from tests.test_stock_alert_briefing import row, payload, article, NOW


class AnalysisTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({'Close': range(100, 350)},
                            index=pd.date_range(end='2026-09-28', periods=250, freq='B'))

    def test_ema_is_computed_from_daily_history_not_provider_sma(self):
        history = self.history()
        result = daily_technicals(history, 55)
        self.assertAlmostEqual(result['ema200'], history.Close.ewm(span=200, adjust=False).mean().iloc[-1])
        self.assertGreater(result['ema20'], result['ema50'])
        self.assertEqual(result['asof'], '2026-09-28')
        self.assertEqual(result['rsi14'], 55)

    def test_incomplete_bad_or_unsorted_history_never_fabricates_ema(self):
        history = self.history()
        bad = history.copy(); bad.iloc[10, 0] = 0
        missing = history.copy(); missing.iloc[10, 0] = float('nan')
        for value in (history.head(199), bad, missing, history.iloc[::-1], pd.DataFrame()):
            self.assertEqual(daily_technicals(value, 55), {})

    def test_technical_dates_and_rsi_do_not_override_entry_checks(self):
        value = row(); value['technical'] = daily_technicals(self.history(), 25)
        result = technical_analysis(value, NOW)
        self.assertIn('รอสัญญาณกลับตัว', result['momentum'])
        self.assertIn('ระยะสั้นเอนขึ้น', result['short_term'])
        for date in ('2026-09-30', '2026-09-01', None):
            value['technical']['asof'] = date
            value.pop('price_asof', None)
            self.assertFalse(technical_analysis(value, NOW)['current'])
        value['ready_at_calculation'] = False
        self.assertEqual(build_briefing(payload([value]), NOW, lambda _: [])['cards'][0]['status'], 'watch')

    def test_two_level_industry_and_etf_category_are_distinct(self):
        value = row(); value['info'].update(sector='Healthcare', industry='Medical Devices')
        result = industry_labels(value)
        self.assertEqual((result['sector_th'], result['industry_th']), ('สุขภาพ', 'อุปกรณ์การแพทย์'))
        value['asset_type'] = 'ETF'
        self.assertEqual(industry_labels(value)['sector_th'], 'กองทุน ETF')

    def test_unread_headline_has_two_conditional_cases_without_verified_sentiment(self):
        item = {'title': 'Should you buy ACME after earnings?', 'topic': 'ผลประกอบการ',
                'context': 'เทียบกำไรกับงบ', 'evidence_type': 'provider_headline', 'direction': 'positive'}
        result = news_analysis(item)
        self.assertEqual(result['type_label'], 'บทวิเคราะห์/ความเห็น')
        self.assertEqual(result['direction'], 'unassessed')
        self.assertTrue(result['positive_case'].startswith('หาก'))
        self.assertTrue(result['negative_case'].startswith('หาก'))

    def test_five_cards_two_articles_fit_one_line_push_without_losing_sources(self):
        values = [row(ticker) for ticker in ('ACME', 'BET', 'CAT', 'DOG', 'EGG')]
        for value in values:
            value['technical'] = daily_technicals(self.history(), 55)
        def news(ticker):
            first = article(ticker+' Industries quarterly earnings')
            second = article(ticker+' Industries acquisition agreement')
            first['content']['canonicalUrl'] = {'url': 'https://example.com/'+ticker+'/one'}
            second['content']['canonicalUrl'] = {'url': 'https://example.com/'+ticker+'/two'}
            return [first, second]
        text = format_briefing_text(build_briefing(payload(values), NOW, news))
        chunks = text_chunks(text)
        self.assertLessEqual(len(chunks), 4)
        for ticker in ('ACME', 'BET', 'CAT', 'DOG', 'EGG'):
            self.assertIn('https://example.com/'+ticker+'/two', text)
        self.assertIn('อุตสาหกรรม:', text)
        self.assertIn('EMA200', text)

    def test_closed_report_prices_keep_source_clock_and_never_become_entry(self):
        value = row(); value['quote_time'] = '2026-09-28T20:00:00Z'
        value['ready_at_calculation'] = False
        now = datetime(2026, 9, 30, 3, tzinfo=timezone.utc)
        raw = [{'symbol': 'ACME', 'regularMarketPrice': 11,
                'regularMarketTime': datetime(2026, 9, 29, 20, tzinfo=timezone.utc).timestamp(),
                'postMarketPrice': 11.1,
                'postMarketTime': datetime(2026, 9, 29, 23, tzinfo=timezone.utc).timestamp(),
                'marketState': 'CLOSED', 'currency': 'USD'}]
        p = payload([value]); p['computed_at'] = now.isoformat()
        self.assertEqual(refresh_report_quotes(p, ['ACME'], lambda _: raw, now, allow_closed=True), 1)
        report = build_briefing(p, now, lambda _: [])
        self.assertFalse(report['cards'][0]['quote_fresh'])
        self.assertEqual(report['cards'][0]['status'], 'watch')
        self.assertIn('ราคาตลาดปกติล่าสุด $11.00', format_briefing_text(report))
        self.assertIn('หลังตลาด: $11.10', format_briefing_text(report))


if __name__ == '__main__':
    unittest.main()
