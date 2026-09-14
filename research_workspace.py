"""Validated, private research documents. No disk, network or shared-cache writes.

Only explicit UI preferences and research notes are serializable; restoring a
document can never inject arbitrary Streamlit widget or internal state.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, MutableMapping
from datetime import datetime, timezone

from dashboard_selection import set_selected
from filters_ui import ASSET_THAI, STATUS_THAI, METRICS, METRIC_GROUPS, CATEGORIES, PRESETS
from return_periods import RETURN_FIELDS, RETURN_MODES
from screener_view import RESULT_FIELDS, IDENTITY_FIELDS, VIEW_PRESETS

SCHEMA = 1
MAX_DOCUMENT_BYTES = 300_000
MAX_SYMBOLS = 100
MAX_NOTE_LENGTH = 6000
MODES = ('ภาพรวม', 'ลงทุนระยะยาว', 'จังหวะซื้อขาย')
TICKER_RE = re.compile(r'[A-Z0-9.^=/_-]{1,30}\Z')
TRACKING_METRICS = {
    'Close': 'ราคาจากชุดรายวัน', 'ROE': 'ROE (%)',
    'Revenue_Growth': 'การเติบโตรายได้ (%)', 'Profit_Margin': 'อัตรากำไรสุทธิ (%)',
    'Trailing_PE': 'P/E ย้อนหลัง (เท่า)', 'Dividend_Yield': 'อัตราปันผลย้อนหลัง (%)',
    'Debt_To_Equity': 'หนี้ต่อส่วนผู้ถือหุ้น (เท่า)', 'RSI_14': 'RSI 14',
}
RESEARCH_KEYS = {'notes': '_research_notes', 'tracking': '_research_tracking',
                 'baselines': '_research_baselines'}


def _symbol(value):
    return isinstance(value, str) and bool(TICKER_RE.fullmatch(value))


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool): return False
    try: return math.isfinite(value)
    except OverflowError: return False


def _text(value, limit=256):
    return isinstance(value, str) and len(value) <= limit and '\x00' not in value


def _list(value, limit, allowed=None, symbols=False):
    if not isinstance(value, list) or len(value) > limit:
        return None
    if any(not _text(v) or (symbols and not _symbol(v)) or
           (allowed is not None and v not in allowed) for v in value):
        return None
    return list(dict.fromkeys(value))


def preference_defaults():
    defaults = {
        'selected_ticker': 'AAPL', 'comparison_symbols': ['AAPL', 'SPY'], 'favourites': [],
        'research_mode': MODES[0], 'result_view_preset': 'overview', 'result_custom_columns': [],
        'screen_asset': 'All', 'screen_status': 'All', 'screen_return_mode': RETURN_MODES[0],
        'screen_sort': 'Ticker', 'screen_descending': False, 'screen_periods': [],
        'screen_required': [], 'screen_price_age': 4, 'screen_profile_age': 14,
        'stock_search': '', 'screen_preset': 'custom',
        'etf_compare_symbols': [], 'etf_benchmark_symbol': 'SPY',
    }
    defaults.update({key: [] for key in METRIC_GROUPS})
    defaults.update({'screen_cat_' + field: [] for field in CATEGORIES})
    defaults.update({'screen_' + field: False for field in
                     ('missing', 'fresh', 'profile_fresh', 'above_sma', 'bullish', 'favourites')})
    for field in (*RETURN_FIELDS, *METRICS):
        defaults['screen_min_' + field] = defaults['screen_max_' + field] = None
    return defaults


def validate_preferences(raw):
    if not isinstance(raw, Mapping) or len(raw) > 300:
        raise ValueError('รูปแบบการตั้งค่าชุดวิเคราะห์ไม่ถูกต้อง')
    clean = {}
    choices = {'research_mode': MODES, 'result_view_preset': VIEW_PRESETS,
               'screen_asset': ASSET_THAI, 'screen_status': STATUS_THAI,
               'screen_return_mode': RETURN_MODES, 'screen_preset': PRESETS,
               'screen_sort': ('Ticker', 'Industry', *RETURN_FIELDS, *METRICS)}
    defaults = preference_defaults()
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        valid = False
        if key in ('selected_ticker', 'etf_benchmark_symbol'): valid = _symbol(value)
        elif key in choices: valid = isinstance(value, str) and value in choices[key]
        elif key == 'stock_search': valid = _text(value, 200)
        elif key in ('comparison_symbols', 'favourites'):
            value = _list(value, 6 if key == 'comparison_symbols' else 25, symbols=True)
            valid = value is not None
        elif key == 'etf_compare_symbols':
            value = _list(value, 3, symbols=True); valid = value is not None
        elif key.startswith('peer_selection_') and _symbol(key[len('peer_selection_'):]):
            value = _list(value, 5, symbols=True); valid = value is not None
        elif key == 'result_custom_columns':
            value = _list(value, len(RESULT_FIELDS), set(RESULT_FIELDS) - set(IDENTITY_FIELDS))
            valid = value is not None
        elif key in ('screen_periods', 'screen_required'):
            value = _list(value, len(RETURN_FIELDS), RETURN_FIELDS); valid = value is not None
        elif key in METRIC_GROUPS:
            value = _list(value, len(METRICS), METRIC_GROUPS[key][1]); valid = value is not None
        elif key in {'screen_cat_' + field for field in CATEGORIES}:
            value = _list(value, 100); valid = value is not None
        elif key in ('screen_price_age', 'screen_profile_age'):
            valid = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 3650
        elif key in defaults and isinstance(defaults[key], bool): valid = isinstance(value, bool)
        elif key in defaults and key.startswith(('screen_min_', 'screen_max_')):
            valid = value is None or (_number(value) and abs(value) <= 1e18)
        else:
            # Unknown keys, credentials, component events and internal state are
            # intentionally never restored, even from an otherwise valid file.
            continue
        if not valid:
            raise ValueError('ค่าที่บันทึกไว้ไม่ถูกต้อง: ' + key)
        clean[key] = value
    for field in (*RETURN_FIELDS, *METRICS):
        lo, hi = clean.get('screen_min_' + field), clean.get('screen_max_' + field)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError('ค่าต่ำสุดมากกว่าค่าสูงสุด: ' + field)
    return clean


def validate_research(raw):
    if not isinstance(raw, Mapping):
        raise ValueError('รูปแบบบันทึกงานวิจัยไม่ถูกต้อง')
    result = {kind: {} for kind in RESEARCH_KEYS}
    for kind in RESEARCH_KEYS:
        records = raw.get(kind, {})
        if not isinstance(records, Mapping) or len(records) > MAX_SYMBOLS:
            raise ValueError('จำนวนหุ้นในบันทึกเกินกำหนด')
        for ticker, value in records.items():
            if not _symbol(ticker): raise ValueError('สัญลักษณ์หุ้นในบันทึกไม่ถูกต้อง')
            if kind == 'notes':
                if not _text(value, MAX_NOTE_LENGTH): raise ValueError('บันทึกต่อหุ้นยาวเกิน 6,000 ตัวอักษร')
                result[kind][ticker] = value
            elif kind == 'tracking':
                if not isinstance(value, list) or len(value) > 10:
                    raise ValueError('เงื่อนไขติดตามต่อหุ้นต้องไม่เกิน 10 รายการ')
                clean = []
                for item in value:
                    if (not isinstance(item, Mapping) or not isinstance(item.get('metric'), str) or
                        item.get('metric') not in TRACKING_METRICS or
                        item.get('op') not in ('>=', '<=') or not _number(item.get('value')) or
                        abs(item['value']) > 1e18):
                        raise ValueError('เงื่อนไขติดตามไม่ถูกต้อง')
                    entry = {key: item[key] for key in ('metric', 'op', 'value')}
                    if entry not in clean: clean.append(entry)
                result[kind][ticker] = clean
            else:
                if not isinstance(value, Mapping) or len(value) > 64:
                    raise ValueError('ข้อมูลเปรียบเทียบครั้งก่อนมีขนาดเกินกำหนด')
                baseline = {}
                for key, scalar in value.items():
                    if not _text(key, 80) or not (scalar is None or isinstance(scalar, bool) or
                                                _text(scalar, 256) or _number(scalar)):
                        raise ValueError('ข้อมูลเปรียบเทียบครั้งก่อนผิดรูปแบบ')
                    baseline[key] = scalar
                result[kind][ticker] = baseline
    return result


def validate_document(raw):
    if not isinstance(raw, Mapping) or raw.get('schema') != SCHEMA or isinstance(raw.get('schema'), bool):
        raise ValueError('ไฟล์นี้ไม่ใช่ชุดวิเคราะห์รุ่นที่รองรับ')
    name = raw.get('name', 'ชุดวิเคราะห์')
    if not _text(name, 80) or not name.strip(): raise ValueError('ชื่อชุดวิเคราะห์ต้องยาว 1–80 ตัวอักษร')
    created = raw.get('saved_at', '')
    if not _text(created, 40): raise ValueError('เวลาที่บันทึกผิดรูปแบบ')
    clean = {'schema': SCHEMA, 'name': name.strip(), 'saved_at': created,
             'preferences': validate_preferences(raw.get('preferences', {})),
             'research': validate_research(raw.get('research', {}))}
    if len(json.dumps(clean, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_DOCUMENT_BYTES:
        raise ValueError('ไฟล์ชุดวิเคราะห์มีขนาดเกิน 300 KB')
    return clean


def loads_document(data):
    if not isinstance(data, (str, bytes)) or len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError('ไฟล์ชุดวิเคราะห์มีขนาดเกิน 300 KB')
    try:
        raw = json.loads(data, parse_constant=lambda token: (_ for _ in ()).throw(ValueError('ค่าตัวเลขไม่ถูกต้อง')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('อ่านไฟล์ JSON ไม่สำเร็จ') from exc
    return validate_document(raw)


def capture_document(state: Mapping, name='ชุดวิเคราะห์'):
    preferences = preference_defaults()
    for key, value in state.items():
        if key in preferences or (isinstance(key, str) and key.startswith('peer_selection_')):
            preferences[key] = value
    research = {kind: dict(state.get(key, {})) for kind, key in RESEARCH_KEYS.items()}
    return validate_document({'schema': SCHEMA, 'name': name,
        'saved_at': datetime.now(timezone.utc).isoformat(), 'preferences': preferences, 'research': research})


def dumps_document(document):
    return json.dumps(validate_document(document), ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def restore_document(state: MutableMapping, document):
    """Only call before widgets exist, or in a Streamlit widget callback."""
    clean = validate_document(document)
    preferences = preference_defaults()
    preferences.update(clean['preferences'])
    ticker = preferences.pop('selected_ticker')
    # Invalidate old table/callback identity before restoring custom comparisons.
    set_selected(state, ticker, reset_table=True)
    for key in list(state):
        if isinstance(key, str) and key.startswith(('peer_selection_', 'research_note_')):
            state.pop(key, None)
    state.update(preferences)
    for kind, key in RESEARCH_KEYS.items(): state[key] = clean['research'][kind]
    state['_screen_group_layout'] = 1
    state['table_page'] = 1
    state['_filter_reset_version'] = state.get('_filter_reset_version', 0) + 1
    state['_research_active_name'] = clean['name']
    return clean


def hydrate_research(state: MutableMapping, raw):
    """A late browser response cannot replace notes already edited this visit."""
    clean = validate_research(raw)
    for kind, key in RESEARCH_KEYS.items():
        values = clean[kind]
        values.update(state.get(key, {}))
        state[key] = values


def research_digest(research):
    return hashlib.sha256(json.dumps(research, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def condition_id(condition):
    return hashlib.sha256(json.dumps(condition, sort_keys=True).encode()).hexdigest()[:16]


def evaluate_condition(condition, metrics):
    """Unknown or disputed values cannot be reported as a threshold crossing."""
    field = condition['metric']
    value = metrics.get(field) if metrics is not None else None
    source_state = metrics.get(field + '_State') if metrics is not None else None
    if source_state in ('source_disagreement', 'invalid_source', 'not_applicable') or not _number(value):
        return {'status': 'ข้อมูลไม่พอ', 'value': None, 'triggered': False}
    triggered = value >= condition['value'] if condition['op'] == '>=' else value <= condition['value']
    return {'status': 'เข้าเงื่อนไข' if triggered else 'ยังไม่เข้าเงื่อนไข', 'value': value, 'triggered': triggered}
