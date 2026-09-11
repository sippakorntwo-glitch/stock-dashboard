"""Actual public/CI board interaction; no stock-selection state injection."""
import re
from playwright.sync_api import expect


def verify_board(page,app):
    from production_smoke import chart_for_symbol,no_exception
    board=app.locator('.st-key-ranking_board')
    expect(board.get_by_role('heading',name='Top 10 · น่าจับตาซื้อ')).to_be_visible(timeout=60000)
    expect(board.get_by_text(re.compile(r'ตรวจ 4,900/4,900 รายชื่อ'))).to_be_visible(timeout=120000)
    buttons=board.get_by_role('button',name=re.compile(r'^\d{2} · '))
    assert 1<=buttons.count()<=10,'Actual ranking must be populated for this deployment verification'
    labels=buttons.all_text_contents()
    assert len(set(labels))==len(labels)
    first=labels[0];ticker=first.split(' · ')[1].strip()
    # The board is on the top right; changing table filters must not change its universe.
    query=app.get_by_role('textbox',name='ค้นหา Ticker / บริษัท / อุตสาหกรรม',exact=True)
    query.fill('NO-MATCH-FOR-RANK-TEST');query.press('Enter')
    page.wait_for_timeout(1000)
    expect(board.get_by_text(re.compile(r'ตรวจ 4,900/4,900 รายชื่อ'))).to_be_visible()
    assert buttons.all_text_contents()==labels
    buttons.first.scroll_into_view_if_needed();buttons.first.click()
    expect(app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)).to_have_value(ticker,timeout=30000)
    chart,payload=chart_for_symbol(page,app,ticker)
    assert payload['ticker']==ticker and not payload['demo']
    no_exception(app)
    query.fill('');query.press('Enter')
    return {'title':'Top 10 · น่าจับตาซื้อ','catalog_scanned':4900,'rows':len(labels),
            'first_rank':first,'clicked':ticker,'chart_bars':len(payload['records']),
            'filter_independent':True,'refresh_schedule':'7,37 * * * *'}
