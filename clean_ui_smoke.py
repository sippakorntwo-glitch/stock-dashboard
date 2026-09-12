"""Public UI expectations; diagnostics continue to be verified through backend data."""
from playwright.sync_api import expect

HIDDEN_HEADERS={'ข้อมูลอ้างอิง','แหล่งข้อมูล','ฟิลด์ต้นทาง','สถานะข้อมูล'}


def verify_industry_placement(app):
    control=app.locator('.st-key-overview_controls [data-testid="stMultiSelect"]').filter(
        has=app.get_by_text('Industry / ETF Category',exact=True))
    expect(control).to_have_count(1)
    expect(control).to_be_visible()
    assert control.evaluate('(e)=>e.closest("[data-testid=stExpander]")===null'), 'Industry still inside Advanced Filters'
    expect(app.get_by_role('textbox',name='Search Ticker / Company',exact=True)).to_have_count(1)
    return True


def verify_clean_presentation(app):
    expect(app.locator('.st-key-research_health')).to_have_count(0)
    expect(app.get_by_role('heading',name='สถานะข้อมูลและระบบ',exact=True)).to_have_count(0)
    expect(app.get_by_role('heading',name='รายงานความครบของข้อมูลทุกส่วน',exact=True)).to_have_count(0)
    expect(app.locator('a[href="#system-status"]')).to_have_count(0)
    expect(app.locator('[data-testid="stJson"]')).to_have_count(0)
    for label in ('ดาวน์โหลดรายงานความครบทุกฟิลด์','ดาวน์โหลดสถานะข้อมูลครบทุกหุ้น'):
        expect(app.get_by_role('button',name=label,exact=True)).to_have_count(0)
    headers=[s.strip() for s in app.locator('.workspace-help-table th').all_text_contents()]
    assert headers and not HIDDEN_HEADERS.intersection(headers), headers
    names=app.locator('[data-testid="stExpander"] summary').all_text_contents()
    assert not any('ตรวจข้อมูลที่ขาดของ ' in text for text in names)
    verify_industry_placement(app)
    return {'industry_dropdown_top_level':True,'source_columns_removed':True,
            'diagnostics_ui_removed':True,'headers_checked':len(headers)}
