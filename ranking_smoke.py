"""Real board checks. Empty entry lists are valid and must not be filled artificially."""
import re
from playwright.sync_api import expect


def verify_board(page,app):
    from production_smoke import chart_for_symbol,no_exception,wait_page_ready
    from quality_smoke import public_summary
    _,source=public_summary();total=len(source['universe'])
    board=app.locator('.st-key-ranking_board')
    expect(board.get_by_role('heading',name='Top 10 · จังหวะเข้าซื้อ')).to_be_visible(timeout=60000)
    expect(board.get_by_text(re.compile(re.escape(f'ตรวจ {total:,}/{total:,} รายชื่อ')))).to_be_visible(timeout=120000)
    expect(board.get_by_text('ผ่านโมเดล ณ เวลาตรวจ ไม่ใช่การรับประกันกำไร',exact=True)).to_be_visible()
    # Exercise a REAL public candidate when available; no synthetic watchlist or entry.
    buttons=board.get_by_role('button',name=re.compile(r'^\d{2} · '))
    labels=buttons.all_text_contents()
    assert len(labels)<=10 and len(set(labels))==len(labels)
    report={'title':'Top 10 · จังหวะเข้าซื้อ','catalog_scanned':total,'rows':len(labels),
            'entry_rows':sum('ผ่าน ณ เวลาตรวจ' in x for x in labels),
            'watch_rows':sum('เฝ้าดู ไม่ใช่จุดซื้อ' in x for x in labels),'refresh_schedule':'7,37 * * * *'}
    if not labels:
        expect(board.get_by_text(re.compile('ยังไม่มีหุ้นผ่านเงื่อนไขซื้อครบ'))).to_be_visible()
        report['empty_is_honest']=True;return report
    query=app.get_by_role('textbox',name='Search Ticker / Company',exact=True)
    field=app.locator('[data-testid="stSidebar"]').get_by_role('textbox',name='Ticker สำหรับวิเคราะห์',exact=True)
    previous_ticker=field.input_value()
    sentinel='NO-MATCH-FOR-RANK-TEST'
    query.fill(sentinel);query.press('Enter')
    # The board and filtered export render before the research sections. Wait
    # for this exact search to finish before sending the single board click.
    wait_page_ready(app,previous_ticker,query=sentinel)
    expect(query).to_have_value(sentinel)
    expect(board.get_by_text(re.compile(re.escape(f'ตรวจ {total:,}/{total:,} รายชื่อ')))).to_be_visible()
    assert [x.split(' · ')[1] for x in buttons.all_text_contents()]==[x.split(' · ')[1] for x in labels]
    first=labels[0];ticker=first.split(' · ')[1].strip()
    if not buttons.first.is_visible():
        board.get_by_text('เฝ้าดู / รอยืนยัน — ยังไม่ใช่จุดซื้อ',exact=True).click()
    buttons.first.scroll_into_view_if_needed();buttons.first.click()
    # Selection preserves the search. Use the existing completed-page budget,
    # then require the input and real chart to agree with the clicked ticker.
    wait_page_ready(app,ticker,query=sentinel)
    expect(field).to_have_value(ticker,timeout=30000)
    chart,payload=chart_for_symbol(page,app,ticker)
    assert payload['ticker']==ticker and not payload['demo'];no_exception(app)
    query.fill('');query.press('Enter')
    wait_page_ready(app,ticker,query='')
    expect(query).to_have_value('')
    report.update(first_rank=first,clicked=ticker,chart_bars=len(payload['records']),filter_independent=True,
                  completed_search_before_selection=True,single_click=True,cleared_search_before_return=True)
    return report
