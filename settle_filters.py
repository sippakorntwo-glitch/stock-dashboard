"""Final consistency checks for applied-filter exports and paced metadata freshness."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one anchor {old[:100]!r}; got {s.count(old)}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('filters_ui.py','import pandas as pd','import html\nimport json\nimport pandas as pd')
edit('filters_ui.py',"    work.attrs['return_mode']=mode",'''    work.attrs['return_mode']=mode
    applied={'Asset Type':asset,'Trend Status':status,'Return Display':mode,
             'Search Ticker / Company / Industry':query,
             'Return Periods to Filter':[labels_for_mode(mode)[f] for f in periods]}
    applied.update({label:categories.get(field,[]) for field,label in CATEGORIES.items()})
    for field,(lower,upper) in bounds.items():
        label=labels_for_mode(mode).get(field,METRICS.get(field,field))
        applied['Minimum '+label]=lower
        applied['Maximum '+label]=upper
    encoded=html.escape(json.dumps(applied,ensure_ascii=False),quote=True)
    description=html.escape(f'Applied: {asset} · {len(work):,} results · {mode}')
    st.markdown(f'<output class="screener-ready" data-controls="{encoded}" data-count="{len(work)}">{description}</output>',unsafe_allow_html=True)''')
edit('dashboard_views.py',"'filtered_watchlist.csv','text/csv')","'filtered_watchlist.csv','text/csv',on_click='ignore')")
edit('screener_smoke.py','def choose(app,label,value,multi=False):', '''def wait_applied(app,label,value):
    app.wait_for_function("""([label,value]) => {
        const e=document.querySelector('.screener-ready');
        if(!e) return false;
        const actual=JSON.parse(e.dataset.controls)[label];
        return Array.isArray(actual) ? actual.includes(value) : actual===value;
    }""",arg=[label,value],timeout=60000)


def reset_controls(app):
    app.locator('.st-key-overview_controls').get_by_role('button',name='Reset Filters',exact=True).click()
    app.wait_for_function("""() => {
        const e=document.querySelector('.screener-ready');
        if(!e) return false;
        const s=JSON.parse(e.dataset.controls);
        return s['Asset Type']==='All' && s['Return Display']==='Cumulative (Adjusted Close)'
            && s['Search Ticker / Company / Industry']===''
            && Object.values(s).filter(Array.isArray).every(v=>v.length===0)
            && !Object.keys(s).some(k=>k.startsWith('Minimum ')||k.startsWith('Maximum '));
    }""",timeout=60000)


def choose(app,label,value,multi=False):''')
edit('screener_smoke.py',"    if multi:control.press('Escape')", "    if multi:control.press('Escape')\n    wait_applied(app,label,value)")
p=Path('screener_smoke.py');s=p.read_text();needle="controls.get_by_role('button',name='Reset Filters',exact=True).click()";assert s.count(needle)==5;s=s.replace(needle,'reset_controls(app)');p.write_text(s)
edit('screener_smoke.py',"    minimum.fill('0');minimum.press('Enter')", "    minimum.fill('0');minimum.press('Enter')\n    wait_applied(app,'Minimum 1 Month (%)',0)")
edit('screener_smoke.py',"    search.fill('AAPL');search.press('Enter')", "    search.fill('AAPL');search.press('Enter')\n    wait_applied(app,'Search Ticker / Company / Industry','AAPL')")
edit('screener_smoke.py',"    assert all(r['Asset Type']=='ETF' and r['Industry / ETF Category']==category for r in selected)", "    assert all(r['Asset Type']=='ETF' and r['Industry / ETF Category']==category for r in selected), {'selected_rows':len(selected),'bad_rows':[r['Ticker'] for r in selected if r['Asset Type']!='ETF' or r['Industry / ETF Category']!=category][:10]}")
edit('live_quote_ui.py','เวลาเริ่มแท่ง 1 นาที: ','เวลาข้อมูลราคา 1 นาที: ')
edit('data_quality.py',"status=missing_metric(field,row,shape);count('price.'+field,status)","status=missing_metric(field,row,shape)\n            if status=='pending' and missing_state(objects,'history',t)=='failed':status='failed'\n            count('price.'+field,status)")
edit('data_quality.py','    result=[]\n    while any(groups.values()):', '''    # Missing work first, then oldest observations within each fair asset/kind queue.
    # Partial-label retries must not starve stale profiles at the end of the catalog.
    for key,queue in groups.items():
        groups[key]=deque(sorted(queue,key=lambda job:(
            job[0]+':'+job[1] in metadata,
            timestamp(metadata.get(job[0]+':'+job[1],{}).get('fetched_at')))))
    result=[]
    while any(groups.values()):''')
p=Path('workspace_theme.py');s=p.read_text();s=s.replace('.workspace-nav {', '.screener-ready { display:block; margin:.5rem 0; padding:.6rem .8rem; border-left:3px solid #70e4bd; border-radius:6px; background:#122c35; color:#c9f2e5; font-size:.8rem; }\n.workspace-nav {',1);p.write_text(s)
p=Path('RELEASE_NOTES_V22.md');s=p.read_text();s+='\nApplied filter receipts expose the exact completed filter state and result count. CSV export uses that displayed result without triggering an unrelated page rerun. Browser checks wait for the actual applied state before downloading, not for a guessed sleep interval. Metadata queues retain stock/ETF and profile/dividend fairness while prioritizing missing and then oldest observations.\n';p.write_text(s)
Path('settle_filters.py').unlink(missing_ok=True)
