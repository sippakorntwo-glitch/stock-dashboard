"""Grouped financial research beside related metrics; no page-load network work."""
from __future__ import annotations
from collections import Counter
from html import escape
import json
import pandas as pd
import streamlit as st
from company_metrics import GROUPS,SOURCES,GUIDE_NOTE,BY_KEY
from company_research import build_review,format_value
from financial_statements import derived_metrics

CSS='''<style>
.company-review{min-width:0;width:100%;color:#eaf2ff}.company-review h4{margin:1.1rem 0 .5rem;color:#a9e5f4;font-size:1.05rem}
.company-review .financial-scroll{max-width:100%;overflow:auto;border:1px solid #354964;border-radius:10px;margin-bottom:.8rem}
.company-review table{border-collapse:collapse;width:100%;min-width:900px;font:14px sans-serif}
.company-review th,.company-review td{padding:10px 12px;vertical-align:top;border-bottom:1px solid #2c3e56;text-align:left;line-height:1.5}
.company-review th{background:#203450;color:#d5effa;position:sticky;top:0}.company-review tr:nth-child(even){background:#101e32}
.company-review td:first-child{min-width:155px}.company-review td:nth-child(2){font-variant-numeric:tabular-nums;min-width:110px}
.company-review abbr{cursor:help;text-decoration:none;border:0;color:#d8eef8}.company-review abbr:focus-visible{outline:3px solid #f8d98e;outline-offset:3px}
.company-review .grade{padding:3px 7px;border-radius:5px;display:inline-block;background:#27334d;color:#d3dbeb;font-weight:600}
.company-review .favorable{background:#123e35;color:#97ebc9}.company-review .watch{background:#453922;color:#f7d997}.company-review .risk{background:#4b252e;color:#ffb4c1}
.company-review .period{font-size:.8rem;color:#b8c9df;min-width:120px}.company-review small{color:#9bd7e6}
.company-review .financial-glossary{padding:10px 12px;background:#132238;border-radius:10px;margin-top:10px}
.company-review .financial-glossary dt{font-weight:700;margin-top:12px}.company-review .financial-glossary dd{margin:4px 0 8px;white-space:pre-line;line-height:1.5}
.company-review .review-note{border-left:3px solid #bba7fa;padding:.6rem .8rem;background:#192440;margin-bottom:1rem;color:#dbe0f7}
</style>'''


def tooltip(row):
    parts=[row['definition'],'Formula: '+(row['formula'] or 'Needs applicable reported inputs'),
           'Reference: '+row['guide'],'Basis: '+row['basis'],'Interpretation: '+row['interpretation']]
    if row.get('source'):parts.append('Source: '+row['source'])
    if row.get('filed'):parts.append('Filed: '+row['filed'])
    if row.get('fetched_at'):parts.append('Retrieved: '+str(row['fetched_at'])+' (not the fiscal period)')
    if row.get('inputs'):parts.append('Inputs: '+json.dumps(row['inputs'],ensure_ascii=False,allow_nan=False))
    if row.get('note'):parts.append(row['note'])
    return '\n'.join(parts)


def review_html(review):
    fragments=[];glossary=[]
    for group in GROUPS:
        rows=[r for r in review['rows'] if r['group']==group]
        body=[]
        for r in rows:
            tip=tooltip(r);grade=r['grade']
            tone='risk' if grade in ('Risk flag','Above earnings','Leverage watch') else 'favorable' if grade in ('Favorable (guide)','Positive','Positive equity','Net cash','Above WACC assumption') else 'watch' if any(t in grade for t in ('Watch','watch','Below','Stale')) else ''
            evidence=json.dumps({k:r[k] for k in ('key','value','unit','status','basis','formula','inputs','source','grade')},ensure_ascii=False,allow_nan=False)
            body.append(f'<tr data-metric="{escape(r["key"],quote=True)}" data-observation="{escape(evidence,quote=True)}"><td><abbr tabindex="0" title="{escape(tip,quote=True)}" aria-label="{escape(r["metric"]+": "+tip,quote=True)}">{escape(r["metric"])} <small>ⓘ</small></abbr></td><td>{escape(format_value(r))}</td><td>{escape(r["guide"])}</td><td><span class="grade {tone}">{escape(grade)}</span><br>{escape(r["interpretation"])}</td><td class="period">{escape(r["basis"])}</td></tr>')
            glossary.append(f'<dt>{escape(r["metric"])}</dt><dd>{escape(tip)}</dd>')
        fragments.append(f'<section data-financial-group="{escape(group,quote=True)}"><h4>{escape(group)}</h4><div class="financial-scroll"><table class="workspace-help-table" data-tooltip-column="0"><thead><tr><th>Metric</th><th>Current Value</th><th>Reference / Screening Guide</th><th>Assessment / Interpretation</th><th>Period / Basis</th></tr></thead><tbody>{"".join(body)}</tbody></table></div></section>')
    attrs=json.dumps(review['counts'],allow_nan=False)
    return CSS+f'<div class="company-review" data-ticker="{escape(review["ticker"],quote=True)}" data-method="{review["method"]}" data-coverage="{escape(attrs,quote=True)}"><div class="review-note">{escape(GUIDE_NOTE)}</div>'+''.join(fragments)+'<details class="financial-glossary"><summary>ⓘ Metric definitions, formulas and evidence — tap to read on mobile</summary><dl>'+''.join(glossary)+'</dl></details></div>'


def export_frame(review):
    return pd.DataFrame([{'Group':r['group'],'Metric':r['metric'],'Value':r['value'],'Unit':r['unit'],
        'Availability':r['status'],'Reference Guide':r['guide'],'Assessment':r['grade'],
        'Interpretation':r['interpretation'],'Period / Basis':r['basis'],'Source':r['source'],
        'Formula':r['formula'],'Inputs':json.dumps(r['inputs'],ensure_ascii=False),'Definition':r['definition']}
        for r in review['rows']])


def render_company_review(ticker,info,cache):
    st.subheader('Company Financial Review')
    st.caption('แยกงบการเงิน อัตราส่วน มูลค่า และความคาดหวัง ไม่ให้สัญญาณเทคนิครวมกับคุณภาพบริษัท · ชี้ที่ชื่อ Metric เพื่ออ่านความหมาย สูตร และข้อจำกัด')
    with st.expander('Analysis Assumptions',expanded=False):
        wacc=st.number_input('WACC assumption (%)',min_value=0.0,max_value=100.0,value=None,step=.5,
            key='company_wacc_'+ticker,help='Optional user assumption, not a verified company WACC. ROIC is compared only when this is entered; no default cost of capital is fabricated.')
        st.caption('เกณฑ์ตัวเลขเป็นแนวคัดกรองทั่วไป ไม่ใช่มาตรฐานทุกอุตสาหกรรม ไม่ถือว่าข้อมูลที่ขาด = 0 และไม่ได้แก้คะแนนซื้อ/Top 10')
    reference,_=cache.get('reference:'+ticker,request_remote=False)
    raw,meta=cache.get('info:'+ticker,request_remote=False)
    profile=dict(info);profile.setdefault('_Fetched_At_UTC',meta.get('fetched_at'))
    review=build_review(ticker,profile,reference,wacc=wacc)
    counts=Counter(r['grade'] for r in review['rows'])
    available=review['counts'].get('available',0)
    favorable=sum(counts[k] for k in ('Favorable (guide)','Positive','Positive equity','Net cash','Above WACC assumption'))
    risks=sum(counts[k] for k in ('Risk flag','Above earnings','Leverage watch','Below WACC assumption'))
    st.write(f'**Reported / calculated:** {available}/{len(review["rows"])} metrics · **Positive / favorable guide signals:** {favorable} · **Risk / leverage flags:** {risks}')
    st.caption('ตัวนับนี้ไม่ใช่คะแนนคุณภาพบริษัท ไม่ใช่โอกาสกำไร และไม่รับรองว่าควรซื้อ; ข้อมูลอาจยังไม่ครบและต้องดูบริบทธุรกิจ')
    if review['sector_guides_suppressed']:
        st.info('Sector-specific review: เกณฑ์หนี้/กระแสเงินสดทั่วไปถูกงดประเมินสำหรับธุรกิจการเงิน อสังหาริมทรัพย์ หรือเมื่อยังไม่ทราบ Sector')
    st.html(review_html(review))
    st.download_button('Download Company Financial Review',export_frame(review).to_csv(index=False).encode('utf-8-sig'),
                       file_name=ticker+'_financial_review.csv',mime='text/csv',on_click='ignore',key='company_export_'+ticker)
    annual=(reference or {}).get('financial_statements',{}).get('annual',[])
    if annual:
        with st.expander('Financial Statement History (FY)',expanded=False):
            data={}
            for i,p in enumerate(annual):
                calculated=derived_metrics(p,annual[i+1] if i+1<len(annual) else None)
                data[p['end']+' · '+p['currency']]={BY_KEY[k].label:v['value'] for k,v in calculated.items() if k in BY_KEY}
            st.dataframe(pd.DataFrame(data),use_container_width=True)
            st.caption('Historical reported fiscal-year values; percentage metrics are already ×100 and ratio metrics are times. No TTM interpolation or zero-filling.')
    with st.expander('Methodology and financial definitions',expanded=False):
        for label,url in SOURCES.items():st.link_button(label,url)
        st.write('P/B (P/BV) ใช้เป็นชื่อมาตรฐานของ Price / Book; งบ SEC เป็น FY ไม่ใช่ TTM. ห้ามเทียบยอดหรือคำนวณจากงวด/สกุลเงินต่างกันโดยไม่ปรับฐาน. ROIC ใช้ทุนเฉลี่ยและภาษีที่คำนวณได้ ไม่สมมติ WACC ให้ทุกบริษัท.')
    return review
