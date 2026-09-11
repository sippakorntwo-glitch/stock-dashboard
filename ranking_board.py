"""Small read-only Top 10 card. Only its fragment polls; no visitor starts a scan."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import requests
import streamlit as st
import dashboard_runtime as a
from dashboard_selection import set_selected
from github_store import checked_repo
from ranking_engine import SCHEMA, MODEL, fresh, utc, seconds, display_status, STALE_SECONDS


def validate_payload(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('model') != MODEL:
        raise ValueError('Unknown ranking format')
    if seconds(data.get('computed_at')) is None or not isinstance(data.get('counts'), dict):
        raise ValueError('Missing ranking observation time/coverage')
    items = data.get('items')
    if not isinstance(items, list) or len(items) > 10:
        raise ValueError('Invalid Top 10 items')
    seen = set()
    for row in items:
        t = row.get('ticker', '') if isinstance(row, dict) else ''
        if not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}', t) or t in seen:
            raise ValueError('Invalid or duplicate ranking symbol')
        seen.add(t)
        score, coverage = row.get('score'), row.get('coverage')
        if (not isinstance(score, (int, float)) or not isinstance(coverage, (int, float))
                or not 0 <= score <= coverage <= 100):
            raise ValueError('Invalid ranking score')
        if not isinstance(row.get('ready_at_calculation'), bool) or not isinstance(row.get('qualified'), bool):
            raise ValueError('Invalid readiness flags')
    return data


@st.cache_data(ttl=60, show_spinner=False)
def read_ranking(repo, local_file=''):
    try:
        if local_file:
            data = json.loads(Path(local_file).read_text(encoding='utf-8'))
        else:
            repo = checked_repo(repo)
            url = f'https://raw.githubusercontent.com/{repo}/dashboard-rankings/top10.json'
            with requests.Session() as session:
                session.trust_env = False
                with session.get(url, headers={'Authorization':None, 'Accept':'application/json'}, timeout=(3, 8), stream=True) as response:
                    response.raise_for_status()
                    parts = []; size = 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 1_000_000:
                            raise ValueError('Ranking response exceeds the size budget')
                        parts.append(chunk)
                    data = json.loads(b''.join(parts))
        return validate_payload(data), ''
    except (requests.RequestException, ValueError, OSError, TypeError, KeyError):
        return None, 'อ่านอันดับรอบใหม่ไม่ได้ — คงอันดับเดิมและเวลาจริงไว้'


def consume_selection(cache):
    pending = st.session_state.pop('_ranking_pending', None)
    if not pending:
        return
    ticker, info, meta = pending
    if not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}', ticker):
        return
    set_selected(st.session_state, ticker, reset_table=True)
    # Only import newer full public provider info, never stamp older fields as new.
    old, oldmeta = cache.get('info:' + ticker, request_remote=False)
    if (isinstance(info, dict) and isinstance(meta, dict) and
            (seconds(meta.get('fetched_at')) or 0) > (seconds(oldmeta.get('fetched_at')) or 0)):
        cache.put('info:' + ticker, info, meta)


def queue_selection(row):
    st.session_state['_ranking_pending'] = (row['ticker'], row.get('info', {}), row.get('info_meta', {}))


def compact_number(value, digits=2):
    n = a.number(value)
    return '—' if n is None else f'{n:,.{digits}f}'


@st.fragment(run_every=60)
def render_board(cache):
    if st.session_state.get('_ranking_pending'):
        st.rerun()
    config = a.settings() or {}
    repo = config.get('DASHBOARD_DATA_REPO') or a.DEFAULT_REPO
    local = os.environ.get('DASHBOARD_RANKING_FILE', '')
    payload, error = read_ranking(repo, local)
    key = 'ranking:last-good:' + repo + ':' + local
    previous, _ = cache.get(key, request_remote=False)
    if payload:
        # Never roll a user's board back to an older publication due to a CDN cache.
        if previous and (seconds(previous.get('computed_at')) or 0) > (seconds(payload['computed_at']) or 0):
            payload = previous
        elif not previous or previous.get('computed_at') != payload['computed_at']:
            cache.put(key, payload, {'fetched_at':utc().isoformat()})
    elif previous:
        try:
            payload = validate_payload(previous)
        except ValueError:
            payload = None
    with st.container(border=True, height=560, key='ranking_board'):
        st.subheader('Top 10 · น่าจับตาซื้อ')
        st.caption('จัดอันดับตามโมเดล / 100 · คลิกเพื่อเปิดกราฟ')
        if not payload:
            st.info('กำลังเตรียมอันดับจากทั้งทะเบียน ไม่ใช้รายชื่อสุ่มหรือข้อมูลจำลอง')
            st.caption('รอบจัดอันดับอัตโนมัติทุก 30 นาที')
            return
        counts = payload['counts']
        st.caption('จัดอันดับ '+a.thai_time(payload['computed_at']))
        st.caption(f"ตรวจ {counts.get('scanned',0):,}/{counts.get('total',0):,} รายชื่อ · ผ่านคัดกรอง {counts.get('candidates',0):,}")
        if error:
            st.warning(error)
        if not fresh(payload['computed_at'], utc(), STALE_SECONDS):
            st.warning('อันดับเกิน 35 นาที — ยังไม่รับรองว่าเป็นอันดับล่าสุด')
        if not payload['items']:
            st.info('ยังไม่มีหุ้นผ่านเกณฑ์ขั้นต่ำ ไม่เติมรายชื่อให้ครบ 10 โดยไม่มีหลักฐาน')
        for rank, row in enumerate(payload['items'], 1):
            status, ready = display_status(row, payload)
            badge = 'ผ่านแผน' if ready else 'รอยืนยัน' if row.get('qualified') else 'เฝ้าดู'
            label = f"{rank:02d} · {row['ticker']} · {row['score']}/100 · {badge}"
            st.button(label, key='ranking_pick_'+row['ticker'], width='stretch',
                      on_click=queue_selection, args=(row,))
        st.caption('รอบ 30 นาที · ไม่ใช่ราคาสตรีมสด / ไม่ใช่คำสั่งซื้อ')
        with st.expander('เหตุผล เงื่อนไข และอายุข้อมูล'):
            st.write('ใช้เกณฑ์คะแนนเดิม: แนวโน้ม โมเมนตัม วอลุ่ม ความผันผวน และพื้นฐาน; ETF ใช้ผลตอบแทน/เทียบ SPY แทน P/E คะแนนไม่ใช่โอกาสกำไร')
            st.write('อันดับพิจารณาทั้งทะเบียน ไม่เปลี่ยนตามการกรองตาราง: ราคา ≥ 1 USD, ราคา×ปริมาณเฉลี่ย 20 วัน ≥ 1 ล้าน USD, ประวัติ ≥ 200 แท่ง, ราคาไม่เกิน 4 วันปฏิทิน; ตัดข้อมูลไม่พอ บริษัท Shell และ ETF ทด/ผกผันที่ตรวจพบ')
            st.write('เรียงกลุ่มผ่านเงื่อนไข ณ เวลาราคาก่อน แล้วกลุ่มคะแนน ≥80/100 ข้อมูลครบและ R:R ≥2 ตามด้วยคะแนน ความครบ R:R และระยะห่างโซนเข้า; กลุ่มเฝ้าดูต้องคะแนน ≥60 แนวโน้มขึ้น และ R:R >0 ไม่เติมอันดับให้ครบสิบ')
            st.write('ผ่านแผนต้องมี quote ไม่เกิน 15 นาทีและอยู่ในโซนเข้า ช่วงตลาดปกติเท่านั้น; สถานะหมดอายุเองแม้อันดับยังไม่ถึงรอบใหม่ และการเรียงอันดับไม่ได้ยืนยันว่าราคาขณะกดซื้อยังเข้าเงื่อนไข')
            st.caption('Snapshot ต้นทาง '+a.thai_time(payload.get('source_published_at')))
            st.caption('รอบตามตารางถัดไป '+a.thai_time(payload.get('next_scheduled_at'))+' — อาจล่าช้าตาม GitHub Actions')
            refresh = payload.get('quote_refresh', {})
            st.caption(f"รอบนี้ตรวจ quote เฉพาะตัวคัดเลือก {refresh.get('success',0)}/{refresh.get('attempted',0)} ตัว; ไม่ได้ดึงราคาใหม่ทั้งทะเบียนทุก 30 นาที ข้อมูลเทคนิคหลักเป็นแท่งรายวัน")
            for row in payload['items']:
                status, _ = display_status(row, payload)
                st.markdown('**'+row['ticker']+' · '+str(row.get('name',''))+'**')
                st.write(f"{status} · คะแนน {row['score']}/100 · ความครบ {row['coverage']}/100 · R:R {compact_number(row.get('rr'))}")
                st.caption('เหตุผล: '+'; '.join(row.get('reasons', [])))
                st.caption(f"โซน {compact_number(row.get('zone_low'))}–{compact_number(row.get('zone_high'))} USD · RSI {compact_number(row.get('rsi'))}")
                st.caption('ราคาปิดวันที่ '+str(row.get('price_asof') or '—')+' · Quote ณ '+a.thai_time(row.get('quote_time')))
                for blocker in row.get('blockers', [])[:5]:
                    st.caption('รอ: '+str(blocker))
            sectors = [x.get('industry') for x in payload['items'] if x.get('industry') not in (None, '', 'ไม่ระบุ')]
            if sectors and max(sectors.count(x) for x in set(sectors)) >= 4:
                st.warning('หลายอันดับอยู่ในอุตสาหกรรมเดียวกัน ไม่ใช่พอร์ตที่กระจายความเสี่ยงแล้ว')
            st.json({'coverage': counts, 'excluded':payload.get('excluded', {})}, expanded=False)
