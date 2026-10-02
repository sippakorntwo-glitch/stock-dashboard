from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from short_term_context import daily_context, company_context, company_view, trend_view, pack_context, unpack_context
from short_term_report import report_rows, format_report, render_report
from thai_news_translation import valid_translation, decode_translations, enrich_prepared, REVIEWED, protect_names, restore_names
from test_short_term_events import wdc_report


class ContextTests(unittest.TestCase):
    def test_context_compression_retains_evidence_and_rejects_foreign_symbols(self):
        rows = [{'ticker': 'AAA', 'company': {'business_en': 'Acme makes devices.'},
                 'daily_context': {'sma20': 5.1, 'sma50': None}}]
        original = deepcopy(rows)
        blob = pack_context(rows)
        pool = {'items': rows, 'context_version': 2, 'context_blob': blob}
        self.assertNotIn('company', rows[0])
        self.assertEqual(unpack_context(pool), original)
        pool['items'][0]['ticker'] = 'BBB'
        with self.assertRaises(ValueError): unpack_context(pool)

    def test_sma_uses_exact_completed_windows_and_does_not_invent_200_days(self):
        frame = pd.DataFrame({'Close': range(1, 211)}, index=pd.date_range('2025-01-01', periods=210))
        value = daily_context(frame)
        self.assertEqual(value['sma20'], 200.5)
        self.assertEqual(value['sma50'], 185.5)
        self.assertEqual(value['sma200'], 110.5)
        self.assertIsNone(daily_context(frame.tail(100))['sma200'])
        frame.iloc[-1, 0] = float('nan')
        self.assertIsNone(daily_context(frame)['sma20'])

    def test_undated_financials_cannot_support_company_growth_outlook(self):
        values = {'revenueGrowthFY': {'state': 'available', 'value': .2, 'end': None},
                  'profitMargins': {'state': 'available', 'value': .3, 'end': '2027-01-01'}}
        with patch('company_metrics.metric_observations', return_value=values):
            company = company_context('AAA', {'longBusinessSummary': 'Acme Inc. makes storage devices. It operates worldwide.'},
                                      {}, {}, datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(company['business_en'], 'Acme Inc. makes storage devices.')
        self.assertEqual(company['financials'], [])
        self.assertIn('ยังไม่มีงบ', company_view({'company': company})['outlook'])

    def test_incompatible_daily_prices_do_not_become_a_bullish_sma_claim(self):
        row = {'price': 400, 'daily_context': {'sma20': 100, 'sma50': 90},
               'reasons': ['daily_price_scale_mismatch']}
        self.assertIn('ไม่สอดคล้อง', trend_view(row)['daily'])
        self.assertIn('ไม่สอดคล้อง', trend_view({'price': 12, 'previous_close': 12.57,
                      'daily_context': {'sma20': 78, 'sma50': 80}})['daily'])

    def test_numbering_is_shared_across_plan_event_text_and_image(self):
        report = wdc_report()
        event = report['events'][0]
        event['company'] = {'business_th': 'ผลิตอุปกรณ์จัดเก็บข้อมูล', 'country': 'United States',
                            'financials': [{'key': 'revenueGrowthFY', 'value': .1, 'end': '2026-06-30'}]}
        event['daily_context'] = {'sma20': 90, 'sma50': 85, 'sma200': None, 'asof': '2026-10-01'}
        report['events'] = [dict(deepcopy(event), ticker='T' + str(i), name='Company ' + str(i)) for i in range(5)]
        text = format_report(report)
        self.assertEqual([r['ticker'] for r in report_rows(report)], ['T0', 'T1', 'T2', 'T3', 'T4'])
        for i in range(5):
            self.assertIn(f'{i+1}) T{i} — Company {i}', text)
        self.assertNotIn('RVOL =', text)
        self.assertNotIn('อ่านตัวเลขง่าย', text)
        self.assertNotIn('ที่มาข่าว', text)
        self.assertIn('SMA20 $90.00 · SMA50 $85.00 · SMA200 —', text)
        self.assertLess(text.index('SMA20 $90.00'), text.index('บริษัท'))
        self.assertIn(event['news'][0]['url'], text)


class TranslationTests(unittest.TestCase):
    def test_company_names_are_protected_and_untranslated_headlines_do_not_leak(self):
        from short_term_report import thai_headline
        source = 'Acme reports higher revenue in Europe'
        masked, mappings = protect_names([source], ['Acme'])
        self.assertNotIn('Acme', masked[0])
        self.assertEqual(restore_names(masked[0], mappings[0]), source)
        self.assertEqual(restore_names('บริษัทอื่น', mappings[0]), '')
        shown = thai_headline({'title': source})
        self.assertIn('รอตรวจคำแปล', shown)
        self.assertNotIn(source, shown)

    def test_time_sensitive_bars_are_requested_after_translation(self):
        from test_short_term_engine import NOW, pool, raw_quote, news, bars
        from short_term_service import scan
        events = []
        def quotes(tickers):
            events.append('quotes')
            return [raw_quote(t) for t in tickers]
        def chart(ticker):
            events.append('chart')
            return bars()
        with patch('thai_news_translation.enrich_prepared', side_effect=lambda _: events.append('translation')):
            report = scan({'short_term_pool': pool()}, clock=lambda: NOW, quote_fetcher=quotes,
                          news_fetcher=lambda *a: news(), chart_fetcher=chart)
        self.assertLess(events.index('translation'), events.index('chart'))
        self.assertEqual(events[-1], 'quotes')
        self.assertEqual(report['counts']['charts_checked'], 1)

    def test_missing_bond_coupon_negation_or_false_financial_noun_rejected(self):
        self.assertFalse(valid_translation('Senior notes 2.300% due 2030', 'หุ้นกู้ไม่ด้อยสิทธิครบกำหนด 2030'))
        self.assertTrue(valid_translation('Senior notes 2.300% due 2030', 'หุ้นกู้ไม่ด้อยสิทธิ 2.3% ครบกำหนด 2030'))
        self.assertFalse(valid_translation('may not ease supply shortage', 'อาจบรรเทาภาวะอุปทานขาดแคลน'))
        self.assertFalse(valid_translation('supply shortage', 'ความเสียหายของแหล่งจ่ายไฟ'))
        self.assertFalse(valid_translation('lower profit margins', 'กำไรลดลง'))
        self.assertFalse(valid_translation('devices in Europe, the Middle East and Africa', 'อุปกรณ์ในอยุธยาและแอฟริกา'))
        self.assertTrue(valid_translation('Toshiba plans to double capacity', 'Toshiba วางแผนเพิ่มกำลังผลิตเป็น 2 เท่า'))
        self.assertFalse(valid_translation('Toshiba plans to double capacity', 'Toshiba วางแผนเพิ่มกำลังผลิตเป็น 3 เท่า'))

    def test_partial_model_output_never_invents_an_unfinished_translation(self):
        self.assertEqual(decode_translations('</think> ["ข่าวแรก", "ข่าวยังไม่จบ'), ['ข่าวแรก'])

    def test_reviewed_translation_cache_and_unknown_fallback(self):
        title = 'Analysts say Toshiba HDD expansion may not ease global supply shortage'
        articles = [{'title': title}, {'title': 'Acme reports revenue growth of 12%'}]
        row = {'company': {'business_en': 'Acme makes storage devices.'}}
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'THAI_TRANSLATION_CACHE': folder + '/cache.json'}):
            enrich_prepared([(row, None, articles, {})], translator=lambda _: ['Acme รายงานรายได้โต 12%', 'Acme ผลิตอุปกรณ์จัดเก็บข้อมูล'])
            self.assertIn('อาจยังไม่', articles[0]['title_th'])
            self.assertIn('12%', articles[1]['title_th'])
            self.assertIn('อุปกรณ์', row['company']['business_th'])
            self.assertEqual(json.loads(Path(folder + '/cache.json').read_text())['items'][articles[1]['title']], articles[1]['title_th'])


if __name__ == '__main__':
    unittest.main()
