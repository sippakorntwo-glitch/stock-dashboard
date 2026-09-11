"""One-time guarded patch of the exact reviewed v19 source; removed before merge."""
from pathlib import Path
import ast
import re


def replace(path, old, new):
    p=Path(path);source=p.read_text(encoding='utf-8')
    if source.count(old)!=1:
        raise RuntimeError(f'{path}: expected one anchor, got {source.count(old)}: {old[:100]!r}')
    p.write_text(source.replace(old,new),encoding='utf-8')

replace('analytics.py','METRIC_VERSION = 1','METRIC_VERSION = 2')
replace('analytics.py','    return out\n\n\ndef comparison(',
        '    from return_periods import table_returns\n    out.update(table_returns(history))\n    return out\n\n\ndef comparison(')
replace('dashboard_runtime.py',"EXTRA_NUMERIC = ['Return_1D','Return_1M','Return_3M','Return_6M','Volatility_20D','Dollar_Volume_20D','Drawdown_52W','ATR_Pct','Metric_Calc_Version']",
        "from return_periods import RETURN_FIELDS\nEXTRA_NUMERIC = list(dict.fromkeys([*RETURN_FIELDS,'Return_3M','Volatility_20D','Dollar_Volume_20D','Drawdown_52W','ATR_Pct','Metric_Calc_Version']))")
# A six-calendar-year request supplies an actual starting close for a full 5Y return.
p=Path('dashboard_core.py');s=p.read_text(encoding='utf-8');tree=ast.parse(s)
assignments=[node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HISTORY_YEARS' for t in node.targets)]
assert len(assignments)==1 and ast.literal_eval(assignments[0].value)==5
node=assignments[0];lines=s.splitlines(keepends=True)
lines[node.lineno-1:node.end_lineno]=['HISTORY_YEARS = 6  # One-year buffer for full calendar 5Y returns.\n']
p.write_text(''.join(lines),encoding='utf-8')
# Use an explicit start date for custom history lengths; avoid provider range enums.
replace('dashboard_core.py','        return {"period": f"{max(years, int(meta.get(\'years\', 0)))}y"}',
        '        depth = max(years, int(meta.get("years", 0)))\n        return {"start": (pd.Timestamp.now(tz="America/New_York").normalize() - pd.DateOffset(years=depth)).strftime("%Y-%m-%d"), "_full_window": True}')
# The private marker is stripped before the provider call and preserves full-refresh semantics.
replace('dashboard_core.py','        kwargs = dict(key)\n        try:',
        '        kwargs = dict(key)\n        full_window = bool(kwargs.pop("_full_window", False)) or "period" in kwargs\n        try:')
replace('dashboard_core.py','                    if adjusted and "start" in kwargs:',
        '                    if adjusted and not full_window:')
replace('dashboard_core.py','                    elif "period" in kwargs:',
        '                    elif full_window:')
replace('dashboard_core.py','stamp if "period" in kwargs or adjusted else meta.get(',
        'stamp if full_window or adjusted else meta.get(')
replace('dashboard_core.py','stats["incremental" if "start" in kwargs and not adjusted else "initial"]',
        'stats["incremental" if not full_window and not adjusted else "initial"]')
replace('dashboard_views.py','from chart_ranges import PAGE_SIZE, page_slice, render_chart',
        'from chart_ranges import PAGE_SIZE, page_slice, render_chart\nfrom return_periods import (RETURN_FIELDS, RETURN_LABELS, RETURN_CAPTION, TABLE_FIELDS,\n                            return_column_config, export_watchlist)')
replace('dashboard_views.py',"'ผลตอบแทน 1 ปีขั้นต่ำ (%)'","'Minimum 1 Year Return (%)'")
replace('dashboard_views.py',"sort = x.selectbox('เรียงตาม',['Ticker','Historical_Return','Return_3M','Return_2Y','Return_3Y','RSI_14','ATR_Pct','Volatility_20D','Dollar_Volume_20D'])",
        "sort = x.selectbox('เรียงตาม',['Ticker',*RETURN_FIELDS,'RSI_14','ATR_Pct','Volatility_20D','Dollar_Volume_20D'],format_func=lambda key: RETURN_LABELS.get(key,key))")
replace('dashboard_views.py',"    fields = ['Ticker','Security_Name','Industry','Asset_Type','Status','Close','Return_1D','Return_3M','Historical_Return','Return_2Y','Return_3Y','RSI_14','ATR_Pct','Volatility_20D','Dollar_Volume_20D','Price_AsOf','Data_Status']",
        '    fields = list(TABLE_FIELDS)')
replace('dashboard_views.py',"subset=['Return_1D','Return_3M','Historical_Return','Return_2Y','Return_3Y']",'subset=list(RETURN_FIELDS)')
replace('dashboard_views.py',"    for field,label in {'Return_1D':'1D (%)','Return_3M':'3M (%)','ATR_Pct':'ATR / ราคา (%)','Volatility_20D':'Volatility 20D ต่อปี (%)'}.items():",
        "    for field,label in {'ATR_Pct':'ATR / ราคา (%)','Volatility_20D':'Volatility 20D ต่อปี (%)'}.items():")
replace('dashboard_views.py','    config = column_help(fields,config)',
        '    config.update(return_column_config())\n    config = column_help(fields,config)')
replace('dashboard_views.py',"    st.download_button('ดาวน์โหลดผลกรองครบทุกแถว',work.to_csv(index=False).encode('utf-8-sig'),'filtered_watchlist.csv','text/csv')",
        "    st.caption(RETURN_CAPTION)\n    st.download_button('ดาวน์โหลดผลกรองครบทุกแถว',export_watchlist(work).to_csv(index=False).encode('utf-8-sig'),'filtered_watchlist.csv','text/csv')")
replace('data_quality.py',"BARS_REQUIRED = {'Close':1,'Return_1D':2,", "BARS_REQUIRED = {'Close':1,'Return_1D':2,'Return_3D':4,'Return_7D':8,")
replace('data_quality.py',"'Return_2Y':24,'Return_3Y':36}","'Return_2Y':24,'Return_3Y':36,'Return_5Y':60}")
replace('dashboard_help.py','def field_help(name):\n    name=str(name)',
        'def field_help(name):\n    from return_periods import return_help\n    tip=return_help(name)\n    if tip is not None:return tip\n    name=str(name)')
replace('update_data.py','        summary = {"schema": SCHEMA,',
        '        from return_periods import RETURN_FIELDS\n        coverage["return_periods"] = {field: sum(app.number(r.get(field)) is not None for r in quotes.values()) for field in RETURN_FIELDS}\n        summary = {"schema": SCHEMA,')
# Existing tests now use the shared migration version/depth instead of frozen v19 constants.
replace('tests/test_analytics.py',"row['Metric_Calc_Version']==1","row['Metric_Calc_Version']==runtime.METRIC_VERSION")
replace('tests/test_analytics.py',"'2026-09-10T00:00:00Z',years=5)","'2026-09-10T00:00:00Z',years=runtime.HISTORY_YEARS)")
p=Path('tests/test_analytics.py');s=p.read_text();old='"History_Years_Loaded": 5'
assert s.count(old)==2;p.write_text(s.replace(old,'"History_Years_Loaded": runtime.HISTORY_YEARS'))
replace('workspace_boot.py',"'quality_views', 'chart_inspector')","'quality_views', 'chart_inspector', 'return_periods')")
for path in ['app.py','dashboard_runtime.py']:
    p=Path(path);s=p.read_text(encoding='utf-8');assert '2026-09-11.19' in s
    p.write_text(s.replace('2026-09-11.19','2026-09-12.20'),encoding='utf-8')
print('Guarded return-period integration completed; run tests before committing.')
