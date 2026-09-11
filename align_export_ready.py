"""One-time ordering fix: a completed filter calculation is not yet a rendered CSV."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one reviewed anchor, got {s.count(old)}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('filters_ui.py',"    encoded=html.escape(json.dumps(applied,ensure_ascii=False),quote=True)","    work.attrs['applied_filters']=applied\n    encoded=html.escape(json.dumps(applied,ensure_ascii=False),quote=True)")
edit('dashboard_views.py',"'filtered_watchlist.csv','text/csv',on_click='ignore')\n    return work",''' 'filtered_watchlist.csv','text/csv',on_click='ignore')
    import html, json
    receipt=html.escape(json.dumps(work.attrs.get('applied_filters',{}),ensure_ascii=False),quote=True)
    # The marker is emitted AFTER the CSV button for this exact rendered result.
    st.markdown(f'<span class="export-ready" data-controls="{receipt}" data-count="{len(work)}"></span>',unsafe_allow_html=True)
    return work''')
p=Path('screener_smoke.py');s=p.read_text();old="document.querySelector('.screener-ready')";assert s.count(old)==2;p.write_text(s.replace(old,"document.querySelector('.export-ready')"))
p=Path('tests/test_applied_filters.py');s=p.read_text();s=s.replace('def test_combined_controls_report_only_the_completed_filter_state():','def test_combined_controls_report_only_the_completed_filter_state(tmp_path,monkeypatch):');s=s.replace('    from streamlit.testing.v1 import AppTest\n    script=',"    from streamlit.testing.v1 import AppTest\n    import dashboard_runtime as a\n    cache=a.DashboardCache(tmp_path/'applied-ui.sqlite3')\n    monkeypatch.setattr(a,'get_data_cache',lambda:cache)\n    script=");s=s.replace('from filters_ui import filter_universe\nf=', 'from filters_ui import filter_universe\nfrom dashboard_views import overview\nf=');s=s.replace('if r is not None:st.dataframe(r)','if r is not None:overview(f,prepared=r)');s=s.replace("    assert applied(at)['Asset Type']=='ETF'", "    receipt=next(m.value for m in at.markdown if 'class=\"export-ready\"' in m.value)\n    exported=json.loads(html.unescape(re.search(r'data-controls=\"([^\"]*)\"',receipt).group(1)))\n    assert exported==applied(at)\n    assert applied(at)['Asset Type']=='ETF'");p.write_text(s)
Path('align_export_ready.py').unlink(missing_ok=True)
