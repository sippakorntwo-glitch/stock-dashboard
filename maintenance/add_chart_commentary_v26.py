"""Guarded one-time integration on the owner-requested feature branch."""
from pathlib import Path


def edit(path,old,new,count=1):
    p=Path(path);s=p.read_text(encoding='utf-8')
    if s.count(old)!=count:raise RuntimeError(f'{path}: reviewed anchor changed ({s.count(old)} vs {count})')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('app.py','2026-09-12.25','2026-09-12.26',2)
edit('dashboard_runtime.py','2026-09-12.25','2026-09-12.26')
edit('workspace_boot.py',"'reference_ui')","'reference_ui', 'chart_commentary')")
anchor='        else:components.html(html,height=900,scrolling=False)'
edit('chart_ranges.py',anchor,anchor+'\n        from chart_commentary import commentary_html\n        st.markdown(commentary_html(payload),unsafe_allow_html=True)')
# Keep equality distinct from below-average activity in the visible sentence.
edit('chart_commentary.py',"else 'ต่ำกว่าค่าเฉลี่ย' if data['volume_ratio']==1 else 'ต่ำกว่าค่าเฉลี่ย'","else 'ต่ำกว่าค่าเฉลี่ย' if data['volume_ratio']<1 else 'เท่าค่าเฉลี่ย'")
edit('production_smoke.py',"            report.update(chart=True,chart_bars=", "            from chart_commentary_smoke import verify_chart_commentary\n            report['chart_commentary']=verify_chart_commentary(page,app,payload,screenshot=True)\n            report.update(chart=True,chart_bars=")
anchor='        frame,payload=wait_range(page,app,period);page.wait_for_timeout(500)'
edit('enhanced_smoke.py',anchor,anchor+"\n        from chart_commentary_smoke import verify_chart_commentary\n        report.setdefault('chart_commentary',[]).append(verify_chart_commentary(page,app,payload))")
Path(__file__).unlink()
print('Installed commentary with no changes to market-data calls, chart controls or trading scores.')
