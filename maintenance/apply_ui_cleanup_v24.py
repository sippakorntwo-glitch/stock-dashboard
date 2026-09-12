"""One-time guarded UI migration, allowed only on the owner's feature branch."""
from pathlib import Path
import os

if os.environ.get('GITHUB_REF') != 'refs/heads/feat/industry-dropdown-clean-ui-v24':
    raise RuntimeError('This migration is only allowed on the isolated UI branch')


def edit(file, old, new, count=1):
    p=Path(file);s=p.read_text(encoding='utf-8')
    if s.count(old)!=count:
        raise RuntimeError(f'{file}: expected {count} exact source anchors, got {s.count(old)}')
    p.write_text(s.replace(old,new),encoding='utf-8')

for file in ('filters_ui.py','production_smoke.py','screener_smoke.py','ranking_smoke.py','enhanced_smoke.py','return_table_smoke.py'):
    p=Path(file);s=p.read_text()
    if 'Search Ticker / Company / Industry' not in s:raise RuntimeError(file+': search label changed')
    p.write_text(s.replace('Search Ticker / Company / Industry','Search Ticker / Company'))
edit('filters_ui.py',"    query=st.text_input('Search Ticker / Company',key='stock_search', help='Exact ticker matches take priority. Use name:MSFT to find every fund or company name containing MSFT.').strip()\n    mode=st.selectbox('Return Display',RETURN_MODES,key='screen_return_mode',", """    # Keep this dropdown outside Advanced Filters and preserve its existing key.
    options=categorical_values(frame,'Industry')
    key='screen_cat_Industry'
    if key in st.session_state:
        valid=[v for v in st.session_state[key] if v in options]
        if valid!=st.session_state[key]:st.session_state[key]=valid
    industry=st.multiselect('Industry / ETF Category',options,key=key,
        placeholder='All industries / ETF categories',
        help='Select one or more industries or ETF categories. Empty means all. Choices come from the published catalog, not guessed labels.')
    search_box,return_box=st.columns([3,2])
    query=search_box.text_input('Search Ticker / Company',key='stock_search', help='Exact ticker matches take priority. Use name:MSFT to find every fund or company name containing MSFT.').strip()
    mode=return_box.selectbox('Return Display',RETURN_MODES,key='screen_return_mode',""")
edit('filters_ui.py','    categories={};bounds={};required=[]',"    categories={'Industry':industry};bounds={};required=[]")
edit('filters_ui.py','for i,(field,label) in enumerate(CATEGORIES.items()):',"for i,(field,label) in enumerate((item for item in CATEGORIES.items() if item[0]!='Industry')):")
# Hide only presentation columns. Original rows still supply indicator definitions.
edit('dashboard_help.py',"LABEL_COLUMNS=('เกณฑ์','ปัจจัย','มิติ','ข้อมูล','ช่วงคะแนน')", "LABEL_COLUMNS=('เกณฑ์','ปัจจัย','มิติ','ข้อมูล','ช่วงคะแนน')\nPRESENTATION_ONLY_HIDDEN_COLUMNS=frozenset(('ข้อมูลอ้างอิง','แหล่งข้อมูล','ฟิลด์ต้นทาง','สถานะข้อมูล'))")
edit('dashboard_help.py',"    tooltip_column = list(frame.columns).index(label) if label else -1\n    headers=''.join(cell('th',col) for col in frame.columns)","    columns=[col for col in frame.columns if col not in PRESENTATION_ONLY_HIDDEN_COLUMNS]\n    tooltip_column = columns.index(label) if label in columns else -1\n    headers=''.join(cell('th',col) for col in columns)")
edit('dashboard_help.py',"for col in frame.columns)+'</tr>')","for col in columns)+'</tr>')")
edit('dashboard_views.py',"'เปรียบเทียบหลายตัว','สถานะข้อมูล']","'เปรียบเทียบหลายตัว']")
edit('dashboard_views.py','ตารางวิเคราะห์ 360° และแหล่งข้อมูล','ตารางวิเคราะห์ 360°')
edit('dashboard_ui.py','industry_summary, technical, fundamentals, risk, compare, health)', 'industry_summary, technical, fundamentals, risk, compare)')
edit('dashboard_ui.py','from quality_views import render_family_counts, render_symbol_quality\n','')
edit('dashboard_ui.py',' → สถานะข้อมูล','')
edit('dashboard_ui.py','        render_family_counts(cache)\n','')
edit('dashboard_ui.py','        render_symbol_quality(ticker,cache,history,info)\n','')
edit('dashboard_ui.py',"    with st.container(key='research_health'):\n        health(reader,frame,cache)\n",'')
edit('dashboard_ui.py','        if error: st.warning(error)',"        if error: st.warning(error)\n        if cache.error: st.warning('Local cache มีข้อผิดพลาด: '+cache.error)")
edit('dashboard_ui.py','time.monotonic()-render_started),unsafe_allow_html=True)',"time.monotonic()-render_started,\n                            generation=(reader.status().get('manifest') or {}).get('generation','') if reader else ''),unsafe_allow_html=True)")
edit('ui_stability.py','def page_receipt(version: str, ticker: str, query: str, elapsed: float) -> str:',"def page_receipt(version: str, ticker: str, query: str, elapsed: float, *, generation: str = '') -> str:")
edit('ui_stability.py',"f'data-render-seconds=\"{elapsed:.3f}\"></span>')", "f'data-render-seconds=\"{elapsed:.3f}\" '\n            f'data-generation=\"{html.escape(str(generation), quote=True)}\"></span>')")
edit('workspace_theme.py','<a href="#system-status">สถานะระบบ</a>','')
edit('production_smoke.py',"'เปรียบเทียบหลายตัว','สถานะข้อมูล']","'เปรียบเทียบหลายตัว']")
edit('production_smoke.py',"    expect(app.locator('.st-key-research_health').get_by_role('heading',name='สถานะข้อมูลและระบบ')).to_be_visible()", "    from clean_ui_smoke import verify_clean_presentation\n    verify_clean_presentation(app)")
edit('production_smoke.py',"            app.get_by_text(re.compile(r'generations/')).first.wait_for(timeout=120000)","            app.locator('.workspace-ready[data-generation^=\"generations/\"]').wait_for(state='attached',timeout=120000)")
edit('tests/test_ui.py',"        assert 'สถานะข้อมูลและระบบ' in [h.value for h in at.subheader]","        assert 'สถานะข้อมูลและระบบ' not in [h.value for h in at.subheader]\n        assert 'รายงานความครบของข้อมูลทุกส่วน' not in [h.value for h in at.subheader]\n        assert not any(e.label.startswith('ตรวจข้อมูลที่ขาดของ ') for e in at.expander)\n        assert not at.json")
edit('screener_smoke.py',"    choose(app,'Asset Type','ETF')\n    category=", "    exp.click()\n    from clean_ui_smoke import verify_industry_placement\n    verify_industry_placement(app)\n    choose(app,'Asset Type','ETF')\n    category=")
edit('screener_smoke.py',"    choose(app,'Return Periods to Filter','1 Month (%)',multi=True)","    exp.click()\n    choose(app,'Return Periods to Filter','1 Month (%)',multi=True)")
edit('screener_smoke.py',"    report['result']='passed'", "    from clean_ui_smoke import verify_clean_presentation\n    report['clean_presentation']=verify_clean_presentation(app)\n    report['top_level_industry_dropdown']=True\n    report['result']='passed'")
p=Path('quality_smoke.py');s=p.read_text();start=s.index('def verify_quality(')
s=s[:start]+'''def verify_quality(page,app):
    """Audit backend quality data; the public diagnostic panels are intentionally absent."""
    from production_smoke import no_exception,chart_for_symbol,wait_page_ready
    from clean_ui_smoke import verify_clean_presentation
    manifest,summary=public_summary()
    quality=summary.get('quality',{})
    assert quality.get('version')==1, 'Published backend quality report must remain available'
    assert set(quality['symbols'])==set(summary['universe'])
    total=len(summary['universe'])
    etfs=sum(v['asset_type']=='ETF' for v in quality['symbols'].values())
    stocks=total-etfs
    assert total==quality['counts']['universe'] and stocks==4200 and etfs>=700
    assert len(quality['columns'])>50
    assert all(sum(v.values())==(etfs if field.startswith('etf.') else stocks if field.startswith('stock.') else total)
               for field,v in quality['columns'].items())
    report={'backend_field_report':True,'backend_symbol_report':True,'source_verified':True,
            'source_generation':manifest['generation'],'counts':quality['counts'],
            'public_diagnostics_removed':verify_clean_presentation(app)}
    app.get_by_role('radiogroup',name='ช่วงเวลาแสดงกราฟ').get_by_text('1 ปี',exact=True).click()
    inspected=[]
    ticker_input=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    for ticker in ('AEON','AESP','SPY'):
        ticker_input.fill(ticker);ticker_input.press('Enter')
        wait_page_ready(app,ticker=ticker)
        if ticker!='AESP':chart_for_symbol(page,app,ticker)
        assert app.locator('.st-key-research_fundamentals .workspace-help-table').count()>=1
        values=app.locator('.st-key-research_fundamentals .workspace-help-table td').all_text_contents()
        assert not any(v.strip() in ('None','nan','null') for v in values)
        verify_clean_presentation(app)
        no_exception(app)
        inspected.append({'ticker':ticker,'industry_state':quality['symbols'][ticker]['industry_state'],
                          'dividend_state':quality['symbols'][ticker]['dividend_state'],
                          'history_bars':quality['symbols'][ticker]['history']['bars']})
    report['examples']=inspected
    return report
''';p.write_text(s)
for file in ('app.py','dashboard_runtime.py'):
    p=Path(file);s=p.read_text()
    if '2026-09-12.23' not in s:raise RuntimeError('Unexpected release version in '+file)
    p.write_text(s.replace('2026-09-12.23','2026-09-12.24'))
Path(__file__).unlink()
print('UI-only migration applied. Compile, test and verify the browser before publishing.')
