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


CONTROL_LABELS = {
    'Asset Type':'ประเภทสินทรัพย์','Industry / ETF Category':'อุตสาหกรรม / หมวด ETF',
    'Return Display':'รูปแบบผลตอบแทน','Return Periods to Filter':'ช่วงผลตอบแทนที่ต้องการกรอง',
    'Require Available Return Periods':'ต้องมีข้อมูลผลตอบแทนครบช่วงที่เลือก',
    'Currency':'สกุลเงินราคา / มูลค่าตลาด','Financial Statement Currency':'สกุลเงินในงบการเงิน',
}
ASSET_LABELS = {'All':'ทั้งหมด','Common Stock':'หุ้นบริษัท','ETF':'ETF'}
ADVANCED_TABS = ('ผลตอบแทน','ราคา / ปันผล','ความเสี่ยง / แนวโน้ม','บริษัท / กองทุน','หมวดหมู่ / คุณภาพข้อมูล')


def wait_frontend_ready(app):
    app.wait_for_function('''() => {
        const root=document.querySelector('[data-testid="stApp"]');
        return root?.getAttribute('data-test-script-state')==='notRunning'
            && root.getAttribute('data-test-connection-state')==='CONNECTED';
    }''',timeout=60000)


def wait_applied(app,label,value):
    app.wait_for_function("""([label,value]) => {
        const e=document.querySelector('.export-ready');
        if(!e || e.closest('[data-stale="true"]')) return false;
        const actual=JSON.parse(e.dataset.controls)[label];
        return Array.isArray(actual) ? actual.includes(value) : actual===value;
    }""",arg=[label,value],timeout=60000)
    # Exports render before the research sections. A same-ticker page receipt
    # can also belong to the previous bound, so require frontend completion.
    wait_frontend_ready(app)
    from production_smoke import wait_page_ready
    ticker=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True).input_value()
    query=app.locator('.export-ready').evaluate('(e)=>JSON.parse(e.dataset.controls)["Search Ticker / Company"]')
    wait_page_ready(app,ticker,query=query)


def reset_controls(app):
    from production_smoke import wait_page_ready
    field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    ticker=field.input_value()
    previous=app.evaluate("""() => {
        const e=document.querySelector('.export-ready') || document.querySelector('.screener-ready');
        return e ? (JSON.parse(e.dataset.controls)['Reset Version'] || 0) : 0;
    }""")
    controls=app.locator('.st-key-overview_controls')
    controls.get_by_role('button',name='ล้างตัวกรองทั้งหมด',exact=True).click()
    defaults={'Asset Type':'All','Trend Status':'All','Return Display':'Cumulative (Adjusted Close)',
        'Search Ticker / Company':'','Return Periods to Filter':[],'Include Missing Values':False,
        'Require Available Return Periods':[],'Price Above SMA200':False,'Price > EMA20 > EMA50':False,
        'Session Favourites Only':False,'Company Filters Active':False,'Fund Filters Active':False,
        'Industry / ETF Category':[],'Sector':[],'Country':[],'Fund Family / Issuer':[],
        'Exchange':[],'Currency':[],'Financial Statement Currency':[],'Sort By':'Ticker','Descending':False}
    app.wait_for_function("""([previous,defaults]) => {
        const e=document.querySelector('.export-ready');
        if(!e || e.closest('[data-stale="true"]')) return false;
        const s=JSON.parse(e.dataset.controls);
        if(!(s['Reset Version']>previous)) return false;
        delete s['Reset Version'];
        return Object.keys(s).length===Object.keys(defaults).length
            && Object.entries(defaults).every(([key,value])=>JSON.stringify(s[key])===JSON.stringify(value));
    }""",arg=[previous,defaults],timeout=60000)
    wait_frontend_ready(app)
    wait_page_ready(app,ticker,query='')
    expect(field).to_have_value(ticker)
    expect(controls.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)).to_have_value('')
    asset=controls.locator('[data-testid="stSelectbox"]').filter(has=app.get_by_text('ประเภทสินทรัพย์',exact=True)).first
    expect(asset.get_by_role('combobox')).to_have_value('ทั้งหมด')
    expect(app.get_by_text('ค่าต่ำสุดต้องไม่มากกว่าค่าสูงสุด: 1 Month (%)',exact=True)).to_have_count(0,timeout=30000)
    return app.locator('.export-ready').evaluate('(e)=>JSON.parse(e.dataset.controls)')


def choose(app,label,value,multi=False,*,receipt_label=None,receipt_value=...):
    # Visible translations are distinct from the canonical receipt/export keys.
    wait_frontend_ready(app)
    testid='stMultiSelect' if multi else 'stSelectbox'
    widget=app.locator('.st-key-overview_controls [data-testid="'+testid+'"]').filter(
        has=app.get_by_text(CONTROL_LABELS.get(label,label),exact=True)).first
    visible=ASSET_LABELS[value] if label=='Asset Type' else value
    widget.scroll_into_view_if_needed()
    control=widget.get_by_role('combobox').first
    control.click()
    if multi:widget.locator('input').first.fill(visible)
    app.get_by_role('option',name=visible,exact=True).click(timeout=15000)
    if multi:
        # Streamlit 1.63 renders selected values as [data-tag] elements. Wait
        # for the user's actual selection before closing the menu; a lost click
        # fails here rather than being retried or concealed by another click.
        tag=widget.locator('[data-tag]').filter(has_text=re.compile('^'+re.escape(visible)+'$'))
        expect(tag).to_be_visible(timeout=15000)
        control.press('Escape')
    wait_applied(app,receipt_label or label,value if receipt_value is ... else receipt_value)


def verify_grouped_filters(page,app,initial,summary,button):
    """Cross all five real tabs and independently check their combined CSV."""
    controls=app.locator('.st-key-overview_controls')
    profiles=summary.get('screener',{})
    def number(value):
        try:
            value=float(value)
            return value if math.isfinite(value) else None
        except (TypeError,ValueError):
            return None
    def passes(row):
        profile=profiles.get(row['Ticker'],{})
        price,rsi,annual,roe=map(number,(row['Watchlist Price'],row['RSI (14)'],row['1 Year (%)'],profile.get('ROE')))
        return (row['Asset Type']=='Common Stock' and price is not None and price>=5
                and rsi is not None and rsi<=70 and annual is not None and roe is not None and roe>=10)
    candidates=[row for row in initial if passes(row) and profiles.get(row['Ticker'],{}).get('Currency')]
    assert candidates,'No real covered company supports the bounded five-tab filter check'
    currency=profiles[candidates[0]['Ticker']]['Currency']
    expected={row['Ticker']:row for row in initial if passes(row) and profiles.get(row['Ticker'],{}).get('Currency')==currency}
    for tab in ADVANCED_TABS:
        expect(controls.get_by_role('tab',name=tab,exact=True)).to_be_visible()
    controls.get_by_role('tab',name='ผลตอบแทน',exact=True).click()
    choose(app,'Require Available Return Periods','1 Year (%)',multi=True)
    controls.get_by_role('tab',name='ราคา / ปันผล',exact=True).click()
    choose(app,'เลือกเกณฑ์ราคาและสภาพคล่อง','ราคาจากชุดรายวัน',multi=True,
           receipt_label='Minimum Watchlist Price',receipt_value=None)
    minimum=controls.get_by_role('spinbutton',name='ต่ำสุด ราคาจากชุดรายวัน',exact=True)
    minimum.fill('5');minimum.press('Enter')
    wait_applied(app,'Minimum Watchlist Price',5)
    controls.get_by_role('tab',name='ความเสี่ยง / แนวโน้ม',exact=True).click()
    choose(app,'เลือกเกณฑ์ความเสี่ยง','RSI 14',multi=True,receipt_label='Maximum RSI (14)',receipt_value=None)
    maximum=controls.get_by_role('spinbutton',name='สูงสุด RSI 14',exact=True)
    maximum.fill('70');maximum.press('Enter')
    wait_applied(app,'Maximum RSI (14)',70)
    controls.get_by_role('tab',name='บริษัท / กองทุน',exact=True).click()
    choose(app,'เลือกเกณฑ์พื้นฐานบริษัท','ผลตอบแทนต่อส่วนผู้ถือหุ้น ROE (%)',multi=True,
           receipt_label='Minimum ROE (%)',receipt_value=None)
    minimum=controls.get_by_role('spinbutton',name='ต่ำสุด ผลตอบแทนต่อส่วนผู้ถือหุ้น ROE (%)',exact=True)
    minimum.fill('10');minimum.press('Enter')
    wait_applied(app,'Minimum ROE (%)',10)
    wait_applied(app,'Company Filters Active',True)
    controls.get_by_role('tab',name='หมวดหมู่ / คุณภาพข้อมูล',exact=True).click()
    choose(app,'Currency',currency,multi=True)
    actual=read_download(page,button)
    actual_tickers={row['Ticker'] for row in actual}
    assert len(actual)==len(expected) and actual_tickers==set(expected), {
        'expected':len(expected),'actual':len(actual),
        'missing':sorted(set(expected)-actual_tickers)[:10],'unexpected':sorted(actual_tickers-set(expected))[:10]}
    for row in actual:
        assert passes(row) and profiles[row['Ticker']]['Currency']==currency,row['Ticker']
        for label in ('Watchlist Price','RSI (14)','1 Year (%)'):
            assert math.isclose(float(row[label]),float(expected[row['Ticker']][label]),rel_tol=1e-8,abs_tol=1e-7), (row['Ticker'],label)
    reset=reset_controls(app)
    restored=read_download(page,button)
    assert len(restored)==len(initial) and {row['Ticker'] for row in restored}=={row['Ticker'] for row in initial}
    return {'tabs':list(ADVANCED_TABS),'rows':len(actual),'minimum_price':5,'maximum_rsi':70,
            'minimum_roe':10,'required_return':'1 Year (%)','currency':currency,
            'source_screener_schema':summary.get('screener_schema'),
            'exact_csv_membership':True,'csv_values_verified':True,'restored_rows':len(restored),
            'complete_reset_receipt':reset}


def viewport_box(locator):
    locator.scroll_into_view_if_needed()
    expect(locator).to_be_visible()
    box=locator.evaluate('''e => {
        const r=e.getBoundingClientRect();
        return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
                width:window.innerWidth,height:window.innerHeight};
    }''')
    assert (box['left']>=-1 and box['right']<=box['width']+1
            and box['top']>=-1 and box['bottom']<=box['height']+1),box
    return box


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
    exp=controls.get_by_text('ตัวกรองขั้นสูง',exact=True)
    exp.click()
    reset_controls(app)
    search=controls.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)
    expect(search).to_have_value('',timeout=30000)
    button=app.get_by_role('button',name='ดาวน์โหลดผลกรองครบทุกแถว',exact=True)
    initial=read_download(page,button)
    assert len(initial)==len(universe) and {r['Ticker'] for r in initial}==universe
    report['catalog_rows']=len(initial)
    report['original_stock_rows']=sum(r['Asset Type']=='Common Stock' for r in initial)
    report['etf_rows']=sum(r['Asset Type']=='ETF' for r in initial)
    assert report['original_stock_rows']==4200 and report['etf_rows']>700
    report['five_tab_combined_filter']=verify_grouped_filters(page,app,initial,summary,button)
    exp.click()
    from clean_ui_smoke import verify_industry_placement
    verify_industry_placement(app)
    choose(app,'Asset Type','ETF')
    category=summary['classifications']['QQQI']['Industry']
    choose(app,'Industry / ETF Category',category,multi=True)
    selected=read_download(page,button)
    assert selected and any(r['Ticker']=='QQQI' for r in selected)
    assert all(r['Asset Type']=='ETF' and r['Industry / ETF Category']==category for r in selected), {'selected_rows':len(selected),'bad_rows':[r['Ticker'] for r in selected if r['Asset Type']!='ETF' or r['Industry / ETF Category']!=category][:10]}
    report['category_filter']={'category':category,'rows':len(selected),'QQQI':True}
    exp.click()
    controls.get_by_role('tab',name='ผลตอบแทน',exact=True).click()
    choose(app,'Return Periods to Filter','1 Month (%)',multi=True)
    minimum=controls.get_by_role('spinbutton',name='ต่ำสุด 1 Month (%)',exact=True)
    minimum.fill('0');minimum.press('Enter')
    wait_applied(app,'Minimum 1 Month (%)',0)
    filtered=read_download(page,button)
    assert all(r['1 Month (%)'] and float(r['1 Month (%)'])>=0 for r in filtered)
    report['combined_numeric_filter']={'rows':len(filtered),'minimum_1m':0}
    maximum=controls.get_by_role('spinbutton',name='สูงสุด 1 Month (%)',exact=True)
    minimum.fill('10');minimum.press('Enter')
    wait_applied(app,'Minimum 1 Month (%)',10)
    maximum.fill('0');maximum.press('Enter')
    expect(app.get_by_text('ค่าต่ำสุดต้องไม่มากกว่าค่าสูงสุด: 1 Month (%)',exact=True)).to_be_visible(timeout=30000)
    no_exception(app);report['invalid_bounds_handled']=True
    reset_controls(app)
    choose(app,'Return Display','Annualized (3Y / 5Y only)')
    search.fill('AAPL');search.press('Enter')
    wait_applied(app,'Search Ticker / Company','AAPL')
    expect(app.get_by_text('หุ้นในผลค้นหา: AAPL',exact=True)).to_be_visible(timeout=30000)
    annual=read_download(page,button)
    assert len(annual)==1 and annual[0]['Ticker']=='AAPL'
    for field,label in [('Return_3Y','3 Years (Annualized %)'),('Return_5Y','5 Years (Annualized %)')]:
        expected=summary['quotes']['AAPL']['Return_Observations'][field]['annualized']
        assert annual[0][label] and math.isclose(float(annual[0][label]),expected,rel_tol=1e-7)
    report['annualized_csv_verified']=True
    reset_controls(app)
    search.fill('NO-MATCH-FOR-FINAL-CHECK');search.press('Enter')
    expect(app.get_by_text('ผ่านตัวกรอง 0 ตัว',exact=False)).to_be_visible(timeout=30000)
    no_exception(app);report['empty_results_handled']=True
    reset_controls(app)
    chart,payload=click_filtered_stock(page,app,'QQQI')
    assert payload['ticker']=='QQQI' and not payload.get('demo')
    report['QQQI_chart_bars']=len(payload['records'])
    from quote_refresh_smoke import verify_quote_refresh
    report.update(verify_quote_refresh(page,app,chart,payload,'QQQI'))
    app.get_by_text('Return Calculation Details — QQQI',exact=True).click()
    expect(app.get_by_role('button',name='Download Return Calculation Details',exact=True)).to_be_visible(timeout=30000)
    no_exception(app)
    theme=app.locator('#workspace-theme-v22')
    assert theme.count()==1
    report['theme']={'background':app.locator('.stApp').evaluate('(e)=>getComputedStyle(e).backgroundImage'),
                     'metric_background':app.locator('[data-testid="stMetric"]').first.evaluate('(e)=>getComputedStyle(e).backgroundImage')}
    assert 'gradient' in report['theme']['background'] and 'gradient' in report['theme']['metric_background']
    exp.click()
    app.get_by_role('heading',name='Stock Research Workspace',exact=True).scroll_into_view_if_needed()
    report['desktop_screenshot']=snapshot_image(page,'v22-desktop')
    page.set_viewport_size({'width':390,'height':844})
    page.wait_for_timeout(1500)
    no_exception(app)
    exp.click()
    mobile_tabs=[]
    for name in ADVANCED_TABS:
        tab=controls.get_by_role('tab',name=name,exact=True)
        tab.scroll_into_view_if_needed();tab.click()
        expect(tab).to_have_attribute('aria-selected','true')
        mobile_tabs.append({'tab':name,'box':viewport_box(tab)})
    controls.get_by_role('tab',name='ผลตอบแทน',exact=True).click()
    choose(app,'Return Periods to Filter','1 Month (%)',multi=True)
    number_input=controls.get_by_role('spinbutton',name='ต่ำสุด 1 Month (%)',exact=True)
    expect(number_input).to_have_value('')
    numeric_box=viewport_box(number_input)
    reset_button=controls.get_by_role('button',name='ล้างตัวกรองทั้งหมด',exact=True)
    reset_box=viewport_box(reset_button)
    assert reset_button.evaluate('(e)=>e.closest("[data-testid=stExpander]")===null')
    mobile_reset=reset_controls(app)
    assert int(app.locator('.export-ready').get_attribute('data-count'))==len(universe)
    report['mobile_filter_controls']={'tabs':mobile_tabs,'numeric_input_box':numeric_box,
        'reset_button_box':reset_box,'complete_reset_receipt':mobile_reset,'restored_rows':len(universe)}
    exp.click()
    app.get_by_role('heading',name='Stock Research Workspace',exact=True).scroll_into_view_if_needed()
    dimensions=app.locator('body').evaluate('(e)=>({width:e.clientWidth,scroll:e.scrollWidth})')
    assert dimensions['scroll']<=dimensions['width']+4,dimensions
    report['mobile_dimensions']=dimensions
    report['mobile_screenshot']=snapshot_image(page,'v22-mobile')
    page.set_viewport_size({'width':1440,'height':1000})
    exp.click()
    reset_controls(app)
    from clean_ui_smoke import verify_clean_presentation
    report['clean_presentation']=verify_clean_presentation(app)
    report['top_level_industry_dropdown']=True
    report['result']='passed'
    return report
