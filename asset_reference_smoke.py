"""Real browser + checksum-verified data. No state injection or invented prices."""
from __future__ import annotations
import gzip
import hashlib
import json
from playwright.sync_api import expect
from quality_smoke import public_summary,fetch_public,REPO


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
    from production_smoke import no_exception,wait_page_ready,chart_for_symbol
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
    field.fill('AAAU');field.press('Enter')
    wait_page_ready(app,'AAAU');chart_for_symbol(page,app,'AAAU')
    expect(field).to_have_value('AAAU')
    section=app.locator('.st-key-research_fundamentals')
    expect(section.get_by_text('AAAU holds physical gold',exact=False)).to_be_visible()
    technical=app.locator('.st-key-research_technical .workspace-help-table')
    for label in ('Forward P/E','Trailing P/E','Target Price'):
        row=technical.locator('tr').filter(has=app.get_by_text(label,exact=False)).first
        expect(row).to_contain_text('N/A — Not applicable')
    fundrow=section.locator('.workspace-help-table tr').filter(has=app.get_by_text('Portfolio P/E',exact=False)).first
    expect(fundrow).to_contain_text('N/A — Not applicable')
    section.get_by_text('Official sources & filed financials',exact=True).click()
    expect(section.get_by_role('link',name='Gold trust annual report',exact=True)).to_have_attribute('href',
        'https://www.sec.gov/Archives/edgar/data/1708646/000119312526067559/d56933d10k.htm')
    expect(section.get_by_text('Annual sponsor fee: 0.18%',exact=False)).to_be_visible()
    verify_clean_presentation(app);no_exception(app)
    report={'AAAU_pe_not_applicable':True,'AAAU_issuer_filing_link':True,'diagnostics_still_absent':True,'SEC_examples':[]}
    for ticker in ('AAPL','MSFT'):
        field.fill(ticker);field.press('Enter');wait_page_ready(app,ticker)
        expect(field).to_have_value(ticker)
        section=app.locator('.st-key-research_fundamentals')
        reference=reference_for(ticker,manifest)
        expander=section.locator('[data-testid="stExpander"]').filter(has=app.get_by_text('Official sources & filed financials',exact=True)).first
        summary=expander.locator('summary').first
        if not expander.locator('[data-testid="stDataFrame"]').is_visible():summary.click()
        link=expander.get_by_role('link',name='SEC filings',exact=True)
        expect(link).to_be_visible()
        assert link.get_attribute('href').startswith('https://www.sec.gov/')
        facts=reference.get('facts',[])
        if facts:
            expect(expander.locator('[data-testid="stDataFrame"]')).to_be_visible()
            expect(expander.get_by_text('SEC reported fiscal-year or point-in-time figures',exact=False)).to_be_visible()
        report['SEC_examples'].append({'ticker':ticker,'verified_cik':reference.get('cik'),
            'stored_fiscal_records':len(facts),'submissions_checked_at':reference.get('checked_at')})
        verify_clean_presentation(app);no_exception(app)
    report['result']='passed'
    return report
