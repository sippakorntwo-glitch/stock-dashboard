"""Actual event-panel renders and ticker selection; no external data calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1', reason='Requires actual Streamlit AppTest')

SCRIPT = '''
import streamlit as st
from market_event_ui import render_event_board
from ranking_board import consume_selection
class Cache:
    def get(self, *args, **kwargs): return None, {}
    def put(self, *args, **kwargs): pass
consume_selection(Cache())
render_event_board()
st.text_input('Independent search', key='event_independent_search')
'''


def run_panel(monkeypatch, report, pool=None):
    from streamlit.testing.v1 import AppTest
    import market_event_ui as ui
    class Reader:
        def read(self): return deepcopy(report), '', False
    monkeypatch.setenv('DASHBOARD_ALLOW_MARKET_EVENTS', 'true')
    monkeypatch.setattr(ui, 'get_reader', lambda repo: Reader())
    monkeypatch.setattr(ui, 'read_pool_metadata', lambda *args: (deepcopy(pool), '', False))
    return AppTest.from_string(SCRIPT, default_timeout=8).run()


def fixture():
    from test_short_term_events import wdc_report
    value = wdc_report()
    value['generated_at'] = datetime.now(timezone.utc).isoformat()
    return value


def test_negative_news_panel_explains_recovery_and_opens_correct_chart(monkeypatch):
    value = fixture()
    at = run_panel(monkeypatch, value)
    assert not at.exception, str(at.exception)
    frame = at.dataframe[0].value
    assert frame.iloc[0]['หุ้น'] == 'WDC'
    assert frame.iloc[0]['สถานะ'] == 'รอฟื้นตัว'
    assert frame.iloc[0]['เปลี่ยนแปลง %'] < -10
    assert any('Toshiba' in text.value for text in at.markdown)
    assert any('ยังไม่ยืนยันการฟื้นตัว' in text.value for text in at.markdown)
    assert frame.iloc[0]['ลำดับ'] == 1
    at.text_input(key='event_independent_search').set_value('KEEP').run()
    at.button(key='event_select_WDC').click().run()
    assert not at.exception, str(at.exception)
    assert at.session_state['selected_ticker'] == 'WDC'
    assert at.text_input(key='event_independent_search').value == 'KEEP'


def test_expired_plan_retains_news_without_showing_current_entry(monkeypatch):
    value = fixture()
    value['cards'] = [dict(value['events'][0], expires_at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())]
    value['generated_at'] = (datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
    at = run_panel(monkeypatch, value)
    assert not at.exception, str(at.exception)
    assert at.dataframe[0].value.iloc[0]['สถานะ'] == 'รอฟื้นตัว'
    assert any('เกิน 15 นาที' in text.value for text in at.warning)


def test_missing_first_report_keeps_other_controls_usable(monkeypatch):
    at = run_panel(monkeypatch, None)
    assert not at.exception, str(at.exception)
    assert not at.dataframe
    at.text_input(key='event_independent_search').set_value('WDC').run()
    assert at.text_input(key='event_independent_search').value == 'WDC'


def test_new_pool_keeps_last_scan_denominator_and_separates_failed_validation(monkeypatch):
    value = fixture()
    value['generated_at'] = (datetime.now(timezone.utc)-timedelta(hours=12)).isoformat()
    value['counts'].update(catalog=9876, universe=1000, quote_attempted=1000,
                           fresh_quotes=999, news_checked=10, charts_checked=6)
    pool = {'computed_at': datetime.now(timezone.utc).isoformat(), 'count': 2140, 'items': [],
            'catalog_common_stocks': 5420, 'catalog_funds': 4110, 'catalog_other': 346,
            'eligible_before_cap': 2670, 'eligible_after_validation': 2140, 'excluded_by_cap': 0}
    at = run_panel(monkeypatch, value, pool)
    assert not at.exception, str(at.exception)
    captions = '\n'.join(text.value for text in at.caption)
    details = '\n'.join(text.value for text in at.markdown)
    assert 'ราคาผ่านเกณฑ์ 999/1,000 หุ้น' in captions
    assert 'ชุดเตรียมสแกนล่าสุด 2,140 หุ้น' in captions
    assert 'ยังไม่ใช่ผลอ่านราคาของรอบข้างต้น' in captions
    assert '999/2,140' not in captions + details
    assert 'ผ่านสภาพคล่องเบื้องต้น 2,670 หุ้น' in details
    assert 'ยังไม่ยืนยันความครบถ้วนและวันอ้างอิงของข้อมูล' in details
    assert 'ผ่านการตรวจครบ 2,140 หุ้น' in details
    assert 'ไม่มี/เก่า/ล่าช้าหรือไม่ผ่านการตรวจ 1' in details
    assert 'ยังไม่ได้ขอราคา 0' in details
    assert 'คำขอที่ล้มเหลวทั้งหมด' in captions


def test_pending_history_explains_zero_new_pool_without_erasing_last_scan(monkeypatch):
    value = fixture()
    value['generated_at'] = (datetime.now(timezone.utc)-timedelta(hours=12)).isoformat()
    value['counts'].update(catalog=9876, universe=1000, fresh_quotes=999)
    pool = {'computed_at': datetime.now(timezone.utc).isoformat(), 'count': 0, 'items': [],
            'baseline_day': '2026-10-02', 'eligible_before_cap': 2352,
            'eligible_after_validation': 0, 'excluded_by_cap': 0,
            'excluded': {'daily_baseline_not_previous_session': 2352}}
    at = run_panel(monkeypatch, value, pool)
    assert not at.exception, str(at.exception)
    captions = '\n'.join(text.value for text in at.caption)
    details = '\n'.join(text.value for text in at.markdown)
    assert 'ราคาผ่านเกณฑ์ 999/1,000 หุ้น' in captions
    assert 'ชุดเตรียมสแกนล่าสุด 0 หุ้น' in captions
    assert 'รอข้อมูลราคาย้อนหลังให้ถึงวันอ้างอิงตลาดสหรัฐฯ 2026-10-02 2,352 หุ้น' in captions
    assert 'ยังไม่นับรวมในชุดที่ผ่านตรวจ' in captions
    assert 'ผ่านสภาพคล่องเบื้องต้น 2,352 หุ้น' in details
    assert 'ผ่านการตรวจครบ 0 หุ้น' in details
    assert '999/0' not in captions + details
    assert at.dataframe[0].value.iloc[0]['หุ้น'] == 'WDC'


def test_legacy_counts_do_not_invent_attempted_quotes(monkeypatch):
    value = fixture()
    value['counts'].pop('quote_attempted', None)
    value['counts'].update(universe=1000, fresh_quotes=999)
    at = run_panel(monkeypatch, value)
    assert not at.exception, str(at.exception)
    assert any('ไม่ได้แยกจำนวนคำขอราคา' in text.value for text in at.markdown)


def test_partial_scan_separates_unattempted_from_unusable_quotes(monkeypatch):
    value = fixture()
    value['counts'].update(universe=2140, quote_attempted=1000, quote_unattempted=1140,
                           fresh_quotes=999)
    at = run_panel(monkeypatch, value)
    assert not at.exception, str(at.exception)
    details = '\n'.join(text.value for text in at.markdown)
    assert 'ขอราคา 1,000/2,140 หุ้น' in details
    assert 'ไม่มี/เก่า/ล่าช้าหรือไม่ผ่านการตรวจ 1 · ยังไม่ได้ขอราคา 1,140' in details


def test_all_twenty_events_have_numbered_details_and_chart_controls(monkeypatch):
    import market_event_ui as ui
    value = fixture()
    template = value['events'][0]
    value['events'] = [dict(deepcopy(template), ticker=f'STOCK{i:02d}') for i in range(1, 21)]
    value['cards'] = []
    ui.validate_board(value)
    at = run_panel(monkeypatch, value)
    assert not at.exception, str(at.exception)
    assert len(at.dataframe[0].value) == 20
    assert at.dataframe[0].value.iloc[-1]['ลำดับ'] == 20
    assert at.dataframe[0].value.iloc[-1]['หุ้น'] == 'STOCK20'
    assert len([x for x in at.expander if 'บริษัท ข่าวไทย' in x.label]) == 20
    at.button(key='event_select_STOCK20').click().run()
    assert not at.exception, str(at.exception)
    assert at.session_state['selected_ticker'] == 'STOCK20'
