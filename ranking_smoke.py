"""Real board checks. Empty entry lists are valid and must not be filled artificially."""
import re
from playwright.sync_api import expect


def pulse_receipts(board):
    """Capture provider availability and original observation clocks, not fake freshness."""
    status=board.locator('.ranking-pulse-status')
    expect(status).to_have_count(1)
    expect(status).to_have_attribute('data-refresh-seconds','30')
    expect(status).to_have_attribute('data-news-seconds','300')
    expect(status).to_have_attribute('data-scope','published-top10')
    status_data=status.evaluate('(node)=>({...node.dataset})')
    assert status_data.get('state') in {
        'disabled','paused','updating','scheduled','waiting','refreshing','ready',
        'rate_limited','budget','retry','error','partial',
    },status_data
    assert status_data.get('renderedAt'),status_data
    candidates=board.locator('.ranking-pulse-candidate')
    buttons=board.get_by_role('button',name=re.compile(r'^\d{2} · '),include_hidden=True)
    expect(candidates).to_have_count(buttons.count())
    rows=candidates.evaluate_all('(nodes)=>nodes.map(node=>({...node.dataset}))')
    assert [row['ticker'] for row in rows]==[text.split(' · ')[1].strip() for text in buttons.all_text_contents()]
    assert all(row.get('entryIndependent')=='true' and row.get('state') in ('strong','watch','unknown') for row in rows),rows
    return {'provider_state':status_data['state'],'refresh_seconds':30,'news_seconds':300,
            'scope':status_data['scope'],'rendered_at':status_data['renderedAt'],
            'quotes_checked_at':status_data.get('checkedAt') or None,
            'observations':[{'ticker':row['ticker'],'assessment':row['state'],
                             'quote_observed_at':row.get('quoteTime') or None,
                             'news_checked_at':row.get('newsCheckedAt') or None} for row in rows]}


def verify_candidate_detail(board,ticker):
    """Missing/limited providers are valid; explanations must remain usable."""
    title=board.get_by_text('แรงส่งและข่าว · '+ticker,exact=True)
    if not title.is_visible():
        board.get_by_text('เฝ้าดู / รอยืนยัน — ยังไม่ใช่จุดซื้อ',exact=True).click()
    details=title.locator('xpath=ancestor::details[1]')
    if details.get_attribute('open') is None:
        title.click()
    expect(details.get_by_text('ประเมินแรงเก็งกำไรแยกจากคะแนน 100 จุดและสถานะผ่านเงื่อนไขซื้อ',exact=True)).to_be_visible()
    for phrase in ('ราคาเพิ่มขึ้นอย่างน้อย 2%',
                   'แข็งกว่าตลาด SPY อย่างน้อย 1 จุดเปอร์เซ็นต์',
                   'ปริมาณวันนี้อย่างน้อย 1.5 เท่าของค่าเฉลี่ยเต็มวัน'):
        expect(details.get_by_text(re.compile(re.escape(phrase))).first).to_be_visible()
    expect(details.get_by_text('ข่าวที่ผู้ให้ข้อมูลเชื่อมโยงกับหุ้น',exact=True)).to_be_visible()
    expect(details.get_by_text(re.compile('Yahoo Finance · รอบตรวจไม่ใช่อายุราคา'))).to_be_visible()
    links=details.get_by_role('link')
    link_count=links.count()
    assert link_count<=3
    if link_count:
        assert all((url or '').startswith('https://') for url in links.evaluate_all('(nodes)=>nodes.map(node=>node.getAttribute("href"))'))
    else:
        expect(details.get_by_text('ยังไม่มีข่าวที่อ่านและตรวจวันเผยแพร่ได้ ไม่ได้หมายความว่าไม่มีเหตุการณ์ใหม่',exact=True)).to_be_visible()
    # Keep the compact board usable for the existing single-click selection test.
    title.click()
    return {'ticker':ticker,'criteria_explained':3,'news_detail_opened':True,
            'news_links':link_count,'provider_success_required':False}


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
    report['pulse_before']=pulse_receipts(board)
    expect(board.get_by_role('checkbox',name='อัปเดตการประเมินทุก 30 วินาที',exact=True)).to_be_visible()
    if not labels:
        expect(board.get_by_text(re.compile('ยังไม่มีหุ้นผ่านเงื่อนไขซื้อครบ'))).to_be_visible()
        report['empty_is_honest']=True;return report
    report['pulse_detail']=verify_candidate_detail(board,labels[0].split(' · ')[1].strip())
    query=app.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)
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
    # Reuse the existing search/selection waits; never wait for a successful feed
    # or label an honest closed-market / 429 response as fresh market data.
    report['pulse_after']=pulse_receipts(board)
    report.update(first_rank=first,clicked=ticker,chart_bars=len(payload['records']),filter_independent=True,
                  completed_search_before_selection=True,single_click=True,cleared_search_before_return=True)
    return report
