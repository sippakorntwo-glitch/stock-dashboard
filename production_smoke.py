"""Exercise the real single-page app, actual table selection, and real charts.

The report always names its target URL; localhost success is not production success.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

URL='https://my-stock-terminal.streamlit.app/'
VIEWS=['ภาพรวมและค้นหา','กราฟและแผนซื้อ','พื้นฐานและปันผล','ความเสี่ยง','เปรียบเทียบหลายตัว']


def no_exception(app):
    errors=app.locator('[data-testid="stException"]')
    if errors.count(): raise RuntimeError('Streamlit exception: '+errors.first.inner_text()[:1600])


def open_research_expander(app, label):
    text = app.get_by_text(label, exact=True)
    if text.count():
        details = text.locator('xpath=ancestor::details[1]')
        if details.get_attribute('open') is None:
            text.click()


def diagnose(page):
    try:
        Path('work').mkdir(exist_ok=True)
        page.screenshot(path='work/browser-failure.png',full_page=False)
    except Exception as exc:
        print('SCREENSHOT_DIAGNOSTIC_ERROR:',type(exc).__name__,flush=True)
    for frame in page.frames:
        try:
            u=urlsplit(frame.url)
            print('BROWSER_FRAME:',json.dumps({'url':u.scheme+'://'+u.netloc+u.path,'payload_count':frame.locator('#payload').count(),'canvas_count':frame.locator('canvas').count(),'text':frame.locator('body').inner_text()[:12000], 'inputs':frame.locator('input').evaluate_all('(xs)=>xs.filter(x=>x.type!=="password").map(x=>({label:x.getAttribute("aria-label"),value:x.value}))'), 'receipts':frame.locator('.workspace-ready,.export-ready').evaluate_all('(xs)=>xs.map(x=>({...x.dataset}))')},ensure_ascii=False),flush=True)
        except Exception as exc: print('FRAME_DIAGNOSTIC_ERROR:',type(exc).__name__,flush=True)


def app_frame(page):
    for frame in page.frames:
        try:
            if frame.get_by_role('heading',name='Stock Research Workspace',exact=True).count(): return frame
        except Exception: pass
    return None


def wait_for_release(page,version):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        page.goto(URL,wait_until='domcontentloaded',timeout=60000)
        for _ in range(20):
            app=app_frame(page)
            if app:
                if app.get_by_text(re.compile(re.escape(version))).count() and app.locator('.st-key-research_overview').count():
                    return app
            wake=page.get_by_role('button',name=re.compile('Yes, get this app back up',re.I))
            if wake.count(): wake.click()
            page.wait_for_timeout(1000)
        print('Waiting for single-page hosting release',version,flush=True)
        page.wait_for_timeout(5000)
    raise RuntimeError('Production did not load the expected single-page release')


def wait_page_ready(app,ticker,query=None):
    # A new chart can appear before the slower sections finish. Wait for the
    # real completed page, not a guessed sleep or an old section's DOM.
    app.wait_for_function("""([ticker,query]) => {
        const nodes=[...document.querySelectorAll('.workspace-ready')];
        const e=nodes.at(-1);
        return e && e.dataset.ticker===ticker
            && (query===null || e.dataset.search===query)
            && !e.closest('[data-stale="true"]');
    }""",arg=[ticker,query],timeout=120000)
    no_exception(app)


def select_manual_ticker(app,ticker):
    """Enter a ticker once through an open, focused, on-screen sidebar input.

    Responsive layout can leave sidebar controls mounted but outside the view.
    Locator.fill alone does not establish that a human can reach the control.
    """
    app.wait_for_function('''() => {
        const root=document.querySelector('[data-testid="stApp"]');
        return root?.getAttribute('data-test-script-state')==='notRunning'
            && root.getAttribute('data-test-connection-state')==='CONNECTED';
    }''',timeout=60000)
    sidebar=app.locator('[data-testid="stSidebar"]')
    if sidebar.get_attribute('aria-expanded')!='true':
        app.locator('[data-testid="stExpandSidebarButton"]').click()
    expect(sidebar).to_have_attribute('aria-expanded','true')
    field=sidebar.get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    field.scroll_into_view_if_needed()
    field.click()
    expect(field).to_be_focused()
    geometry=field.evaluate('''element=>{
        const r=element.getBoundingClientRect();
        return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,
            viewportWidth:window.innerWidth,viewportHeight:window.innerHeight,
            sidebarExpanded:element.closest('[data-testid="stSidebar"]').getAttribute('aria-expanded')};
    }''')
    assert (geometry['sidebarExpanded']=='true' and geometry['left']>=0 and geometry['top']>=0
            and geometry['right']<=geometry['viewportWidth'] and geometry['bottom']<=geometry['viewportHeight']), geometry
    field.fill(ticker)
    expect(field).to_have_value(ticker)
    expect(field).to_be_focused()
    field.press('Enter')
    return field


def chart_for_symbol(page,app,ticker):
    wait_page_ready(app,ticker)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        no_exception(app)
        for frame in page.frames:
            try:
                if frame.locator('#payload').count() and frame.locator('#chart canvas').count():
                    payload=frame.eval_on_selector('#payload','(el)=>JSON.parse(el.textContent)')
                    if payload.get('ticker')==ticker and not payload.get('demo') and len(payload.get('records',[]))>=60:
                        return frame,payload
            except Exception: pass
        page.wait_for_timeout(1000)
    raise RuntimeError('No real candlestick history rendered for '+ticker)


def verify_reused_company_rows(app,canonical_rows):
    """The 360-degree view must reuse the same Thai figures and explanations."""
    open_research_expander(app, 'เปิดกราฟและแผนซื้อขาย')
    expander=app.get_by_text('ตารางวิเคราะห์ 360°',exact=True).locator('xpath=ancestor::details[1]')
    table=expander.locator('.workspace-help-table')
    expect(table).to_have_count(1)
    if not table.is_visible():
        expander.locator('summary').first.click()
    expect(table).to_be_visible()
    reused=table.locator('tbody tr[data-company-metric]')
    keys={'debtToEquity','returnOnEquity','returnOnAssets','roic','grossMargins',
          'operatingMargins','profitMargins','currentRatio','interestCoverage',
          'revenue','grossProfit','ebit','netIncome','operatingCashflow','freeCashflow'}
    expect(reused).to_have_count(len(keys))
    expect(reused.locator('abbr[title][tabindex="0"]')).to_have_count(len(keys))
    actual=table.evaluate('''table=>{
        const headers=[...table.querySelectorAll('thead th')].map(e=>e.textContent.trim());
        return {headers,rows:[...table.querySelectorAll('tbody tr[data-company-metric]')].map(row=>({
            key:row.dataset.companyMetric,state:row.dataset.companyState,
            cells:Object.fromEntries([...row.querySelectorAll('td')].map((cell,i)=>[headers[i],cell.textContent.trim()])),
            label:[...row.querySelector('abbr').childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim(),
            help:row.querySelector('abbr').getAttribute('title')
        }))};
    }''')
    assert set(actual['headers'])=={'หมวด','ปัจจัย','ค่าล่าสุด','การแปลผล','เกณฑ์อ้างอิง','รอบข้อมูล'},actual['headers']
    assert {row['key'] for row in actual['rows']}==keys
    expected=canonical_rows.evaluate_all('''rows=>Object.fromEntries(rows.map(row=>{
        const abbr=row.querySelector('abbr'),cells=[...row.querySelectorAll('td')].map(e=>e.textContent.trim());
        return [row.dataset.metric,{state:row.dataset.state,
            group:row.closest('.company-analysis').querySelector('h4').textContent.trim(),
            label:[...abbr.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim(),
            help:abbr.getAttribute('title'),cells}];
    }))''')
    thai=re.compile(r'[\u0e00-\u0e7f]')
    for row in actual['rows']:
        canonical=expected[row['key']]
        cells=row['cells']
        assert row['state']==canonical['state'],row
        assert row['label']==canonical['label'] and thai.search(row['label']),row
        assert cells['หมวด']==canonical['group'] and thai.search(cells['หมวด']),row
        assert cells['ค่าล่าสุด']==canonical['cells'][0],row
        assert cells['การแปลผล']==canonical['cells'][2]+' — '+canonical['cells'][3],row
        assert cells['เกณฑ์อ้างอิง']==canonical['cells'][1],row
        assert cells['รอบข้อมูล']==canonical['cells'][4],row
        assert all(thai.search(cells[key]) for key in ('การแปลผล','เกณฑ์อ้างอิง','รอบข้อมูล')),row
        assert canonical['help'] in row['help'] and thai.search(row['help']),row
    return {'rows':len(keys),'thai_labels_and_help':True,'values_states_and_explanations_match':True}


def verify_fundamentals(app,ticker,*,is_fund=False,annual_periods=None):
    open_research_expander(app, 'เปิดรายละเอียดพื้นฐานและปันผล')
    from company_analysis_th import METRIC_ALIASES,STATEMENT_ALIASES
    section=app.locator('.st-key-research_fundamentals')
    groups=section.locator('.st-key-company_financial_analysis .company-analysis[data-ticker][data-group]')
    if is_fund:
        expect(groups).to_have_count(0)
        expect(section.locator('.company-analysis[data-statement]')).to_have_count(0)
        expect(app.locator('.st-key-research_technical tr[data-company-metric]')).to_have_count(0)
        expect(section.locator('.workspace-help-table').first).to_be_visible()
        return {'ticker':ticker,'fund_specific_table':True}
    expect(section.get_by_role('heading',name='วิเคราะห์ข้อมูลการเงินบริษัท',exact=True)).to_be_visible()
    expect(groups).to_have_count(9)
    expect(groups.filter(has=app.locator('table.company-table'))).to_have_count(9)
    assert groups.evaluate_all('(xs)=>xs.every(x=>x.dataset.ticker=== '+json.dumps(ticker)+')')
    rows=groups.locator('tbody tr[data-metric]')
    expect(rows).to_have_count(54)
    assert len(set(rows.evaluate_all('(xs)=>xs.map(x=>x.dataset.metric)')))==54
    expect(rows.locator('th abbr[title][tabindex="0"]')).to_have_count(54)
    expect(groups.locator('td [title], thead [title]')).to_have_count(0)
    expect(groups.locator('details.company-glossary')).to_have_count(9)
    thai=re.compile(r'[\u0e00-\u0e7f]')
    assert all(thai.search(label) for label in groups.locator('h4').all_text_contents())
    assert all(thai.search(label) for label in groups.locator('thead th').all_text_contents())
    assert all(thai.search(label) for label in groups.locator('.company-glossary summary').all_text_contents())
    for row in rows.all():
        expect(row.locator('td')).to_have_count(5)
        assert all(cell.strip() and cell.strip() not in ('None','nan','null') for cell in row.locator('td').all_text_contents())
        assert len(row.locator('abbr').get_attribute('title'))>25
        assert thai.search(row.locator('th').inner_text()), row.get_attribute('data-metric')
        alias=METRIC_ALIASES[row.get_attribute('data-metric')]
        label=row.locator('abbr').evaluate("e=>[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()")
        assert re.search(r'[A-Za-z]',alias) and label.endswith(' ('+alias+')') and label.count('('+alias+')')==1, label
        assert thai.search(row.locator('abbr').get_attribute('title')), row.get_attribute('data-metric')
        # The benchmark, interpretation and period must explain the figures
        # in Thai; raw values/currency codes and canonical keys stay intact.
        cells=row.locator('td').all_text_contents()
        assert all(thai.search(cells[i]) for i in (1,2,3,4)), (row.get_attribute('data-metric'),cells)
    expect(section.get_by_role('button',name='ดาวน์โหลดบทวิเคราะห์บริษัท',exact=True)).to_be_visible()
    reused_360=verify_reused_company_rows(app,rows)
    # AAPL/MSFT regression callers retain the default mandatory three statements.
    # Quality examples pass dates from their independently checked source bundle;
    # a missing source statement must not be fabricated to satisfy this gate.
    if annual_periods is not None:
        assert set(annual_periods) <= {'income','balance','cashflow'}, annual_periods
        expect(section.locator('.company-analysis[data-statement]')).to_have_count(sum(bool(v) for v in annual_periods.values()))
        if not any(annual_periods.values()):
            expect(section.get_by_text('งบการเงินย้อนหลัง — สูงสุด 4 ปีบัญชี',exact=True)).to_have_count(0)
    annual=[]
    for kind,title in [('income','งบกำไรขาดทุน'),('balance','งบฐานะการเงิน'),('cashflow','งบกระแสเงินสด')]:
        table=section.locator('.company-analysis[data-statement="'+kind+'"]')
        if annual_periods is not None and not annual_periods.get(kind):
            expect(table).to_have_count(0)
            if any(annual_periods.values()):
                expect(section.get_by_text(title+': ไม่มีข้อมูลรายงาน',exact=True)).to_be_visible()
            annual.append({'statement':kind,'state':'not_available_in_source','periods':[],'rows':0})
            continue
        expect(table).to_have_count(1)
        expect(table.get_by_role('heading',name=title,exact=True)).to_be_visible()
        columns=table.locator('thead th').all_text_contents()
        assert 2 <= len(columns) <= 5, (kind,columns)
        assert thai.search(columns[0]), (kind,columns)
        assert all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) for date in columns[1:]), (kind,columns)
        assert columns[1:]==sorted(set(columns[1:]),reverse=True), (kind,columns)
        if annual_periods is not None:
            assert columns[1:]==annual_periods[kind], (kind,columns,annual_periods[kind])
        # Every available annual statement retains its complete set of raw rows,
        # including the five fields restored in the Thai release.
        expected_rows={'income':10,'balance':9,'cashflow':6}[kind]
        expect(table.locator('tbody tr')).to_have_count(expected_rows)
        for row in table.locator('tbody tr').all():
            expect(row.locator('td')).to_have_count(len(columns)-1)
            assert thai.search(row.locator('th').inner_text()), row.inner_text()
            field=row.get_attribute('data-statement-field')
            metric={'capitalExpenditure':'capex','repurchaseOfCapitalStock':'buybacks','cashDividendsPaid':'dividendsPaid'}.get(field,field)
            alias=STATEMENT_ALIASES[metric]
            label=row.locator('abbr').evaluate("e=>[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()")
            assert re.search(r'[A-Za-z]',alias) and label.endswith(' ('+alias+')') and label.count('('+alias+')')==1, label
            assert thai.search(row.locator('abbr').get_attribute('title')), row.inner_text()
        required={'income':('interestExpense','pretaxIncome','taxProvision'),
                  'balance':('receivables','inventory'),'cashflow':()}[kind]
        for field in required:
            expect(table.locator('tr[data-statement-field="'+field+'"]')).to_have_count(1)
        annual.append({'statement':kind,'periods':columns[1:],'rows':table.locator('tbody tr').count()})
    return {'ticker':ticker,'groups':9,'metrics':54,'metric_only_help':True,
            'thai_labels_and_explanations':True,'bilingual_metric_labels':True,
            'annual_statements':annual,'reused_360':reused_360}


def verify_sections(app,ticker,*,is_fund=False):
    no_exception(app)
    for label in ('เปิดกราฟและแผนซื้อขาย','เปิดรายละเอียดพื้นฐานและปันผล',
                  'เปิดรายละเอียดความเสี่ยง','เปิดผลตอบแทนและความสัมพันธ์'):
        open_research_expander(app, label)
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('radiogroup')).to_have_count(0)
    for section,title in [('research_technical','กราฟและแผนซื้อ'),('research_fundamentals','พื้นฐานและปันผล'),('research_risk','ความเสี่ยง'),('research_comparison','เปรียบเทียบหลายตัว')]:
        expect(app.locator('.st-key-'+section).get_by_role('heading',name=title,exact=True)).to_be_visible(timeout=60000)
    expect(app.locator('.st-key-research_fundamentals').get_by_role('heading',name=re.compile('ประวัติปันผล'))).to_be_visible(timeout=60000)
    verify_fundamentals(app,ticker,is_fund=is_fund)
    expect(app.locator('.st-key-research_risk [data-testid="stPlotlyChart"]')).to_have_count(2,timeout=60000)
    expect(app.locator('.st-key-research_comparison [data-testid="stPlotlyChart"]')).to_have_count(1,timeout=120000)
    expect(app.locator('.st-key-research_comparison').get_by_role('heading',name='Correlation ของผลตอบแทนรายวัน')).to_be_visible(timeout=30000)
    from clean_ui_smoke import verify_clean_presentation
    verify_clean_presentation(app)
    no_exception(app)


def click_filtered_stock(page,app,ticker,*,row_selector=False):
    query=app.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)
    query.fill(ticker);query.press('Enter')
    wait_page_ready(app,app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True).input_value(),ticker)
    expect(app.get_by_text('หุ้นในผลค้นหา: '+ticker,exact=True)).to_be_visible(timeout=30000)
    page.wait_for_timeout(1000)
    # Glide draws into a canvas but receives real pointer events on its scroller.
    # Target that surface, not the underlying canvas, and keep clear of the header.
    surface=app.locator('.st-key-stock_picker_table .dvn-scroller').first
    expect(surface).to_be_visible()
    surface.evaluate('(el)=>el.scrollIntoView({block:"center",inline:"nearest"})')
    page.wait_for_timeout(300)
    surface.click(position={'x':16 if row_selector else 180,'y':54})
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)).to_have_value(ticker,timeout=30000)
    expect(app.get_by_role('heading',name=re.compile('^'+re.escape(ticker)+r' ·'))).to_be_visible(timeout=30000)
    return chart_for_symbol(page,app,ticker)


def run():
    version=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
    report={'url':URL,'expected_version':version,'layout':'single-page','views':[],'chart':False,'selections':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        javascript_errors=[]
        page.on('pageerror',lambda e:(javascript_errors.append(str(e)),print('JAVASCRIPT_ERROR:',str(e)[:1000],flush=True)))
        try:
            app=wait_for_release(page,version)
            app.locator('.workspace-ready[data-generation^="generations/"]').wait_for(state='attached',timeout=120000)
            app.get_by_text(re.compile('พร้อมใช้งาน · ตรวจชุดข้อมูลใหม่|กำลังอ่านข้อมูลที่เลือก')).first.wait_for(timeout=30000)
            chart,payload=chart_for_symbol(page,app,'AAPL')
            from volume_split_smoke import verify_volume_split
            report['volume_split']=verify_volume_split(page,chart,payload)
            chart.locator('#rsi').click();chart.locator('#macd').click()
            page.wait_for_timeout(1000)
            if chart.locator('#error').is_visible(): raise RuntimeError('Candlestick JavaScript error')
            verify_sections(app,'AAPL')
            report['company_analysis']=[verify_fundamentals(app,'AAPL')]
            print('VERIFIED_INITIAL_SINGLE_PAGE: AAPL; all research sections',flush=True)
            from chart_commentary_smoke import verify_chart_commentary
            report['chart_commentary']=verify_chart_commentary(page,app,payload,screenshot=True)
            report.update(chart=True,chart_bars=len(payload['records']),chart_last_bar=payload.get('lastBar'),deployed_version=version,views=list(VIEWS))
            for ticker,row_selector in [('MSFT',False),('AAPL',True)]:
                chart,payload=click_filtered_stock(page,app,ticker,row_selector=row_selector)
                verify_sections(app,ticker)
                report['company_analysis'].append(verify_fundamentals(app,ticker))
                report['selections'].append({'ticker':ticker,'via':'row' if row_selector else 'cell','bars':len(payload['records'])})
                print('VERIFIED_STOCK_SELECTION:',ticker,flush=True)
            from research_workspace_smoke import verify_research_features
            report['research_improvements']=verify_research_features(page,app,'AAPL')
            field=select_manual_ticker(app,'SPY')
            chart,payload=chart_for_symbol(page,app,'SPY')
            verify_sections(app,'SPY',is_fund=True)
            expect(app.locator('.st-key-research_comparison').get_by_text('QQQ',exact=True).first).to_be_visible()
            report['selections'].append({'ticker':'SPY','via':'manual','bars':len(payload['records'])})
            from enhanced_smoke import verify_enhancements
            report['enhancements']=verify_enhancements(page,app)
            report['javascript_errors']=javascript_errors
            if javascript_errors:raise RuntimeError('Browser JavaScript errors: '+str(javascript_errors[:5]))
            report['result']='passed'
            print('BROWSER_SMOKE_REPORT:',json.dumps(report,ensure_ascii=False),flush=True)
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as f:
                    f.write('### Single-page browser verification — see target URL\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')
        except Exception:
            diagnose(page)
            raise
        finally:
            browser.close()


if __name__=='__main__': run()
