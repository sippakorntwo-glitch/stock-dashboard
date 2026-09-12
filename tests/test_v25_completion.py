from copy import deepcopy
import json
import pytest
from asset_semantics import field_state,display_value,safe_numeric_profile


@pytest.mark.parametrize('eps',[0,-1,-100.5])
@pytest.mark.parametrize('reported',[None,10,'Infinity'])
def test_nonpositive_earnings_are_not_mislabeled_as_a_missing_pe(eps,reported):
    info={'trailingEps':eps,'trailingPE':reported}
    assert field_state('TEST',info,'trailingPE')=='not_meaningful'
    assert display_value('TEST',info,'trailingPE')=='N/M — Non-positive earnings'
    assert safe_numeric_profile(info,'TEST')['trailingPE'] is None


def test_portfolio_pe_never_uses_corporate_eps_or_manufactures_gold_earnings():
    info={'quoteType':'ETF','category':'Large Blend','trailingPE':25,'trailingEps':-1}
    assert field_state('SPY',info,'trailingPE',is_etf=True)=='available'
    assert field_state('AAAU',info,'trailingPE',is_etf=True)=='not_applicable'


def test_invalid_inputs_cannot_award_fundamental_points(monkeypatch):
    import dashboard_runtime as app
    original={'symbol':'TEST','forwardPE':True,'targetMeanPrice':0,'trailingPE':20,'trailingEps':-1}
    before=deepcopy(original);seen=[]
    monkeypatch.setattr(app,'_base_criteria_score',lambda ctx,info,is_etf:seen.append(info) or {'score':0})
    assert app.criteria_score({'metrics':{}},original,False)=={'score':0}
    assert seen[0]['forwardPE'] is None and seen[0]['targetMeanPrice'] is None
    assert seen[0]['trailingPE'] is None and original==before


def test_valid_calculation_inputs_and_negative_cashflow_are_preserved():
    valid={'regularMarketPrice':10,'regularMarketTime':1700000000,'forwardPE':12,
           'forwardEps':1,'totalDebt':0,'freeCashflow':-1000,'profitMargins':-.2}
    assert safe_numeric_profile(valid,'TEST')==valid


def test_unusable_quote_does_not_become_an_entry_price():
    import dashboard_runtime as app
    original={'regularMarketPrice':-10,'regularMarketTime':True}
    ctx=app.decision_context(None,original)
    assert ctx['quote'] is None and ctx['quote_time'] is None
    assert original=={'regularMarketPrice':-10,'regularMarketTime':True}


def test_prepared_filters_quarantine_invalid_numbers_but_retain_raw(tmp_path):
    import dashboard_runtime as app
    from screening import profile_rows
    c=app.DashboardCache(tmp_path/'safe-profile.sqlite3')
    original={'symbol':'TEST','forwardPE':True,'marketCap':-100,'freeCashflow':-7,'currency':'USD'}
    c.put('info:TEST',original,{'fetched_at':'2026-09-12T11:00:00Z'})
    result=profile_rows(c,('TEST',))['TEST']
    assert result['Forward_PE'] is None and result['Market_Cap'] is None
    assert result['Free_Cash_Flow']==-7
    restored,_=c.get('info:TEST',request_remote=False)
    assert restored==original


def test_sec_declares_configured_contact_without_authentication(monkeypatch):
    from sec_reference import SecClient,INDEX_URL
    captured=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,size):yield b'{"test":true}'
    class Session:
        def get(self,url,**kw):captured.append(kw);return Response()
    monkeypatch.setenv('SEC_USER_AGENT','TestProject test@example.org')
    client=SecClient(Session())
    assert client.get(INDEX_URL)=={'test':True}
    assert captured[0]['headers']['User-Agent']=='TestProject test@example.org'
    assert 'Authorization' not in captured[0]['headers']
    assert not captured[0]['allow_redirects']
    with pytest.raises(ValueError):SecClient(Session(),user_agent='bad\r\nHost: other')
