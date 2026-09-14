"""Interaction checks for the research release, used by CI and production gates."""
from __future__ import annotations

from playwright.sync_api import expect


def verify_research_features(page, app, ticker):
    from production_smoke import open_research_expander, wait_page_ready, no_exception
    wait_page_ready(app,ticker)
    report = {}
    expect(app.get_by_role('heading',name='สรุปเพื่อเริ่มวิเคราะห์',exact=True)).to_be_visible()
    expect(app.locator('.selected-context strong')).to_have_text(ticker)
    modes = app.get_by_role('radiogroup',name='มุมมองการวิเคราะห์',exact=True)
    for mode in ('ลงทุนระยะยาว','จังหวะซื้อขาย','ภาพรวม'):
        modes.get_by_text(mode,exact=True).click()
        wait_page_ready(app,ticker)
        expect(modes.get_by_role('radio',name=mode,exact=True)).to_be_checked()
    report['modes_preserve_ticker'] = True
    open_research_expander(app,'เปิดรายละเอียดพื้นฐานและปันผล')
    trends = app.locator('.st-key-financial_trends')
    expect(trends).to_be_visible()
    basis = trends.get_by_role('radiogroup',name='รอบบัญชีของกราฟ',exact=True)
    if basis.count():
        labels = basis.locator('label').all_text_contents()
        # Every offered source period is exercised. Missing periods are not invented.
        for radio in basis.get_by_role('radio').all():
            radio.check()
            wait_page_ready(app,ticker)
        basis.get_by_role('radio').first.check()
        wait_page_ready(app,ticker)
        report['financial_periods'] = labels
    else:
        report['financial_periods'] = 'source unavailable, explicit state displayed'
    open_research_expander(app,'เปิดสถานการณ์ราคา')
    expect(app.get_by_role('heading',name='ประเมินราคาหลายสถานการณ์',exact=True)).to_be_visible()
    horizon=app.get_by_role('spinbutton',name='ระยะประมาณการ (ปี)',exact=True)
    if horizon.count():
        old=horizon.input_value()
        horizon.fill('6');horizon.press('Enter');wait_page_ready(app,ticker)
        expect(horizon).to_have_value('6')
        horizon.fill(old);horizon.press('Enter');wait_page_ready(app,ticker)
        report['valuation_editable'] = True
    else:
        report['valuation_editable'] = 'source unavailable, manual input offered'
    open_research_expander(app,'เปิดตารางคู่แข่ง')
    expect(app.get_by_role('heading',name='เปรียบเทียบพื้นฐานกับคู่แข่ง',exact=True)).to_be_visible()
    report['peers_visible'] = True
    open_research_expander(app,'ชุดวิเคราะห์และบันทึกส่วนตัว')
    component = None
    for frame in page.frames:
        if frame.locator('#workspace-name').count():
            component = frame
            break
    assert component is not None, 'Private workspace component was not rendered'
    expect(component.locator('#save')).to_be_enabled(timeout=30000)
    name='CI research verification'
    component.locator('#workspace-name').fill(name)
    query=app.get_by_role('textbox',name='ค้นหาสัญลักษณ์ / ชื่อบริษัท',exact=True)
    old_query=query.input_value()
    component.locator('#save').click()
    expect(component.locator('#status')).to_contain_text('ในเบราว์เซอร์นี้แล้ว')
    query.fill('NO-MATCH-RESEARCH-CHECK');query.press('Enter')
    wait_page_ready(app,ticker,'NO-MATCH-RESEARCH-CHECK')
    component.locator('#workspace-list').select_option(label=name)
    component.locator('#load').click()
    wait_page_ready(app,ticker,old_query)
    expect(query).to_have_value(old_query)
    report['private_workspace_restores_filters'] = True
    # Remove only the record created by this isolated verification browser.
    page.once('dialog',lambda dialog:dialog.accept())
    component.locator('#delete').click()
    expect(component.locator('#status')).to_contain_text('ลบชุดที่เลือกแล้ว')
    no_exception(app)
    return report
