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
            or not isinstance(value.get('events'), list) or len(value['events']) > 20
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


def read_pool_metadata(version, repo):
    """Reuse the asynchronous ranking cache; metadata needs no pool decompression."""
    from ranking_board import ranking_reader
    payload, error, busy = ranking_reader(version, repo).read()
    pool = payload.get('short_term_pool') if isinstance(payload, dict) else None
    return pool if isinstance(pool, dict) else None, error, busy


def render_coverage(value, pool):
    """Keep observed scan totals separate from a newer published stock pool."""
    from short_term_report import thai_time
    counts = value.get('counts', {}) if value else {}
    if value:
        universe = counts.get('universe', 0)
        fresh = counts.get('fresh_quotes', 0)
        st.caption(f"รอบ {thai_time(value['generated_at'])} ไทย · ราคาผ่านเกณฑ์ {fresh:,}/{universe:,} หุ้น · ฐานทั้งหมด {counts.get('catalog', 0):,} รายการ")
    if pool:
        pool_count = pool.get('count', len(pool.get('items', [])))
        pool_time = instant(pool.get('computed_at'))
        scan_pool_time = instant(value.get('pool_computed_at')) if value else None
        scan_time = scan_pool_time or (instant(value['generated_at']) if value else None)
        differs = not value or pool_count != counts.get('universe', 0) or (
            pool_time is not None and scan_time is not None and pool_time > scan_time)
        st.caption(f"ชุดเตรียมสแกนล่าสุด {pool_count:,} หุ้น · จัดชุด {thai_time(pool.get('computed_at'))} ไทย"
                   + (' · ยังไม่ใช่ผลอ่านราคาของรอบข้างต้น' if value and differs else ''))
        pending_history = pool.get('excluded', {}).get('daily_baseline_not_previous_session', 0)
        if isinstance(pending_history, int) and pending_history > 0:
            baseline = pool.get('baseline_day')
            reference = f'วันอ้างอิงตลาดสหรัฐฯ {baseline}' if baseline else 'วันอ้างอิงล่าสุด'
            st.caption(f'รอข้อมูลราคาย้อนหลังให้ถึง{reference} {pending_history:,} หุ้น · ยังไม่นับรวมในชุดที่ผ่านตรวจ')
        if differs:
            st.caption('นอกเวลาตลาดจะแสดงผลรอบเดิม; ชุดหุ้นใหม่ใช้เมื่อถึงรอบสแกนและข้อมูลผ่านการตรวจ')
    with st.expander('สแกนครอบคลุมแค่ไหน'):
        st.markdown('ฐานทั้งหมดรวมหุ้น กองทุน และหลักทรัพย์ประเภทอื่น จึงไม่ใช่จำนวนหุ้นที่อ่านราคาทุกรอบ '
                    'ชุดสแกนใช้หุ้นสามัญ USD ที่ผ่านการตรวจข้อมูลและสภาพคล่องเฉลี่ย 20 วัน '
                    'อย่างน้อย 5 ล้านดอลลาร์และ 250,000 หุ้นต่อวัน ไม่มีเงื่อนไขว่าราคาต้องเกิน 10 ดอลลาร์')
        if pool:
            categories = [('catalog_common_stocks', 'หุ้นสามัญ'), ('catalog_funds', 'กองทุน'),
                          ('catalog_other', 'ประเภทอื่น')]
            known = [f"{label} {pool[key]:,}" for key, label in categories if isinstance(pool.get(key), int)]
            if known:
                st.markdown('**องค์ประกอบฐานในชุดล่าสุด:** ' + ' · '.join(known))
            preliminary = pool.get('eligible_before_cap')
            validated = pool.get('eligible_after_validation')
            if isinstance(preliminary, int):
                validation_label = (f'ผ่านการตรวจครบ {validated:,} หุ้น' if isinstance(validated, int)
                                    else f'อยู่ในชุด {pool_count:,} หุ้น (รุ่นนี้ไม่แยกยอดผ่านการตรวจทั้งหมด)')
                st.markdown(f'**ขั้นตอนจัดชุดล่าสุด:** ผ่านสภาพคล่องเบื้องต้น {preliminary:,} หุ้น'
                            ' (ยังไม่ยืนยันความครบถ้วนและวันอ้างอิงของข้อมูล) · ' + validation_label)
            cap_excluded = pool.get('excluded_by_cap')
            if isinstance(cap_excluded, int):
                st.markdown('**ขอบเขตชุดล่าสุด:** ' + (
                    'ไม่มีหุ้นที่ผ่านการตรวจถูกตัดออกด้วยเพดานจำนวน'
                    if cap_excluded == 0 else f'มี {cap_excluded:,} ตัวที่ผ่านเกณฑ์แต่ยังอยู่นอกเพดานชุดสแกน'))
            st.caption('เกณฑ์รุ่นใหม่รองรับได้สูงสุด 5,000 หุ้น; รอบเก่าที่แสดง 1,000 ใช้ชุดคัดตามสภาพคล่องของรุ่นเดิม')
        if value:
            attempted = counts.get('quote_attempted')
            if isinstance(attempted, int):
                missing = max(0, attempted - counts.get('fresh_quotes', 0))
                unattempted = counts.get('quote_unattempted', max(0, counts.get('universe', 0) - attempted))
                st.markdown(f"**ผลรอบ {thai_time(value['generated_at'])}:** ขอราคา {attempted:,}/{counts.get('universe', 0):,} หุ้น"
                            f" · ใช้ได้ {counts.get('fresh_quotes', 0):,} · ไม่มี/เก่า/ล่าช้าหรือไม่ผ่านการตรวจ {missing:,}"
                            f" · ยังไม่ได้ขอราคา {unattempted:,}")
            else:
                st.markdown(f"**ผลรอบ {thai_time(value['generated_at'])}:** ราคาผ่านเกณฑ์ {counts.get('fresh_quotes', 0):,}"
                            f" จากชุด {counts.get('universe', 0):,} หุ้น · รายงานรุ่นนี้ไม่ได้แยกจำนวนคำขอราคา")
            st.caption('ส่วนต่างของราคาที่ใช้ได้อาจเกิดจากไม่มีข้อมูล ราคาย้อนหลัง ฟีดล่าช้า หรือข้อมูลไม่ผ่านการตรวจ '
                       'จึงไม่เท่ากับจำนวนคำขอที่ล้มเหลวทั้งหมด')
            st.markdown(f"**ตรวจต่อจากการเคลื่อนไหว:** ข่าว {counts.get('news_checked', 0):,} หุ้น"
                        f" · ข่าวผ่าน {counts.get('news_passed', 0):,} · กราฟ {counts.get('charts_checked', 0):,}"
                        f" · เทคนิคผ่านการตรวจข้อมูล {counts.get('technical_checked', 0):,}")
        st.caption('รุ่นใหม่ตรวจข่าวได้สูงสุด 20 หุ้นต่อรอบ: ให้โควตาหุ้นขึ้นและลงแรง พร้อมสลับคิวตัวอื่น '
                   'ตรวจกราฟได้สูงสุด 10 หุ้นภายในเวลาที่กำหนด จึงไม่ได้วิเคราะห์ข่าวและกราฟครบทุกตัวพร้อมกัน')


@st.fragment(run_every=30)
def render_event_board():
    import dashboard_runtime as a
    import pandas as pd
    from short_term_report import thai_time, report_sections, report_rows
    from short_term_context import daily_values
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
        pool, _, _ = read_pool_metadata(a.APP_VERSION, a.DEFAULT_REPO)
        if value is None:
            st.caption('กำลังอ่านรายงานหุ้นขึ้น/ลงและข่าวกระทบอุตสาหกรรม' if busy else 'รอรายงานเหตุการณ์รอบแรก')
            if pool:
                render_coverage(None, pool)
            if error:
                st.caption(error)
            return
        now = datetime.now(timezone.utc)
        render_coverage(value, pool)
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
        ordered = ordered[:20]
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
            st.caption(f'ตัวเลือกที่มีข่าวผ่านเกณฑ์ {len(rows)} หุ้น · Dashboard แสดงสูงสุด 20 หุ้น · LINE สรุปสูงสุด 5 หุ้น')
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch',
                         column_config={'ราคา USD': st.column_config.NumberColumn(format='$%.4f'),
                                        'เปลี่ยนแปลง %': st.column_config.NumberColumn(format='%+.2f%%'),
                                        'RVOL': st.column_config.NumberColumn(format='%.2fx'),
                                        'VWAP': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA20': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA50': st.column_config.NumberColumn(format='$%.2f'),
                                        'SMA200': st.column_config.NumberColumn(format='$%.2f'),
                                        'ข่าว': st.column_config.LinkColumn(display_text='อ่านต้นฉบับ')})
            for index, e in enumerate(ordered, 1):
                with st.expander(f"{index}) {e['ticker']} · บริษัท ข่าวไทย และแผนวันนี้"):
                    c = plans.get(e['ticker'])
                    current = c if c and instant(c.get('expires_at')) and now < instant(c['expires_at']) else None
                    for heading, body in report_sections(e, plan=current):
                        st.markdown('**' + heading + '**')
                        st.markdown(literal_text(body).replace('$', r'\$').replace('\n', '  \n'))
                    for article in e['news']:
                        url = _safe_url(article['url'])
                        st.markdown('<' + url + '>')
                    st.button('ดูกราฟ ' + e['ticker'], key='event_select_' + e['ticker'],
                              on_click=queue_selection, args=({'ticker': e['ticker']},))
        else:
            st.info('รอบนี้ยังไม่มีข่าวเหตุการณ์ที่ผ่านการคัด หรือข้อมูลยังไม่พอ')
