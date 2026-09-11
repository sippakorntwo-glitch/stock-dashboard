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
    from production_smoke import URL,no_exception,chart_for_symbol
    report={'field_report':False,'symbol_report':False,'source_verified':False}
    expect(app.get_by_role('heading',name='รายงานความครบของข้อมูลทุกส่วน',exact=True)).to_be_visible(timeout=60000)
    manifest,summary=public_summary()
    quality=summary.get('quality',{})
    if not quality:
        # The PR can precede the first quality-enabled publication. This exception
        # is NEVER allowed for the public production verification after merge.
        assert urlsplit(URL).hostname in ('localhost','127.0.0.1'), 'Production snapshot lacks quality metadata'
        expect(app.get_by_text('รอรายงานจากงานอัปเดตข้อมูลรุ่นใหม่ ไม่ได้หมายความว่าข้อมูลครบแล้ว',exact=True)).to_be_visible()
        return {'quality_status':'awaiting_first_publication_on_CI_only','no_false_completeness':True}
    assert quality.get('version')==1
    assert set(quality['symbols'])==set(summary['universe'])
    assert len(summary['universe'])==quality['counts']['universe']==4900
    assert all(sum(v.values())==(700 if field.startswith('etf.') else 4200 if field.startswith('stock.') else 4900)
               for field,v in quality['columns'].items())
    report.update(source_verified=True,source_generation=manifest['generation'],counts=quality['counts'])
    fields_button=app.get_by_role('button',name='ดาวน์โหลดรายงานความครบทุกฟิลด์',exact=True)
    expect(fields_button).to_be_visible(timeout=90000)
    fields=read_download(page,fields_button)
    assert len(fields)==len(quality['columns']) and len(fields)>50
    for row in fields:
        total=int(row['ทั้งหมดที่ใช้ฟิลด์นี้'])
        assert total==sum(int(v) for k,v in row.items() if k not in ('ข้อมูล / ฟิลด์','ทั้งหมดที่ใช้ฟิลด์นี้'))
    report['field_report']=True
    symbols=read_download(page,app.get_by_role('button',name='ดาวน์โหลดสถานะข้อมูลครบทุกหุ้น',exact=True))
    assert len(symbols)==4900 and {r['Ticker'] for r in symbols}==set(summary['universe'])
    assert all(r['Industry_Status'] not in ('','None','nan') for r in symbols)
    report['symbol_report']=True
    # Reuse daily prepared observations; do not spend provider calls to test metadata.
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
    inspected=[]
    ticker_input=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    for ticker in ('AEON','AESP','SPY'):
        ticker_input.fill(ticker);ticker_input.press('Enter')
        if ticker!='AESP':chart_for_symbol(page,app,ticker)
        exp=app.get_by_text('ตรวจข้อมูลที่ขาดของ '+ticker,exact=True)
        expect(exp).to_be_visible(timeout=60000)
        exp.click();page.wait_for_timeout(700)
        expect(app.get_by_text('ฟิลด์ต้นทาง',exact=True).first).to_be_visible(timeout=30000)
        assert app.locator('.st-key-research_fundamentals .workspace-help-table').count()>=1
        values=app.locator('.st-key-research_fundamentals .workspace-help-table td').all_text_contents()
        assert not any(v.strip() in ('None','nan','null') for v in values)
        no_exception(app)
        inspected.append({'ticker':ticker,'industry_state':quality['symbols'][ticker]['industry_state'],
                          'dividend_state':quality['symbols'][ticker]['dividend_state'],
                          'history_bars':quality['symbols'][ticker]['history']['bars']})
    report['examples']=inspected
    return report
