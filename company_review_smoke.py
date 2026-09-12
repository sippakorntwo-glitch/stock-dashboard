"""Browser reads actual stored financials. No state injection or synthetic prices."""
from __future__ import annotations
import gzip
import hashlib
import json
import math
from pathlib import Path
from playwright.sync_api import expect
from quality_smoke import public_summary,fetch_public,read_download,REPO


def source_objects(ticker,manifest):
    slot=str(int(hashlib.sha256(ticker.encode()).hexdigest()[:8],16)%128)
    record=manifest['details'][slot];generation=manifest['generation'].split('/')[1]
    raw=fetch_public(f'https://github.com/{REPO}/releases/download/dashboard-data-{generation}/details--{slot}.jsonl.gz')
    assert hashlib.sha256(raw).hexdigest()==record['sha256']
    output={}
    for line in gzip.decompress(raw).splitlines():
        symbol,key,value,meta=json.loads(line)
        if symbol==ticker:output[key]=(value,meta)
    return output


def verify_company_review(page,app):
    from production_smoke import wait_for_release,wait_page_ready,chart_for_symbol,no_exception
    import re
    version=re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)",Path('dashboard_runtime.py').read_text()).group(1)
    # The preceding stability test reloads twice, invalidating the old hosted iframe.
    app=wait_for_release(page,version)
    wait_page_ready(app,'AAPL')
    sidebar=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    report={'symbols':[],'independent_calculations':[]}
    manifest,_=public_summary()
    for ticker in ('AAPL','MSFT'):
        if sidebar.input_value()!=ticker:
            sidebar.fill(ticker);sidebar.press('Enter');wait_page_ready(app,ticker)
        card=app.locator('.company-review')
        expect(card).to_have_count(1)
        expect(card).to_have_attribute('data-ticker',ticker)
        observations={};by_label={}
        for row in card.locator('tr[data-metric]').all():
            key=row.get_attribute('data-metric');observations[key]=json.loads(row.get_attribute('data-observation'))
            by_label[row.locator('td').first.inner_text().split('ⓘ')[0].strip()]=observations[key]
            tooltip=row.locator('abbr[title]')
            expect(tooltip).to_have_count(1)
            assert len(tooltip.get_attribute('title'))>100
            assert row.locator('td:not(:first-child) abbr').count()==0
        assert len(observations)>=55
        assert all(k in observations for k in ('roe','roa','roic','de','gross_profit','ebit','ebitda','net_income','price_book','current_ratio','fcf'))
        objects=source_objects(ticker,manifest)
        reference=objects.get('reference:'+ticker,({},{}))[0]
        annual=reference.get('financial_statements',{}).get('annual',[])
        assert annual,'Verified filed statements must be actually published for the sample company'
        period=annual[0];values=period['values'];opening=period.get('opening',{})
        def check(key,expected):
            row=observations[key]
            assert row['status']=='available' and math.isclose(row['value'],expected,rel_tol=1e-8,abs_tol=1e-7),(ticker,key,row,expected)
            assert period['end'] in row['basis']
            report['independent_calculations'].append({'ticker':ticker,'metric':key,'value':row['value'],'period':period['end']})
        if values.get('revenue',0)>0 and 'net_income' in values:
            check('net_margin',values['net_income']/values['revenue']*100)
        if values.get('equity',0)>0 and opening.get('equity',0)>0 and 'net_income' in values:
            check('roe',values['net_income']/((opening['equity']+values['equity'])/2)*100)
        if 'ocf' in values and 'capex' in values:check('fcf',values['ocf']-values['capex'])
        if 'pretax_income' in values and values.get('interest_expense',-1)>=0:check('ebit',values['pretax_income']+values['interest_expense'])
        if observations['roic']['status']=='available':
            d=lambda v:v['debt_current']+v['debt_long']+v['debt_short']
            capital=(values['equity']+d(values)-values['cash']+opening['equity']+d(opening)-opening['cash'])/2
            nopat=values['operating_income']*(1-values['tax_expense']/values['pretax_income'])
            check('roic',nopat/capital*100)
            assert observations['roic']['grade']=='Compare with WACC'
        rows=read_download(page,app.get_by_role('button',name='Download Company Financial Review',exact=True))
        assert len(rows)==len(observations)
        assert all('Definition' in r and r['Definition'] for r in rows)
        for row in rows:
            metric=by_label[row['Metric']]
            if metric['value'] is None:assert not row['Value']
            else:assert math.isclose(float(row['Value']),metric['value'],rel_tol=1e-8,abs_tol=1e-7)
        assert card.locator('[data-financial-group]').count()>=8
        report['symbols'].append({'ticker':ticker,'metrics':len(observations),'csv_matches':True,'metric_only_tooltips':True})
        no_exception(app)
    sidebar.fill('AAAU');sidebar.press('Enter');wait_page_ready(app,'AAAU')
    expect(app.locator('.company-review')).to_have_count(0)
    report['fund_company_ratios_not_mixed']=True
    sidebar.fill('AAPL');sidebar.press('Enter');wait_page_ready(app,'AAPL')
    app.get_by_role('heading',name='Company Financial Review',exact=True).scroll_into_view_if_needed()
    Path('work').mkdir(exist_ok=True)
    page.screenshot(path='work/company-financial-review.png',full_page=False)
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(1000)
    dimensions=app.locator('body').evaluate('(e)=>({width:e.clientWidth,scroll:e.scrollWidth})')
    assert dimensions['scroll']<=dimensions['width']+4
    page.screenshot(path='work/company-financial-mobile.png',full_page=False)
    page.set_viewport_size({'width':1440,'height':1000})
    report['mobile_dimensions']=dimensions;report['result']='passed'
    return report
