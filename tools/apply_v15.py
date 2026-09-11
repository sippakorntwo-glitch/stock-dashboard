"""One-time hash-guarded migration. Removed before the final feature commit."""
from pathlib import Path
import hashlib


def change(path,old,new,count=1):
    p=Path(path);text=p.read_text(encoding='utf-8')
    found=text.count(old)
    if found!=count:raise ValueError(f'{path}: expected {count}, found {found}: {old[:70]}')
    p.write_text(text.replace(old,new),encoding='utf-8')

expected={'dashboard_core.py':'fce2e6982109f85bd0af296c47effb09e41d141d','dashboard_views.py':'4ffe5c8d72172d0f3fc6a418da5fcdb037307460','dashboard_ui.py':'da1957ee2e9db35018a8292c5c891df454de57b1','dashboard_runtime.py':'0265126a24e09dab4c4af5347e6f68c26070866c'}
for path,sha in expected.items():
    data=Path(path).read_bytes()
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha,path
for path in ['app.py','dashboard_runtime.py']:
    text=Path(path).read_text(encoding='utf-8');assert '2026-09-11.14' in text
    Path(path).write_text(text.replace('2026-09-11.14','2026-09-11.15'),encoding='utf-8')
change('dashboard_core.py','import yfinance as yf','import yfinance as yf\nfrom dashboard_help import help_table')
change('dashboard_core.py','PERIODS = ["1 วัน", "5 วัน", "7 วัน", "1 เดือน", "3 เดือน", "6 เดือน", "1 ปี", "2 ปี", "3 ปี"]','PERIODS = ["1 วัน", "3 วัน", "5 วัน", "7 วัน", "1 เดือน", "3 เดือน", "6 เดือน", "1 ปี", "2 ปี", "3 ปี", "5 ปี", "10 ปี"]')
change('dashboard_core.py','if period in ["1 วัน", "5 วัน", "7 วัน"]:','if period in ["1 วัน", "3 วัน", "5 วัน", "7 วัน"]:')
change('dashboard_core.py','minBarSpacing:2,','minBarSpacing:.05,')
change('dashboard_core.py','if(currentRange)chart.timeScale().setVisibleLogicalRange(currentRange);else reset();',"chart.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r){el('chart').dataset.rangeFrom=String(r.from);el('chart').dataset.rangeTo=String(r.to);}});\n if(currentRange)chart.timeScale().setVisibleLogicalRange(currentRange);else reset();")
change('dashboard_core.py',"new ResizeObserver(()=>{if(chart){chart.resize(el('chart').clientWidth,Math.max(350,el('chartwrap').clientHeight));paneLabels();}})","new ResizeObserver(()=>{if(chart){const r=chart.timeScale().getVisibleLogicalRange();chart.resize(el('chart').clientWidth,Math.max(350,el('chartwrap').clientHeight));if(r)chart.timeScale().setVisibleLogicalRange(r);paneLabels();}})")
p=Path('dashboard_core.py');text=p.read_text(encoding='utf-8')
start=text.index('def render_decision(');end=text.index('\ndef width_options(',start)
part=text[start:end];assert part.count('st.dataframe(')==2
text=text[:start]+part.replace('st.dataframe(','help_table(')+text[end:];p.write_text(text,encoding='utf-8')
change('dashboard_core.py','        a.dataframe(displayed,hide_index=True,**width_options(st.dataframe),height=300)','        with a:\n            help_table(displayed,height=300)')
change('dashboard_core.py','        b.dataframe(yearly.rename(columns={"Year":"ปี","Total":"รวมต่อหน่วย","Payments":"จำนวนครั้ง"}),hide_index=True,**width_options(st.dataframe),height=300)','        with b:\n            help_table(yearly.rename(columns={"Year":"ปี","Total":"รวมต่อหน่วย","Payments":"จำนวนครั้ง"}),height=300)')
change('dashboard_views.py','from dashboard_selection import table_key, apply_table_selection','from dashboard_selection import table_key, apply_table_selection\nfrom dashboard_help import help_table, column_help\nfrom chart_ranges import PAGE_SIZE, page_slice, render_chart')
change('dashboard_views.py','    st.dataframe(frame, hide_index=True, **a.width_options(st.dataframe), **kwargs)','    return help_table(frame, **kwargs)')
change('dashboard_views.py','math.ceil(len(work)/100)','math.ceil(len(work)/PAGE_SIZE)')
change('dashboard_views.py','หน้าตาราง — หน้าละ 100 ตัว','หน้าตาราง — หน้าละ 500 ตัว')
change('dashboard_views.py','work.iloc[(page-1)*100:page*100].reindex(columns=fields)','page_slice(work,page).reindex(columns=fields)')
change('dashboard_views.py','    options = {}',"    config = column_help(fields,config)\n    st.caption(f'แสดง {len(shown):,} ตัวในหน้านี้ · หน้า {page:,} / {pages:,}')\n    options = {}")
p=Path('dashboard_views.py');text=p.read_text(encoding='utf-8')
start=text.index('    periods=',text.index('def technical('));end=text.index('    # Daily criteria',start)
text=text[:start]+'    render_chart(ticker,daily_history)\n'+text[end:]
old="st.dataframe(result['correlation'].style.format('{:.2f}',na_rep='—'),**a.width_options(st.dataframe))"
assert text.count(old)==1
text=text.replace(old,"help_table(result['correlation'].style.format('{:.2f}',na_rep='—'),hide_index=False,correlation=True)")
p.write_text(text,encoding='utf-8')
change('dashboard_ui.py','from dashboard_selection import set_selected','from dashboard_selection import set_selected\nfrom chart_ranges import get_chart_service')
change('dashboard_ui.py','def _poll_data(reader, rendered_revision, rendered_worker_revision):','def _poll_data(reader, rendered_revision, rendered_worker_revision, rendered_chart_revision=0):')
change('dashboard_ui.py',"    worker = a.get_updater().state()\n    if state['revision'] != rendered_revision or worker['revision'] != rendered_worker_revision:","    worker = a.get_updater().state()\n    chart_state = get_chart_service().state()\n    if state['revision'] != rendered_revision or worker['revision'] != rendered_worker_revision or chart_state['revision'] != rendered_chart_revision:")
change('dashboard_ui.py',"    if state['busy'] or worker['busy']:","    if state['busy'] or worker['busy'] or chart_state['busy']:")
change('dashboard_ui.py',"    worker_revision=a.get_updater().state()['revision']","    worker_revision=a.get_updater().state()['revision']\n    chart_revision=get_chart_service().state()['revision']")
change('dashboard_ui.py','    _poll_data(reader,revision,worker_revision)','    _poll_data(reader,revision,worker_revision,chart_revision)')
change('workspace_boot.py',"'dashboard_core', 'data_sync', 'github_store', 'analytics')","'dashboard_core', 'data_sync', 'github_store', 'analytics',\n            'dashboard_help', 'chart_ranges', 'dashboard_selection')")
change('production_smoke.py',"            report['result']='passed'","            from enhanced_smoke import verify_enhancements\n            report['enhancements']=verify_enhancements(page,app)\n            report['result']='passed'")
change('production_smoke.py',"app.locator('.st-key-research_fundamentals [data-testid=\"stDataFrame\"]').first","app.locator('.st-key-research_fundamentals .workspace-help-table').first")
p=Path('README.md');text=p.read_text(encoding='utf-8')
text+='''\n## v15: 500 แถว, Tooltip และช่วงกราฟเพิ่มเติม\n\nตารางแสดงหน้าละ 500 ตัว รักษาตัวกรอง การเรียง และการเลือกหุ้นแบบหน้าเดียว ชี้หัวคอลัมน์เพื่อดูคำอธิบาย; ตารางเกณฑ์/พื้นฐาน/วิเคราะห์/สถานะมี ⓘ ที่ชื่อแต่ละแถว พร้อมคำอธิบายที่กดอ่านบนมือถือได้ ไม่เปลี่ยนสูตรหรือคะแนนเดิม\n\nกราฟเพิ่ม 1 วัน, 3 วัน, 5 ปี, 10 ปี และคงช่วงเดิม: วัน = วันซื้อขายล่าสุดที่มีข้อมูล ใช้แท่ง 5 นาทีในเวลาตลาดปกติ; เดือน/ปี = แท่งรายวัน ไม่ใช่แท่งละ 3 วัน แสดงช่วงจริงและคำเตือนเมื่อประวัติไม่ครบ ไม่สร้างข้อมูลให้หุ้นที่อายุน้อยกว่า 10 ปี\n\nเลือกช่วงสั้น/ยาวพิเศษอาจดึง Yahoo เฉพาะหุ้นนั้นจากเซิร์ฟเวอร์ Streamlit: แคชอย่างน้อย 15 นาทีสำหรับ intraday และ 24 ชั่วโมงสำหรับระยะยาว คิวไม่เกิน 8 และไม่เกิน 60 คำขอต่อชั่วโมงต่อเซิร์ฟเวอร์ พักเมื่อผู้ให้ข้อมูลจำกัดคำขอ ไม่ใช่ราคาสตรีมสด การโหลดล้มเหลวคงข้อมูลเดิม ประวัติกราฟพิเศษแยกจากการให้คะแนนและไม่เผยแพร่กลับ GitHub ค่า DASHBOARD_ALLOW_LIVE_UPDATES ยังไม่ถูกเปิด ปิดคำขอกราฟเพิ่มเติมได้ด้วย DASHBOARD_ALLOW_CHART_REQUESTS=false ใน Streamlit Secrets ค่าเริ่มต้น true เพื่อรองรับช่วงที่ขอ\n\nกราฟรักษาช่วงเวลาเมื่อปรับขนาดหน้าจอ และแสดง 10 ปีได้โดยไม่ติดข้อจำกัดความกว้างขั้นต่ำต่อแท่ง\n'''
p.write_text(text,encoding='utf-8')
print('APPLIED_V15_WITH_HASH_GUARDS')
