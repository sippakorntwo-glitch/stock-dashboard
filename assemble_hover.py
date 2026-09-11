"""Temporary guarded integration; only the owner feature branch is updated."""
from pathlib import Path
import hashlib

EXPECTED = {
 'chart_ranges.py':'5145480e5e39f1b21b0e4010c1c7fc377de4ac4d',
 'app.py':'65673f07bb3313b78fd46897cd311805f7a50a1f',
 'dashboard_runtime.py':'c7ce0bfa925f50c21cb40ac7961d36048f46611c',
 'workspace_boot.py':'623a7a9fe068e2d6ceeb9f8873c10f5825a42100',
 'enhanced_smoke.py':'f66b314e6724c4f3983d61b3f0b904aa5108d047',
}
for file,expected in EXPECTED.items():
 raw=Path(file).read_bytes()
 actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 if actual != expected:raise RuntimeError('Unexpected source version: '+file)


def patch(file, old, new):
 p=Path(file); text=p.read_text(encoding='utf-8')
 if text.count(old)!=1:raise RuntimeError('Ambiguous source anchor: '+file+' '+old[:60])
 p.write_text(text.replace(old,new,1),encoding='utf-8')

patch('chart_ranges.py','from chart_performance import period_performance, with_performance',
      'from chart_performance import period_performance, with_performance\nfrom chart_inspector import with_inspector')
patch('chart_ranges.py','html=with_performance(a.build_chart_html(payload),payload)',
      'html=with_inspector(with_performance(a.build_chart_html(payload),payload))')
for file in ['app.py','dashboard_runtime.py']:
 p=Path(file); text=p.read_text(encoding='utf-8')
 if '2026-09-11.17' not in text:raise RuntimeError('Missing current version')
 p.write_text(text.replace('2026-09-11.17','2026-09-11.18'),encoding='utf-8')
patch('workspace_boot.py', "'chart_performance', 'ranking_board', 'ranking_engine')",
      "'chart_performance', 'ranking_board', 'ranking_engine', 'chart_inspector')")
patch('enhanced_smoke.py','    return report',
      "    from hover_smoke import verify_hover\n    report['chart_inspector']=verify_hover(page,app)\n    return report")
with Path('README.md').open('a',encoding='utf-8') as f:
 f.write('''\n\n## v18 — ชี้กราฟเพื่ออ่านค่าของทุกเส้นที่เปิด\n\nปุ่ม **ข้อมูลตามเมาส์** อยู่ในแถบอินดิเคเตอร์ของกราฟ (เปิดเป็นค่าเริ่มต้น) ชี้แท่งราคา เส้น EMA20/EMA50/SMA200 หรือแผง Volume/RSI/MACD เพื่อแสดงค่าจากแท่งเวลาเดียวกันในกล่องใกล้เมาส์ เส้นที่ชี้จะถูกเน้นเมื่ออยู่ใกล้จุดข้อมูล; ไม่มีการประมาณค่าระหว่างแท่ง ข้อมูลที่ไม่มีแสดง — ไม่ดึงค่าจากแท่งล่าสุดมาแทน\n\nกล่องแสดง Open, High, Low, Close, อินดิเคเตอร์ที่เปิด, Volume แบบจำนวนเต็ม, RSI14, MACD/Signal/Histogram และ % เปลี่ยนจากแท่งก่อนของแท่งที่เลือก ช่วงระหว่างวันแสดงวันเวลาเต็มพร้อม timezone ของตลาด แถบค่าด้านบนอ่านเส้น EMA50/SMA200/Signal/Histogram เพิ่มด้วย ปิดเส้นใดจะไม่ค้างค่าของเส้นนั้นในกล่องหรือแถบค่า\n\nคลิก/แตะเพื่อตรึงข้อมูล คลิกแท่งอื่นเพื่อเปลี่ยน กด Escape หรือ **เลิกตรึง** เพื่อปล่อย ใช้ Tab โฟกัสกราฟแล้วลูกศรซ้าย/ขวาเพื่ออ่านทีละแท่งได้ ปุ่มปิดข้อมูลตามเมาส์ทำให้กลับไปใช้กราฟธรรมดา การลาก/ซูม/Log/คืนมุมมองยังใช้ได้\n\nการชี้กราฟทำงานในเบราว์เซอร์เท่านั้น ไม่ส่ง request ใหม่ ไม่เปลี่ยนราคา/ผลตอบแทนช่วงกราฟ/สูตรให้คะแนน/Top 10/ตารางข้อมูล และไม่เพิ่ม Tooltip คืนในตารางอธิบายที่นำออกไปแล้ว ข้อมูลที่ตรึงไม่ใช่ราคาที่กำลังอัปเดต\n\nอ้างอิง API ของ Lightweight Charts 5.0 (รุ่น library ที่ใช้ 5.0.9): MouseEventParams, IPaneApi, subscribeCrosshairMove, subscribeClick; เพิ่ม browser regressions ที่ใช้เมาส์จริงกับ ORCL/SPY และตรวจค่าจาก candles จริงก่อนรายงานผลใช้งาน\n''')
print('INSPECTOR_SOURCE_INTEGRATED',flush=True)
