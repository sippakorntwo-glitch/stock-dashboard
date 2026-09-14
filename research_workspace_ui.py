"""Browser-local named research workspaces and private per-stock notes.

Integration: startup_before_widgets() before any input widgets; render_sidebar()
once per full run; render_stock_notes(ticker, metrics) in the stock detail area.
The v1 component speaks the official component-lib postMessage protocol. It has
no external JavaScript, requests, analytics, cookies or server-side storage.
"""
from __future__ import annotations

from pathlib import Path
import uuid

import streamlit as st
import streamlit.components.v1 as components

from research_workspace import (
    TRACKING_METRICS, MAX_NOTE_LENGTH, MAX_DOCUMENT_BYTES, MAX_SYMBOLS,
    capture_document, dumps_document, loads_document, restore_document,
    validate_document, hydrate_research, research_digest, condition_id,
    evaluate_condition,
)

_browser_store = None


def startup_before_widgets():
    """Apply a validated pending load exactly once, before widget construction."""
    state = st.session_state
    state.setdefault('_research_boot_token', uuid.uuid4().hex)
    hydration = state.pop('_research_pending_hydration', None)
    if hydration is not None:
        try:
            hydrate_research(state, hydration)
            # Hydration arrives after the previous render. Synchronize these
            # widgets only now, before construction, retaining this visit's edits.
            for key in list(state):
                if isinstance(key, str) and key.startswith('research_note_'):
                    state[key] = state.get('_research_notes', {}).get(key[len('research_note_'):], '')
        except ValueError as exc:
            state['_research_error'] = str(exc)
        state['_research_hydrated'] = True
    pending = state.pop('_research_pending_restore', None)
    if pending is not None:
        try:
            clean = restore_document(state, pending)
            state['_research_notice'] = 'เปิดชุดวิเคราะห์ “' + clean['name'] + '” แล้ว'
        except ValueError as exc:
            state['_research_error'] = str(exc)


def _import_uploaded():
    uploaded = st.session_state.get('research_workspace_import')
    if uploaded is None:
        st.session_state['_research_error'] = 'เลือกไฟล์ JSON ก่อนเปิดชุดวิเคราะห์'
        return
    try:
        data = uploaded.getvalue()
        if len(data) > MAX_DOCUMENT_BYTES: raise ValueError('ไฟล์ชุดวิเคราะห์มีขนาดเกิน 300 KB')
        st.session_state['_research_pending_restore'] = loads_document(data)
    except ValueError as exc:
        st.session_state['_research_error'] = str(exc)


def _component_event(event):
    if not isinstance(event, dict) or not isinstance(event.get('id'), str) or len(event['id']) > 120:
        return False
    state = st.session_state
    if event['id'] == state.get('_research_last_event'): return False
    state['_research_last_event'] = event['id']
    try:
        if event.get('action') == 'hydrate':
            if not state.get('_research_hydrated'):
                state['_research_pending_hydration'] = event.get('research', {})
                return True
        elif event.get('action') == 'load':
            state['_research_pending_restore'] = validate_document(event.get('document'))
            return True
    except ValueError as exc:
        state['_research_error'] = str(exc)
        # Corrupt/old local storage must not create a hydration rerun loop.
        if event.get('action') == 'hydrate': state['_research_hydrated'] = True
        return True
    return False


def render_sidebar():
    global _browser_store
    if _browser_store is None:
        _browser_store = components.declare_component(
            'private_research_workspace', path=str(Path(__file__).with_name('research_workspace_component')))
    state = st.session_state
    with st.sidebar.expander('ชุดวิเคราะห์และบันทึกส่วนตัว', expanded=False):
        st.caption('บันทึกในเบราว์เซอร์นี้ ผู้ใช้โปรไฟล์เบราว์เซอร์เดียวกันเข้าถึงได้ · ส่งออก JSON เพื่อย้ายเครื่องหรือสำรองข้อมูล')
        error = state.pop('_research_error', None)
        notice = state.pop('_research_notice', None)
        if error: st.warning(error)
        if notice: st.success(notice)
        try:
            document = capture_document(state, state.get('_research_active_name', 'ชุดวิเคราะห์ของฉัน'))
        except ValueError as exc:
            st.warning(str(exc) + ' · แก้การตั้งค่านี้ก่อนบันทึก')
            return
        research = document['research']
        event = _browser_store(
            document=document, draft=research, draft_revision=research_digest(research),
            hydrated=bool(state.get('_research_hydrated')),
            boot_token=state.get('_research_boot_token', ''),
            key='research_private_browser_store', default=None,
        )
        if _component_event(event): st.rerun()
        st.download_button('ส่งออกชุดวิเคราะห์ JSON', dumps_document(document),
            file_name='stock_research_workspace.json', mime='application/json',
            key='research_workspace_export',
            help='รวมตัวกรอง คอลัมน์ หุ้นเปรียบเทียบ รายการโปรด บันทึก และเงื่อนไขติดตาม')
        st.file_uploader('นำเข้าชุดวิเคราะห์ JSON', type=['json'], key='research_workspace_import',
                         help='ไฟล์จากปุ่มส่งออก ขนาดไม่เกิน 300 KB')
        st.button('เปิดชุดวิเคราะห์จากไฟล์', key='research_workspace_import_apply', on_click=_import_uploaded)


def _save_note(ticker, widget_key):
    notes = dict(st.session_state.get('_research_notes', {}))
    text = st.session_state.get(widget_key, '')
    # An empty edit is a tombstone: delayed browser hydration must not revive
    # a note that the user cleared during this visit.
    if ticker in notes or len(notes) < MAX_SYMBOLS:
        notes[ticker] = text[:MAX_NOTE_LENGTH]
    st.session_state['_research_notes'] = notes


def _add_condition(ticker):
    prefix = 'research_condition_' + ticker + '_'
    item = {'metric': st.session_state.get(prefix + 'metric', 'Close'),
            'op': st.session_state.get(prefix + 'op', '<='),
            'value': float(st.session_state.get(prefix + 'value', 0.0))}
    tracking = dict(st.session_state.get('_research_tracking', {}))
    if ticker not in tracking and len(tracking) >= MAX_SYMBOLS: return
    current = list(tracking.get(ticker, []))
    if item not in current and len(current) < 10: current.append(item)
    tracking[ticker] = current
    st.session_state['_research_tracking'] = tracking


def _remove_condition(ticker, identity):
    tracking = dict(st.session_state.get('_research_tracking', {}))
    tracking[ticker] = [item for item in tracking.get(ticker, []) if condition_id(item) != identity]
    st.session_state['_research_tracking'] = tracking


def render_stock_notes(ticker, metrics=None):
    with st.expander('บันทึกเหตุผลการลงทุนและเงื่อนไขติดตาม', expanded=False):
        st.caption('จดเหตุผลที่สนใจ สิ่งที่ต้องเห็นในงบหน้า และเหตุการณ์ที่จะทำให้เปลี่ยนมุมมอง · บันทึกอัตโนมัติในเบราว์เซอร์นี้เมื่อออกจากช่อง')
        key = 'research_note_' + ticker
        if key not in st.session_state:
            st.session_state[key] = st.session_state.get('_research_notes', {}).get(ticker, '')
        st.text_area('บันทึกของฉัน · ' + ticker, key=key, max_chars=MAX_NOTE_LENGTH,
                     height=130, on_change=_save_note, args=(ticker, key),
                     disabled=ticker not in st.session_state.get('_research_notes', {}) and len(st.session_state.get('_research_notes', {})) >= MAX_SYMBOLS,
                     placeholder='เหตุผลที่สนใจ / หลักฐานที่ต้องติดตาม / เงื่อนไขที่จะเปลี่ยนมุมมอง')
        conditions = st.session_state.get('_research_tracking', {}).get(ticker, [])
        st.caption('เงื่อนไขประเมินจากชุดข้อมูลที่หน้าเว็บกำลังแสดงเมื่อเปิดหรือรีเฟรช ไม่ส่งการแจ้งเตือนเมื่อปิดเว็บ · ราคาใช้ชุดรายวัน')
        for item in conditions:
            result = evaluate_condition(item, metrics)
            value = '—' if result['value'] is None else f"{result['value']:,.4g}"
            left, right = st.columns([5, 1])
            sign = '≥' if item['op'] == '>=' else '≤'
            left.write(f"{TRACKING_METRICS[item['metric']]} {sign} {item['value']:,.4g} · {result['status']} · ล่าสุด {value}")
            identity = condition_id(item)
            right.button('ลบ', key='research_remove_' + ticker + '_' + identity,
                         on_click=_remove_condition, args=(ticker, identity))
        with st.form('research_condition_form_' + ticker, clear_on_submit=False):
            prefix = 'research_condition_' + ticker + '_'
            st.selectbox('ตัวแปรที่ติดตาม', list(TRACKING_METRICS), format_func=TRACKING_METRICS.get,
                         key=prefix + 'metric')
            left, right = st.columns(2)
            left.selectbox('เงื่อนไข', ['<=', '>='], format_func=lambda op: 'ไม่เกิน (≤)' if op == '<=' else 'อย่างน้อย (≥)', key=prefix + 'op')
            right.number_input('ค่าที่ต้องการติดตาม', value=0.0, min_value=-1e18, max_value=1e18, key=prefix + 'value')
            st.form_submit_button('เพิ่มเงื่อนไขติดตาม', on_click=_add_condition, args=(ticker,),
                disabled=len(conditions) >= 10 or (ticker not in st.session_state.get('_research_tracking', {}) and len(st.session_state.get('_research_tracking', {})) >= MAX_SYMBOLS))
        st.caption('เก็บบันทึกได้ 100 หุ้น และไม่เกิน 10 เงื่อนไขต่อหุ้น · บันทึกชุดวิเคราะห์แบบตั้งชื่อเพื่อเก็บตัวกรองและมุมมองปัจจุบันด้วย')
