"""Thai peer research, bounded to five peers and the supplied coherent cache."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from company_analysis_th import (FORMULAS, METRIC_TEXT, PERIOD_LABELS, SOURCE_LABELS,
                                 STATE_VALUES, TEXT, format_value_th)
from company_metrics import BY_KEY
from peer_analysis import (MAX_PEERS, MIN_BENCHMARK_PEERS, PERIOD_TOLERANCE_DAYS,
                           build_peer_analysis, peer_candidates, selected_peer_symbols)

REASONS = {
    'unavailable': 'ข้อมูลไม่พร้อมหรือใช้คำนวณไม่ได้',
    'unknown_period': 'ไม่ทราบรอบบัญชี จึงไม่นำมาคำนวณค่ากลาง',
    'unknown_currency': 'ไม่ทราบสกุลเงินของงบ',
    'unknown_source': 'ไม่ทราบแหล่งข้อมูล',
    'unknown_window': 'ข้อมูลวันที่ทั้ง 4 ไตรมาสไม่ครบหรือไม่ต่อเนื่อง',
    'currency_mismatch': 'สกุลเงินของงบต่างกัน',
    'basis_mismatch': 'ชนิดงวดต่างกัน เช่น FY กับ TTM',
    'period_mismatch': 'วันสิ้นงวดห่างกันเกิน 31 วัน',
    'window_mismatch': 'ช่วง 4 ไตรมาสไม่ตรงกันภายใน 31 วัน',
    'method_mismatch': 'แหล่งข้อมูลหรือวิธีคำนวณต่างกัน',
}


def _reason(reason):
    if reason and reason.startswith('reference_'):
        return 'หุ้นที่กำลังวิเคราะห์: ' + REASONS.get(reason[10:], reason[10:])
    return REASONS.get(reason, reason or '')


def _period(item):
    basis = item.get('basis', 'Not reported')
    return PERIOD_LABELS.get(basis, basis) + (' · ' + item['end'] if item.get('end') else '')


def peer_tables(analysis, records):
    """The CSV and visible table share observations and comparison exclusions."""
    ticker, peers = analysis['ticker'], analysis['peers']
    comparison, evidence = [], []
    for row in analysis['rows']:
        key, benchmark = row['key'], row['benchmark']
        metric = BY_KEY[key]
        label = METRIC_TEXT[key][0]
        shown = {'ตัวชี้วัด': label}
        for symbol, item in row['observations'].items():
            info = (records.get(symbol) or {}).get('info') or {}
            value = format_value_th(metric, item, info)
            shown[symbol] = value + (' · ' + _period(item) if item.get('state') == 'available' else '')
            excluded = benchmark['excluded'].get(symbol)
            source_reason = item.get('reason')
            evidence.append({'หุ้น': symbol, 'ตัวชี้วัด': label,
                             'ค่าที่แสดง': value, 'ค่าก่อนปัดเศษ': item.get('value'),
                             'หน่วยค่าดิบ': 'สัดส่วน (คูณ 100 เป็น %)' if metric.unit == '%' else metric.unit,
                             'สถานะ': STATE_VALUES.get(item.get('state'), 'ไม่มีข้อมูลรายงาน'),
                             'รอบข้อมูล': _period(item), 'สิ้นงวด': item.get('end'),
                             'สกุลเงินงบ': item.get('currency'),
                             'แหล่งข้อมูล': SOURCE_LABELS.get(item.get('source'), item.get('source')),
                             'ดึงข้อมูลเมื่อ UTC': info.get('_Fetched_At_UTC') if item.get('source') == 'Yahoo Finance profile' else ((records.get(symbol) or {}).get('bundle') or {}).get('fetched_at'),
                             'สูตร': FORMULAS.get(item.get('formula'), item.get('formula')),
                             'เหตุผลจากต้นทาง': TEXT.get(source_reason, source_reason) or '',
                             'การเทียบกลุ่ม': 'หุ้นที่กำลังวิเคราะห์' if symbol == ticker else _reason(excluded) if excluded else 'เข้าเกณฑ์รอบข้อมูลเดียวกัน',
                             'ค่ากลางกลุ่ม (ค่าดิบ)': benchmark['median'],
                             'ตำแหน่งค่าในกลุ่ม (%)': benchmark['percentile'],
                             'จำนวนคู่เทียบที่ใช้ได้': benchmark['count']})
        if benchmark['median'] is not None:
            shown['ค่ากลางคู่เทียบ'] = format_value_th(metric, {'state': 'available', 'value': benchmark['median']}, {})
            shown['ตำแหน่งค่าในกลุ่ม'] = f"{benchmark['percentile']:.0f}%"
        else:
            shown['ค่ากลางคู่เทียบ'] = 'ข้อมูลที่เทียบกันได้ไม่พอ'
            shown['ตำแหน่งค่าในกลุ่ม'] = '—'
        shown['คู่เทียบที่ใช้ได้'] = f"{benchmark['count']}/{len(peers)}"
        comparison.append(shown)
    return pd.DataFrame(comparison), pd.DataFrame(evidence)


def render_peer_analysis(ticker, frame, cache, info=None):
    st.subheader('เปรียบเทียบพื้นฐานกับคู่แข่ง', anchor='peer-analysis')
    candidates = peer_candidates(ticker, frame, info)
    if not candidates:
        st.info('ยังไม่มีบริษัทหุ้นสามัญในอุตสาหกรรมเดียวกันที่ยืนยันได้ในรายชื่อ หรือหลักทรัพย์นี้เป็นกองทุน จึงไม่สร้างคู่เทียบจากชื่อหรือกลุ่มธุรกิจที่ต่างกัน')
        return
    options = [row['Ticker'] for row in candidates]
    labels = {row['Ticker']: f"{row['Ticker']} · {row.get('Security_Name') or row['Ticker']}" for row in candidates}
    key = f'peer_selection_{ticker}'
    saved = st.session_state.get(key)
    chosen = selected_peer_symbols(ticker, frame, saved, info)
    if not isinstance(saved, (list, tuple)) or list(saved) != chosen:
        st.session_state[key] = chosen
    # A default is established after the root pinned its dependency vector.
    # Rerun before reading peers so page_revision never projects unfrozen keys.
    dependencies = getattr(cache, 'dependencies', None)
    if dependencies is not None and not set(chosen).issubset(dependencies):
        st.rerun()
    st.caption('เริ่มจากบริษัทอุตสาหกรรมเดียวกัน โดยให้ความสำคัญกับสกุลเงินงบ สกุลเงินราคา และขนาดกิจการที่ใกล้กัน ปรับรายชื่อได้สูงสุด 5 บริษัท ควรตรวจลักษณะรายได้และรูปแบบธุรกิจร่วมด้วย')
    chosen = st.multiselect('เลือกคู่แข่ง 3–5 บริษัท', options, key=key,
                            max_selections=MAX_PEERS, format_func=lambda symbol: labels.get(symbol, symbol),
                            help='การลบทุกตัวจะคงชุดว่างไว้ เลือกน้อยกว่า 3 ตัวได้เพื่ออ่านค่ารายบริษัท แต่จะยังไม่มีค่ากลางหรือเปอร์เซ็นไทล์')
    if dependencies is not None and not set(chosen).issubset(dependencies):
        st.rerun()
    if not chosen:
        st.info('เลือกบริษัทคู่แข่งเพื่อเริ่มเปรียบเทียบ')
        return
    records = {}
    for symbol in [ticker, *chosen]:
        if symbol == ticker and info is not None:
            profile = dict(info)
        else:
            profile, metadata = cache.get('info:' + symbol)
            profile = dict(profile or {})
            profile['_Fetched_At_UTC'] = (metadata or {}).get('fetched_at')
        bundle, _ = cache.get('financials:' + symbol)
        records[symbol] = {'info': profile, 'bundle': bundle}
    analysis = build_peer_analysis(ticker, records, chosen)
    comparison, evidence = peer_tables(analysis, records)
    valid = sum(row['benchmark']['state'] == 'available' for row in analysis['rows'])
    st.caption(f'มีค่ากลางที่เทียบกันได้ {valid}/{len(analysis["rows"])} ตัวชี้วัด · ไม่เติมข้อมูลที่ขาดเป็นศูนย์')
    st.dataframe(comparison, hide_index=True, width='stretch', column_config={
        'ตัวชี้วัด': st.column_config.TextColumn('ตัวชี้วัด', pinned=True),
        'ค่ากลางคู่เทียบ': st.column_config.TextColumn('ค่ากลางคู่เทียบ', help='มัธยฐานของคู่แข่งที่ผ่านการตรวจรอบข้อมูลอย่างน้อย 3 บริษัท ไม่รวมหุ้นที่กำลังวิเคราะห์'),
        'ตำแหน่งค่าในกลุ่ม': st.column_config.TextColumn('ตำแหน่งค่าในกลุ่ม', help='สัดส่วนคู่เทียบที่มีค่าต่ำกว่า ค่าที่เท่ากันนับครึ่งหนึ่ง ค่าสูงไม่ได้แปลว่าดีหรือควรซื้อ โดยเฉพาะ P/E และหนี้'),
        'คู่เทียบที่ใช้ได้': st.column_config.TextColumn('คู่เทียบที่ใช้ได้', help='จำนวนที่ผ่านเกณฑ์ / จำนวนที่เลือก ตัวที่ไม่ผ่านยังปรากฏในตารางและมีเหตุผลในรายละเอียด'),
    })
    st.caption(f'ค่ากลางต้องมีคู่เทียบอย่างน้อย {MIN_BENCHMARK_PEERS} บริษัท: ใช้สกุลเงินงบ แหล่งข้อมูล วิธีคำนวณ และชนิดงวดเดียวกัน วันสิ้นงวดห่างไม่เกิน {PERIOD_TOLERANCE_DAYS} วัน; TTM ตรวจครบทั้ง 4 ไตรมาส ข้อมูล P/E หรืออัตราส่วนจากผู้ให้ข้อมูลที่ไม่ระบุรอบบัญชีแสดงให้อ่านได้ แต่ไม่รวมในค่ากลาง')
    st.caption('ตำแหน่งค่าในกลุ่มเป็นลำดับของตัวเลข ไม่ใช่คะแนนคุณภาพหรือสัญญาณซื้อขาย กลุ่ม 3–5 บริษัทมีขนาดเล็ก และสกุลเงินเดียวกันไม่ได้ยืนยันว่ามาตรฐานบัญชีหรือส่วนผสมธุรกิจเหมือนกัน')
    with st.expander('แหล่งข้อมูล สูตร และเหตุผลที่บางบริษัทไม่อยู่ในค่ากลาง'):
        st.dataframe(evidence.drop(columns=['ค่าก่อนปัดเศษ', 'ค่ากลางกลุ่ม (ค่าดิบ)']), hide_index=True, width='stretch')
    st.download_button('ดาวน์โหลดการเปรียบเทียบคู่แข่ง', evidence.to_csv(index=False).encode('utf-8-sig'),
                       f'{ticker}_peer_analysis.csv', 'text/csv', key=f'peer_export_{ticker}', on_click='ignore')
