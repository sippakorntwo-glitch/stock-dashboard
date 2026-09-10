# ผลตรวจชุดแก้ไข 2026-09-10.12

## สิ่งที่แก้จาก ZIP ก่อนหน้า

- tests/test_analytics.py: เรียก history_missing(row) ให้ตรงกับฟังก์ชันจริงที่รับ 1 argument แทนการส่ง 3 arguments โดยคง assertions การตรวจ metric version เดิม ไม่ปิดหรือลบ test
- update_data.py: ใช้ app.METRIC_VERSION ร่วมกับส่วนคำนวณ แทนเลข version ตายตัว
- เพิ่ม regression tests 2 รายการ สำหรับ bootstrap ที่ต้องเติม metric version เก่าและการเปลี่ยนค่าของ METRIC_VERSION
- dashboard_runtime.py: ระบุ APP_VERSION เป็น 2026-09-10.12
- คู่มือ: ขยายขั้นตอนทีละคลิกและแก้ชื่อ Release/ไฟล์ข้อมูลให้ตรงโค้ด: dashboard-data-*, checkpoint.sqlite3, details--<number>.jsonl.gz ไม่มี watchlist.csv แยกเป็น asset

## คำสั่งที่รันจริง

```bash
python -m compileall -q .
DASHBOARD_OFFLINE_TEST_STUBS=1 python -m pytest -q tests --disable-warnings
```

## ผลที่ได้

```text
........................................s                                [100%]
40 passed, 1 skipped in 2.33s
```

ผลนี้ใช้ import stubs สำหรับ Streamlit/yfinance และ HTTP mocks สำหรับบริการภายนอก มีการทดสอบด้วย Streamlit จริง (AppTest) 1 รายการถูกข้าม จึงไม่ใช่ผลทดสอบระบบจริงครบทั้งหมด

## ยังไม่ได้ยืนยัน

- การติดตั้ง dependencies จริงครบชุดตาม requirements.txt บน Python 3.12 ยังไม่ได้รันในสภาพแวดล้อมนี้ การเข้าถึง PyPI จาก runtime ไม่สำเร็จ จึงไม่ยืนยัน availability/compatibility ของทุก pin จากการทดสอบนี้
- ยังไม่รัน Streamlit AppTest จริง ไม่ตรวจ JavaScript ของกราฟใน browser
- ไม่ได้เรียก Yahoo Finance จริง ไม่ได้ตรวจราคา 4,900 ตัว ไม่ใช่ backtest และไม่ยืนยันสิทธิการเผยแพร่ข้อมูล
- ไม่ได้ publish Release หรือสร้าง snapshot จริง ไม่ได้เปลี่ยนโค้ด main หรือ deploy/reboot Streamlit ในคำตอบนี้

ก่อน merge ให้ workflow Validate dashboard ติดตั้ง dependencies จริงและรัน tests โดยไม่เปิด DASHBOARD_OFFLINE_TEST_STUBS หากมี Failure, Skipped หรือไม่มี Checks ให้หยุดและตรวจสาเหตุก่อน merge

Python ที่ใช้ตรวจออฟไลน์: 3.13.5; เป้าหมาย deployment ใน workflow: Python 3.12
