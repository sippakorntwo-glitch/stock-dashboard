"""Independent real-browser checks; no generated market prices or state injection."""
from __future__ import annotations
from datetime import datetime, timezone
import base64
import math
import os
from pathlib import Path
import re
import time
import requests
from playwright.sync_api import expect
from quality_smoke import public_summary, read_download


def choose(app,label,value,multi=False):
    testid='stMultiSelect' if multi else 'stSelectbox'
    widget=app.locator('[data-testid="'+testid+'"]').filter(has=app.get_by_text(label,exact=True)).first
    widget.scroll_into_view_if_needed()
    control=widget.get_by_role('combobox').first
    control.click()
    if multi:
        field=widget.locator('input').first
        field.fill(value)
    app.get_by_role('option',name=value,exact=True).click(timeout=15000)
    if multi:control.press('Escape')


def snapshot_image(page,name):
    path=Path('work')/(name+'.png');path.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(path),full_page=False)
    token=os.environ.get('DASHBOARD_GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if os.environ.get('GITHUB_ACTIONS')!='true' or not token:return str(path)
    repo=os.environ.get('GITHUB_REPOSITORY')
    if repo!='sippakorntwo-glitch/stock-dashboard':return str(path)
    raw=path.read_bytes()
    if len(raw)>2_000_000:raise ValueError('Screenshot exceeds bounded upload size')
    url=f'https://api.github.com/repos/{repo}/contents/reports/{name}.png'
    branch='verify/v22-results'
    with requests.Session() as session:
        session.trust_env=False;session.headers.update({'Authorization':'Bearer '+token})
        old=session.get(url,params={'ref':branch},timeout=30)
        if old.status_code not in (200,404):old.raise_for_status()
        body={'branch':branch,'message':'Record public UI screenshot','content':base64.b64encode(raw).decode()}
        if old.status_code==200:body['sha']=old.json()['sha']
        session.put(url,json=body,timeout=45).raise_for_status()
    return f'https://raw.githubusercontent.com/{repo}/{branch}/reports/{name}.png'


def verify_screener(page,app):
    from production_smoke import no_exception,click_filtered_stock,chart_for_symbol,URL
    report={'target':URL,'verified_at':datetime.now(timezone.utc).isoformat()}
    manifest,summary=public_summary()
    universe=set(summary['universe'])
    assert 'QQQI' in universe and len(universe)>4900,'Expanded snapshot must be published first'
    quote=summary['quotes'].get('QQQI',{})
    assert quote.get('Close') and quote.get('Price_AsOf'),'QQQI must have real prepared prices'
    controls=app.locator('.st-key-overview_controls')
    exp=controls.get_by_text('Advanced Filters',exact=True)
    exp.click()
    controls.get_by_role('button',name='Reset Filters',exact=True).click()
    search=controls.get_by_role('textbox',name='Search Ticker / Company / Industry',exact=True)
    expect(search).to_have_value('',timeout=30000)
    button=app.get_by_role('button',name='ดาวน์โหลดผลกรองครบทุกแถว',exact=True)
    initial=read_download(page,button)
    assert len(initial)==len(universe) and {r['Ticker'] for r in initial}==universe
    report['catalog_rows']=len(initial)
    report['original_stock_rows']=sum(r['Asset Type']=='Common Stock' for r in initial)
    report['etf_rows']=sum(r['Asset Type']=='ETF' for r in initial)
    assert report['original_stock_rows']==4200 and report['etf_rows']>700
    choose(app,'Asset Type','ETF')
    category=summary['classifications']['QQQI']['Industry']
    choose(app,'Industry / ETF Category',category,multi=True)
    selected=read_download(page,button)
    assert selected and any(r['Ticker']=='QQQI' for r in selected)
    assert all(r['Asset Type']=='ETF' and r['Industry / ETF Category']==category for r in selected)
    report['category_filter']={'category':category,'rows':len(selected),'QQQI':True}
    choose(app,'Return Periods to Filter','1 Month (%)',multi=True)
    minimum=controls.get_by_role('spinbutton',name='Minimum 1 Month (%)',exact=True)
    minimum.fill('0');minimum.press('Enter')
    filtered=read_download(page,button)
    assert all(r['1 Month (%)'] and float(r['1 Month (%)'])>=0 for r in filtered)
    report['combined_numeric_filter']={'rows':len(filtered),'minimum_1m':0}
    maximum=controls.get_by_role('spinbutton',name='Maximum 1 Month (%)',exact=True)
    minimum.fill('10');minimum.press('Enter');maximum.fill('0');maximum.press('Enter')
    expect(app.get_by_text('Return_1M: maximum is below minimum',exact=True)).to_be_visible(timeout=30000)
    no_exception(app);report['invalid_bounds_handled']=True
    controls.get_by_role('button',name='Reset Filters',exact=True).click()
    choose(app,'Return Display','Annualized (3Y / 5Y only)')
    search.fill('AAPL');search.press('Enter')
    expect(app.get_by_text('หุ้นในผลค้นหา: AAPL',exact=True)).to_be_visible(timeout=30000)
    annual=read_download(page,button)
    assert len(annual)==1 and annual[0]['Ticker']=='AAPL'
    for field,label in [('Return_3Y','3 Years (Annualized %)'),('Return_5Y','5 Years (Annualized %)')]:
        expected=summary['quotes']['AAPL']['Return_Observations'][field]['annualized']
        assert annual[0][label] and math.isclose(float(annual[0][label]),expected,rel_tol=1e-7)
    report['annualized_csv_verified']=True
    controls.get_by_role('button',name='Reset Filters',exact=True).click()
    search.fill('NO-MATCH-FOR-FINAL-CHECK');search.press('Enter')
    expect(app.get_by_text('ผ่านตัวกรอง 0 ตัว',exact=False)).to_be_visible(timeout=30000)
    no_exception(app);report['empty_results_handled']=True
    controls.get_by_role('button',name='Reset Filters',exact=True).click()
    chart,payload=click_filtered_stock(page,app,'QQQI')
    assert payload['ticker']=='QQQI' and not payload.get('demo')
    report['QQQI_chart_bars']=len(payload['records'])
    panel=app.locator('.st-key-minute_quote_panel')
    minute=panel.locator('.minute-quote[data-ticker="QQQI"]')
    expect(minute).to_be_visible(timeout=90000)
    first=minute.get_attribute('data-fetched-at')
    assert first and float(minute.get_attribute('data-price'))>0
    observed=datetime.fromisoformat(minute.get_attribute('data-bar-time'))
    assert observed<=datetime.now(timezone.utc)
    # Verify a second actual provider acquisition, not a cosmetic countdown.
    local=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York'))
    if local.weekday()<5 and 4<=local.hour<20:
        deadline=time.monotonic()+100
        while time.monotonic()<deadline and minute.get_attribute('data-fetched-at')==first:
            page.wait_for_timeout(2000);no_exception(app)
        assert minute.get_attribute('data-fetched-at')!=first,'Minute-price polling did not acquire a second observation'
        report['auto_refresh_verified']=True
    else:
        report['auto_refresh_verified']='outside request window: 30-minute budget applies'
    report['minute_price']={'price':float(minute.get_attribute('data-price')),'bar_time':minute.get_attribute('data-bar-time'),
                            'fetched_at':minute.get_attribute('data-fetched-at'),'state':minute.get_attribute('data-state')}
    app.get_by_text('Return Calculation Details — QQQI',exact=True).click()
    expect(app.get_by_role('button',name='Download Return Calculation Details',exact=True)).to_be_visible(timeout=30000)
    no_exception(app)
    theme=app.locator('#workspace-theme-v22')
    assert theme.count()==1
    report['theme']={'background':app.locator('.stApp').evaluate('(e)=>getComputedStyle(e).backgroundImage'),
                     'metric_background':app.locator('[data-testid="stMetric"]').first.evaluate('(e)=>getComputedStyle(e).backgroundImage')}
    assert 'gradient' in report['theme']['background'] and 'gradient' in report['theme']['metric_background']
    exp.click()  # Show the normal compact controls in the responsive screenshots.
    app.get_by_role('heading',name='Stock Research Workspace',exact=True).scroll_into_view_if_needed()
    report['desktop_screenshot']=snapshot_image(page,'v22-desktop')
    page.set_viewport_size({'width':390,'height':844})
    page.wait_for_timeout(1500)
    no_exception(app)
    dimensions=app.locator('body').evaluate('(e)=>({width:e.clientWidth,scroll:e.scrollWidth})')
    assert dimensions['scroll']<=dimensions['width']+4,dimensions
    report['mobile_dimensions']=dimensions
    report['mobile_screenshot']=snapshot_image(page,'v22-mobile')
    page.set_viewport_size({'width':1440,'height':1000})
    exp.click()
    controls.get_by_role('button',name='Reset Filters',exact=True).click()
    report['result']='passed'
    return report
