"""One-time hash-guarded source edits. Removed before merging the feature."""
from pathlib import Path
import hashlib
import textwrap

ROOT=Path(__file__).resolve().parent
EXPECTED={
'dashboard_views.py':'c0f628e3d760600e03d8ebd3b9198904d2d6d613',
'dashboard_ui.py':'3e3fe3c0a25edb1e02f62eb0efad5cd45ef26a0a',
'dashboard_runtime.py':'b20abe1c800af081d6133982c1097e6b5fad5273',
'enhanced_smoke.py':'b3734ba803035290dbffe1d7dcd5b4c2010504d2'}
for name,sha in EXPECTED.items():
    raw=(ROOT/name).read_bytes()
    assert hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()==sha, name+' changed; inspect before migrating'


def change(path,old,new,count=1):
    p=ROOT/path;s=p.read_text()
    assert s.count(old)==count,(path,old,s.count(old))
    p.write_text(s.replace(old,new),encoding='utf-8')

# Split only existing filter presentation from the table; all filter formulas stay intact.
p=ROOT/'dashboard_views.py';s=p.read_text()
begin=s.index('def overview(frame, selectable=False):')
end=s.index('    pages = max(1,math.ceil(len(work)/PAGE_SIZE))',begin)
filters=s[begin:end].replace('def overview(frame, selectable=False):','def filter_universe(frame):',1)
s=s[:begin]+filters+'    return work\n\n\ndef overview(frame, selectable=False, prepared=None):\n    work = filter_universe(frame) if prepared is None else prepared\n    if work is None:\n        return None\n'+s[end:]
p.write_text(s,encoding='utf-8')

change('dashboard_ui.py','from chart_ranges import get_chart_service','from chart_ranges import get_chart_service\nfrom ranking_board import render_board, consume_selection')
change('dashboard_ui.py','original_watchlist, overview,','original_watchlist, overview, filter_universe,')
change('dashboard_ui.py','    cache=a.get_data_cache()\n','    cache=a.get_data_cache()\n    consume_selection(cache)\n')
p=ROOT/'dashboard_ui.py';s=p.read_text()
begin=s.index("    st.title('Stock Research Workspace')")
end=s.index('    st.divider()',begin)
block=s[begin:end]
old="    with st.container(key='research_overview'):\n        work=overview(frame,selectable=True)\n"
assert old in block
block=block.replace(old,"    with st.container(key='overview_controls'):\n        work=filter_universe(frame)\n")
new="    top_left, top_right = st.columns([2.6, 1.15], gap='large')\n    with top_left:\n"+textwrap.indent(block,'    ')+"    with top_right:\n        render_board(cache)\n    with st.container(key='research_overview'):\n        if work is not None:\n            overview(frame, selectable=True, prepared=work)\n"
s=s[:begin]+new+s[end:]
s=s.replace("[data-testid=\"stMetricValue\"]{font-size:1.65rem}</style>","[data-testid=\"stMetricValue\"]{font-size:1.65rem}\n    .st-key-ranking_board [data-testid=\"stVerticalBlock\"]{gap:.25rem}\n    .st-key-ranking_board [data-testid=\"stButton\"] button{min-height:1.9rem;padding:.16rem .5rem}\n    .st-key-ranking_board [data-testid=\"stButton\"] p{font-size:.82rem}\n    .st-key-ranking_board h3{font-size:1.15rem}</style>")
p.write_text(s,encoding='utf-8')
change('dashboard_runtime.py',"APP_VERSION = '2026-09-11.16'","APP_VERSION = '2026-09-11.17'")
change('app.py','2026-09-11.16','2026-09-11.17',count=2)
change('workspace_boot.py',"'chart_performance'","'chart_performance', 'ranking_board', 'ranking_engine'",count=1)
change('enhanced_smoke.py','    return report\n','    from ranking_smoke import verify_board\n    report[\'top10\'] = verify_board(page,app)\n    return report\n')

# Create an initial ranking on deployment before the PUBLIC browser verification.
ranking_job='''  ranking:
    if: ${{ toJSON(github.event.repository.private) == 'false' }}
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: write
    concurrency:
      group: top10-ranking-publication
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -q -r requirements.txt
      - name: Publish whole-catalog Top 10 board
        env:
          DASHBOARD_DATA_REPO: ${{ github.repository }}
          DASHBOARD_GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DASHBOARD_DATA_VISIBILITY: public
          DASHBOARD_DATA_BRANCH: dashboard-data
          PYTHONUNBUFFERED: '1'
        run: python ranking_job.py --publish
'''
change('.github/workflows/deploy_verify.yml','  browser:\n    needs: seed\n',ranking_job+'  browser:\n    needs: [seed, ranking]\n')
# CI evaluates the REAL entire checkpoint, but does not publish or refresh quotes.
change('.github/workflows/full_browser.yml', '      - name: Check public cold reader independently of the browser',
'''      - name: Prepare real whole-catalog ranking for browser verification
        run: python ranking_job.py --no-quote-refresh --output work/top10.json
      - name: Check public cold reader independently of the browser''')
change('.github/workflows/full_browser.yml','          DASHBOARD_CACHE_FILE: work/full-browser.sqlite3',
       '          DASHBOARD_CACHE_FILE: work/full-browser.sqlite3\n          DASHBOARD_RANKING_FILE: work/top10.json')
# Unit tests never use the public ranking endpoint. Each test receives an isolated fixture.
p=ROOT/'tests/conftest.py'
p.write_text(p.read_text()+'''

@pytest.fixture(autouse=True)
def isolated_ranking_feed(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    fixture = {
        'schema': 1, 'model': 'existing-100-point-pullback-v1',
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'counts': {'total':4900, 'scanned':4900, 'evaluated':1, 'candidates':1},
        'items': [{'ticker':'MSFT', 'name':'UNIT TEST FIXTURE', 'score':85, 'coverage':100,
                   'qualified':False, 'ready_at_calculation':False, 'reasons':[], 'blockers':[]}]
    }
    path = tmp_path / 'ranking-unit-fixture.json'
    path.write_text(json.dumps(fixture))
    monkeypatch.setenv('DASHBOARD_RANKING_FILE', str(path))
''',encoding='utf-8')
change('tests/test_ui.py',"        assert at.metric[0].value=='4,900'\n",'''        assert at.metric[0].value=='4,900'
        assert any(h.value=='Top 10 · น่าจับตาซื้อ' for h in at.subheader)
        at.button(key='ranking_pick_MSFT').click().run()
        assert not at.exception,str(at.exception)
        assert at.sidebar.text_input(key='ticker_input').value=='MSFT'
        at.sidebar.text_input(key='ticker_input').set_value('AAPL').run()
''')
with (ROOT/'README.md').open('a',encoding='utf-8') as f:
    f.write('''

## v17: บอร์ด Top 10 ด้านขวาบน — รอบ 30 นาที

บอร์ด **Top 10 · น่าจับตาซื้อ** คลิกแล้วเปลี่ยนหุ้นและกราฟหน้าเดียว ตัวกรองส่วนบุคคลไม่เปลี่ยนทะเบียนที่ใช้จัดอันดับ ตารางคะแนนใช้โมเดล 100 จุดเดิม ไม่ใช่ความน่าจะเป็นกำไรหรือคำสั่งซื้อ อันดับไม่ใช่พอร์ตที่กระจายความเสี่ยงแล้ว

`Refresh Top 10 board (30 minutes)` ตั้ง cron `7,37 * * * *` ทุกวัน (นาที :07 และ :37 ของทุกชั่วโมงไทยเช่นกัน) ทำงานแม้ไม่มีคนเปิดเว็บ แต่เวลาเริ่มจริงอาจล่าช้าหรือข้ามรอบตาม GitHub Actions: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule หน้าเว็บตรวจไฟล์บอร์ดใหม่ทุก 60 วินาทีเมื่อเซสชันเปิดอยู่ โดยไม่โหลดกราฟใหม่ทั้งหน้าเพียงเพื่ออัปเดตบอร์ด

อ่าน checkpoint ที่ตรวจ SHA-256 แล้ว ประเมินสมาชิกทั้งทะเบียนหุ้นและ ETF ไม่ใช้เฉพาะหน้าตาราง/หุ้นที่ผู้ชมเคยเปิดดู พิจารณาข้อมูลรายวันล่าสุดที่มี ไม่ได้ดึงราคาใหม่ทั้ง 4,900 ตัวทุกครึ่งชั่วโมง ระหว่างช่วงนาฬิกาตลาดปกติสหรัฐ ตรวจข้อมูล Yahoo ของตัวคัดเลือกไม่เกิน 20 ตัวแล้วจัดอันดับทั้งทะเบียนอีกครั้ง; นอกช่วงเวลาดังกล่าวไม่ดึง quote เพิ่ม แสดงเวลาคำนวณ เวลาข้อมูลรายวัน เวลาของ quote และจำนวนที่ขาด/ถูกคัดออกแยกกัน

เกณฑ์คุณภาพ: หุ้น/ETF ที่มีข้อมูลสกุล USD, ราคา ≥1, ค่าเฉลี่ยราคาปรับแล้ว×Volume 20 วัน ≥1 ล้าน USD, ≥200 แท่ง และราคาล่าสุดไม่เกิน 4 วันปฏิทิน ไม่ใช่ปฏิทินตลาด ตัดบริษัท Shell และกองทุนทด/ผกผันที่ตรวจพบ กลุ่มเฝ้าดูต้องคะแนน ≥60 แนวโน้มขึ้นและ R:R เป็นบวก; กลุ่มผ่านแผนต้องคะแนน ≥80 ข้อมูลครบ R:R ≥2 อยู่ในโซนราคาและ quote อายุ ≤15 นาทีด้วย หากเข้าเงื่อนไขไม่ถึงสิบตัวจะแสดงตามจริง

สถานะผ่านแผนหมดอายุเองเมื่อ quote เกิน 15 นาที แม้รอบจัดอันดับยังไม่ถึง 30 นาที บอร์ดเกิน 35 นาทีเตือนข้อมูลเก่า; โหลด/คำนวณล้มเหลวไม่ประทับเวลาใหม่ให้ข้อมูลเดิม ผลเผยแพร่เป็น JSON เล็กที่ `dashboard-rankings/top10.json` บน branch `dashboard-rankings` แยกจาก snapshot และ main หน้าเว็บไม่ถือ token เขียน GitHub

คะแนนหลังคลิกหุ้นอาจเปลี่ยนตามชุดข้อมูลใหม่; บอร์ดระบุเวลาที่คำนวณเสมอ เมื่อเลือกจากบอร์ด ข้อมูลพื้นฐานสาธารณะที่ใหม่กว่าจะถูกนำมาใช้ในรายละเอียดโดยไม่ย้อนทับข้อมูลที่ใหม่กว่า ไม่ลบ CSV, snapshot เดิม หรือประวัติสำหรับย้อนกลับ
''')
print('TOP10_SOURCE_EDITS_APPLIED')
