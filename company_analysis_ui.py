"""Thai company research tables with metric-only, keyboard-accessible help."""
from __future__ import annotations

from html import escape
import json
from urllib.parse import urlsplit
from reviewed_financials import apply_reviewed, ISSUER_SOURCE, AARD_RELEASE_URL
import pandas as pd
import streamlit as st
from company_metrics import BY_KEY, GROUPS, REFERENCE_URLS, NONNEGATIVE, Metric
from company_analysis_th import (METRIC_TEXT, GROUP_LABELS, CSV_HEADERS, build_rows_th,
                                 export_rows_th, format_value_th, profile_text_th, bilingual_label)
from financial_statements import (INCOME_KEYS, CASHFLOW_KEYS, BALANCE_FIELDS, number,
                                  field_provenance, provenance_source, cell_conflicts)

STATEMENT_EXTRA = {
    'interestExpense': ('ดอกเบี้ยจ่าย', 'ดอกเบี้ยจ่ายที่รายงานสำหรับปีบัญชีที่ระบุ ใช้แยกจากกำไรก่อนดอกเบี้ยและภาษีเพื่อประเมินความสามารถชำระดอกเบี้ย'),
    'pretaxIncome': ('กำไรก่อนภาษี', 'กำไรหรือขาดทุนก่อนภาษีเงินได้สำหรับปีบัญชีที่ระบุ'),
    'taxProvision': ('ค่าใช้จ่ายภาษีเงินได้', 'ค่าใช้จ่ายหรือประโยชน์ทางภาษีที่รับรู้ในงบกำไรขาดทุน ไม่จำเป็นต้องเท่ากับเงินสดจ่ายภาษี'),
    'receivables': ('ลูกหนี้', 'ยอดลูกหนี้ที่รายงาน ณ วันสิ้นปีบัญชี ใช้ข้อมูลตามขอบเขตของผู้ให้ข้อมูล ไม่สมมติให้ยอดที่ไม่รายงานเป็นศูนย์'),
    'inventory': ('สินค้าคงเหลือ', 'มูลค่าสินค้าคงเหลือที่รับรู้ ณ วันสิ้นปีบัญชี ไม่ใช่มูลค่ายอดขาย'),
}

COLORS = {'Positive': 'good', 'Growing': 'good', 'Positive equity': 'good',
          'Positive coverage': 'good', 'At or above reference': 'good',
          'Negative': 'bad', 'Negative equity': 'bad', 'Loss-making': 'bad',
          'EBIT below interest': 'bad', 'Above reported earnings': 'bad',
          'Liquidity review': 'watch', 'Higher leverage': 'watch',
          'Thin coverage': 'watch', 'High multiple': 'watch', 'Contracting': 'watch'}
CSS = '''<style>
.company-analysis{border:1px solid #2c415b;border-radius:12px;margin:12px 0 22px;overflow:hidden;background:rgba(15,28,46,.4)}
.company-analysis h4{margin:0;padding:13px 16px;background:linear-gradient(110deg,#17354e,#18263c);font:600 17px sans-serif;color:#dceef8}
.company-table-scroll{overflow:auto;max-height:650px}.company-table{border-collapse:collapse;width:100%;font:13px/1.5 sans-serif;color:#dfebf6}
.company-table td,.company-table th{text-align:left;vertical-align:top;padding:11px 14px;border-bottom:1px solid #25374e}
.company-table thead th{position:sticky;top:0;background:#14273c;color:#a8bfd4;font-weight:500;z-index:1}
.company-table tbody th{min-width:165px;font-weight:600}
.company-table td:first-child{min-width:165px;font-weight:600}.company-table td:nth-child(2){min-width:125px;font-variant-numeric:tabular-nums}
.company-table td:nth-child(3){min-width:210px}.company-table td:nth-child(5){min-width:260px}.company-table td:nth-child(6){min-width:150px;color:#b2c4d5}
.company-table abbr{border:0;text-decoration:none;cursor:help}.company-table abbr:focus{outline:2px solid #58cdb7;outline-offset:4px}.company-table small{color:#68c9cf}
.company-rating{display:inline-block;padding:3px 7px;border-radius:5px;background:#263b53;color:#d3dfed;white-space:normal;min-width:95px}
.company-rating.good{background:#123e37;color:#81e2bf}.company-rating.bad{background:#492c3b;color:#ffb6c5}.company-rating.watch{background:#473d26;color:#f5d68c}
.company-glossary{padding:10px 16px;font:13px/1.6 sans-serif;color:#bacde0}.company-glossary summary{cursor:pointer}.company-glossary dt{font-weight:600;margin-top:10px}.company-glossary dd{margin:3px 0 10px;white-space:pre-line}
</style>'''


def analysis_html(rows, ticker, *, group=None):
    groups = [group] if group else GROUPS
    html = [CSS]
    for name in groups:
        selected = [r for r in rows if r['Group'] == name]
        if not selected:
            continue
        header = ''.join(f'<th scope="col">{escape(CSV_HEADERS[c])}</th>' for c in ('Metric', 'Current Value', 'Reference / Benchmark', 'Assessment', 'Interpretation', 'Period'))
        body, glossary = [], []
        for row in selected:
            label, tip = escape(row['Metric']), escape(row['_help'], quote=True)
            cells = f'<th scope="row"><abbr tabindex="0" title="{tip}" aria-label="{escape(row["Metric"]+": "+row["_help"],quote=True)}">{label} <small>ⓘ</small></abbr></th>'
            cells += '<td>'+escape(row['Current Value'])+'</td><td>'+escape(row['Reference / Benchmark'])+'</td>'
            css = COLORS.get(row.get('_assessment', row['Assessment']), '')
            cells += f'<td><span class="company-rating {css}">{escape(row["Assessment"])}</span></td>'
            cells += '<td>'+escape(row['Interpretation'])+'</td><td>'+escape(row['Period'])+'</td>'
            body.append(f'<tr data-metric="{escape(row["_key"],quote=True)}" data-state="{escape(row["_state"],quote=True)}">{cells}</tr>')
            glossary.append(f'<dt>{label}</dt><dd>{escape(row["_help"])}</dd>')
        html.append(f'<section class="company-analysis" data-ticker="{escape(ticker,quote=True)}" data-group="{escape(name,quote=True)}"><h4>{escape(GROUP_LABELS[name])}</h4>'
                    f'<div class="company-table-scroll"><table class="company-table"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                    '<details class="company-glossary"><summary>คำอธิบายตัวชี้วัด — อ่านได้ด้วยแป้นพิมพ์และมือถือ</summary><dl>'+''.join(glossary)+'</dl></details></section>')
    return ''.join(html)


def statement_table(bundle, kind):
    bundle = apply_reviewed(bundle)
    keys = INCOME_KEYS if kind == 'income' else CASHFLOW_KEYS if kind == 'cashflow' else tuple(BALANCE_FIELDS)
    aliases = {'capitalExpenditure': 'capex', 'repurchaseOfCapitalStock': 'buybacks', 'cashDividendsPaid': 'dividendsPaid'}
    records = bundle.get('annual', {}).get(kind, [])[:4]
    rows = []
    for raw in keys:
        key = aliases.get(raw, raw)
        metric = BY_KEY.get(key)
        if metric:
            label, definition = METRIC_TEXT[key]
        else:
            label, definition = STATEMENT_EXTRA[raw]
            label = bilingual_label(raw, label)
            metric = Metric(raw, label, '', 'money', 'context', definition)
        row = {'Metric': label, '_help': definition, '_field': raw, '_provenance': {}, '_conflicts': {}}
        for period in records:
            value = number(period['values'].get(raw))
            state = 'available' if value is not None else 'not_reported'
            if raw in aliases and value is not None:
                value, state = (-value, 'available') if value <= 0 else (None, 'invalid')
            if value is not None and (key in NONNEGATIVE or raw in ('receivables', 'inventory')) and value < 0:
                value, state = None, 'invalid'
            row[period['end']] = format_value_th(metric, {'state': state,
                'value': value, 'currency': bundle.get('currency')}, {'financialCurrency': bundle.get('currency')})
            row['_provenance'][period['end']] = field_provenance(period, raw, bundle)
            row['_conflicts'][period['end']] = cell_conflicts(bundle, period, raw, period='annual', kind=kind)
        rows.append(row)
    return rows


def _sec_badge(origins):
    origin = next((p for p in origins if p.get('source') == 'SEC EDGAR'), None)
    if not origin:
        return ''
    detail = ' · '.join(str(v) for v in ('SEC EDGAR', origin.get('tag'),
                           'ยื่นเมื่อ '+str(origin['filed']) if origin.get('filed') else None,
                           'เอกสาร '+str(origin['accession']) if origin.get('accession') else None) if v)
    url = str(origin.get('url') or '')
    try:
        parsed = urlsplit(url)
        safe = (parsed.scheme == 'https' and parsed.netloc in ('www.sec.gov', 'sec.gov')
                and parsed.path.startswith('/Archives/edgar/data/') and not parsed.query and not parsed.fragment
                and not any(ord(c) < 32 for c in url))
    except ValueError:
        safe = False
    if safe:
        return ' <a href="'+escape(url, quote=True)+'" target="_blank" rel="noopener noreferrer" title="'+escape(detail, quote=True)+'" aria-label="'+escape(detail, quote=True)+'">SEC</a>'
    return ' <abbr tabindex="0" title="'+escape(detail, quote=True)+'">SEC</abbr>'


def _issuer_badge(origins):
    origin = next((p for p in origins if p.get('source') == ISSUER_SOURCE), None)
    if not origin:
        return ''
    original = origin.get('original_observation', {})
    detail = ('รายงานบริษัท · เผยแพร่ '+str(origin.get('published', ''))+
              ' · หนี้สินรวมตามรายงานบริษัทแสดงแยกจากหุ้นบุริมสิทธิแปลงสภาพ '+
              str(origin.get('convertible_preferred_stock', ''))+' USD'+
              ' · ยอดเดิมจากผู้ให้ข้อมูล '+str(original.get('value', ''))+' USD')
    attrs = ' title="'+escape(detail, quote=True)+'" aria-label="'+escape(detail, quote=True)+'"'
    if origin.get('url') == AARD_RELEASE_URL:
        return ' <a href="'+escape(AARD_RELEASE_URL, quote=True)+'" target="_blank" rel="noopener noreferrer"'+attrs+'>รายงานบริษัท</a>'
    return ' <abbr tabindex="0"'+attrs+'>รายงานบริษัท</abbr>'


def export_statements(bundle):
    """Exact raw cells, including original cash-outflow signs and filing provenance."""
    bundle = apply_reviewed(bundle)
    rows = []
    for period in ('annual', 'quarterly'):
        for kind, keys in (('income', INCOME_KEYS), ('balance', tuple(BALANCE_FIELDS)), ('cashflow', CASHFLOW_KEYS)):
            for record in bundle.get(period, {}).get(kind, []):
                for key in dict.fromkeys((*keys, *record.get('values', {}))):
                    value = number(record.get('values', {}).get(key))
                    origins = field_provenance(record, key, bundle)
                    rows.append({'หุ้น': bundle.get('ticker'), 'รอบบัญชี': period, 'ประเภทงบ': kind,
                        'วันสิ้นงวด': record.get('end'), 'รายการต้นทาง': key, 'ค่าต้นทาง': value,
                        'สกุลเงินงบ': bundle.get('currency'), 'สถานะ': 'มีข้อมูล' if value is not None else 'ไม่มีข้อมูลรายงาน',
                        'แหล่งข้อมูล': provenance_source(origins, ''),
                        'ที่มารายรายการ': json.dumps(origins, ensure_ascii=False, sort_keys=True),
                        'รายการที่แหล่งข้อมูลต่างกัน': json.dumps(cell_conflicts(bundle, record, key, period=period, kind=kind),
                                                            ensure_ascii=False, sort_keys=True)})
    return rows


def _conflict_badge(conflicts):
    if not conflicts:
        return ''
    item = conflicts[0]
    sec_amount = str(item['sec_value'])+' '+str(item['currency']) if number(item.get('sec_value')) is not None else 'ข้อมูล SEC หลายรายการขัดแย้งกัน'
    detail = ('แหล่งข้อมูลรายงานต่างกัน: ยอดต้นทาง '+str(item['provider_value'])+' '+str(item['currency'])
              +' · SEC EDGAR '+sec_amount+' · อ่านรายละเอียดการเปรียบเทียบด้านล่าง')
    return ' <abbr tabindex="0" title="'+escape(detail, quote=True)+'">⚠ แหล่งข้อมูลต่างกัน</abbr>'


def reconciliation_html(bundle):
    """Show both reported amounts and their filing; do not resolve a definition by fiat."""
    bundle = apply_reviewed(bundle)
    body = []
    for period in ('annual', 'quarterly'):
        for kind in ('income', 'balance', 'cashflow'):
            for record in bundle.get(period, {}).get(kind, []):
                for field in record.get('values', {}):
                    for item in cell_conflicts(bundle, record, field, period=period, kind=kind):
                        label = METRIC_TEXT[field][0] if field in METRIC_TEXT else field
                        sec_amount=number(item.get('sec_value'))
                        values = ['FY' if period == 'annual' else 'Q', item['end'], label,
                                  f'{number(item["provider_value"]):,} {item["currency"]}',
                                  f'{sec_amount:,} {item["currency"]}' if sec_amount is not None else 'ข้อมูล SEC หลายรายการขัดแย้งกัน']
                        cells = ''.join('<td>'+escape(str(v))+'</td>' for v in values)
                        detail = ''
                        preferred = item.get('preferred_equity_reconciliation')
                        if preferred:
                            detail = ('ยอดต้นทางรวมส่วนทุนชั่วคราว/หุ้นบุริมสิทธิที่ SEC แสดงแยก '+
                                      f'{number(preferred["value"]):,} {item["currency"]}; ไม่จัดรายการใหม่อัตโนมัติ')
                        cells += '<td>'+escape(detail)+_sec_badge([{**item, 'source': 'SEC EDGAR'}])+'</td>'
                        body.append('<tr>'+cells+'</tr>')
    if not body:
        return ''
    heads = ''.join('<th scope="col">'+label+'</th>' for label in
                    ('รอบบัญชี', 'วันสิ้นงวด', 'รายการ', 'ยอดต้นทางในตาราง', 'ยอด SEC EDGAR', 'รายละเอียด / เอกสาร'))
    return CSS+'<div class="company-table-scroll"><table class="company-table"><thead><tr>'+heads+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def history_html(rows, title, *, kind=None):
    if not rows:
        return ''
    cols = [c for c in rows[0] if not c.startswith('_')]
    heads = ''.join('<th scope="col">'+escape('รายการ' if col == 'Metric' else col)+'</th>' for col in cols)
    body = []
    for row in rows:
        first = '<th scope="row"><abbr tabindex="0" title="'+escape(row['_help'],quote=True)+'" aria-label="'+escape(row['Metric']+': '+row['_help'],quote=True)+'">'+escape(row['Metric'])+' <small>ⓘ</small></abbr></th>'
        body.append('<tr data-statement-field="'+escape(row.get('_field', ''), quote=True)+'">'+first+''.join(
            '<td>'+escape(str(row[c]))+_sec_badge(row.get('_provenance', {}).get(c, []))+
            _issuer_badge(row.get('_provenance', {}).get(c, []))+
            _conflict_badge(row.get('_conflicts', {}).get(c, []))+'</td>' for c in cols[1:])+'</tr>')
    return CSS+'<section class="company-analysis" data-statement="'+escape(kind or '', quote=True)+'"><h4>'+escape(title)+'</h4><div class="company-table-scroll"><table class="company-table"><thead><tr>'+heads+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>'


def render_company_research(ticker, info, bundle=None):
    bundle = apply_reviewed(bundle)
    st.subheader('วิเคราะห์ข้อมูลการเงินบริษัท', anchor='company-financial-analysis')
    st.caption('ช่วงอ้างอิงเป็นตัวอย่างเพื่อช่วยเปรียบเทียบ ไม่ใช่ค่าเฉลี่ยอุตสาหกรรม มูลค่ายุติธรรม หรือสัญญาณซื้อขาย ระบุหน่วยจำนวนเงิน ร้อยละ และเท่าอย่างชัดเจน พร้อมแยกปีบัญชี (FY) ออกจากข้อมูลย้อนหลัง 12 เดือน (TTM)')
    st.caption('หน่วยย่อ: M = ล้าน · B = พันล้าน · T = ล้านล้าน โดยคงสกุลเงินที่ระบุ เช่น USD ไม่ได้แปลงเป็นเงินบาท วันที่ของงบแสดงเป็นปี ค.ศ.')
    profile = profile_text_th(info)
    if profile:
        st.write(profile)
    st.caption('ดึงข้อมูลบริษัทเมื่อ: '+str(info.get('_Fetched_At_UTC') or 'ไม่มีข้อมูลรายงาน')+' · ดึงงบการเงินเมื่อ: '+str((bundle or {}).get('fetched_at') or 'ยังไม่ได้เก็บข้อมูล'))
    if bundle and bundle.get('errors'):
        st.caption('การดึงงบบางรายการยังไม่ครบ ตัวเลขที่มีข้อมูลยังคงระบุรอบบัญชีของตนเอง และไม่ได้ประมาณค่าที่ขาดหายไป')
    from financial_trends_ui import render_financial_trends
    render_financial_trends(ticker, info, bundle)
    rows = build_rows_th(ticker, info, bundle)
    # One stable element holds all grouped sections; switching symbols replaces it.
    with st.container(key='company_financial_analysis'):
        st.html(analysis_html(rows, ticker))
    export = export_rows_th(rows)
    st.download_button('ดาวน์โหลดบทวิเคราะห์บริษัท', pd.DataFrame(export).to_csv(index=False).encode('utf-8-sig'),
                       f'{ticker}_company_analysis.csv', 'text/csv', key=f'company_export_{ticker}', on_click='ignore')
    if bundle and any(bundle.get('annual', {}).values()):
        with st.expander('งบการเงินย้อนหลัง — สูงสุด 4 ปีบัญชี', expanded=True):
            st.caption('วันที่ในตารางคือวันสิ้นปีบัญชี (ค.ศ.) ตัวเลขเป็นข้อมูลในงบที่รายงาน ไม่ใช่ผลตอบแทนจากราคาตลาด คำอธิบายอยู่ที่ชื่อรายการ และเลื่อนตารางแนวนอนได้เพื่อดูทุกปี')
            if any(r.get('field_provenance') for records in bundle.get('annual', {}).values() for r in records):
                st.caption('ป้าย SEC หรือรายงานบริษัทระบุแหล่งข้อมูลของรายการ โดยกดเพื่อเปิดเอกสารต้นทางได้ รายการที่แหล่งข้อมูลไม่รายงานยังคงแสดงว่าไม่มีข้อมูล')
            for kind, title in [('income', 'งบกำไรขาดทุน'), ('balance', 'งบฐานะการเงิน'), ('cashflow', 'งบกระแสเงินสด')]:
                if bundle.get('annual', {}).get(kind):
                    st.html(history_html(statement_table(bundle, kind), title, kind=kind))
                else:
                    st.caption(title+': ไม่มีข้อมูลรายงาน')
            st.download_button('ดาวน์โหลดงบและแหล่งข้อมูลรายรายการ',
                pd.DataFrame(export_statements(bundle)).to_csv(index=False).encode('utf-8-sig'),
                f'{ticker}_statement_sources.csv', 'text/csv', key=f'statement_sources_{ticker}', on_click='ignore')
    if bundle:
        reconciliation = reconciliation_html(bundle)
        if reconciliation:
            with st.expander('ตรวจรายการที่แหล่งข้อมูลรายงานต่างกัน', expanded=True):
                st.caption('ตารางแสดงยอดต้นทางทั้งสองแหล่ง ณ วันสิ้นงวดเดียวกัน ความต่างอาจเกิดจากขอบเขตรายการหรือการปรับงบ จึงไม่เลือกแทนค่าอัตโนมัติ หนี้สินรวมที่ยังต่างกันจะพักใช้ในการวิเคราะห์อัตราส่วน')
                st.html(reconciliation)
    with st.expander('วิธีอ่านและตีความผลเปรียบเทียบ'):
        st.write('ไม่มีอัตราส่วนเดียวที่ยืนยันคุณภาพบริษัทได้ ควรเปรียบเทียบกับบริษัทในอุตสาหกรรมเดียวกัน ประวัติของบริษัท นโยบายบัญชี กำหนดชำระหนี้ และความสามารถสร้างเงินสดอย่างต่อเนื่อง ธนาคาร บริษัทประกัน และ REIT ต้องใช้ตัวชี้วัดเงินทุนและกระแสเงินสดเฉพาะธุรกิจ')
        st.write('N/A หมายถึงไม่ใช้กับหลักทรัพย์ประเภทนี้ ส่วน N/M หมายถึงตีความอัตราส่วนไม่ได้ สถานะไม่มีข้อมูลรายงานหรือข้อมูลสำหรับคำนวณไม่เพียงพอหมายถึงข้อมูลที่ขาด ไม่ใช่ศูนย์หรือคะแนนลงทุนติดลบ งบการเงินอัปเดตเมื่อบริษัทเผยแพร่รายงาน ไม่ได้เปลี่ยนทุกครั้งที่ราคาหุ้นเคลื่อนไหว')
        for label, (_, url) in zip(('คู่มืออ่านงบการเงินจาก SEC (ภาษาอังกฤษ)', 'ข้อมูลผลตอบแทนต่อเงินลงทุนจาก NYU Stern (ภาษาอังกฤษ)'), REFERENCE_URLS):
            st.link_button(label, url)
