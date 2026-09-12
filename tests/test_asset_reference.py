"""No network or synthetic observations enter production; fixtures are tests only."""
from copy import deepcopy
import json
import pandas as pd
import pytest
from asset_semantics import field_state,display_value,adapt_analysis,kind_for
from sec_reference import allowed_url,identity,ticker_index,filing_facts,SecClient


@pytest.mark.parametrize('field',['forwardPE','trailingPE','targetMeanPrice','operatingCashflow'])
def test_physical_gold_does_not_get_corporate_earnings(field):
    assert field_state('AAAU',{field:100},field,is_etf=True)=='not_applicable'
    assert display_value('AAAU',{},field,is_etf=True).startswith('N/A')


@pytest.mark.parametrize('category',['Commodities Focused','Intermediate Core Bond','Long Government Bond','Currency','Digital Assets'])
def test_reported_non_equity_category_not_name_inference(category):
    assert field_state('FUND',{'category':category,'trailingPE':22},'trailingPE',is_etf=True)=='not_applicable'
    assert kind_for('GOLD',{'industry':'Gold'},False)=='company'


def test_gold_miner_and_equity_fund_ratios_are_not_blanket_removed():
    assert field_state('MINER',{'trailingPE':22,'trailingEps':2},'trailingPE')=='available'
    assert field_state('MINERS',{'category':'Equity Precious Metals','trailingPE':22},'trailingPE',is_etf=True)=='available'
    assert field_state('SPY',{'category':'Large Blend','trailingPE':24},'trailingPE',is_etf=True)=='available'
    assert field_state('SPY',{},'forwardPE',is_etf=True)=='pending'


@pytest.mark.parametrize('value',[0,-1,True,float('inf'),float('nan'),'bad'])
def test_invalid_positive_fund_numbers_are_not_displayed_as_valid(value):
    assert field_state('AAAU',{'totalAssets':value},'totalAssets',is_etf=True)=='invalid'


def test_missing_zero_and_loss_are_different_states():
    assert field_state('COMP',{'totalDebt':0},'totalDebt')=='available'
    assert field_state('COMP',{'shortName':'Company'},'forwardPE')=='not_reported'
    assert field_state('COMP',{},'forwardPE')=='pending'
    assert field_state('COMP',{'trailingPE':-10},'trailingPE')=='not_meaningful'
    assert field_state('COMP',{'trailingPE':10,'trailingEps':-1},'trailingPE')=='not_meaningful'
    assert field_state('COMP',{'profitMargins':-.3},'profitMargins')=='available'


def test_analysis_projection_does_not_mutate_prices_or_scoring_input():
    frame=pd.DataFrame([{'ปัจจัย':label,'ค่าล่าสุด':'22x','การแปลผล':'old'} for label in ('Forward P/E','Trailing P/E','Target Price','Beta','RSI (14)')])
    original=frame.copy(deep=True);info={'category':'Commodities Focused','trailingPE':22,'beta3Year':.12};old=deepcopy(info)
    fixed=adapt_analysis(frame,'AAAU',info,True)
    assert fixed.iloc[:3]['ค่าล่าสุด'].str.startswith('N/A').all()
    assert fixed.iloc[-1].equals(frame.iloc[-1])
    pd.testing.assert_frame_equal(frame,original);assert info==old
    equity=adapt_analysis(frame,'SPY',{'trailingPE':22},True)
    assert equity.iloc[1]['ปัจจัย']=='Portfolio Trailing P/E'
    assert equity.iloc[1]['ค่าล่าสุด']=='22x'


@pytest.mark.parametrize('url',['http://www.sec.gov/files/company_tickers.json','https://example.com/submissions/CIK0000320193.json','https://www.sec.gov@evil.example/files/company_tickers.json','https://data.sec.gov/submissions/CIK0000320193.json?token=bad'])
def test_unreviewed_endpoints_are_refused(url):
    assert not allowed_url(url)


def test_sec_identity_verification_and_aliases():
    sample={'cik':'1067983','tickers':['BRK-A','BRK-B'],'name':'Berkshire','sic':'6331','sicDescription':'Insurance'}
    assert identity(sample,'BRK.B',1067983)['sic']=='6331'
    with pytest.raises(ValueError):identity(sample,'AAPL',1067983)
    with pytest.raises(ValueError):identity(sample,'BRK-B',320193)
    assert identity({**sample,'sic':'0000'},'BRK-B',1067983)['sic_description'] is None


def test_duplicate_ticker_cik_mapping_is_not_guessed():
    rows={str(i):{'ticker':f'T{i}','cik_str':i+1,'title':'Fixture'} for i in range(105)}
    rows['dup']={'ticker':'T1','cik_str':555,'title':'Ambiguous'}
    result=ticker_index(rows)
    assert 'T1' not in result and len(result)==104


def observation(value,*,start='2025-01-01',end='2025-12-31',filed='2026-02-01',accn='0000320193-26-000001',form='10-K'):
    row={'val':value,'end':end,'filed':filed,'accn':accn,'form':form}
    if start:row['start']=start
    return row


def facts_document(rows):
    return {'cik':320193,'facts':{'us-gaap':{tag:{'units':{'USD':values}} for tag,values in rows.items()}}}


def test_sec_calculations_use_same_filing_fiscal_period_and_currency():
    source=facts_document({'Revenues':[observation(100)],'NetIncomeLoss':[observation(20)],
        'NetCashProvidedByUsedInOperatingActivities':[observation(30)],'PaymentsToAcquirePropertyPlantAndEquipment':[observation(10)],
        'Assets':[observation(500,start=None)]})
    parsed={r['metric']:r for r in filing_facts(source,320193,'2026-09-12')}
    assert parsed['Net margin (calculated FY)']['value']==20
    assert parsed['Free cash flow (calculated FY)']['value']==20
    assert parsed['Revenue']['basis']=='fiscal-year (not TTM)'
    assert parsed['Total assets']['basis']=='point-in-time'
    assert 'forwardPE' not in parsed


def test_mismatched_filing_or_quarter_never_becomes_derived_annual_value():
    source=facts_document({'Revenues':[observation(100)],'NetIncomeLoss':[observation(20,accn='0000320193-26-000002')],
        'NetCashProvidedByUsedInOperatingActivities':[observation(40,start='2025-10-01')]})
    parsed={r['metric']:r for r in filing_facts(source,320193,'2026-09-12')}
    assert 'Net margin (calculated FY)' not in parsed
    assert 'Operating cash flow' not in parsed
    with pytest.raises(ValueError):filing_facts(source,999)


def test_future_and_ambiguous_sec_facts_are_not_used():
    source=facts_document({'Revenues':[observation(100),observation(110)],'NetIncomeLoss':[observation(20,filed='2027-01-01')]})
    assert filing_facts(source,320193,'2026-09-12')==[]


def test_sec_circuit_stops_after_forbidden_response(monkeypatch):
    import requests
    class Response:
        status_code=403
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):raise requests.HTTPError('Forbidden')
    class Session:
        def __init__(self):self.calls=0
        def get(self,*args,**kwargs):self.calls+=1;return Response()
    monkeypatch.setattr('sec_reference.time.sleep',lambda _:None)
    session=Session();client=SecClient(session)
    with pytest.raises(requests.HTTPError):client.get('https://www.sec.gov/files/company_tickers.json')
    with pytest.raises(RuntimeError):client.get('https://data.sec.gov/submissions/CIK0000320193.json')
    assert session.calls==1 and client.blocked


def test_only_reference_objects_follow_the_normal_checked_shard_roundtrip(tmp_path):
    import dashboard_runtime as a
    from data_sync import ObjectStore,SnapshotReader
    from update_data import publish_snapshot
    source=a.DashboardCache(tmp_path/'source.sqlite3')
    value={'cik':320193,'source':'SEC EDGAR','facts':[]}
    source.put('reference:AAPL',value,{'fetched_at':'2026-09-12T10:00:00Z'})
    store=ObjectStore({'backend':'local','DASHBOARD_SNAPSHOT_DIR':str(tmp_path/'snapshots')},writable=True)
    manifest=publish_snapshot(store,source,('AAPL',),{},None)
    target=a.DashboardCache(tmp_path/'reader.sqlite3');reader=SnapshotReader(store,target)
    reader._sync();reader._details('AAPL')
    restored,_=target.get('reference:AAPL',request_remote=False)
    assert restored==value
    assert target.get('info:AAPL',request_remote=False)[0] is None
    assert manifest['coverage']['universe']==1
