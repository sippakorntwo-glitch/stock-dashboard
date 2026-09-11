"""One-time guarded source assembly on the feature branch, never on production."""
from pathlib import Path
import ast,json

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one anchor {old[:100]!r}, found {s.count(old)}')
    p.write_text(s.replace(old,new),encoding='utf-8')

def replace_function(path,name,new):
    p=Path(path);s=p.read_text();tree=ast.parse(s)
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(nodes)!=1:raise RuntimeError('Ambiguous function '+name)
    n=nodes[0];lines=s.splitlines(keepends=True)
    p.write_text(''.join(lines[:n.lineno-1])+new+'\n'+''.join(lines[n.end_lineno:]),encoding='utf-8')

# Fetch only fixed, official directory URLs. Data is serialized JSON, never executable code.
from investigate_returns import official_etfs
registry=official_etfs()
Path('etf_directory.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')

edit('dashboard_runtime.py','import dashboard_core as core','import dashboard_core as core\nfrom catalog_extension import install as install_catalog\ninstall_catalog(core)')
edit('dashboard_runtime.py',"APP_VERSION = '2026-09-12.20'","APP_VERSION = '2026-09-12.21'")
edit('app.py','2026-09-12.20','2026-09-12.21')
edit('analytics.py','METRIC_VERSION = 2','METRIC_VERSION = 3')
edit('analytics.py','    from return_periods import table_returns\n    out.update(table_returns(history))',
     "    from return_periods import table_returns, return_observations\n    out.update(table_returns(history))\n    out['Return_Observations'] = return_observations(history)")
edit('workspace_boot.py',"'chart_inspector', 'return_periods')", "'chart_inspector', 'return_periods', 'catalog_extension', 'screening', 'filters_ui', 'return_audit_ui')")
replace_function('dashboard_views.py','filter_universe',"def filter_universe(frame):\n    from filters_ui import filter_universe as advanced_filter\n    return advanced_filter(frame)\n")
edit('dashboard_views.py','    config.update(return_column_config())',
     "    from return_periods import EXPORT_LABELS\n    mode = work.attrs.get('return_mode', 'Cumulative (Adjusted Close)')\n    for field,label in EXPORT_LABELS.items():\n        if field in config and isinstance(config[field],dict):\n            config[field] = {**config[field], 'label':label}\n        elif field in fields:\n            config[field] = st.column_config.Column(label)\n    config.update(return_column_config(mode))")
edit('dashboard_views.py','def technical(ticker,daily_history,info,row):\n    render_chart(ticker,daily_history)',
     'def technical(ticker,daily_history,info,row):\n    from return_audit_ui import render_return_audit\n    render_return_audit(ticker,daily_history,row)\n    render_chart(ticker,daily_history)')
edit('dashboard_ui.py','    frame,outside=a.build_universe_frame(original,cache.quotes(),cache.classifications())',
     "    frame,outside=a.build_universe_frame(original,cache.quotes(),cache.classifications())\n    from screening import enrich_frame\n    profiles,_=cache.get('remote:screener',request_remote=False)\n    frame=enrich_frame(frame,profiles or {})")
edit('dashboard_ui.py','        render_family_counts(cache)',
     "        render_family_counts(cache)\n        etfs=int(frame.Asset_Type.eq('ETF').sum())\n        st.caption(f'Catalog: {len(frame)-etfs:,} stocks + {etfs:,} ETFs. ETF directory: {a.ETF_DIRECTORY_AS_OF or \"legacy\"}. Listing coverage is not data coverage; missing records are prepared in bounded batches.')\n        if a.ETF_DIRECTORY_CONFLICTS:\n            st.caption(f'{len(a.ETF_DIRECTORY_CONFLICTS)} symbol-type conflicts retained for review; no automatic stock reclassification.')")
edit('data_sync.py','    cache.put("remote:quality", summary.get("quality", {}), {"fetched_at": utc_now()})',
     '    cache.put("remote:quality", summary.get("quality", {}), {"fetched_at": utc_now()})\n    cache.put("remote:screener", summary.get("screener", {}), {"fetched_at": utc_now()})')
edit('update_data.py','    quality = make_quality(cache, universe, etfs=app.ETF_NAMES)',
     '    quality = make_quality(cache, universe, etfs=app.ETF_NAMES)\n    from screening import profile_rows\n    from catalog_extension import fingerprint\n    screener = profile_rows(cache, universe)')
edit('update_data.py','"universe": list(universe), "watchlist_csv": watchlist_csv, "quality": quality}',
     '"universe": list(universe), "watchlist_csv": watchlist_csv, "quality": quality, "screener": screener}')
edit('update_data.py','"catalog_as_of": app.CATALOG_AS_OF, "app_version": app.APP_VERSION}',
     '"catalog_as_of": app.CATALOG_AS_OF, "app_version": app.APP_VERSION,\n                    "catalog_fingerprint": fingerprint(universe), "etf_directory_as_of": app.ETF_DIRECTORY_AS_OF}')
edit('update_data.py','    if args.mode == "bootstrap" and previous:',
     '    from catalog_extension import fingerprint\n    same_catalog = previous and previous.get("catalog_fingerprint") == fingerprint(app.select_universe())\n    if args.mode == "bootstrap" and previous and same_catalog:')

# Correct the diagnostic to compare the same observed end date, never an incomplete cached candle.
edit('investigate_returns.py',"old=period_observation(daily_closes(h),sessions=sessions,months=months) if h is not None else {}",
     "old=period_observation(daily_closes(h.loc[h.index.tz_localize(None).normalize()<=end]),sessions=sessions,months=months) if h is not None else {}")

# Update only the return-contract tests changed by the specified behavior.
edit('tests/test_return_periods.py','TABLE_FIELDS[6:14]','TABLE_FIELDS[7:15]')
edit('tests/test_return_periods.py',"'cumulative return (%)' in return_help(field)","'cumulative adjusted return' in return_help(field)")
edit('tests/test_return_periods.py','    window=f.loc[f.index>=cutoff]\n    assert r[\'start\']==str(window.index[0].date())\n    assert r[\'value\']==pytest.approx((f.Close.iloc[-1]/window.Close.iloc[0]-1)*100)',
     "    window=f.loc[f.index<=cutoff]\n    assert r['start']==str(window.index[-1].date())\n    assert r['value']==pytest.approx((f.Close.iloc[-1]/window.Close.iloc[-1]-1)*100)")
edit('tests/test_return_periods.py','pytest.approx((120/105-1)*100)','pytest.approx((120/100-1)*100)')
edit('tests/test_return_periods.py','out.columns[6:14]','out.columns[7:15]')
edit('tests/test_return_periods.py',"row['Metric_Calc_Version']==a.METRIC_VERSION==2","row['Metric_Calc_Version']==a.METRIC_VERSION==3")

# Browser selectors intentionally follow the English label contract, with no lowered assertions.
for p in [*Path('.').glob('*smoke.py'),*Path('tests').glob('*.py')]:
    s=p.read_text()
    s=s.replace('ค้นหา Ticker / บริษัท / อุตสาหกรรม','Search Ticker / Company / Industry')
    p.write_text(s,encoding='utf-8')

# Print remaining fixed-size test/verification assumptions for explicit review.
for p in [*Path('tests').glob('*.py'),*Path('.').glob('*smoke.py')]:
    for line_no,line in enumerate(p.read_text().splitlines(),1):
        if any(x in line for x in ['4900','4,900','700','6:14','7:15','1 Year Return','ประเภท','ทั้งหมด','สถานะ']):
            print('CONTRACT_REVIEW:',str(p),line_no,line,flush=True)
print('ASSEMBLED_OFFICIAL_DIRECTORY:',json.dumps({'etfs':len(registry['funds']),'asof':registry['fetched_at'],'QQQI':registry['funds']['QQQI']},ensure_ascii=False),flush=True)
