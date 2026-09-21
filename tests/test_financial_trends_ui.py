"""Exercise the actual Streamlit trend panel and retained research tables."""
from streamlit.testing.v1 import AppTest


def app():
    import streamlit as st
    from company_analysis_ui import render_company_research
    from tests.test_financial_trends import fixture, quarters
    ticker = st.selectbox('หุ้นทดสอบ', ['TEST', 'NEXT', 'EMPTY'])
    bundle = quarters(fixture()) if ticker != 'EMPTY' else None
    if bundle:
        bundle['ticker'] = ticker
    render_company_research(ticker, {'financialCurrency': 'USD'}, bundle)


def test_basis_topic_switch_and_missing_symbol_preserve_existing_detail():
    at = AppTest.from_function(app, default_timeout=30).run()
    assert not at.exception
    assert any('วิเคราะห์ข้อมูลการเงินบริษัท' in header.value for header in at.subheader)
    assert any(block.value.count('data-metric=') == 54 and 'data-metric="grossMargins"' in block.value
               for block in at.get('html'))
    annual = next(item for item in at.expander if item.label == 'งบการเงินย้อนหลัง — สูงสุด 4 ปีบัญชี')
    assert annual.proto.expanded is False
    basis = next(widget for widget in at.radio if widget.label == 'รอบบัญชีของกราฟ')
    basis.set_value('TTM').run()
    assert not at.exception
    assert next(widget for widget in at.radio if widget.label == 'รอบบัญชีของกราฟ').value == 'TTM'
    topic = next(widget for widget in at.selectbox if widget.label == 'หัวข้อกราฟการเงิน')
    topic.select('ผู้ถือหุ้นและการซื้อหุ้นคืน').run()
    assert not at.exception
    assert len(at.get('plotly_chart')) == 2
    assert any('ไม่รวม EPS' in caption.value for caption in at.caption)
    at.selectbox[0].select('NEXT').run()
    assert not at.exception
    assert next(widget for widget in at.radio if widget.label == 'รอบบัญชีของกราฟ').value == 'FY'
    at.selectbox[0].select('EMPTY').run()
    assert not at.exception
    assert any('ยังไม่มีชุดงบ' in item.value for item in at.info)
    assert len(at.get('plotly_chart')) == 0


def conflict_app():
    from company_analysis_ui import render_company_research
    from tests.test_financial_provenance import bundle
    value = bundle()
    balance = value['annual']['balance'][0]
    balance['values']['totalLiabilities'] = 132_150_000
    value['sec_reconciliation'] = {'conflicts': [{
        'period': 'annual', 'statement': 'balance', 'end': balance['end'],
        'field': 'totalLiabilities', 'provider_value': 132_150_000, 'sec_value': 5_394_000,
        'currency': 'USD', 'tag': 'us-gaap:Liabilities', 'filed': '2026-02-15',
        'url': 'https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/'}]}
    render_company_research('TEST', {'financialCurrency': 'USD'}, value)


def test_conflict_warning_remains_outside_collapsed_source_details():
    at = AppTest.from_function(conflict_app, default_timeout=30).run()
    assert not at.exception
    assert len(at.warning) == 1 and 'พักใช้' in at.warning[0].value
    detail = next(item for item in at.expander if item.label == 'ตรวจรายการที่แหล่งข้อมูลรายงานต่างกัน')
    assert detail.proto.expanded is False and not detail.warning
    assert any('132,150,000.0 USD' in block.value and '5,394,000.0 USD' in block.value
               for block in detail.get('html'))
