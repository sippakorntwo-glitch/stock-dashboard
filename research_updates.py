"""Compare source observations with an explicitly saved, private baseline."""
from __future__ import annotations

import math
from company_metrics import BY_KEY, metric_observations
from financial_statements import number, day

TRACKED = {'revenue': 'รายได้', 'netIncome': 'กำไรสุทธิ', 'operatingCashflow': 'เงินสดจากการดำเนินงาน',
           'forwardEps': 'ประมาณการ EPS จากผู้ให้ข้อมูล', 'targetMeanPrice': 'ราคาเป้าหมายจากผู้ให้ข้อมูล',
           'analystCount': 'จำนวนความเห็นนักวิเคราะห์'}
ESTIMATES = frozenset(('forwardEps', 'targetMeanPrice', 'analystCount'))


def build_tracking_snapshot(ticker, info, row, bundle=None):
    info, row = info or {}, row or {}
    values = metric_observations(ticker, info, bundle)
    snapshot = {'ticker': ticker, 'profile_asof': str(info.get('_Fetched_At_UTC') or ''),
                'financial_asof': str((bundle or {}).get('fetched_at') or ''),
                'price': number(row.get('Close')), 'price_asof': str(row.get('Price_AsOf') or '')}
    for key in TRACKED:
        item = values[key]
        snapshot[key] = number(item.get('value')) if item['state'] == 'available' else None
        snapshot[key + '_period'] = str(item.get('end') or '')
        snapshot[key + '_basis'] = str(item.get('basis') or '')
        snapshot[key + '_currency'] = str(item.get('currency') or '')
        snapshot[key + '_source'] = str(item.get('source') or '')
        snapshot[key + '_formula'] = str(item.get('formula') or '')
        # Scalar strings keep saved-workspace validation bounded and preserve
        # all four dates instead of treating a shared end date as a full match.
        snapshot[key + '_window'] = '|'.join(str(end) for end in item.get('period_ends', []))
        snapshot[key + '_unit'] = BY_KEY[key].unit
    return snapshot


def _valid_window(snapshot, key):
    if snapshot.get(key+'_basis') != 'TTM (4 reported quarters)':
        return True
    dates = [day(end) for end in str(snapshot.get(key+'_window') or '').split('|')]
    return (len(dates) == 4 and all(dates) and dates[0] == day(snapshot.get(key+'_period'))
            and all(65 <= (a-b).days <= 115 for a, b in zip(dates, dates[1:])))


def tracking_changes(previous, current):
    if not isinstance(previous, dict) or previous.get('ticker') != current.get('ticker'):
        return []
    events = []
    for key, label in TRACKED.items():
        old, new = number(previous.get(key)), number(current.get(key))
        if old is None or new is None:
            continue
        old_period, new_period = previous.get(key+'_period'), current.get(key+'_period')
        old_day, new_day = day(old_period), day(new_period)
        source = current.get(key+'_source')
        unit = current.get(key+'_unit')
        currency = current.get(key+'_currency')
        # A newer timestamp or end date alone does not establish a comparable
        # new statement. Legacy baselines without provenance need a new save.
        if (not source or not unit or not current.get(key+'_basis')
                or any(previous.get(key+suffix) != current.get(key+suffix)
                       for suffix in ('_basis', '_currency', '_source', '_formula', '_unit'))
                or (unit != 'count' and not currency)
                or not _valid_window(previous, key) or not _valid_window(current, key)):
            continue
        context = {'รายการ': label, 'เดิม': old, 'ล่าสุด': new,
                   'รอบเดิม': old_period or 'ไม่ระบุ', 'รอบล่าสุด': new_period or 'ไม่ระบุ',
                   'ช่วง': current.get(key+'_basis'), 'แหล่งข้อมูล': source,
                   'หน่วย': 'ความเห็น' if unit == 'count' else currency+'/หุ้น' if unit in ('per_share', 'quote_per_share') else currency}
        if key not in ESTIMATES:
            if (not old_day or not new_day
                    or current.get(key+'_basis') not in ('FY', 'TTM (4 reported quarters)')):
                continue
            if new_day > old_day:
                events.append({**context, 'การเปลี่ยนแปลง': 'มีรอบงบใหม่ในชุดข้อมูล'})
                continue
        if (old_period != new_period
                or previous.get(key+'_window') != current.get(key+'_window')):
            continue
        if not math.isclose(old, new, rel_tol=1e-9, abs_tol=1e-12):
            description = ('ค่าผู้ให้ข้อมูลเปลี่ยน; ยังไม่ยืนยันว่ารอบประมาณการเดิม'
                           if key in ESTIMATES
                           else 'ค่ารอบเดิมในชุดข้อมูลเปลี่ยน; ตรวจรายงานประกอบ')
            events.append({**context, 'การเปลี่ยนแปลง': description})
    return events


def render_research_updates(ticker, info, row, bundle, cache):
    import streamlit as st
    import pandas as pd
    from reference_ui import trusted_link
    with st.expander('สิ่งที่เปลี่ยนและเอกสารที่ควรติดตาม', expanded=False):
        current = build_tracking_snapshot(ticker, info, row, bundle)
        baselines = st.session_state.setdefault('_research_baselines', {})
        previous = baselines.get(ticker)
        events = tracking_changes(previous, current)
        if previous is None:
            st.caption('ยังไม่มีจุดอ้างอิงของหุ้นนี้ กดบันทึกข้อมูลด้านล่างเพื่อเทียบเมื่อกลับมาครั้งหน้า')
        elif events:
            st.dataframe(pd.DataFrame(events), hide_index=True, width='stretch')
        else:
            st.caption('ยังไม่พบการเปลี่ยนแปลงที่เทียบกันได้จากรายการที่ติดตาม; ข้อมูลขาดหรือรอบไม่ตรงกันจะไม่ถูกสรุปว่าเพิ่มหรือลด')
        if st.button('ใช้ข้อมูลนี้เป็นจุดอ้างอิง', key='baseline_'+ticker):
            baselines[ticker] = current
            st.success('ตั้งจุดอ้างอิงแล้ว บันทึกชุดวิเคราะห์เพื่อเก็บกลับมาใช้ครั้งหน้า')
        st.caption('เปรียบเทียบกับจุดอ้างอิงที่บันทึก ไม่ใช่ประวัติการเปลี่ยนแปลงทั้งหมดของผู้ให้ข้อมูล และไม่มีการส่งข้อความภายนอก')
        reference, _ = cache.get('reference:'+ticker, request_remote=False)
        filings = {}
        for fact in (reference or {}).get('facts', []):
            if isinstance(fact, dict) and trusted_link(fact.get('url')):
                filings[(str(fact.get('filed') or ''), fact['url'])] = fact
        if filings:
            st.write('รายงานที่มีในข้อมูลอ้างอิง SEC')
            for (filed, url), fact in sorted(filings.items(), reverse=True)[:3]:
                st.link_button('ยื่นรายงาน '+(filed or 'ไม่ระบุวัน')+' · สิ้นรอบ '+str(fact.get('period_end') or '—'), url)
        else:
            st.caption('ยังไม่มีเอกสาร SEC ที่ตรวจได้ในชุดข้อมูลของหุ้นนี้')
        st.caption('วันประกาศงบในอนาคตต้องมีปฏิทินที่ยืนยันได้; เวลาดึงข้อมูลไม่ใช่วันประกาศงบ')
