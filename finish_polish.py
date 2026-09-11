"""Final guarded fixes from the full regression review; feature branch only."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if old not in s and new in s:return
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one reviewed anchor {old!r}')
    p.write_text(s.replace(old,new))

edit('chart_ranges.py','>=120:return','>=60:return')
edit('chart_ranges.py','120 คำขอกราฟต่อชั่วโมง','60 คำขอกราฟต่อชั่วโมง')
edit('chart_ranges.py','One provider request at a time, 120/hour/server','One provider request at a time, 60/hour/server')
edit('chart_ranges.py','def render_chart(ticker,daily_history):\n    period=',"def render_chart(ticker,daily_history):\n    if st.session_state.get('selected_ticker',ticker) != ticker:\n        return\n    period=")
edit('ranking_board.py',"def queue_selection(row):\n    st.session_state['_ranking_pending']", "def queue_selection(row):\n    set_selected(st.session_state,row['ticker'],reset_table=True)\n    st.session_state['_ranking_pending']")
edit('dashboard_views.py',"st.subheader('สถานะข้อมูลและระบบ')","st.subheader('สถานะข้อมูลและระบบ',anchor='system-status')")
edit('live_quote_ui.py', 'data-bar-time="{html.escape(value[\'bar_time\'])}"', 'data-bar-time="{html.escape(value[\'bar_time\'])}" data-fetched-at="{html.escape(value[\'fetched_at\'])}"')
print('Restored 60/hour chart ceiling, synchronized selections, and added observable fetch timestamps.')
