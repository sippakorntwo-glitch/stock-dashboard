"""Thai ETF research backed by prepared observations and explicit user imports."""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from etf_research import (PRIORITY, SCHEMA, SECTORS_TH, concentration, number,
                          overlap, parse_holdings_csv, price_comparison)


def _pct(value):
    return 'ไม่มีข้อมูล' if value is None else f'{value*100:,.2f}%'


def _source_caption(holdings):
    stamp = holdings.get('source_asof') or 'ผู้ให้ข้อมูลไม่ระบุวันที่ถือครอง'
    fetched = holdings.get('fetched_at') or 'ไม่ระบุเวลารับข้อมูล'
    st.caption(f"{holdings.get('source', 'ไม่ระบุแหล่งข้อมูล')} · วันที่ถือครอง: {stamp} · รับข้อมูล: {fetched}")
    url = holdings.get('source_url')
    if url:
        st.link_button('ดูแหล่งข้อมูลรายการถือครอง', url)


def _get_holdings(ticker, cache):
    imported = st.session_state.get('etf_holdings_imports', {}).get(ticker)
    if imported:
        return imported
    bundle, _ = cache.get('etf_research:'+ticker)
    if isinstance(bundle, dict) and bundle.get('schema') == SCHEMA:
        return bundle.get('holdings', {})
    return {}


def _import_ui(ticker, symbols):
    with st.expander('นำเข้ารายการถือครองจากไฟล์ของผู้ออกกองทุน'):
        st.caption('ใช้เมื่อข้อมูลผู้ให้บริการไม่ครบ: เตรียม CSV UTF-8 คอลัมน์ symbol, name, weight_pct (เช่น 5 หมายถึง 5%) '
                   'ระบุตลาดและรุ่นหลักทรัพย์ให้ตรงกัน รองรับพอร์ตน้ำหนักบวก รวมไม่เกิน 100% และไฟล์ไม่เกิน 1 MB '
                   'ไฟล์ใช้เฉพาะในเซสชันนี้ ไม่เผยแพร่ให้ผู้ใช้อื่น')
        st.download_button('ดาวน์โหลดหัวตาราง CSV', 'symbol,name,weight_pct\n'.encode(),
                           file_name='etf-holdings-template.csv', mime='text/csv', key='etf_template')
        target = st.selectbox('กองทุนของไฟล์ที่จะนำเข้า', list(dict.fromkeys([ticker, *symbols])), key='etf_import_target')
        with st.form('etf_holdings_import_form'):
            upload = st.file_uploader('ไฟล์รายการถือครอง CSV', type=['csv'], key='etf_holdings_upload')
            source = st.text_input('ลิงก์ HTTPS ของไฟล์หรือหน้าข้อมูลต้นทาง', key='etf_holdings_source')
            asof = st.date_input('วันที่ถือครองตามไฟล์ต้นทาง', value=None,
                                 max_value=datetime.now(timezone.utc).date(), key='etf_holdings_asof')
            complete = st.checkbox('ไฟล์นี้มีรายการครบพอร์ต (ผลรวมน้ำหนัก 99.5–100%)', key='etf_holdings_complete')
            submit = st.form_submit_button('ตรวจสอบและใช้รายการถือครอง')
        if submit:
            try:
                observation = parse_holdings_csv(upload.getvalue() if upload else None,
                     source_url=source, source_asof=asof, full_portfolio=complete,
                     fetched_at=datetime.now(timezone.utc).isoformat())
                stored = dict(st.session_state.get('etf_holdings_imports', {}))
                stored[target] = observation
                st.session_state['etf_holdings_imports'] = stored
                st.success(f'ใช้รายการถือครองที่นำเข้าของ {target} แล้ว')
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        imported = st.session_state.get('etf_holdings_imports', {})
        if target in imported and st.button('กลับไปใช้ข้อมูลผู้ให้บริการสำหรับ '+target, key='etf_clear_import'):
            st.session_state['etf_holdings_imports'] = {key:value for key,value in imported.items() if key != target}
            st.rerun()


def render_etf_research(ticker, info, history, cache, frame=None):
    st.subheader('วิเคราะห์กองทุน ETF')
    st.caption('ตรวจค่าธรรมเนียม สิ่งที่กองทุนถือ และความซ้ำซ้อนของการลงทุน โดยแสดงขอบเขตและวันที่ข้อมูลทุกครั้ง')
    catalog = set(PRIORITY)
    if frame is not None and not frame.empty and 'Ticker' in frame:
        rows = frame
        if 'Asset_Type' in frame:
            rows = frame[frame['Asset_Type'].eq('ETF')]
            catalog.update(str(symbol) for symbol in rows['Ticker'])
        elif 'Asset Type' in frame:
            rows = frame[frame['Asset Type'].astype(str).str.contains('ETF|ETP', case=False, regex=True)]
            catalog.update(str(symbol) for symbol in rows['Ticker'])
    from dashboard_runtime import ETF_NAMES
    catalog.update(ETF_NAMES)
    catalog.add(ticker)
    options = sorted(catalog - {ticker})
    prior = st.session_state.get('etf_compare_symbols', [])
    valid = [symbol for symbol in prior if symbol in options][:3]
    if prior != valid or 'etf_compare_symbols' not in st.session_state:
        st.session_state['etf_compare_symbols'] = valid
    comparisons = st.multiselect('เลือก ETF เพื่อเทียบรายการถือครอง (สูงสุด 3 กองทุน)', options,
                                 max_selections=3, key='etf_compare_symbols')
    benchmark_options = list(dict.fromkeys([*PRIORITY, *comparisons]))
    benchmark_options = [symbol for symbol in benchmark_options if symbol != ticker]
    if st.session_state.get('etf_benchmark_symbol') not in benchmark_options:
        st.session_state['etf_benchmark_symbol'] = 'QQQ' if ticker == 'SPY' else 'SPY'
    benchmark = st.selectbox('ตัวเปรียบเทียบผลตอบแทนราคา', benchmark_options, key='etf_benchmark_symbol',
                             help='เลือกกองทุนอ้างอิงให้เหมาะกับกลยุทธ์ ตัวเลือกนี้ไม่ได้ยืนยันว่าเป็นดัชนีที่กองทุนติดตาม')
    dependencies = getattr(cache, 'dependencies', None)
    if dependencies is not None and not set([ticker, benchmark, *comparisons]).issubset(dependencies):
        # Root adds the widget values before pinning the next SQLite read view.
        st.rerun()

    bundle, meta = cache.get('etf_research:'+ticker)
    bundle = bundle if isinstance(bundle, dict) and bundle.get('schema') == SCHEMA else {}
    overview = bundle.get('overview', {})
    family = overview.get('family') or info.get('fundFamily') or 'ไม่มีข้อมูล'
    category = overview.get('categoryName') or info.get('category') or 'ไม่มีข้อมูล'
    st.write(f'ผู้จัดการกองทุน: {family} · ประเภทกองทุน: {category}')
    metrics = st.columns(3)
    metrics[0].metric('ค่าธรรมเนียมต่อปี (Expense Ratio)', _pct(bundle.get('expense_ratio')),
                      help='Annual Report Expense Ratio ที่ผู้ให้ข้อมูลรายงาน; ค่าว่างไม่ใช่ค่าธรรมเนียมศูนย์ ไม่รวมต้นทุนซื้อขายของผู้ลงทุน')
    metrics[1].metric('ค่าธรรมเนียมเฉลี่ยหมวดเดียวกัน', _pct(bundle.get('category_expense_ratio')))
    metrics[2].metric('อัตราหมุนเวียนพอร์ต (Turnover)', _pct(bundle.get('turnover')))
    if bundle:
        st.caption('แหล่งค่าธรรมเนียมและสัดส่วน: Yahoo Finance fund profile · รับข้อมูล: '
                   +str(bundle.get('fetched_at') or meta.get('fetched_at') or 'ไม่ระบุ')
                   +' · แหล่งข้อมูลไม่ระบุวันสิ้นรอบรายงาน จึงยังตรวจความเก่าของรายงานไม่ได้')
    else:
        st.info('ยังไม่มีชุดข้อมูลค่าธรรมเนียมและรายการถือครองที่ผ่านการตรวจสอบ '
                'ระบบจะเก็บข้อมูลเป็นรอบเบื้องหลัง หรือคุณนำเข้าไฟล์รายการถือครองด้านล่างได้')
    assets = number(bundle.get('net_assets'))
    if assets is None:
        assets = number(info.get('totalAssets'))
    if assets is not None and assets >= 0:
        st.caption(f'สินทรัพย์กองทุนตามผู้ให้ข้อมูล: {assets:,.0f} · สกุลเงินของยอดสินทรัพย์ไม่ยืนยันจาก FundsData จึงไม่ใช้แปลงค่าเงิน')

    holdings = _get_holdings(ticker, cache)
    concentration_data = concentration(holdings)
    st.markdown('**รายการถือครองและความกระจุกตัว**')
    if concentration_data['state'] == 'available':
        _source_caption(holdings)
        cols = st.columns(3)
        cols[0].metric('น้ำหนักที่มีข้อมูล', _pct(concentration_data['coverage']))
        cols[1].metric('รายการใหญ่สุดที่มีข้อมูล', _pct(concentration_data['top1']))
        cols[2].metric('5 รายการใหญ่สุดที่มีข้อมูล', _pct(concentration_data['top5']))
        st.caption('ข้อมูลครบพอร์ตตามไฟล์ที่ผู้ใช้ระบุ' if holdings.get('complete') else
                   'เป็นเพียงรายการที่แหล่งข้อมูลส่งมา ไม่ใช่รายการครบพอร์ต; ส่วนที่ขาดไม่ถูกนับเป็นศูนย์หรือปรับน้ำหนักใหม่ให้ครบ 100%')
        table = pd.DataFrame(holdings['rows']).rename(columns={'symbol':'หลักทรัพย์', 'name':'ชื่อ', 'weight':'น้ำหนัก (%)'})
        table['น้ำหนัก (%)'] *= 100
        st.dataframe(table, hide_index=True, width='stretch',
                     column_config={'น้ำหนัก (%)':st.column_config.NumberColumn(format='%.2f%%')})
    else:
        st.info('ยังไม่มีรายการถือครองที่ใช้คำนวณความกระจุกตัวได้')
    sectors = bundle.get('sectors') or {}
    if sectors:
        with st.expander('สัดส่วนอุตสาหกรรม (Sector Allocation)', expanded=False):
            sector_table = pd.DataFrame([{'อุตสาหกรรม':SECTORS_TH.get(key, key), 'น้ำหนัก (%)':value*100}
                                        for key,value in sectors.items()]).sort_values('น้ำหนัก (%)', ascending=False)
            st.bar_chart(sector_table.set_index('อุตสาหกรรม'))
            st.dataframe(sector_table, hide_index=True, width='stretch')
            st.caption('ผลรวมน้ำหนักที่รายงาน '+_pct(sum(sectors.values()))+
                       ' · ใช้สัดส่วนอุตสาหกรรมจากผู้ให้ข้อมูลโดยตรง แหล่งข้อมูลไม่ระบุว่าใช้ฐานทั้งกองทุนหรือเฉพาะหุ้น')
    else:
        st.caption('สัดส่วนอุตสาหกรรม: ผู้ให้ข้อมูลยังไม่ส่งค่าที่ใช้ได้')

    if comparisons:
        st.markdown('**หลักทรัพย์ที่ถือซ้ำระหว่าง ETF**')
        for other in comparisons:
            other_holdings = _get_holdings(other, cache)
            result = overlap(holdings, other_holdings)
            with st.expander(ticker+' เทียบ '+other, expanded=True):
                if result['state'] != 'available':
                    st.info('ยังคำนวณไม่ได้: กองทุนอย่างน้อยหนึ่งฝั่งไม่มีรายการถือครอง นำเข้าไฟล์ของแต่ละกองทุนได้ด้านล่าง')
                    continue
                st.metric('น้ำหนักซ้ำที่พบในชุดข้อมูล', _pct(result['weight']))
                st.caption(f"ความครอบคลุม: {ticker} {_pct(result['left_coverage'])} / {other} {_pct(result['right_coverage'])} · "
                           f"วันที่ถือครอง: {result['left_asof'] or 'ไม่ระบุ'} / {result['right_asof'] or 'ไม่ระบุ'}")
                if result['complete']:
                    st.caption('ทั้งสองไฟล์ระบุว่าครบพอร์ตและเป็นวันเดียวกัน ผลรวม min(น้ำหนัก A, น้ำหนัก B) สำหรับหลักทรัพย์ร่วมกัน')
                elif result['date_state'] == 'aligned':
                    st.caption('ข้อมูลวันเดียวกันแต่ไม่ครบพอร์ต ค่านี้เป็นเพียงน้ำหนักซ้ำที่พบ ยังอาจมีรายการซ้ำเพิ่มเติม')
                else:
                    st.warning('วันที่ข้อมูลต่างกันหรือไม่ระบุ จึงใช้ดูรายการซ้ำในชุดข้อมูลเท่านั้น ยังสรุปสัดส่วนพอร์ตซ้ำ ณ วันเดียวกันไม่ได้')
                st.caption('จับคู่ตามรหัสหลักทรัพย์ ต้องตรวจว่าตลาดและรุ่นหลักทรัพย์ตรงกัน; ไม่นับการถือผ่านกองทุนย่อยหรืออนุพันธ์เป็นหุ้นอ้างอิง')
                if result['rows']:
                    table = pd.DataFrame(result['rows']).rename(columns={'symbol':'หลักทรัพย์', 'left_weight':ticker+' (%)',
                              'right_weight':other+' (%)', 'overlap':'น้ำหนักซ้ำ (%)'})
                    for column in table.columns[1:]:
                        table[column] *= 100
                    st.dataframe(table, hide_index=True, width='stretch')

    with st.expander('ผลตอบแทนราคาเทียบกองทุนอ้างอิง', expanded=False):
        other_info, _ = cache.get('info:'+benchmark)
        other_history, _ = cache.history(benchmark)
        result = price_comparison(history, other_history, currency=info.get('currency'),
                                  benchmark_currency=(other_info or {}).get('currency'))
        st.caption('เปรียบเทียบราคาปิดที่ปรับแล้วในวันร่วมกัน ฐานเริ่มต้น 100 · ไม่ใช่ Tracking Error หรือผลต่าง NAV '
                   'และตัวเปรียบเทียบอาจมีกลยุทธ์ต่างจากกองทุนที่เลือก')
        if result['state'] == 'available':
            data = result['data'].rename(columns={'กองทุน':ticker, 'ตัวเปรียบเทียบ':benchmark})
            st.line_chart(data)
            st.caption(f"ช่วงข้อมูลร่วม {result['start']} ถึง {result['end']} · {result['observations']} วัน · สกุลเงิน {result['currency']}")
            st.write(f"ผลตอบแทนราคา {ticker}: {_pct(result['fund_return'])} · {benchmark}: {_pct(result['benchmark_return'])} · "
                     f"ส่วนต่าง {result['gap_pp']:+.2f} จุดเปอร์เซ็นต์")
        else:
            reasons = {'currency_mismatch':'สกุลเงินต่างกันหรือไม่ทราบสกุลเงิน', 'insufficient_history':'มีวันข้อมูลร่วมกันน้อยกว่า 20 วัน',
                       'missing_history':'ข้อมูลราคาของกองทุนอ้างอิงยังไม่พร้อม', 'invalid_history':'ข้อมูลราคามีรูปแบบไม่ถูกต้อง'}
            st.info('ยังเปรียบเทียบไม่ได้: '+reasons.get(result['state'], 'ข้อมูลไม่พร้อม'))
    with st.expander('ประเด็นเพิ่มเติมที่ควรตรวจจากผู้ออกกองทุน'):
        st.write('ส่วนเกิน/ส่วนลดต่อ NAV ต้องใช้ราคาตลาดและ NAV ที่เป็นเวลาเดียวกัน '
                 'ชุดข้อมูลนี้ยังยืนยันเวลาคู่นี้ไม่ได้ จึงไม่คำนวณจากตัวเลขคนละเวลา')
        st.write('เงินจ่ายของกองทุนอาจมีเงินปันผล กำไรจากการขายสินทรัพย์ หรือเงินคืนทุน (Return of Capital) '
                 'ตรวจเอกสารการจ่ายเงินของผู้ออกกองทุนก่อนใช้เป็นรายได้คาดหวัง')
    _import_ui(ticker, comparisons)
