"""Guarded one-time integration. No changes to return formulas or trading scores."""
from pathlib import Path
import ast


def edit(path,old,new,count=1):
    p=Path(path);s=p.read_text(encoding='utf-8')
    if s.count(old)!=count:raise RuntimeError(f'{path}: expected {count} anchors, got {s.count(old)}: {old[:80]}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('app.py','2026-09-12.24','2026-09-12.25',2)
edit('dashboard_runtime.py','2026-09-12.24','2026-09-12.25')
edit('dashboard_runtime.py',"('history:1d:', 'info:', 'dividends:')","('history:1d:', 'info:', 'dividends:', 'reference:')")
edit('update_data.py','("history:1d:", "info:", "dividends:")','("history:1d:", "info:", "dividends:", "reference:")')
edit('dashboard_views.py',"    analysis,metrics,_=a.build_analysis(ctx.get('metrics',{}),row,info)","    analysis,metrics,_=a.build_analysis(ctx.get('metrics',{}),row,info)\n    from asset_semantics import adapt_analysis\n    analysis=adapt_analysis(analysis,ticker,info,is_etf)")
edit('dashboard_views.py',"    etf=a.asset_is_etf(ticker,row,info)\n    fields=", "    etf=a.asset_is_etf(ticker,row,info)\n    from reference_ui import render_references\n    from asset_semantics import field_state,display_value\n    render_references(ticker,info,etf,a.get_data_cache())\n    fields=")
edit('dashboard_views.py',"('Beta 3Y จากแหล่งข้อมูล','beta3Year',False)]","('Beta 3Y จากแหล่งข้อมูล','beta3Year',False),('Portfolio P/E','trailingPE',False)]")
edit('dashboard_views.py',"        records.append({'มิติ':label,'ค่า':value,'หน่วย': '%' if pct else profile_unit(info,key),'สถานะข้อมูล':profile_field_state(info,key),'ฟิลด์ต้นทาง':key})", "        state=field_state(ticker,info,key,is_etf=etf)\n        if state!='available':value=display_value(ticker,info,key,is_etf=etf,percent=pct)\n        records.append({'มิติ':label,'ค่า':value,'หน่วย': '%' if pct else profile_unit(info,key),'สถานะข้อมูล':state,'ฟิลด์ต้นทาง':key})")
edit('dashboard_help.py','HELP={alias:description for aliases,description in _DEFINITIONS for alias in aliases.split(\'|\')}', '''HELP={alias:description for aliases,description in _DEFINITIONS for alias in aliases.split('|')}
HELP.update({
    'Portfolio P/E':'Reported valuation of the underlying equity holdings, not corporate earnings per fund unit. Not applicable to physical gold, bond or currency funds. Not reported is different from N/A.',
    'Portfolio Trailing P/E':'Holdings-level trailing valuation reported by the fund data provider, not corporate earnings per ETF unit. Definitions can differ between providers.',
    'Portfolio Forward P/E':'Forward valuation of underlying equity holdings if reported. It is not a forecast of earnings per ETF unit.',
    'Beta (3Y, provider)':'Three-year beta reported by the fund data provider; not a guarantee of future sensitivity.'})''')
# Include new modules in coherent on-host version reloads.
p=Path('workspace_boot.py');s=p.read_text();tree=ast.parse(s)
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_MODULES' for t in node.targets):
        names=tuple(dict.fromkeys((*ast.literal_eval(node.value),'asset_semantics','sec_reference','reference_ui')))
        lines=s.splitlines(True);lines[node.lineno-1:node.end_lineno]=['_MODULES = '+repr(names)+'\n'];s=''.join(lines);break
p.write_text(s)
# A dropdown can close while a full-page render finishes. Retry the interaction
# only when the actual selection was not applied; never inject session state.
p=Path('screener_smoke.py');s=p.read_text();start=s.index('def choose(');end=s.index('\ndef snapshot_image(',start)
s=s[:start]+'''def choose(app,label,value,multi=False):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    testid='stMultiSelect' if multi else 'stSelectbox'
    widget=app.locator('[data-testid="'+testid+'"]').filter(has=app.get_by_text(label,exact=True)).first
    for attempt in range(3):
        existing=app.evaluate("""([label,value])=>{
            const e=document.querySelector('.export-ready');if(!e)return false;
            const actual=JSON.parse(e.dataset.controls)[label];
            return Array.isArray(actual)?actual.includes(value):actual===value;
        }""",[label,value])
        if existing:return
        widget.scroll_into_view_if_needed()
        control=widget.get_by_role('combobox').first
        control.click()
        if multi:widget.locator('input').first.fill(value)
        try:
            app.get_by_role('option',name=value,exact=True).click(timeout=15000)
            if multi:control.press('Escape')
            wait_applied(app,label,value)
            return
        except BrowserTimeout:
            if attempt==2:raise
            control.press('Escape')

''' + s[end:];p.write_text(s)
# Backend audit must tolerate malformed provider objects without hiding them.
edit('asset_data_audit.py',"missing_accounts=[t for t in universe if t not in etfs and any(not present(profiles.get('info:'+t,({},{}))[0].get(f)) for f in ('operatingCashflow','freeCashflow','totalCash'))]", "missing_accounts=[t for t in universe if t not in etfs and any(not present((profiles.get('info:'+t,({},{}))[0] if isinstance(profiles.get('info:'+t,({},{}))[0],dict) else {}).get(f)) for f in ('operatingCashflow','freeCashflow','totalCash'))]")
# Expand real-browser checks after the ordinary clean-screen assertions.
edit('enhanced_smoke.py',"    report['advanced_screener_and_ui']=verify_screener(page,app)","    report['advanced_screener_and_ui']=verify_screener(page,app)\n    from asset_reference_smoke import verify_asset_reference\n    report['asset_aware_sources']=verify_asset_reference(page,app)")
Path('maintenance/apply_asset_data_v25.py').unlink()
print('Integrated asset-specific fields, independent references and robust real dropdown interactions.')
