"""Real board checks. Empty entry lists are valid and must not be filled artificially."""
import re
from playwright.sync_api import expect


def verify_board(page,app):
    from production_smoke import chart_for_symbol,no_exception
    board=app.locator('.st-key-ranking_board')
    expect(board.get_by_role('heading',name='Top 10 · จังหวะเข้าซื้อ')).to_be_visible(timeout=60000)
    expect(board.get_by_text(re.compile(r'ตรวจ 4,900/4,900 รายชื่อ'))).to_be_visible(timeout=120000)
    expect(board.get_by_text('ผ่านโมเดล ณ เวลาตรวจ ไม่ใช่การรับประกันกำไร',exact=True)).to_be_visible()
    # Exercise a REAL public candidate when available; no synthetic watchlist or entry.
    buttons=board.get_by_role('button',name=re.compile(r'^\d{2} · '))
    labels=buttons.all_text_contents()
    assert len(labels)<=10 and len(set(labels))==len(labels)
    report={'title':'Top 10 · จังหวะเข้าซื้อ','catalog_scanned':4900,'rows':len(labels),
            'entry_rows':sum('ผ่าน ณ เวลาตรวจ' in x for x in labels),
            'watch_rows':sum('เฝ้าดู ไม่ใช่จุดซื้อ' in x for x in labels),'refresh_schedule':'7,37 * * * *'}
    if not labels:
        expect(board.get_by_text(re.compile('ยังไม่มีหุ้นผ่านเงื่อนไขซื้อครบ'))).to_be_visible()
        report['empty_is_honest']=True;return report
    query=app.get_by_role('textbox',name='ค้นหา Ticker / บริษัท / อุตสาหกรรม',exact=True)
    query.fill('NO-MATCH-FOR-RANK-TEST');query.press('Enter');page.wait_for_timeout(1000)
    expect(board.get_by_text(re.compile(r'ตรวจ 4,900/4,900 รายชื่อ'))).to_be_visible()
    assert [x.split(' · ')[1] for x in buttons.all_text_contents()]==[x.split(' · ')[1] for x in labels]
    first=labels[0];ticker=first.split(' · ')[1].strip()
    if not buttons.first.is_visible():
        board.get_by_text('เฝ้าดู / รอยืนยัน — ยังไม่ใช่จุดซื้อ',exact=True).click()
    buttons.first.scroll_into_view_if_needed();buttons.first.click()
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)).to_have_value(ticker,timeout=30000)
    chart,payload=chart_for_symbol(page,app,ticker)
    assert payload['ticker']==ticker and not payload['demo'];no_exception(app)
    query.fill('');query.press('Enter')
    report.update(first_rank=first,clicked=ticker,chart_bars=len(payload['records']),filter_independent=True)
    return report
