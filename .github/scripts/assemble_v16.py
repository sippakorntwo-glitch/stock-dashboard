"""One-time, blob-hash-guarded edits on the user's dedicated feature branch."""
from pathlib import Path
import hashlib
import json

EXPECTED={
 'chart_ranges.py':'94992782fd2869de070ee62db6ce6a4d3c517c40',
 'dashboard_help.py':'da0b54cf017d9d89adfe3eb4f943b45da5c209ff',
 'app.py':'5d49f2e47a38668e0dcc2fb7991a0ce4d7f1daad',
 'dashboard_runtime.py':'2b5b8f6fb034945310754729c4e21b5e2ac8d217',
 'workspace_boot.py':'baebcef20939bf7f4f84864f170536305eeedfd7',
 'enhanced_smoke.py':'929cd72c192697c5bdba4026b7b682baae05ede0',
 'README.md':'f9b35ba8a8f161485185fca88d51aec560a99ab2',
}
texts={}
for name,sha in EXPECTED.items():
    b=Path(name).read_bytes()
    actual=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    if actual!=sha:raise RuntimeError('Source changed, refusing migration: '+name)
    texts[name]=b.decode('utf-8')


def replace(name,old,new,count=1):
    if texts[name].count(old)!=count:raise RuntimeError('Unexpected patch occurrence: '+name+' '+old[:80])
    texts[name]=texts[name].replace(old,new)


replace('chart_ranges.py','import dashboard_runtime as a\n','import dashboard_runtime as a\nfrom chart_performance import period_performance, with_performance\n')
replace('chart_ranges.py','    return payload\n',"    payload['periodReturn'] = period_performance(payload)\n    return payload\n")
replace('chart_ranges.py','        html=a.build_chart_html(payload)','        html=with_performance(a.build_chart_html(payload),payload)')
replace('chart_ranges.py',"        if not payload['full_window']:st.warning", "        st.caption('ผลตอบแทนสะสม = (Close ล่าสุด / Close แรกในช่วงที่เลือก − 1) × 100; ใช้ราคาปรับแล้ว ไม่บวกปันผลซ้ำ ไม่ใช่ CAGR หรือผลตอบแทนสุทธิหลังค่าธรรมเนียม/ภาษี และไม่เปลี่ยนตามการลากหรือซูมกราฟ')\n        if not payload['full_window']:st.warning")
replace('dashboard_help.py','    def cell(tag,value,tip):','    def cell(tag,value,tip=None):\n        if tip is None:return f\'<{tag}>{escape(_plain(value))}</{tag}>\'')
replace('dashboard_help.py',"    headers=''.join(cell('th',col,field_help(col)) for col in frame.columns)","    # Keep help ONLY on indicator/criterion names, not values or category/source cells.\n    if label == 'ช่วงคะแนน':label = None\n    tooltip_column = list(frame.columns).index(label) if label else -1\n    headers=''.join(cell('th',col) for col in frame.columns)")
replace('dashboard_help.py',"tip if col==label else field_help(col)","tip if col==label else None")
replace('dashboard_help.py','<table class="workspace-help-table">','<table class="workspace-help-table" data-tooltip-column="{tooltip_column}">')
replace('app.py','2026-09-11.15','2026-09-11.16',count=2)
replace('dashboard_runtime.py','2026-09-11.15','2026-09-11.16')
replace('workspace_boot.py',"'dashboard_help', 'chart_ranges', 'dashboard_selection')", "'dashboard_help', 'chart_ranges', 'dashboard_selection', 'chart_performance')")
replace('enhanced_smoke.py','    return report\n',"    from performance_smoke import verify_growth_and_plain_cells\n    report['growth_and_plain_cells']=verify_growth_and_plain_cells(page,app)\n    return report\n")
texts['README.md']+='''\n\n## v16: ผลตอบแทนตามช่วงกราฟและตารางที่อ่านง่ายขึ้น\n\nหัวกราฟเพิ่ม **ผลตอบแทนสะสม** ของช่วงที่เลือก เช่น 7 วัน หรือ 10 ปี แยกจากเปอร์เซ็นต์ของแท่งล่าสุด คำนวณ `(Close สุดท้าย / Close แรกภายในช่วงที่เลือก - 1) × 100` จากแท่งราคาปรับแล้วชุดเดียวกับกราฟ ไม่ใช้ประวัติ warm-up ก่อนช่วง ไม่บวกปันผลซ้ำ ไม่ใช่ CAGR และยังไม่หักค่าธรรมเนียมหรือภาษี ช่วงระหว่างวันใช้ Close ของแท่ง 5 นาทีแรกในวันซื้อขายแรกของช่วง ไม่ใช่ราคาปิดวันก่อน; แสดงราคาและวันเริ่ม/สิ้นสุดให้ตรวจได้ ผลตอบแทนนี้ติดตามปุ่มช่วงเวลา ไม่เปลี่ยนเมื่อเลื่อน/ซูมกราฟเอง\n\nข้อมูลไม่ครบสิบปีจะแสดง **ผลตอบแทนข้อมูลที่มี** และคำเตือน ไม่อ้างว่าเป็นผลสิบปีเต็ม เมื่อราคาไม่สมบูรณ์หรือมีน้อยกว่าสองแท่งแสดง — แทนการสมมติเป็นศูนย์\n\nนำ Tooltip และไอคอน ⓘ ออกจากช่องตัวเลข หมวดหมู่ คำแปลผล คะแนน/เงื่อนไข และแหล่งข้อมูลในตารางอธิบายตามภาพ รวมทั้งหัวคอลัมน์ของตารางเหล่านี้ เหลือคำอธิบายเฉพาะชื่อเกณฑ์/ชื่อตัวชี้วัดที่จำเป็น ส่วนหัวคอลัมน์ในตารางรายชื่อหุ้น 500 ตัวและการเลือกหุ้นหน้าเดียวยังเหมือนเดิม ไม่เปลี่ยนสูตรให้คะแนน ราคา แหล่งข้อมูล หรือสิทธิการเข้าถึง\n'''
for name,text in texts.items():Path(name).write_text(text,encoding='utf-8')
Path('/tmp/v16-files.json').write_text(json.dumps(list(texts)))
print('V16_PATCHED',', '.join(texts))
