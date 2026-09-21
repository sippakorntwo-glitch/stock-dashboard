"""Consolidate presentation without changing source values or applicable fund rows."""
from copy import deepcopy
from io import BytesIO
import os

import pandas as pd
import pytest

from dashboard_runtime import build_analysis
from dashboard_views import technical_analysis_rows
from reference_ui import REFERENCE_LABEL, reference_rows


def test_company_technical_projection_removes_nineteen_duplicate_fundamentals_only():
    analysis, metrics, extra = build_analysis({}, {'Ticker': 'AAPL', 'Asset_Type': 'Common Stock'},
        {'symbol': 'AAPL', 'quoteType': 'EQUITY', 'currency': 'USD', 'regularMarketPrice': 100.,
         'forwardPE': 20., 'trailingPE': 25., 'trailingEps': 4., 'targetMeanPrice': 120.})
    original = analysis.copy(deep=True)
    metrics_before, extra_before = deepcopy(metrics), deepcopy(extra)
    projected = technical_analysis_rows(analysis)
    assert len(analysis) == 28 and len(projected) == 9
    assert set(projected['หมวด']) == {'เทคนิค', 'สภาพคล่อง', 'ความเสี่ยง'}
    assert projected['_company_metric'].eq('—').all()
    assert {'Forward P/E', 'Trailing P/E', 'Target Price', 'Dividend Yield'}.isdisjoint(projected['ปัจจัย'])
    assert {'เกณฑ์อ้างอิง', 'รอบข้อมูล'}.isdisjoint(projected.columns)
    pd.testing.assert_frame_equal(projected, original.loc[original['หมวด'].isin(
        ('เทคนิค', 'สภาพคล่อง', 'ความเสี่ยง'))].drop(columns=['เกณฑ์อ้างอิง', 'รอบข้อมูล']))
    pd.testing.assert_frame_equal(analysis, original)
    assert metrics == metrics_before and extra == extra_before


def test_technical_projection_preserves_populated_context_and_only_drops_blank_columns():
    original = pd.DataFrame([
        {'หมวด': 'เทคนิค', 'ปัจจัย': 'RSI', 'เกณฑ์อ้างอิง': '30–70', 'รอบข้อมูล': None},
        {'หมวด': 'ความเสี่ยง', 'ปัจจัย': 'ATR', 'เกณฑ์อ้างอิง': '—', 'รอบข้อมูล': '  '},
        {'หมวด': 'พื้นฐาน', 'ปัจจัย': 'Revenue', 'เกณฑ์อ้างอิง': '—', 'รอบข้อมูล': 'FY 2025'},
    ])
    before = original.copy(deep=True)
    projected = technical_analysis_rows(original)
    assert projected['เกณฑ์อ้างอิง'].tolist() == ['30–70', '—']
    assert 'รอบข้อมูล' not in projected
    pd.testing.assert_frame_equal(original, before)
    pd.testing.assert_frame_equal(technical_analysis_rows(original, is_etf=True), before)


def test_fund_projection_retains_applicability_and_does_not_modify_source():
    from asset_semantics import adapt_analysis
    from company_analysis_th import localize_360_frame
    info = {'symbol': 'AAAU', 'quoteType': 'ETF', 'currency': 'USD', 'category': 'Commodities Focused'}
    analysis, _, _ = build_analysis({}, {'Ticker': 'AAAU', 'Asset_Type': 'ETF'}, info)
    analysis = localize_360_frame(adapt_analysis(analysis, 'AAAU', info, True))
    original = analysis.copy(deep=True)
    projected = technical_analysis_rows(analysis, is_etf=True)
    pd.testing.assert_frame_equal(projected, original)
    assert len(projected) == 13
    assert projected.loc[projected['หมวด'].eq('พื้นฐาน'), 'ค่าล่าสุด'].str.contains('N/A').sum() >= 3
    projected.iloc[0, 0] = 'changed'
    pd.testing.assert_frame_equal(analysis, original)


def test_sec_reference_rows_keep_periods_units_percent_and_cash_definition_distinct():
    facts = [
        {'metric': 'Revenue', 'value': 416161000000., 'currency': 'USD',
         'basis': 'fiscal-year (not TTM)', 'period_start': '2024-09-29',
         'period_end': '2025-09-27', 'filed': '2025-10-31', 'tag': 'Revenues'},
        {'metric': 'Cash and cash equivalents', 'value': 39544000000., 'currency': 'USD',
         'basis': 'point-in-time', 'period_start': None, 'period_end': '2026-06-27',
         'filed': '2026-07-31', 'tag': 'CashAndCashEquivalentsAtCarryingValue'},
        {'metric': 'Net margin (calculated FY)', 'value': 26.9151, 'currency': '%',
         'basis': 'fiscal-year (not TTM)', 'period_start': '2024-09-29',
         'period_end': '2025-09-27', 'filed': '2025-10-31', 'calculated': True},
    ]
    original = deepcopy(facts)
    revenue, cash, margin = reference_rows(facts)
    assert revenue['ค่าที่รายงาน'] == '416.16B USD'
    assert revenue['รอบบัญชี'] == margin['รอบบัญชี'] == 'ปีบัญชี (FY)'
    assert revenue['วันเริ่มรอบ'] == '2024-09-29'
    assert revenue['วันสิ้นงวด'] == '2025-09-27' and revenue['วันที่ยื่นเอกสาร'] == '2025-10-31'
    assert cash['รายการ'] == 'เงินสดและรายการเทียบเท่าเงินสด (Cash & equivalents)'
    assert cash['ค่าที่รายงาน'] == '39.54B USD' and cash['รอบบัญชี'] == 'ณ วันสิ้นงวด'
    assert cash['วันเริ่มรอบ'] == '—' and cash['วันสิ้นงวด'] == '2026-06-27'
    assert cash['วันที่ยื่นเอกสาร'] == '2026-07-31'
    assert margin['ค่าที่รายงาน'] == '26.92%'
    assert facts == original


def test_sec_reference_preserves_zero_loss_and_unknown_period_without_guessing():
    rows = reference_rows([{'metric': 'Net income', 'value': value, 'currency': 'USD'}
                           for value in (0., -1000000., None)])
    assert [row['ค่าที่รายงาน'] for row in rows] == ['0.00 USD', '-1.00M USD', 'ไม่มีข้อมูลรายงาน']
    assert all(row['รอบบัญชี'] == 'ไม่ระบุรอบบัญชี' for row in rows)


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1', reason='Requires real Streamlit AppTest')
def test_source_panel_is_collapsed_and_keeps_filing_and_exact_value_export():
    from streamlit.testing.v1 import AppTest
    script = '''
import streamlit as st
from unittest.mock import patch
from reference_ui import render_references
class Cache:
    def get(self, key, request_remote=False):
        assert key == 'reference:AAPL' and request_remote is False
        return {'cik': 320193, 'checked_at': '2026-09-21T00:00:00Z', 'facts': [{
            'metric': 'Revenue', 'value': 416161000000., 'currency': 'USD',
            'basis': 'fiscal-year (not TTM)', 'period_start': '2024-09-29',
            'period_end': '2025-09-27', 'filed': '2025-10-31',
            'url': 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/',
            'tag': 'Revenues'}]}, {}
download = st.download_button
def capture_download(label, data, *args, **kwargs):
    st.session_state['sec_export'] = data
    return download(label, data, *args, **kwargs)
with patch.object(st, 'download_button', side_effect=capture_download):
    render_references('AAPL', {'quoteType': 'EQUITY'}, False, Cache())
'''
    at = AppTest.from_string(script, default_timeout=20).run()
    assert not at.exception
    assert at.expander[0].label == REFERENCE_LABEL
    assert at.expander[0].proto.expanded is False
    assert at.dataframe[0].value.iloc[0]['ค่าที่รายงาน'] == '416.16B USD'
    assert any('TTM' in caption.value for caption in at.caption)
    assert any('เงินลงทุนระยะสั้น' in caption.value for caption in at.caption)
    assert any('2026-09-21T00:00:00Z' in caption.value for caption in at.caption)
    assert any(button.proto.label == 'ดาวน์โหลดค่าจริงและแหล่งข้อมูล SEC'
               for button in at.get('download_button'))
    assert any(link.proto.url.endswith('000032019325000001/') for link in at.get('link_button'))
    exported = pd.read_csv(BytesIO(at.session_state['sec_export']))
    assert exported.iloc[0]['value'] == 416161000000.
    assert exported.iloc[0]['tag'] == 'Revenues'
    assert exported.iloc[0]['basis'] == 'fiscal-year (not TTM)'
    assert exported.iloc[0]['url'].endswith('000032019325000001/')
