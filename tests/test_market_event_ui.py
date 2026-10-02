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


def run_panel(monkeypatch, report):
    from streamlit.testing.v1 import AppTest
    import market_event_ui as ui
    class Reader:
        def read(self): return deepcopy(report), '', False
    monkeypatch.setenv('DASHBOARD_ALLOW_MARKET_EVENTS', 'true')
    monkeypatch.setattr(ui, 'get_reader', lambda repo: Reader())
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
    assert any('ยังไม่ยืนยันการฟื้นตัว' in text.value for text in at.caption)
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
