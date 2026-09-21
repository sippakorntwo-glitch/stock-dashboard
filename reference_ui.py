"""Compact optional research sources; not a system status/debug panel."""
from __future__ import annotations
from urllib.parse import quote,urlsplit
import pandas as pd
import streamlit as st
from asset_semantics import REVIEWED_INSTRUMENTS,kind_for
from company_metrics import Metric
from company_analysis_th import format_value_th
from financial_statements import number


REFERENCE_LABEL = 'แหล่งข้อมูลและงบที่ยื่นต่อ SEC'
FACT_LABELS = {
    'Revenue': 'รายได้ (Revenue)',
    'Net income': 'กำไรสุทธิ (Net income)',
    'Operating cash flow': 'กระแสเงินสดดำเนินงาน (OCF)',
    'Capital expenditure': 'รายจ่ายลงทุน (CapEx)',
    'Total assets': 'สินทรัพย์รวม (Total assets)',
    'Total liabilities': 'หนี้สินรวม (Total liabilities)',
    'Cash and cash equivalents': 'เงินสดและรายการเทียบเท่าเงินสด (Cash & equivalents)',
    'Net margin (calculated FY)': 'อัตรากำไรสุทธิจากปีบัญชี (Net margin)',
    'Free cash flow (calculated FY)': 'กระแสเงินสดอิสระจากปีบัญชี (FCF)',
}


def reference_rows(facts):
    """Present filed facts without equating annual, instant or market measures."""
    rows = []
    for fact in facts:
        value = number(fact.get('value'))
        percent = fact.get('currency') == '%'
        item = {'value': value / 100 if percent and value is not None else value,
                'state': 'available' if value is not None else 'not_reported',
                'currency': fact.get('currency')}
        metric = Metric('sec_reference', '', '', '%' if percent else 'money', '', '')
        basis = fact.get('basis')
        period = ('ปีบัญชี (FY)' if basis == 'fiscal-year (not TTM)' else
                  'ณ วันสิ้นงวด' if basis == 'point-in-time' else
                  'ไม่ระบุรอบบัญชี')
        rows.append({'รายการ': FACT_LABELS.get(fact.get('metric'), fact.get('metric') or 'ไม่ระบุรายการ'),
                     'ค่าที่รายงาน': format_value_th(metric, item, {}),
                     'รอบบัญชี': period,
                     'วันเริ่มรอบ': fact.get('period_start') or '—',
                     'วันสิ้นงวด': fact.get('period_end') or 'ไม่ระบุ',
                     'วันที่ยื่นเอกสาร': fact.get('filed') or 'ไม่ระบุ'})
    return rows


def trusted_link(url):
    try:
        part=urlsplit(str(url))
        return part.scheme=='https' and part.hostname in ('www.sec.gov','data.sec.gov','www.gsam.com','am.gs.com','neosfunds.com') and not part.username and not part.password and part.port in (None,443)
    except ValueError:return False


def render_references(ticker,info,is_etf,cache):
    kind=kind_for(ticker,info,is_etf)
    if kind=='physical_gold':
        st.info('AAAU holds physical gold, not operating-company shares. P/E and corporate analyst targets are N/A, not a loading error. Review gold exposure, fund assets, NAV, sponsor fee and liquidity instead.')
    elif kind=='non_equity_fund':
        st.caption('This fund has non-equity exposure according to its reported category. Corporate P/E and analyst targets are not applicable; missing fund-specific figures remain Not reported.')
    elif is_etf:
        st.caption('For equity funds, portfolio P/E describes underlying holdings, not company earnings per ETF unit. N/A means not applicable; Not reported means the source did not supply a meaningful field.')
    reference,_=cache.get('reference:'+ticker,request_remote=False)
    reference=reference if isinstance(reference,dict) else {}
    curated=REVIEWED_INSTRUMENTS.get(ticker,{})
    with st.expander(REFERENCE_LABEL,expanded=False):
        cik=reference.get('cik') or curated.get('cik')
        url=f'https://www.sec.gov/edgar/browse/?CIK={int(cik):010d}&owner=exclude' if isinstance(cik,int) and 0<cik<10**10 else 'https://www.sec.gov/edgar/search/#/q='+quote(ticker,safe='')
        st.link_button('เอกสารที่ยื่นต่อ SEC',url)
        if curated and trusted_link(curated.get('issuer_url')):st.link_button('Official fund page',curated['issuer_url'])
        if ticker in ('QQQI','SPYI'):st.link_button('Official fund page','https://neosfunds.com/'+ticker.lower()+'/')
        if curated:
            st.write(curated['description'])
            st.write(f"Annual sponsor fee: {curated['sponsor_fee_pct']:.2f}% — annual filing as of {curated['source_as_of']}; reviewed {curated['reviewed_at']}. Not a live NAV or price.")
            st.link_button('Gold trust annual report',curated['filing_url'])
        if reference.get('sic_description'):
            st.caption('หมวดธุรกิจ SEC SIC '+str(reference.get('sic'))+' — '+str(reference['sic_description'])+' · ใช้ระบบจัดหมวดต่างจากอุตสาหกรรมในข้อมูลบริษัท')
        facts=reference.get('facts',[])
        if facts:
            st.caption('งบ SEC แสดงปีบัญชี (FY) หรือยอด ณ วันสิ้นงวด ส่วนมูลค่าตลาดและอัตราส่วนในตารางหลักใช้ฐานตามผู้ให้ข้อมูล เช่น TTM หรือประมาณการ จึงไม่ควรนำตัวเลขต่างรอบมาคำนวณเทียบกันโดยตรง')
            st.dataframe(pd.DataFrame(reference_rows(facts)),hide_index=True,width='stretch')
            st.caption('M = ล้าน · B = พันล้าน · T = ล้านล้าน · คงสกุลเงินต้นทาง วันที่เป็น ค.ศ. '
                       'เงินสดของ SEC ในตารางนี้ไม่รวมเงินลงทุนระยะสั้นที่แสดงเป็นอีกรายการ '
                       'อัตรากำไรและ FCF ที่คำนวณใช้เอกสาร งวด และสกุลเงินเดียวกัน')
            links={r['url'] for r in facts if trusted_link(r.get('url'))}
            for i,link in enumerate(sorted(links)[:3]):st.link_button('เปิดเอกสารอ้างอิง '+str(i+1),link)
            st.download_button('ดาวน์โหลดค่าจริงและแหล่งข้อมูล SEC',
                pd.DataFrame(facts).to_csv(index=False).encode('utf-8-sig'),
                f'{ticker}_sec_sources.csv', 'text/csv', key=f'sec_sources_{ticker}', on_click='ignore')
        if reference.get('checked_at'):st.caption('ดึงข้อมูลอ้างอิง SEC เมื่อ: '+str(reference['checked_at']))
        st.caption('ข้อมูลนี้ใช้ตรวจแหล่งที่มา ไม่แทนราคาตลาดหรือประมาณการในตารางหลัก '
                   'ความต่างของวัน งวดบัญชี และนิยามรายการยังคงแยกไว้ ไม่เฉลี่ยยอดที่ขัดแย้งกันหรือเติมค่าที่ขาดด้วยศูนย์')
