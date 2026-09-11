import os
import pytest

@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires real Streamlit')
def test_old_selected_return_date_is_clamped_to_current_verified_history():
    from streamlit.testing.v1 import AppTest
    script='''
from datetime import date
import pandas as pd
import streamlit as st
from return_audit_ui import render_return_audit
st.session_state['return_audit_date_AAPL']=date(2027,1,1)
h=pd.DataFrame({'Close':[100.,110.,120.]},index=pd.to_datetime(['2026-09-07','2026-09-08','2026-09-09']))
render_return_audit('AAPL',h,{'Price_AsOf':'2026-09-09'})
'''
    at=AppTest.from_string(script,default_timeout=15).run()
    assert not at.exception,str(at.exception)
    assert str(at.date_input[0].value)=='2026-09-09'
