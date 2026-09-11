"""Reviewed one-time corrections; removed before production deployment."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one anchor {old[:100]!r}, got {s.count(old)}')
    p.write_text(s.replace(old,new))

edit('quality_smoke.py',"        total=int(row['ทั้งหมดที่ใช้ฟิลด์นี้'])\n        assert total==sum", "        field_total=int(row['ทั้งหมดที่ใช้ฟิลด์นี้'])\n        assert field_total==sum")
edit('chart_ranges.py',"    kind='5m' if short else 'long';message=''", "    kind='5m' if short else 'long';message=''\n    st.session_state.pop('_chart_first_load_waiting',None)")
edit('chart_ranges.py',"        if need:\n            if chart_requests_enabled():message=service.request(ticker,kind)", "        if need:\n            if chart_requests_enabled():\n                first_load=history is None or (long and extra is None and not covers_years(history,int(period.split()[0])))\n                if first_load:st.session_state['_chart_first_load_waiting']=ticker\n                message=service.request(ticker,kind)")
p=Path('chart_ranges.py');s=p.read_text();s += '''

def first_chart_load_finished(state, current_revision, rendered_revision):
    """Wake once for an awaited chart, never for routine minute refreshes."""
    waiting=state.get('_chart_first_load_waiting')
    return bool(waiting and waiting==state.get('selected_ticker')
                and current_revision!=rendered_revision)
''';p.write_text(s)
edit('dashboard_ui.py',"    chart_state = get_chart_service().state()\n    if state['revision']", "    chart_state = get_chart_service().state()\n    from chart_ranges import first_chart_load_finished\n    if first_chart_load_finished(st.session_state,chart_state['revision'],rendered_chart_revision):\n        st.session_state.pop('_chart_first_load_waiting',None)\n        st.rerun()\n    if state['revision']")
edit('dashboard_ui.py',"{etfs:,} ETFs. ETF directory:","{etfs:,} ETF / ETP entries. Directory:")
edit('dashboard_ui.py',"Listing coverage is not data coverage; missing records are prepared in bounded batches.'", "The Nasdaq ETF flag can include ETNs; check each product name. Listing coverage is not data coverage; missing records are prepared in bounded batches.'")
edit('data_sync.py','อ่านชุดข้อมูลที่เตรียมไว้ — ไม่ต้องสแกน 4,900 ตัวบนหน้าเว็บ','อ่านชุดข้อมูลที่เตรียมไว้ — ไม่ต้องสแกนทั้งทะเบียนบนหน้าเว็บ')
edit('ranking_job.py','Not a fresh quote scan of all 4,900 symbols.','Not a fresh quote scan of every catalog member.')
edit('production_smoke.py','def diagnose(page):\n    for frame',"def diagnose(page):\n    try:\n        Path('work').mkdir(exist_ok=True)\n        page.screenshot(path='work/browser-failure.png',full_page=False)\n    except Exception as exc:\n        print('SCREENSHOT_DIAGNOSTIC_ERROR:',type(exc).__name__,flush=True)\n    for frame")
edit('screener_smoke.py',"    app.get_by_role('heading',name='Stock Research Workspace',exact=True).scroll_into_view_if_needed()", "    exp.click()  # Show the normal compact controls in the responsive screenshots.\n    app.get_by_role('heading',name='Stock Research Workspace',exact=True).scroll_into_view_if_needed()")
edit('screener_smoke.py',"    page.set_viewport_size({'width':1440,'height':1000})\n    controls.get_by_role", "    page.set_viewport_size({'width':1440,'height':1000})\n    exp.click()\n    controls.get_by_role")
p=Path('RELEASE_NOTES_V22.md');s=p.read_text().replace('5,676 ETFs / 9,876 total members','5,676 ETF/ETP directory entries / 9,876 total members').replace('All-catalog daily histories and weekly profiles','All-catalog daily histories and incrementally refreshed profiles');s += '\nThe Nasdaq ETF flag also includes exchange-traded notes; these are identified in their security names and are not legally the same as investment funds. First-time chart requests wake the page as soon as the background load finishes, while routine intraday refreshes remain confined to the chart fragment.\n';p.write_text(s)
Path('polish_workspace.py').unlink()
print('Applied source and verifier corrections without weakening the assertions or request ceilings.')
