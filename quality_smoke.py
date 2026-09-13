"""Verify public availability reports and actual missing-data UI, not fake values."""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from playwright.sync_api import expect

REPO='sippakorntwo-glitch/stock-dashboard'


def fetch_public(url):
    req=Request(url,headers={'User-Agent':'dashboard-quality-verification','Accept':'application/octet-stream'})
    with urlopen(req,timeout=45) as response:return response.read(20_000_001)


def public_summary():
    manifest=json.loads(fetch_public(f'https://raw.githubusercontent.com/{REPO}/dashboard-data/dashboard/latest.json'))
    generation=manifest['generation'].split('/')[1]
    raw=fetch_public(f'https://github.com/{REPO}/releases/download/dashboard-data-{generation}/summary.json.gz')
    assert len(raw)<=20_000_000
    assert hashlib.sha256(raw).hexdigest()==manifest['summary']['sha256']
    return manifest,json.loads(gzip.decompress(raw))


def read_download(page,button):
    button.scroll_into_view_if_needed()
    with page.expect_download(timeout=45000) as info:button.click()
    download=info.value
    if download.failure():raise RuntimeError(download.failure())
    from pathlib import Path
    return list(csv.DictReader(io.StringIO(Path(download.path()).read_text(encoding='utf-8-sig'))))


def verify_quality(page,app):
    """Audit backend quality data; the public diagnostic panels are intentionally absent."""
    from production_smoke import no_exception,chart_for_symbol,wait_page_ready,verify_fundamentals
    from clean_ui_smoke import verify_clean_presentation
    manifest,summary=public_summary()
    quality=summary.get('quality',{})
    assert quality.get('version') in (1,2), 'Published backend quality report must remain available'
    if quality['version']==2:
        assert len([key for key in quality['columns'] if key.startswith('company.')])>=50
    assert set(quality['symbols'])==set(summary['universe'])
    total=len(summary['universe'])
    etfs=sum(v['asset_type']=='ETF' for v in quality['symbols'].values())
    stocks=total-etfs
    assert total==quality['counts']['universe'] and stocks==4200 and etfs>=700
    assert len(quality['columns'])>50
    assert all(sum(v.values())==(etfs if field.startswith('etf.') else stocks if field.startswith('stock.') else total)
               for field,v in quality['columns'].items())
    report={'backend_field_report':True,'backend_symbol_report':True,'source_verified':True,
            'source_generation':manifest['generation'],'counts':quality['counts'],
            'public_diagnostics_removed':verify_clean_presentation(app)}
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
    inspected=[]
    ticker_input=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    for ticker in ('AEON','AESP','SPY'):
        ticker_input.fill(ticker);ticker_input.press('Enter')
        wait_page_ready(app,ticker=ticker)
        if ticker!='AESP':chart_for_symbol(page,app,ticker)
        verify_fundamentals(app,ticker,is_fund=ticker=='SPY')
        values=app.locator('.st-key-research_fundamentals .workspace-help-table td, .st-key-research_fundamentals .company-table td').all_text_contents()
        assert not any(v.strip() in ('None','nan','null') for v in values)
        verify_clean_presentation(app)
        no_exception(app)
        inspected.append({'ticker':ticker,'industry_state':quality['symbols'][ticker]['industry_state'],
                          'dividend_state':quality['symbols'][ticker]['dividend_state'],
                          'history_bars':quality['symbols'][ticker]['history']['bars']})
    report['examples']=inspected
    return report
