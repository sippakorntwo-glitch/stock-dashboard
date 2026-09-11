"""One-time guarded integration; run on the feature branch, then remove before merge."""
from pathlib import Path
import ast

def edit(path,old,new,count=1):
    p=Path(path);s=p.read_text(encoding='utf-8')
    if s.count(old)!=count:raise RuntimeError(f'{path}: expected {count} anchors, got {s.count(old)}: {old[:90]}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('app.py','2026-09-12.21','2026-09-12.22',2)
edit('dashboard_runtime.py','2026-09-12.21','2026-09-12.22')
# The numeric merge intentionally does not carry nested audit records. Preserve
# them explicitly, only from the same eligible saved quote used by the table.
edit('dashboard_runtime.py','    return indexed.reset_index(), outside', '''    if rows:
        observations = {}
        for t in incoming.index[eligible]:
            source = (saved or {}).get(t, {})
            if (core.number(source.get('Metric_Calc_Version')) == METRIC_VERSION
                    and isinstance(source.get('Return_Observations'), dict)):
                observations[t] = source['Return_Observations']
        indexed['Return_Observations'] = pd.Series(observations, dtype=object)
    return indexed.reset_index(), outside''')
# A cached partial daily candle must not become complete just because wall time
# advanced since acquisition. Cap snapshot calculations at the acquisition date.
edit('dashboard_runtime.py','    row = base_snapshot(ticker, history, stamp)', '''    history = core.completed_daily_history(history, now=stamp)
    row = base_snapshot(ticker, history, stamp)''')
p=Path('dashboard_ui.py');s=p.read_text();start=s.index("    st.markdown('''<style>");end=s.index('unsafe_allow_html=True)',start)+len('unsafe_allow_html=True)')
s=s[:start]+"    from workspace_theme import apply_theme\n    apply_theme()"+s[end:];p.write_text(s)
edit('dashboard_ui.py',"        st.title('Stock Research Workspace')", "        st.title('Stock Research Workspace')\n        from workspace_theme import navigation\n        navigation()")
edit('dashboard_ui.py','        render_symbol_quality(ticker,cache,history,info)', '        from live_quote_ui import render_live_quote\n        render_live_quote(ticker)\n        render_symbol_quality(ticker,cache,history,info)')
for old,anchor in [('พื้นฐานและปันผล','fundamentals'),('ความเสี่ยง','risk'),('เปรียบเทียบหลายตัว','comparison')]:
    edit('dashboard_ui.py',f"st.header('{old}')",f"st.header('{old}',anchor='{anchor}')")
# Chart-only updates redraw their own fragment instead of rebuilding 9,876 rows.
edit('dashboard_ui.py'," or chart_state['revision'] != rendered_chart_revision",'')
edit('chart_ranges.py','def render_chart(ticker,daily_history):','@st.fragment(run_every=60)\ndef render_chart(ticker,daily_history):')
edit('chart_ranges.py',"ttl=900 if kind=='5m' else 86400","ttl=60 if kind=='5m' else 86400")
edit('chart_ranges.py','>=60:return', '>=120:return')
edit('chart_ranges.py','60 คำขอกราฟต่อชั่วโมง','120 คำขอกราฟต่อชั่วโมง')
edit('chart_ranges.py','แคชอย่างน้อย 15 นาที ไม่ใช่ราคาสตรีมสด','ตรวจใหม่ประมาณทุก 1 นาที; แท่งยังเป็น 5 นาที และผู้ให้ข้อมูลอาจล่าช้า ไม่ใช่ราคาสตรีมสด')
edit('chart_ranges.py','One provider request at a time, 60/hour/server','One provider request at a time, 120/hour/server')
edit('workspace_boot.py',"'return_periods')","'return_periods', 'workspace_theme', 'live_quotes', 'live_quote_ui')") if "'return_periods')" in Path('workspace_boot.py').read_text() else None
# Ensure all newly added application modules participate in coherent reload.
p=Path('workspace_boot.py');s=p.read_text();tree=ast.parse(s)
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_MODULES' for t in node.targets):
        names=tuple(ast.literal_eval(node.value));names=tuple(dict.fromkeys((*names,'workspace_theme','live_quotes','live_quote_ui')))
        lines=s.splitlines(True);lines[node.lineno-1:node.end_lineno]=['_MODULES = '+repr(names)+'\n'];s=''.join(lines);break
p.write_text(s)
# Recheck test isolation; tests are never allowed to call the quote provider.
edit('tests/conftest.py','    import json\n    from datetime',"    monkeypatch.setenv('DASHBOARD_ALLOW_MINUTE_QUOTES','false')\n    import json\n    from datetime")
# The expanded controls must not accidentally include empty/unknown trend states.
edit('filters_ui.py',"['ไม่มีข้อมูล' if status=='Insufficient Data' else status]","['ไม่มีข้อมูล','ข้อมูลไม่พอ','INSUFFICIENT'] if status=='Insufficient Data' else [status]") if "['ไม่มีข้อมูล' if status=='Insufficient Data' else status]" in Path('filters_ui.py').read_text() else None
# Stable numeric dimensions and units are unchanged; no cosmetic changes to scores.
p=Path('.streamlit/config.toml');s=p.read_text();p.write_text('''[theme]
base = "dark"
primaryColor = "#6cddf5"
backgroundColor = "#090f1e"
secondaryBackgroundColor = "#14223a"
textColor = "#eaf2ff"
font = "sans serif"

[server]
headless = true
''')
Path('work').mkdir(exist_ok=True)
# Document source hooks used for the independent completeness review.
import dashboard_core as core, inspect
Path('work/source-audit.txt').write_text(inspect.getsource(core._fetch_dividends)+ '\n'+inspect.getsource(core.asset_directory_rows)+ '\n'+inspect.getsource(core.summary_is_current),encoding='utf-8')
print('Guarded integration complete; compile and test before publishing this source.')
