"""Real browser + checksum-verified data. No state injection or invented prices."""
from __future__ import annotations
import gzip
import hashlib
import json
from playwright.sync_api import expect
from quality_smoke import public_summary,fetch_public,REPO
from reference_ui import REFERENCE_LABEL


def reference_for(ticker,manifest):
    slot=str(int(hashlib.sha256(ticker.encode()).hexdigest()[:8],16)%128)
    record=manifest['details'][slot];generation=manifest['generation'].split('/')[1]
    raw=fetch_public(f'https://github.com/{REPO}/releases/download/dashboard-data-{generation}/details--{slot}.jsonl.gz')
    assert hashlib.sha256(raw).hexdigest()==record['sha256']
    for line in gzip.decompress(raw).splitlines():
        symbol,key,value,meta=json.loads(line)
        if symbol==ticker and key=='reference:'+ticker:return value
    return {}


def verify_asset_reference(page,app):
    from production_smoke import no_exception,wait_page_ready,chart_for_symbol,select_manual_ticker,open_research_expander
    from clean_ui_smoke import verify_clean_presentation
    manifest,_=public_summary()
    field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    # The preceding screener check ends with Reset Filters. Its export receipt
    # precedes completion of the selected-stock sections and final widget state.
    # Wait for that exact empty-query page before typing, not a transient input
    # that a still-running reset render can replace. Never retry a lost action
    # or suppress a wrong-symbol assertion.
    current=field.input_value()
    wait_page_ready(app,current,query='')
    expect(field).to_have_value(current)
    # Force the responsive-layout precondition with ordinary UI controls so
    # both CI and production exercise recovery from a collapsed sidebar.
    sidebar=app.locator('[data-testid="stSidebar"]')
    if sidebar.get_attribute('aria-expanded')!='true':
        app.locator('[data-testid="stExpandSidebarButton"]').click()
    expect(sidebar).to_have_attribute('aria-expanded','true')
    sidebar.locator('[data-testid="stSidebarHeader"]').hover()
    sidebar.locator('[data-testid="stSidebarCollapseButton"]').get_by_role('button').click()
    expect(sidebar).to_have_attribute('aria-expanded','false')
    field=select_manual_ticker(app,'AAAU')
    wait_page_ready(app,'AAAU');chart_for_symbol(page,app,'AAAU')
    expect(field).to_have_value('AAAU')
    open_research_expander(app,'เปิดรายละเอียดพื้นฐานและปันผล')
    open_research_expander(app,'เปิดกราฟและแผนซื้อขาย')
    section=app.locator('.st-key-research_fundamentals')
    expect(section.get_by_text('AAAU holds physical gold',exact=False)).to_be_visible()
    analysis=app.get_by_text('ตารางวิเคราะห์ 360°',exact=True).locator('xpath=ancestor::details[1]')
    technical=analysis.locator('.workspace-help-table')
    if not technical.is_visible():
        analysis.locator('summary').first.click()
    expect(technical).to_be_visible()
    for label in ('ราคาต่อกำไรคาดการณ์ (Forward P/E)','ราคาต่อกำไรย้อนหลัง (P/E)',
                  'ราคาเป้าหมายเฉลี่ยของนักวิเคราะห์'):
        row=technical.locator('tr').filter(has=app.get_by_text(label,exact=False))
        expect(row).to_have_count(1)
        expect(row).to_contain_text('N/A — ไม่ใช้กับหลักทรัพย์ประเภทนี้')
    fundrow=section.locator('.workspace-help-table tr').filter(has=app.get_by_text('Portfolio P/E',exact=False)).first
    expect(fundrow).to_contain_text('N/A — Not applicable')
    open_research_expander(app,REFERENCE_LABEL)
    expect(section.get_by_role('link',name='Gold trust annual report',exact=True)).to_have_attribute('href',
        'https://www.sec.gov/Archives/edgar/data/1708646/000119312526067559/d56933d10k.htm')
    expect(section.get_by_text('Annual sponsor fee: 0.18%',exact=False)).to_be_visible()
    verify_clean_presentation(app);no_exception(app)
    report={'AAAU_pe_not_applicable':True,'AAAU_issuer_filing_link':True,'diagnostics_still_absent':True,
            'collapsed_sidebar_manual_selection':{'from':current,'to':'AAAU','single_entry':True},'SEC_examples':[]}
    for ticker in ('AAPL','MSFT'):
        field=select_manual_ticker(app,ticker);wait_page_ready(app,ticker)
        expect(field).to_have_value(ticker)
        open_research_expander(app,'เปิดรายละเอียดพื้นฐานและปันผล')
        section=app.locator('.st-key-research_fundamentals')
        reference=reference_for(ticker,manifest)
        expander=section.get_by_text(REFERENCE_LABEL,exact=True).locator('xpath=ancestor::details[1]')
        open_research_expander(app,REFERENCE_LABEL)
        link=expander.get_by_role('link',name='เอกสารที่ยื่นต่อ SEC',exact=True)
        expect(link).to_be_visible()
        assert link.get_attribute('href').startswith('https://www.sec.gov/')
        facts=reference.get('facts',[])
        if facts:
            expect(expander.locator('[data-testid="stDataFrame"]')).to_be_visible()
            expect(expander.get_by_text('งบ SEC แสดงปีบัญชี (FY) หรือยอด ณ วันสิ้นงวด',exact=False)).to_be_visible()
        report['SEC_examples'].append({'ticker':ticker,'verified_cik':reference.get('cik'),
            'stored_fiscal_records':len(facts),'submissions_checked_at':reference.get('checked_at')})
        verify_clean_presentation(app);no_exception(app)
    report['result']='passed'
    return report
