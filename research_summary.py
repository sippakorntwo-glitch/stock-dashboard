"""Evidence-led company overview; coverage never becomes an investment score."""
from __future__ import annotations

from company_metrics import BY_KEY, metric_observations, specialized_company
from company_analysis_th import (METRIC_TEXT, format_value_th, profile_text_th,
                                 TEXT, PERIOD_LABELS, SOURCE_LABELS, STATE_VALUES)
from financial_statements import number

SUMMARY_KEYS = ('revenueGrowthFY', 'cashConversion', 'trailingPE', 'netDebt')


def research_summary(ticker, info, bundle=None, *, is_etf=False):
    info = info or {}
    values = metric_observations(ticker, info, bundle, is_etf=is_etf)
    cards = []
    for key in SUMMARY_KEYS:
        item = values[key]
        cards.append({'key': key, 'label': METRIC_TEXT[key][0],
                      'display': format_value_th(BY_KEY[key], item, info),
                      'period': item.get('end') or 'ต้นทางไม่ระบุวันสิ้นรอบ',
                      'basis': item.get('basis') or '', 'state': item['state'],
                      'currency': item.get('currency') or '', 'unit': BY_KEY[key].unit,
                      'source': item.get('source') or '',
                      'reason': TEXT.get(item.get('reason'), item.get('reason') or '')})
    def available(key):
        item = values[key]
        return number(item.get('value')) if item.get('state') == 'available' else None
    followups = []
    if not is_etf:
        growth, profit_growth = available('revenueGrowthFY'), available('netIncomeGrowthFY')
        if growth is not None and profit_growth is not None:
            revenue_item, profit_item = values['revenueGrowthFY'], values['netIncomeGrowthFY']
            if revenue_item.get('end') == profit_item.get('end') and growth > 0 > profit_growth:
                followups.append('รายได้ปีบัญชีเพิ่มแต่กำไรลด: ตรวจต้นทุน อัตรากำไร ภาษี และรายการพิเศษของรอบเดียวกัน')
        conversion = available('cashConversion')
        if conversion is not None and conversion < 1:
            followups.append('เงินสดจากการดำเนินงานต่ำกว่ากำไรสุทธิในรอบที่คำนวณ: ตรวจลูกหนี้ สินค้าคงเหลือ และจังหวะรับจ่ายเงิน')
        fcf = available('freeCashflow')
        if fcf is not None and fcf < 0:
            followups.append('กระแสเงินสดอิสระติดลบในรอบที่แสดง: ตรวจรายจ่ายลงทุนและแหล่งเงินทุนประกอบ')
        coverage = available('interestCoverage')
        if coverage is not None and coverage < 1:
            followups.append('EBIT ต่ำกว่าดอกเบี้ยจ่ายในรอบที่คำนวณ: ตรวจเงินสดและกำหนดชำระหนี้')
        if specialized_company(info):
            followups.append('ธุรกิจนี้ต้องใช้ตัวชี้วัดเฉพาะอุตสาหกรรมประกอบ เช่น เงินกองทุน หรือ FFO/AFFO')
    return {'profile': profile_text_th(info), 'cards': cards, 'followups': followups,
            'available': sum(x['state'] == 'available' and number(x.get('value')) is not None for x in values.values()),
            'applicable': sum(x['state'] != 'not_applicable' for x in values.values()),
            'observations': values}


def render_research_summary(ticker, info, row, bundle=None, *, is_etf=False):
    import streamlit as st
    import pandas as pd
    result = research_summary(ticker, info, bundle, is_etf=is_etf)
    with st.container(key='research_summary', border=True):
        st.subheader('สรุปเพื่อเริ่มวิเคราะห์', anchor='research-summary')
        if result['profile']:
            st.caption(result['profile'])
        if is_etf:
            st.write('อ่านกลยุทธ์กองทุน ค่าธรรมเนียม ความกระจุกตัว และการถือครองซ้ำ ก่อนเทียบผลตอบแทนกับดัชนีที่เหมาะสม')
            st.markdown('[↓ วิเคราะห์ ETF และการถือครอง](#fundamentals) · [↓ เปรียบเทียบผลตอบแทน](#comparison)')
        else:
            for box, card in zip(st.columns(4), result['cards']):
                box.metric(card['label'], card['display'])
                box.caption(PERIOD_LABELS.get(card['basis'], card['basis'])+' · '+card['period'])
            st.caption(f"มีค่าที่ใช้ได้ {result['available']} / {result['applicable']} ตัวชี้วัดที่เกี่ยวข้อง · จำนวนนี้บอกความพร้อมของข้อมูล ไม่ใช่คุณภาพการลงทุน")
            st.markdown('[แนวโน้มงบและคุณภาพกำไร](#fundamentals) · [เทียบคู่แข่ง](#peer-analysis) · [จำลองราคา](#valuation)')
        if result['followups']:
            for text in result['followups'][:4]:
                st.write('• ' + text)
        elif not is_etf:
            st.caption('เริ่มตรวจความต่อเนื่องของรายได้ อัตรากำไร เงินสด และหนี้ในกราฟย้อนหลัง แล้วอ่านหมายเหตุประกอบงบ; สรุปนี้ไม่ได้ยืนยันว่าไม่มีความเสี่ยง')
        if not is_etf:
            with st.expander('ที่มาของตัวเลขสรุป', expanded=False):
                st.dataframe(pd.DataFrame([{'ตัวชี้วัด': c['label'], 'ค่า': c['display'],
                    'สิ้นรอบ': c['period'], 'ช่วง': PERIOD_LABELS.get(c['basis'], c['basis']),
                    'หน่วย': '%' if c['unit'] == '%' else 'เท่า' if c['unit'] == 'x' else c['currency'] or 'ไม่ระบุสกุลเงิน',
                    'แหล่งข้อมูล': SOURCE_LABELS.get(c['source'], c['source']),
                    'สถานะ': STATE_VALUES.get(c['state'], c['state']), 'เหตุผล': c['reason']} for c in result['cards']]),
                    hide_index=True, width='stretch')
    return result
