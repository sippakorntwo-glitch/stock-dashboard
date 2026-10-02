"""Non-blocking public event board, independent of the daily investment ranking."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
import threading
import time

import requests
import streamlit as st

from short_term_engine import MODEL, instant


def validate_board(value):
    if (not isinstance(value, dict) or value.get('model') != MODEL
            or instant(value.get('generated_at')) is None
            or not isinstance(value.get('events'), list) or len(value['events']) > 10
            or not isinstance(value.get('cards'), list) or len(value['cards']) > 5):
        raise ValueError('Invalid event board')
    for collection in ('events', 'cards'):
        seen = set()
        for row in value[collection]:
            ticker = row.get('ticker') if isinstance(row, dict) else None
            if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}', ticker) or ticker in seen:
                raise ValueError('Invalid event symbol')
            seen.add(ticker)
    return value


def fetch_board(repo):
    from github_store import checked_repo
    repo = checked_repo(repo)
    url = f'https://raw.githubusercontent.com/{repo}/line-alert-media/event-board.json'
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, params={'minute': int(time.time() // 60)},
                         headers={'Authorization': None}, timeout=(3, 8), stream=True) as response:
            response.raise_for_status()
            raw = bytearray()
            for part in response.iter_content(32768):
                raw.extend(part)
                if len(raw) > 400_000:
                    raise ValueError('Event board too large')
    return validate_board(json.loads(raw))


class EventReader:
    def __init__(self, repo, fetcher=fetch_board):
        self.repo, self.fetcher = repo, fetcher
        self.lock = threading.Lock()
        self.busy, self.next_check, self.value, self.error = False, 0., None, ''

    def read(self):
        with self.lock:
            if not self.busy and time.monotonic() >= self.next_check:
                self.busy = True
                threading.Thread(target=self._run, daemon=True, name='market-event-reader').start()
            return deepcopy(self.value), self.error, self.busy

    def _run(self):
        try:
            value = validate_board(self.fetcher(self.repo))
            with self.lock:
                if self.value is None or instant(value['generated_at']) >= instant(self.value['generated_at']):
                    self.value, self.error = value, ''
        except Exception:
            with self.lock:
                self.error = 'ยังอ่านข่าวรอบใหม่ไม่ได้ แสดงเวลาของรอบล่าสุดที่อ่านสำเร็จ'
        finally:
            with self.lock:
                self.busy, self.next_check = False, time.monotonic() + 30


@st.cache_resource(max_entries=1, show_spinner=False)
def get_reader(repo):
    return EventReader(repo)


@st.fragment(run_every=30)
def render_event_board():
    import dashboard_runtime as a
    import pandas as pd
    from short_term_report import LABELS, thai_time, report_sections, report_rows
    from short_term_context import GLOSSARY, daily_values
    from market_pulse import _safe_url
    from market_pulse_ui import literal_text
    from ranking_board import queue_selection
    if os.environ.get('DASHBOARD_ALLOW_MARKET_EVENTS', 'true').lower() not in ('true', '1'):
        return
    if st.session_state.get('_ranking_pending'):
        st.rerun()
    with st.container(border=True, key='market_event_board'):
        st.subheader('หุ้นเคลื่อนไหวแรงและข่าวกระทบราคา')
        value, error, busy = get_reader(a.DEFAULT_REPO).read()
        if value is None:
            st.caption('กำลังอ่านรายงานหุ้นขึ้น/ลงและข่าวกระทบอุตสาหกรรม' if busy else 'รอรายงานเหตุการณ์รอบแรก')
            if error:
                st.caption(error)
            return
        now = datetime.now(timezone.utc)
        counts = value['counts']
        st.caption(f"รอบ {thai_time(value['generated_at'])} ไทย · อ่านราคา {counts.get('fresh_quotes', 0):,}/{counts.get('universe', 0):,} หุ้น · ฐานทั้งหมด {counts.get('catalog', 0):,} รายการ")
        st.caption('ตรวจตามตารางทุก 10 นาที; เวลาเริ่มอาจล่าช้า · ข่าวสำคัญและแผนซื้อแสดงคนละสถานะ · ราคามีเวลาต้นทางกำกับ')
        if (now - instant(value['generated_at'])).total_seconds() > 15 * 60:
            st.warning('รายงานเกิน 15 นาที ใช้ดูเหตุการณ์ย้อนหลัง; รอราคาและแผนรอบใหม่')
        if error:
            st.caption(error)
        plans = {c['ticker']: c for c in value['cards']}
        rows = []
        ordered = report_rows(value)
        included = {e['ticker'] for e in ordered}
        ordered += [e for e in value['events'] if e['ticker'] not in included]
        for index, e in enumerate(ordered, 1):
            c = plans.get(e['ticker'])
            current = c and instant(c.get('expires_at')) and now < instant(c['expires_at'])
            status = 'แผนมีเงื่อนไข' if current else 'รอฟื้นตัว' if e['status'] == 'recovery_watch' else 'ข่าว/รอติดตาม'
            rows.append({'ลำดับ': index, 'หุ้น': e['ticker'], 'สถานะ': status, 'หมวด': e['industry'],
                         'ราคา USD': e['price'], 'เปลี่ยนแปลง %': e['change_pct'], 'RVOL': e.get('rvol'),
                         'VWAP': e.get('vwap'), 'SMA20': daily_values(e).get('sma20'),
                         'SMA50': daily_values(e).get('sma50'),
                         'SMA200': daily_values(e).get('sma200'),
                         'ราคา ณ (ไทย)': thai_time(e['quote_time']),
                         'ข่าว': _safe_url(e['news'][0]['url'])})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch',
                         column_config={'ราคา USD': st.column_config.NumberColumn(format='$%.4f'),
                                        'เปลี่ยนแปลง %': st.column_config.NumberColumn(format='%+.2f%%'),
                                        'RVOL': st.column_config.NumberColumn(format='%.2fx'),
                                        'VWAP': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA20': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA50': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA200': st.column_config.NumberColumn(format='$%.2f'),
                                        'ข่าว': st.column_config.LinkColumn(display_text='อ่านต้นฉบับ')})
            for index, e in enumerate(ordered[:5], 1):
                with st.expander(f"{index}) {e['ticker']} · บริษัท ข่าวไทย และแผนวันนี้"):
                    c = plans.get(e['ticker'])
                    current = c if c and instant(c.get('expires_at')) and now < instant(c['expires_at']) else None
                    for heading, body in report_sections(e, plan=current):
                        st.markdown('**' + heading + '**')
                        st.markdown(literal_text(body))
                    for article in e['news']:
                        st.link_button(article['publisher'] + ' · ' + thai_time(article['published_at']), _safe_url(article['url']))
                        st.caption(literal_text('ต้นฉบับ: ' + article['title']))
                    st.button('ดูกราฟ ' + e['ticker'], key='event_select_' + e['ticker'],
                              on_click=queue_selection, args=({'ticker': e['ticker']},))
        else:
            st.info('รอบนี้ยังไม่มีข่าวเหตุการณ์ที่ผ่านการคัด หรือข้อมูลยังไม่พอ')
        with st.expander('RVOL, VWAP และ SMA คืออะไร'):
            for line in GLOSSARY.split('\n'):
                st.write(line)
