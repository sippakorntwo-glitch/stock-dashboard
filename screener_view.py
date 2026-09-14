"""Result columns follow the research question and the active filter evidence.

Only presentation changes here. Values, row order, pagination and selection
remain owned by the canonical screener and dashboard table.
"""
from __future__ import annotations

from filters_ui import METRICS, METRIC_THAI, CATEGORIES, CATEGORY_THAI
from return_periods import (TABLE_FIELDS, RETURN_FIELDS, EXPORT_LABELS,
                            RETURN_MODES, labels_for_mode, return_column_config)
from screening import NUMERIC_FIELDS


IDENTITY_FIELDS = ('Ticker', 'Security_Name')
VIEW_PRESETS = {
    'overview': ('ผลตอบแทนภาพรวม', TABLE_FIELDS),
    'fundamentals': ('พื้นฐานและมูลค่าบริษัท', (
        'Ticker', 'Security_Name', 'Industry', 'Asset_Type', 'Close',
        'Market_Cap_Millions', 'Trailing_PE', 'Forward_PE', 'Revenue_Growth',
        'Profit_Margin', 'Operating_Margin', 'ROE', 'Debt_To_Equity',
        'Free_Cash_Flow', 'Price_AsOf', 'Data_Status')),
    'momentum': ('แนวโน้มและความเสี่ยง', (
        'Ticker', 'Security_Name', 'Industry', 'Asset_Type', 'Status', 'Close',
        'Return_1D', 'Return_1M', 'Historical_Return', 'RSI_14', 'Vol_Ratio',
        'SMA200', 'EMA20', 'EMA50', 'ATR_Pct', 'Volatility_20D',
        'Drawdown_52W', 'Dollar_Volume_20D', 'Price_AsOf', 'Data_Status')),
    'etf': ('กองทุน ETF', (
        'Ticker', 'Security_Name', 'Industry', 'Asset_Type', 'Fund_Family',
        'Close', 'Fund_Assets_Millions', 'Dividend_Yield',
        'Historical_Return', 'Return_3Y', 'Return_5Y', 'Volatility_20D',
        'Drawdown_52W', 'Dollar_Volume_20D', 'Price_AsOf', 'Data_Status')),
    'custom': ('เลือกคอลัมน์เอง', TABLE_FIELDS),
}
EXTRA_LABELS = {
    'SMA200': 'SMA 200', 'EMA20': 'EMA 20', 'EMA50': 'EMA 50',
    'Profile_AsOf': 'ข้อมูลพื้นฐานดึงสำเร็จ (UTC)',
    'Dividend_Yield_State': 'สถานะข้อมูลอัตราปันผล',
    'Dividend_Yield_Conflict_Date': 'วันที่เงินจ่ายที่ต้องตรวจนิยาม',
}
RESULT_FIELDS = tuple(dict.fromkeys((
    *TABLE_FIELDS, *METRICS, *CATEGORIES, *EXTRA_LABELS)))
PROFILE_COLUMNS = frozenset((
    *NUMERIC_FIELDS, *CATEGORIES, 'Size_Millions',
    'Market_Cap_Millions', 'Fund_Assets_Millions')) - {'Industry'}
PRICE_MONEY_COLUMNS = frozenset((
    'Close', 'Size_Millions', 'Market_Cap_Millions', 'Fund_Assets_Millions',
    'Dollar_Volume_20D', 'SMA200', 'EMA20', 'EMA50'))


def column_labels(mode=RETURN_MODES[0]):
    return {**EXPORT_LABELS, **METRIC_THAI, **CATEGORY_THAI,
            **EXTRA_LABELS, **labels_for_mode(mode)}


def result_fields(preset='overview', active_fields=(), selected_fields=None):
    """Choose safe ordered columns; filter evidence cannot be hidden.

    Keep the legacy overview exactly when no extra evidence is needed. Custom
    selection order is preserved, while Ticker/Company always identify a row.
    Currency, profile date and disputed-yield status accompany relevant values.
    Unknown or duplicate fields from a saved view are ignored.
    """
    preset = preset if preset in VIEW_PRESETS else 'overview'
    chosen = selected_fields if preset == 'custom' and selected_fields is not None else VIEW_PRESETS[preset][1]
    chosen = [f for f in chosen if f in RESULT_FIELDS and f not in IDENTITY_FIELDS]
    active = list(dict.fromkeys(f for f in active_fields if f in RESULT_FIELDS and f not in IDENTITY_FIELDS))
    # Keep established column positions if all active evidence is already shown.
    missing_active = [f for f in active if f not in chosen]
    fields = list(dict.fromkeys((*IDENTITY_FIELDS, *missing_active, *chosen)))
    # The default overview's legacy schema is intentionally unchanged. New
    # monetary columns and any financial view include their source context.
    extra = set(fields) - set(TABLE_FIELDS)
    context = []
    if (set(fields) & PRICE_MONEY_COLUMNS and (extra or preset != 'overview')) or 'Close' in active:
        context.append('Currency')
    if 'Free_Cash_Flow' in fields:
        context.append('Financial_Currency')
    if set(fields) & PROFILE_COLUMNS:
        context.append('Profile_AsOf')
    if 'Dividend_Yield' in fields:
        context.extend(('Dividend_Yield_State', 'Dividend_Yield_Conflict_Date'))
    return list(dict.fromkeys((*fields, *context)))


def render_result_columns(work):
    """Render purpose/custom controls and return ordered raw field names."""
    import streamlit as st
    mode = work.attrs.get('return_mode', RETURN_MODES[0])
    labels = column_labels(mode)
    if st.session_state.get('result_view_preset', 'overview') not in VIEW_PRESETS:
        st.session_state['result_view_preset'] = 'overview'
    preset = st.selectbox('มุมมองตารางผลลัพธ์', list(VIEW_PRESETS),
        format_func=lambda key: VIEW_PRESETS[key][0], key='result_view_preset',
        help='เปลี่ยนเฉพาะคอลัมน์ หุ้นและเงื่อนไขที่ผ่านตัวกรองยังคงเดิม')
    selected = None
    with st.expander('ปรับคอลัมน์และลำดับ', expanded=preset == 'custom'):
        options = [f for f in RESULT_FIELDS if f not in IDENTITY_FIELDS]
        previous = st.session_state.get('result_custom_columns')
        if previous is not None:
            valid = list(dict.fromkeys(f for f in previous if f in options))
            if valid != previous:
                st.session_state['result_custom_columns'] = valid
        def use_custom():
            st.session_state['result_view_preset'] = 'custom'
        defaults = {} if 'result_custom_columns' in st.session_state else {
            'default': [f for f in TABLE_FIELDS if f not in IDENTITY_FIELDS]}
        selected = st.multiselect('คอลัมน์ตามลำดับที่เลือก', options,
            format_func=lambda f: labels.get(f, f), key='result_custom_columns', on_change=use_custom,
            **defaults,
            help='เลือกใหม่ตามลำดับที่ต้องการ ชื่อหุ้นและชื่อบริษัทอยู่หน้าเสมอ เกณฑ์ที่ใช้กรองและหน่วยอ้างอิงจะยังแสดง')
    active = work.attrs.get('active_filter_fields', [])
    fields = result_fields(preset, active, selected)
    if active:
        st.caption('แสดงหลักฐานของตัวกรองอัตโนมัติ: '+', '.join(
            labels.get(f, f) for f in dict.fromkeys(active) if f in RESULT_FIELDS))
    if preset != 'overview':
        st.caption('มุมมองเปลี่ยนเฉพาะคอลัมน์ หากต้องการเฉพาะหุ้นบริษัทหรือ ETF ให้เลือกประเภทสินทรัพย์ในตัวกรอง · ช่อง — หมายถึงไม่มีข้อมูลหรือใช้ไม่ได้กับสินทรัพย์นั้น')
    work.attrs['result_columns'] = fields
    work.attrs['result_view_preset'] = preset
    return fields


def result_column_config(fields, mode=RETURN_MODES[0]):
    """Numeric source values stay numeric, with percentages already in points."""
    import streamlit as st
    labels = column_labels(mode)
    percent = {'Dividend_Yield', 'Revenue_Growth', 'Profit_Margin',
               'Operating_Margin', 'ROE', 'ROA', 'ATR_Pct',
               'Volatility_20D', 'Drawdown_52W'}
    numeric = set(METRICS) | {'SMA200', 'EMA20', 'EMA50'}
    definitions = {
        'Currency': 'สกุลเงินราคาและมูลค่าตลาดจากผู้ให้ข้อมูล ไม่มีการแปลง FX อัตโนมัติ',
        'Financial_Currency': 'สกุลเงินในงบการเงิน ใช้กับกระแสเงินสด ซึ่งอาจต่างจากสกุลเงินราคา',
        'Profile_AsOf': 'เวลาที่ดึงโปรไฟล์สำเร็จ ไม่ใช่วันสิ้นงวดบัญชีของทุกตัวเลข เปรียบเทียบรอบงบในส่วนวิเคราะห์การเงินประกอบ',
        'Dividend_Yield': 'trailingAnnualDividendYield × 100 จากโปรไฟล์ ไม่ใช่ Distribution Rate หรือ 30-Day SEC Yield; ดูคอลัมน์สถานะเมื่อไม่มีค่า',
        'Dividend_Yield_State': 'available = มีข้อมูล; not_reported = ไม่รายงาน; source_disagreement = นิยามต้นทางขัดแย้ง; invalid_source = ต้นทางไม่ถูกต้อง; not_applicable = ใช้ไม่ได้กับสินทรัพย์นี้',
        'Dividend_Yield_Conflict_Date': 'วันเงินจ่ายบวกที่ทับกับโปรไฟล์ Yield 0% และยังยืนยันนิยามไม่ได้ จึงกักค่า Yield แทนการคำนวณตัวเลขทดแทน',
        'Debt_To_Equity': 'หนี้ต่อส่วนผู้ถือหุ้น หน่วยเท่า (ข้อมูล debtToEquity ของผู้ให้ข้อมูลหาร 100 แล้ว)',
        'Free_Cash_Flow': 'กระแสเงินสดอิสระที่โปรไฟล์รายงาน หน่วยตาม Financial Currency; ตรวจรอบงบและที่มาในหน้าวิเคราะห์บริษัท',
        'Dollar_Volume_20D': 'ค่าเฉลี่ยราคา × ปริมาณ 20 วันจากราคาปรับแล้ว เป็นค่าประมาณสภาพคล่องในสกุลเงินราคา ไม่ใช่มูลค่าซื้อขายจริงจากตลาด',
        'Market_Cap_Millions': 'มูลค่าตลาดบริษัทหาร 1,000,000 ตาม Currency ไม่ใช้กับ ETF',
        'Fund_Assets_Millions': 'สินทรัพย์กองทุนหาร 1,000,000 ตาม Currency ไม่ใช้กับหุ้นบริษัท',
        'Size_Millions': 'มูลค่าตลาดบริษัทหรือสินทรัพย์กองทุนหาร 1,000,000 ตาม Currency ไม่ใช่ตัวเลขที่ใช้แทนกันได้',
        'Close': 'ราคาปรับแล้วจากชุดรายวัน ณ Price As Of ไม่ใช่ราคาเรียลไทม์',
    }
    config = {}
    return_config = return_column_config(mode)
    for field in fields:
        if field in return_config:
            config[field] = return_config[field]
        elif field in numeric:
            fmt = '%.2f%%' if field in percent else '%.0f' if field in ('Dollar_Volume_20D', 'Free_Cash_Flow') else '%.2f'
            config[field] = st.column_config.NumberColumn(labels.get(field, field),
                format=fmt, help=definitions.get(field))
        else:
            config[field] = st.column_config.Column(labels.get(field, field),
                help=definitions.get(field))
    return config
