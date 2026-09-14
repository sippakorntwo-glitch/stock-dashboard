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
