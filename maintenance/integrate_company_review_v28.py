"""Guarded one-time v28 UI integration. Removed after the tested commit."""
from pathlib import Path
import ast


def edit(name,old,new):
    p=Path(name);s=p.read_text(encoding='utf-8')
    if s.count(old)!=1:raise RuntimeError(f'{name}: expected one integration anchor, got {s.count(old)}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('dashboard_views.py',"    with st.expander('ตารางวิเคราะห์ 360°',expanded=True):\n        table(analysis,height=450)","""    with st.expander('ตารางวิเคราะห์ 360°',expanded=True):
        if is_etf:
            table(analysis,height=450)
        else:
            from company_research_ui import render_company_review
            render_company_review(ticker,info,a.get_data_cache())
            st.markdown('#### Market / Technical')
            st.caption('Price trend and market risk are separate from company financial quality. Daily trading-score rules above are unchanged.')
            table(analysis.loc[~analysis['หมวด'].eq('พื้นฐาน')],height=450)""")
edit('dashboard_views.py',"    from quality_views import profile_value, profile_field_state, profile_unit\n    records=[]", """    if not etf:
        fields=[]
        st.write('**Business Profile:**',info.get('industry') or 'Industry not reported','·',info.get('sector') or 'Sector not reported','·',info.get('country') or 'Country not reported')
        st.caption('Financial statements, ratios, screening guides and metric tooltips are grouped above in Company Financial Review. This section retains business context, official filing links and distributions without duplicating the same numeric table.')
    from quality_views import profile_value, profile_field_state, profile_unit
    records=[]""")
edit('dashboard_views.py','    table(pd.DataFrame(records),height=480)','    if records:table(pd.DataFrame(records),height=480)')
for name in ('app.py','dashboard_runtime.py','tests/test_chart_commentary.py'):
    p=Path(name);s=p.read_text();assert '2026-09-13.27' in s;p.write_text(s.replace('2026-09-13.27','2026-09-13.28'))
p=Path('workspace_boot.py');s=p.read_text();tree=ast.parse(s)
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='_MODULES' for x in node.targets):
        names=tuple(dict.fromkeys((*ast.literal_eval(node.value),'financial_statements','company_metrics','company_research','company_research_ui')))
        lines=s.splitlines(True);lines[node.lineno-1:node.end_lineno]=['_MODULES = '+repr(names)+'\n'];s=''.join(lines);break
p.write_text(s)
edit('enhanced_smoke.py',"    return report","    from company_review_smoke import verify_company_review\n    report['company_financial_review']=verify_company_review(page,app)\n    return report")
# Expose the previously available dividend-yield observation beside payouts,
# using its explicitly fractional trailing field, not the ambiguous dividendYield.
edit('company_metrics.py'," m('payout','Shareholder Distributions'", " m('dividend_yield','Shareholder Distributions','Dividend Yield (trailing)','trailingAnnualDividendYield','percent','context','Yield is not total return; assess coverage and continuity','อัตราปันผลย้อนหลังที่ provider รายงานเป็นสัดส่วนจึงคูณ 100 ไม่ใช่ผลตอบแทนรวม และไม่รับประกันการจ่ายงวดถัดไป'),\n m('payout','Shareholder Distributions'")
# The generic unit validator should preserve signed SBC reversals as reported.
edit('company_research.py',"'buybacks','dividends_paid','capex','sbc'}","'buybacks','dividends_paid','capex','dividend_yield'}")
Path(__file__).unlink()
print('Grouped company research integrated; existing fund UI, scoring and prices untouched.')
