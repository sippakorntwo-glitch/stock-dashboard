# คู่มือติดตั้ง Stock Dashboard แบบทีละคลิก

รุ่นชุดแก้ไข **2026-09-10.12** · Repository **sippakorntwo-glitch/stock-dashboard**

## ก่อนเริ่ม: ใช้ ZIP รุ่น v12 เท่านั้น

ZIP ก่อนหน้ารุ่น 2026-09-10.11 มีการทดสอบล้มเหลว 1 รายการ: test เรียก `history_missing` ด้วย 3 arguments แต่โปรแกรมรับเพียง 1 argument ชุด v12 แก้การเรียกใน test ให้ตรงกับโปรแกรม โดยคง assertions เดิมไว้ เพิ่ม regression tests และให้ตัวตรวจใช้ `METRIC_VERSION` ร่วมกันแทนตัวเลขที่เขียนตายตัว

ผลออฟไลน์ของชุด v12: **40 passed, 1 skipped** ส่วนที่ข้ามคือการทดสอบด้วย Streamlit จริง ยังไม่ได้ติดตั้ง dependencies จริงครบชุด ไม่ได้ดึง Yahoo จริง ไม่ได้เผยแพร่ข้อมูลจริง และไม่ได้ทดสอบกราฟ JavaScript ในเบราว์เซอร์จริง ต้องตรวจ GitHub Checks และเว็บจริงตามขั้นตอนด้านล่าง ไม่ใช่คำรับรองว่าทั้งระบบพร้อม production แล้ว

โค้ดใหม่ยังเป็นไฟล์สำหรับอัปโหลด ไม่ได้ commit เข้า main ในคำตอบนี้ ตรวจ GitHub พบ main และ improve/research-workspace-20260910 อยู่ที่ commit 0be231ae7373bf61126bf506b4528c5411c85265 เหมือนกัน ณ เวลาตรวจ

## ภาพรวม: ทำงานที่ไหนบ้าง

| สถานที่ | ใช้ทำอะไร |
|---|---|
| คอมพิวเตอร์ Windows | ดาวน์โหลดและแตก ZIP เท่านั้น ไม่จำเป็นต้องติดตั้ง Python หรือ GitHub Desktop สำหรับวิธีนี้ |
| เว็บไซต์ GitHub | อัปโหลดไฟล์ ตรวจ tests รวมโค้ด และเริ่มงานเตรียมข้อมูล |
| เว็บไซต์ Streamlit | เปิดแอป ดู Logs และตั้งค่าแอปเมื่อจำเป็น |

Repository คือโฟลเดอร์โปรเจกต์ออนไลน์; branch คือชุดงานแยก; commit คือบันทึกการเปลี่ยนแปลง; Pull Request หรือ PR คือหน้าขอรวมงานเข้าชุดหลัก; Merge คือรวมโค้ด; Actions คือระบบรันงานอัตโนมัติ

**ก่อน Merge ต้องเข้าใจ:** ระบบเก็บข้อมูลชุดนี้เผยแพร่ข้อมูลตลาดไปยัง GitHub Releases ใน repository สาธารณะ ตรวจสิทธิใช้/เผยแพร่ข้อมูลจากผู้ให้บริการก่อนเปิดใช้งาน อย่าใส่พอร์ตส่วนตัว ต้นทุน เลขบัญชี รหัสผ่าน หรือ token ลงในไฟล์ที่อัปโหลด การทำให้ repo เป็น Public ไม่ได้ให้สิทธิแจกจ่ายข้อมูลของผู้ให้บริการโดยอัตโนมัติ

## 1. เปิดโปรเจกต์ให้ถูกและเข้าสู่ระบบ

1. เปิด [Repository ของคุณ](https://github.com/sippakorntwo-glitch/stock-dashboard) ใน Chrome หรือ Edge
2. ถ้ามีปุ่ม Sign in ให้เข้าสู่ระบบด้วยบัญชี GitHub ที่เป็นเจ้าของ repo นี้
3. ตรวจข้อความด้านบนว่าเป็น `sippakorntwo-glitch / stock-dashboard`
4. คลิกแท็บ **Code** ซึ่งเป็นแท็บรายชื่อไฟล์ ไม่ใช่แท็บ Actions
5. มองเหนือรายชื่อไฟล์ทางซ้าย จะมีปุ่มเลือก branch ที่แสดงชื่อ `main` หรือชื่อ branch อื่น

**จุดตรวจ:** อยู่ในหน้าไฟล์ของ stock-dashboard และเห็นปุ่มเลือก branch อย่าสร้าง repository ใหม่

## 2. สำรองโค้ดเดิม

1. กดปุ่มเลือก branch พิมพ์ `main` แล้วเลือก main
2. ตรวจอีกครั้งว่าปุ่ม branch แสดง main
3. กดปุ่มสีเขียว **Code** เหนือรายชื่อไฟล์
4. ในเมนูที่เปิดขึ้นเลือก **Download ZIP**
5. เก็บไฟล์ที่ดาวน์โหลดไว้เป็นสำรอง เปลี่ยนชื่อบน Windows ได้ เช่น `stock-dashboard-backup-before-upgrade.zip`
6. แยกไฟล์สำรองนี้ออกจาก ZIP อัปเกรด อย่าลากไฟล์สำรองกลับไปอัปโหลดแทนชุดใหม่

**จุดตรวจ:** มี ZIP ของโค้ดเดิมในเครื่องหนึ่งชุด และยังไม่ได้ลบไฟล์ใดใน GitHub การสำรองด้วย Download ZIP ไม่รวม Streamlit Secrets และข้อมูล runtime ที่อยู่นอก repo

## 3. ดาวน์โหลดและแตกไฟล์อัปเกรด

1. กลับไปที่คำตอบในแชต ดาวน์โหลด **stock_dashboard_upgrade_2026-09-10_v12.zip**
2. กด **Windows + E** เพื่อเปิด File Explorer แล้วเข้า Downloads
3. คลิกขวาที่ ZIP รุ่น v12 แล้วเลือก **Extract All… / แยกทั้งหมด…**
4. เลือกโฟลเดอร์ใหม่ เช่น `Downloads\stock-dashboard-upgrade-v12` แล้วกด Extract
5. เปิดโฟลเดอร์ที่แตกแล้ว ไม่ทำงานจากหน้าต่าง ZIP โดยตรง
6. ตรวจว่าเห็น `app.py`, `update_data.py`, `dashboard_runtime.py` พร้อมโฟลเดอร์ `.github`, `.streamlit`, `tests` อยู่ระดับเดียวกัน
7. ไม่ต้องดับเบิลคลิกไฟล์ `.py` หรือ `.cmd` เพราะรอบนี้เราติดตั้งผ่านเว็บไซต์

หากไม่เห็นนามสกุลไฟล์ บน Windows 11 ใช้ **View → Show → File name extensions** และ **Hidden items** บน Windows 10 ใช้ View/Options เพื่อเปิดการแสดงนามสกุลและไฟล์ซ่อน ไม่ต้องเปลี่ยนชื่อ app.py เป็น app.py.txt

**จุดตรวจ:** เป็นโฟลเดอร์ธรรมดา และมีไฟล์ที่แตกครบ ZIP มี 27 ไฟล์รวมไฟล์ในโฟลเดอร์ย่อย จำนวนรายการที่หน้า root ของ File Explorer จึงไม่จำเป็นต้องเท่ากับ 27

## 4. เปิด branch อัปเกรดที่เตรียมไว้

1. กลับไปที่ GitHub แท็บ Code
2. กดปุ่ม branch ที่แสดง main
3. ในช่องค้นหาพิมพ์ `improve/research-workspace-20260910`
4. เลือก branch ชื่อนี้จากรายการ ไม่ต้องสร้าง branch ชื่ออื่น
5. ตรวจว่าชื่อ branch ที่แสดงเปลี่ยนจาก main เป็นชื่ออัปเกรดแล้ว หากข้อความยาวจนตัด ให้กดเมนูดูชื่อเต็ม

หรือเปิด [branch อัปเกรดโดยตรง](https://github.com/sippakorntwo-glitch/stock-dashboard/tree/improve/research-workspace-20260910)

**จุดตรวจ:** ยังอยู่หน้า root ของ repo ไม่อยู่ใน .github/workflows หรือโฟลเดอร์อื่น และ branch เป็น improve/research-workspace-20260910

ชื่อ `dashboard-data` ไม่ใช่ branch สำหรับอัปโหลดโค้ด อย่าใช้ชื่อนั้นในขั้นตอนนี้

## 5. อัปโหลดไฟล์ใหม่ให้ถูกตำแหน่ง

1. ในหน้า root ของ branch อัปเกรด กด **Add file → Upload files**
2. จัดหน้าต่าง GitHub และ File Explorer ให้อยู่ข้างกัน
3. ใน File Explorer เปิดโฟลเดอร์ v12 จนเห็นไฟล์ app.py อยู่ตรงหน้า ไม่ใช่เลือกโฟลเดอร์ที่ครอบทั้งหมดจากด้านนอก
4. คลิกพื้นที่ไฟล์ในโฟลเดอร์นั้นแล้วกด **Ctrl + A** เพื่อเลือกไฟล์และโฟลเดอร์ทั้งหมดที่แตกออกมา
5. ลากสิ่งที่เลือกไปยังกรอบอัปโหลดใน GitHub โฟลเดอร์ย่อยต้องถูกลากไปด้วย
6. ดูรายการที่อัปโหลด ตรวจว่ามี `app.py`, `update_data.py`, `.github/workflows/validate.yml` และ `.streamlit/config.toml`
7. ไฟล์ app.py ใหม่ต้องอยู่ข้าง daily_watchlist.csv เดิม ไม่ใช่ `stock-dashboard-upgrade-v12/app.py`
8. ยังไม่ลบ app.py เดิมเอง การอัปโหลดไฟล์ชื่อและตำแหน่งเดิมบน branch นี้ใช้แทนเนื้อหาของไฟล์นั้น ส่วนไฟล์ที่ไม่อัปโหลดไม่ได้ถูกสั่งลบโดยขั้นตอนนี้

**ตำแหน่งที่ถูกต้อง**

```text
app.py
update_data.py
dashboard_core.py
dashboard_runtime.py
dashboard_ui.py
analytics.py
data_sync.py
github_store.py
requirements.txt
requirements-dev.txt
.gitignore
.github/workflows/five_min_update.yml
.github/workflows/validate.yml
.streamlit/config.toml
tests/...
```

**ตำแหน่งที่ผิด**

```text
stock-dashboard-upgrade-v12/app.py
stock-dashboard-upgrade-v12/update_data.py
```

ถ้ารายการอัปโหลดผิดชั้น ให้ยกเลิกการอัปโหลดก่อนบันทึก แล้วเริ่มจากหน้า root ใหม่ อย่า Commit ทั้งที่รู้ว่าตำแหน่งผิด

อย่าอัปโหลด ZIP เป็นไฟล์เดียว และอย่าอัปโหลด secrets.toml จริง แม้มี .gitignore ก็ไม่ควรเชื่อว่าไฟล์ที่เลือกอัปโหลดผ่านเว็บจะถูกกรองให้อัตโนมัติ

## 6. บันทึกการอัปโหลดลง branch

1. เลื่อนลงส่วน **Commit changes** ของหน้าอัปโหลด
2. ช่องชื่อ commit ใส่ `Install research workspace v12 and prepared data pipeline`
3. ช่องคำอธิบายยาวปล่อยว่างได้
4. ถ้ามีตัวเลือกให้เลือก **Commit directly to the improve/research-workspace-20260910 branch**
5. ถ้าข้อความกลับแสดง `main` ให้หยุดและกลับไปเลือก branch อัปเกรดให้ถูกก่อน ไม่บันทึกตรง main
6. กดปุ่มยืนยัน ซึ่งหน้าจออาจใช้ชื่อ **Commit changes** หรือ **Propose changes**
7. เมื่อกลับมาหน้าไฟล์ คลิก `update_data.py` ตรวจว่าเปิดเห็นโค้ดได้ แล้วกลับมาหน้า root
8. เปิด `.github → workflows` ต้องเห็นทั้ง `five_min_update.yml` และ `validate.yml`
9. กลับ root เปิด `.streamlit` ต้องเห็น `config.toml` และเปิด `tests` ต้องเห็นไฟล์ทดสอบ
10. ตรวจว่า `daily_watchlist.csv`, `fast_updater.py`, `screener.py`, `app_backup.py` เดิมยังอยู่

**จุดตรวจ:** branch อัปเกรดมีไฟล์ใหม่แล้ว main ยังไม่ได้ถูกแทนด้วยโค้ดใหม่

app.py ใหม่มีขนาดสั้นกว่าของเดิมมาก เป็นเรื่องปกติ เพราะโค้ดส่วนต่าง ๆ อยู่ใน dashboard_core.py, dashboard_runtime.py และ dashboard_ui.py

## 7. เปิด Pull Request เพื่อรวมเข้าชุดหลัก

1. ที่หน้า branch อัปเกรด กด **Compare & pull request** เมื่อมีแถบแจ้งขึ้น
2. ถ้าไม่มีแถบ ให้กดแท็บ **Pull requests → New pull request**
3. ตั้งฝั่ง **base** เป็น `main`
4. ตั้งฝั่ง **compare** เป็น `improve/research-workspace-20260910`
5. ต้องเห็นรายการไฟล์ที่ต่างกัน ถ้าขึ้น There isn't anything to compare แปลว่ายังไม่ได้ commit ไฟล์ หรือเลือก branch ผิด ตรวจขั้น 4–6 ก่อน
6. กด **Create pull request** เพื่อเปิดฟอร์มเมื่อหน้าจอต้องผ่านหน้าดู diff ก่อน
7. ใส่ชื่อ `Upgrade Stock Dashboard to Research Workspace v12`
8. ใส่คำอธิบาย เช่น `Add prepared-data collection, research views and validation tests. Preserve existing watchlist.`
9. กด **Create pull request** เพื่อยืนยัน ไม่เลือก Create draft pull request สำหรับเส้นทางนี้

**จุดตรวจ:** ได้หน้า PR พร้อมหมายเลข เช่น #1 หรือหมายเลขที่ GitHub กำหนด อย่าใช้หมายเลขตัวอย่างเป็นเลขจริง

## 8. ตรวจ Checks และไฟล์ที่จะเปลี่ยน

1. ในหน้า PR เปิดแท็บ **Files changed**
2. ตรวจเส้นทางไฟล์เหมือนขั้น 5 และตรวจว่าไม่ได้ลบ daily_watchlist.csv หรือใส่ข้อมูลลับ
3. app.py แสดงลบบรรทัดจำนวนมากได้ เพราะเปลี่ยนเป็น entrypoint สั้น ๆ แต่ต้องมี dashboard_core.py อยู่ด้วย
4. เปิดแท็บ **Checks**
5. เลือก **Validate dashboard → tests** หรือชื่อที่ GitHub แสดงเป็นชุด workflow/job เดียวกัน
6. เปิด **Install dependencies** ตรวจว่าขั้นตอนติดตั้งไลบรารีจบสำเร็จ
7. เปิด **Compile and test with real Streamlit and mocked data providers** ตรวจผลการทดสอบ
8. ถ้ามีปุ่มอนุมัติ workflow ให้ตรวจว่าตรงกับ PR ของคุณเองก่อนอนุมัติ

| สถานะ | ทำอย่างไร |
|---|---|
| In progress / Queued | งานยังไม่จบ ยังไม่ Merge |
| Failure / เครื่องหมายแดง | เปิดขั้นตอนที่ล้มเหลว อ่าน error ยังไม่ Merge |
| Skipped / ไม่มี Checks | ไม่ใช่หลักฐานว่าทดสอบผ่าน ตรวจไฟล์ validate.yml และสิทธิ Actions |
| Success / ผ่าน tests ครบ | ไปตรวจข้อควรทราบก่อน Merge ในขั้นถัดไป |

ชุด v12 มี tests 41 รายการ ออฟไลน์ผ่าน 40 และข้าม AppTest 1 รายการ บน GitHub ที่ติดตั้ง dependencies จริง workflow ไม่ได้เปิด flag stub จึงควรรัน AppTest ด้วย หากล้มเหลวอย่าปิด test หรือลบเงื่อนไขเพื่อให้เขียว

ห้ามใส่ `DASHBOARD_OFFLINE_TEST_STUBS=1` ใน Actions หรือ Streamlit และอย่าใส่ `[skip ci]` ใน commit อัปเกรดที่ต้องการให้ทดสอบ

## 9. Merge หลังตรวจผ่านแล้ว

ก่อนทำขั้นนี้: ยืนยันว่า Checks ผ่านจริง ไม่มีไฟล์ลับ และยอมรับว่าระบบเก็บข้อมูลจะเผยแพร่ข้อมูลใน repo สาธารณะหลังเปิดใช้งาน ตารางอัปเดตสามารถเริ่มทำงานตามกำหนดเมื่อ workflow อยู่บน main แล้ว

1. กลับแท็บ **Conversation** ของ PR
2. เลื่อนลงบริเวณกล่องรวมโค้ด
3. ถ้ามี merge conflict หรือยังมี Checks ค้าง ไม่กดข้ามเงื่อนไข
4. กด **Merge pull request** ถ้าแสดงวิธีอื่น กดลูกศรแล้วเลือก **Create a merge commit** สำหรับเส้นทางนี้
5. กด **Confirm merge**
6. ตรวจว่ามีสถานะ **Merged**
7. กลับแท็บ Code เลือก branch main เปิด update_data.py ให้แน่ใจว่าไฟล์อยู่บน main แล้ว

**จุดตรวจ:** ตอนนี้ main เป็นโค้ดใหม่แล้ว Streamlit ที่ผูก main/app.py อาจเริ่ม redeploy จากการเปลี่ยนแปลงนี้ ไม่ใช่แค่ขั้น Reboot ที่จะเปลี่ยนเว็บ

ไม่จำเป็นต้องลบ branch อัปเกรดทันที เก็บไว้จนตรวจการใช้งานเสร็จได้

## 10. รัน bootstrap ครั้งแรก

1. เปิดแท็บ **Actions** ของ repository
2. ในแถบซ้ายเลือก **Update market data (free)** ไม่ใช่ Validate dashboard
3. กด **Run workflow** ทางด้านขวาเหนือรายการรัน
4. เลือก **Branch: main**
5. เลือก **mode: bootstrap**
6. กดปุ่ม **Run workflow** ภายในกล่องที่เปิดอยู่เพื่อยืนยัน
7. กลับมาดูรายการรัน และเปิดแถวล่าสุดของรอบที่เพิ่งเริ่ม ไม่ใช่รอบเก่าที่ล้มเหลว
8. คลิก job ชื่อ **update**
9. เปิดขั้นตอน **Validate required files** แล้วตรวจว่าผ่าน
10. เปิด **Update and publish prepared data** เพื่อดูความคืบหน้า

bootstrap ใช้เติมประวัติ/ข้อมูลพื้นฐาน/ปันผลที่ขาด ส่วน daily ใช้อัปเดตรายวัน ไม่รับประกันว่าครบ 4,900 ตัวในรอบเดียวและไม่ควรกดรันถี่ ๆ เมื่อผู้ให้บริการจำกัดคำขอ

**ถ้าไม่เห็น Run workflow:** ตรวจว่าเลือก workflow เฉพาะตัว ไม่อยู่หน้า All workflows และไฟล์มี workflow_dispatch อยู่บน default branch main แล้ว

**ถ้า Actions ถูกปิด:** เปิด Settings → Actions → General ตรวจว่าไม่ได้ Disable actions และอนุญาต actions/checkout, actions/setup-python ที่ workflow ใช้ อย่าขยายสิทธิทุก workflow เป็น write โดยไม่มีเหตุผล ชุดนี้ระบุ contents: write ไว้เฉพาะงานเก็บข้อมูลแล้ว

ไม่ต้องสร้าง Personal Access Token และไม่ต้องคัดลอก token จากแชต งานใช้ GITHUB_TOKEN ของ GitHub Actions เอง หน้าเว็บอ่านข้อมูลสาธารณะโดยไม่ใช้ token เขียน

## 11. ตรวจว่าชุดข้อมูลถูกเผยแพร่

เมื่อขั้นตอนเผยแพร่สำเร็จ เปิด Summary ของรอบ Actions ดูหัวข้อ **Prepared market data** โดยอ่านค่า Prices available, checked today, Industry และ Bootstrap symbols remaining ไม่ดูแค่เครื่องหมายเขียว

จากนั้นกลับ Code เปิดเมนู branch เลือก `dashboard-data` แล้วเปิด `dashboard/latest.json`

**จุดตรวจ:** เห็น generation, published_at, coverage, report และ references ของไฟล์ข้อมูล ไม่ต้องแก้ JSON นี้เอง

เปิด [Releases](https://github.com/sippakorntwo-glitch/stock-dashboard/releases) แล้วเลือก Release ชื่อที่ขึ้นต้น `dashboard-data-` และขยาย Assets ควรพบไฟล์ที่ระบบสร้าง เช่น:

```text
summary.json.gz
manifest.json
checkpoint.sqlite3
details--<หมายเลข>.jsonl.gz
```

จำนวน details ขึ้นกับข้อมูลที่มี ไม่จำเป็นต้องครบทุกหมายเลขในรอบแรก และ `watchlist.csv` ไม่ได้เป็น Release asset แยกในชุดโค้ดนี้ CSV ต้นทางถูกเก็บเป็นข้อมูลใน summary

อย่าสร้าง branch ข้อมูลหรืออัปโหลด SQLite ลง main ด้วยมือ ระบบสร้างเมื่อเผยแพร่ครั้งแรก หน้าเว็บอ่าน summary/details ส่วน checkpoint.sqlite3 ใช้กู้ข้อมูลให้รอบ collector ถัดไป

Success หมายถึงบันทึกงานที่ทำได้สำเร็จ ไม่ได้แปลว่าหุ้นทุกตัวครบและราคาปัจจุบันเสมอ

## 12. เปิดเว็บเดิมและตรวจ Streamlit

1. เปิด [Dashboard เดิม](https://my-stock-terminal.streamlit.app)
2. เมื่อโค้ดใหม่ถูกใช้ ควรเห็นชื่อ **Stock Research Workspace** และเมนู 6 มุมมอง
3. หากเว็บยังหน้าตาเดิม เข้าสู่ [Streamlit workspace](https://share.streamlit.io/) ด้วยบัญชีเจ้าของแอป
4. เลือก workspace ของเจ้าของ repo `sippakorntwo-glitch` และหาแอปเดิม ไม่สร้างแอปใหม่แทนทันที
5. จากหน้าเว็บแอป กด **Manage app** มุมขวาล่างเพื่อเปิด Logs
6. เปิดเมนูสามจุดของแผง Logs แล้วเลือก **Reboot app** จากนั้นกด Reboot ยืนยันเมื่อจำเป็น การ reboot จะรบกวนคนที่กำลังเปิดเว็บอยู่
7. อีกทางคือในหน้า workspace กดสามจุดของแอป → **Reboot** → ยืนยัน
8. ดู Logs ว่าติดตั้ง dependencies และเปิด app.py สำเร็จหรือไม่

แอปเดิมต้องผูกกับ **repository sippakorntwo-glitch/stock-dashboard, branch main, entrypoint app.py** ไม่เปลี่ยนไปใช้ dashboard_core.py หรือ update_data.py หากไม่เห็น Manage app ให้ตรวจการเข้าสู่ระบบและสิทธิใน Streamlit ก่อน การเชื่อม GitHub กับแชตไม่ได้ทำให้เบราว์เซอร์ล็อกอิน Streamlit เป็นเจ้าของโดยอัตโนมัติ

อย่าเลือก Delete app ในขั้นตอนปกติ Python ของ workflow ตั้ง 3.12 ไม่ได้เปลี่ยน Python ของแอปที่ deploy แล้วอัตโนมัติ ถ้า Logs บอกว่า Python ไม่รองรับ dependencies ให้ตรวจปัญหานั้นแยก การเปลี่ยน Python ของแอปเดิมตามเอกสาร Streamlit ต้อง redeploy ไม่ใช่แก้จากหน้า Secrets

## 13. Secrets — ทำเฉพาะเมื่อจำเป็น

ค่าเริ่มต้นของโค้ดชี้ repository ของคุณแล้ว จึงไม่จำเป็นต้องเพิ่ม Secrets เพียงเพื่ออ่าน public snapshot และไม่ต้องแทนที่ Secrets เดิมทั้งหมด

หากต้องการระบุค่าให้ชัด:

1. เข้า Streamlit workspace กดสามจุดข้างแอป → Settings หรือ Manage app → สามจุด → Settings
2. ใน **App settings** เลือกแท็บ **Secrets** ไม่ใช่เมนู Settings มุมขวาบนที่เปลี่ยนหน้าตาเฉย ๆ
3. ตรวจว่ามี key เดิมเหล่านี้หรือไม่ ถ้ามีให้แก้ค่าบรรทัดเดิม ไม่เพิ่ม key ซ้ำ
4. ใส่ค่า top-level ดังนี้ ถ้าในไฟล์มีหัวข้อ `[section]` ให้ใส่กลุ่มนี้ก่อนหัวข้อแรก ไม่ใส่ไปเป็นสมาชิกของ section อื่น

```toml
DASHBOARD_DATA_REPO = "sippakorntwo-glitch/stock-dashboard"
DASHBOARD_DATA_VISIBILITY = "public"
DASHBOARD_DATA_BRANCH = "dashboard-data"
DASHBOARD_ALLOW_LIVE_UPDATES = false
```

5. รักษา Secrets อื่นที่ยังใช้ ไม่ลบทั้งหมดโดยไม่ทราบหน้าที่ แล้วกด **Save**
6. ใช้ false ตัวพิมพ์เล็กและไม่มีเครื่องหมายคำพูดตามตัวอย่าง

ห้ามนำ token จริงไปใส่ secrets.example.toml แล้ว commit ห้ามอัปโหลด .streamlit/secrets.toml จริง และไม่ต้องใส่ DASHBOARD_GITHUB_TOKEN ในเว็บโหมดสาธารณะ ค่า DASHBOARD_SNAPSHOT_DIR หรือ visibility เก่าที่ขัดกันต้องแก้เฉพาะที่ตั้งค่าจริง

DASHBOARD_ALLOW_LIVE_UPDATES=false ทำให้หน้าเว็บเน้นอ่าน prepared data การเปิด true เพิ่มปุ่มเรียก Yahoo โดยผู้ชมที่เข้าถึงเว็บได้ทุกคน ไม่ใช่สิทธิ admin-only จึงยังคง false ในการติดตั้งครั้งแรก

## 14. ตรวจเว็บทีละหน้า

1. เลือก **สถานะข้อมูล** ตรวจรุ่นโปรแกรมเป็น **2026-09-10.12** และมี generation/เวลาเผยแพร่ ถ้ามีเพียงเลขรุ่นแต่ยังไม่มี snapshot แปลว่าโค้ดขึ้นแล้วแต่ข้อมูลยังไม่พร้อม
2. เลือก **ภาพรวมและค้นหา** ตรวจจำนวนรายชื่อรวม 4,900 ตัวและจำนวนมีราคาแยกต่างหาก ค้น AAPL แล้วลอง clear ช่องค้นหา
3. ในช่อง **Ticker ที่ต้องการวิเคราะห์** ด้านซ้าย พิมพ์ AAPL แล้วกด Enter ช่องนี้ต่างจากช่องค้นตาราง
4. เลือก **กราฟและแผนซื้อ** แล้วเลือกช่วง 1 ปี ตรวจแท่งราคาและปุ่ม EMA/RSI/MACD ถ้ายังไม่มีประวัติให้ดูงานข้อมูลก่อน
5. เลือก **พื้นฐานและปันผล** ตรวจเวลาดึงและช่องข้อมูลที่ขาด ไม่ตีความ missing ว่าไม่มีปันผลเสมอ
6. เลือก **ความเสี่ยง** ตรวจช่วงข้อมูลจริงและกราฟ Drawdown
7. เลือก **เปรียบเทียบหลายตัว** เลือก AAPL กับ SPY และเพิ่ม MSFT เมื่อมีข้อมูล ระบบเปรียบเทียบสูงสุด 6 ตัวและใช้วันที่ร่วมกัน
8. กลับ **สถานะข้อมูล** ตรวจข้อผิดพลาดและเวลาของราคา ไม่ดูแค่เวลาที่เปิดหน้าเว็บ

การสแกนใหม่ใช้ข้อมูลรายวัน ไม่ใช่ราคาสตรีมสด ระบบแผนซื้ออาจแสดงรอยืนยันเพราะ quote เก่า ไม่ได้หมายความว่าต้องลดเกณฑ์เพื่อให้ขึ้นซื้อ รายการโปรดอยู่ในเซสชัน ให้ดาวน์โหลด CSV เพื่อเก็บถาวร

## เวลางานอัตโนมัติ

| งาน | เวลาไทยตาม workflow |
|---|---|
| daily | 13:17 วันอังคาร–เสาร์ |
| bootstrap | 01:17, 07:17, 19:17 ทุกวัน |
| หน้าเว็บตรวจ snapshot | โดยปกติทุก 5 นาทีขณะที่เปิดหน้าเว็บ หรือกดตรวจชุดข้อมูลใหม่ |

ชื่อ five_min_update.yml เป็นชื่อเดิม ไม่ได้แปลว่าดึงหุ้นทั้งตลาดทุก 5 นาที GitHub schedule อาจเริ่มล่าช้าหรือข้ามบางรอบ จึงดูเวลาใน run จริงประกอบ

## ทางแก้เมื่อการลากโฟลเดอร์ไม่สำเร็จ

ใช้เส้นทางนี้เฉพาะเมื่ออัปโหลดแบบทั้งชุดไม่รักษาโฟลเดอร์ อย่าทำซ้ำหากไฟล์อยู่ถูกที่แล้ว

1. ที่ root ของ branch อัปเกรดอัปโหลดเฉพาะไฟล์ที่อยู่ root ก่อน
2. เปิด `.github → workflows` บน GitHub แล้ว Add file → Upload files อัปโหลดไฟล์ YAML สองตัวจาก `.github/workflows` ในเครื่องโดยไม่ลากโฟลเดอร์ครอบ
3. หากยังไม่มี `.streamlit` ให้กลับ root กด **Add file → Create new file** ใส่ชื่อ `.streamlit/config.toml` แล้วเปิดไฟล์ config.toml จาก ZIP ด้วย Notepad คัดลอกเนื้อหาทั้งหมดลง editor จากนั้นบันทึกลง branch อัปเกรด เครื่องหมาย `/` ในชื่อเป็นเส้นทางโฟลเดอร์
4. สำหรับ tests ที่ยังไม่มี ใช้ root → Create new file ชื่อ `tests/conftest.py` คัดลอกเนื้อหาจากไฟล์ ZIP แล้วบันทึก จากนั้นเปิดโฟลเดอร์ tests ที่สร้างแล้วและ Upload files ที่เหลือจาก tests ในเครื่อง
5. ตรวจเส้นทางทั้งหมดอีกครั้งก่อนเปิด PR

## เมื่อเกิดข้อผิดพลาด

| อาการ | จุดตรวจ |
|---|---|
| ไม่มีความต่างให้เปิด PR | ยังไม่ commit ไฟล์ใหม่ หรือเลือก base/compare ผิด |
| No such file update_data.py | ไฟล์อยู่ผิดชั้น หรือกำลังดู run/branch เก่า |
| ModuleNotFoundError | อัปโหลดไฟล์ไม่ครบ/ผิดตำแหน่ง หรือ dependencies ติดตั้งล้มเหลว |
| No matching distribution found | ดูชื่อแพ็กเกจ เวอร์ชันและ Python ใน Install dependencies อย่าเปลี่ยนเป็นเวอร์ชันล่าสุดทุกตัวแบบสุ่ม |
| tests แดง | คัดลอกชื่อ test และ traceback โดยไม่ใส่ Secrets ยังไม่ Merge |
| workflow ถูก Skipped | ตรวจ public-only condition และสิทธิ Actions ไม่ถือว่า tests ผ่าน |
| HTTP 403 ตอนเผยแพร่ | ดู contents: write และนโยบาย repo/องค์กร ไม่เพิ่ม token ในเว็บเพื่อแก้ |
| HTTP 404 ตอนอ่านข้อมูล | ตรวจ bootstrap, dashboard-data/dashboard/latest.json และ Release ของ generation นั้น |
| Yahoo 429 | หยุดกดซ้ำ ดู backoff และใช้ข้อมูลเดิม ไม่เพิ่ม concurrency เพื่อหลบการจำกัด |
| UI รุ่นใหม่แต่กราฟว่าง | โค้ดพร้อมแต่หุ้นนั้นอาจไม่มีประวัติที่โหลดสำเร็จ ตรวจ coverage |
| ไม่เห็น Manage app | เข้า Streamlit ด้วยบัญชีเจ้าของและเลือก workspace ให้ตรง |

อ่าน log ของรอบล่าสุดที่ตรงกับ commit อัปเกรด ไม่กด Re-run รอบเก่าเพื่อทดสอบโค้ดใหม่ เพราะการรันซ้ำอาจใช้ commit เดิมของรอบนั้น ให้เริ่ม Run workflow ใหม่เมื่อจะทดสอบ main ปัจจุบัน

## ย้อนกลับ

ก่อน Merge: หยุดทำใน branch อัปเกรดหรือปิด PR ได้ main ไม่ถูกแทนที่

หลัง Merge:

1. ไป Pull requests → Closed เลือก PR อัปเกรดที่มีสถานะ Merged
2. เลื่อนลงหา **Revert**
3. กดเพื่อสร้าง PR ย้อนกลับ ตรวจความเปลี่ยนแปลงแล้ว Merge PR ใหม่นั้น
4. ตรวจ Streamlit และใช้ Reboot เมื่อจำเป็น อย่าใช้ force push หรือลบทั้ง repo
5. ถ้าต้องหยุดงานข้อมูลแยกจากการย้อนโค้ด ไป Actions เลือก Update market data (free) → เมนูสามจุด → Disable workflow การ Revert โค้ดไม่ใช่การลบ Release ข้อมูลที่เผยแพร่ไปแล้ว

หาก Revert ติด conflict อย่าล้างไฟล์ทั้งหมดเพื่อหลบปัญหา ให้ตรวจและแก้ความขัดแย้งก่อน

## แหล่งอ้างอิง

- [GitHub: Upload files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
- [GitHub: Download source archives](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)
- [GitHub: Create a pull request](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request)
- [GitHub: Merge a pull request](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request)
- [GitHub: Run a workflow manually](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
- [GitHub: Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [GitHub: Revert a pull request](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/reverting-a-pull-request)
- [Microsoft: Zip and unzip files](https://support.microsoft.com/en-us/windows/experience/storage-filemanagement/zip-and-unzip-files)
- [Microsoft: File Explorer](https://support.microsoft.com/en-us/windows/experience/fileexplorer/file-explorer-in-windows)
- [Streamlit: Manage app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
- [Streamlit: Reboot](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/reboot-your-app)
- [Streamlit: App settings and Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings)
- [Streamlit: Python version](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python)
