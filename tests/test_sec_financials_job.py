"""Collector integration: real parser on explicit fixtures, no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from dashboard_runtime import DashboardCache
from sec_reference import INDEX_URL
from sec_financials_job import collect_batch
from sec_financials_job import release_access_pause


def seed(cache, ticker='AARD', currency='USD'):
    cache.put('info:'+ticker, {'financialCurrency':currency}, {})
    bundle={'schema':1,'ticker':ticker,'currency':currency,'errors':[],
            'fetched_at':'2026-09-01T00:00:00Z',
            'annual':{'income':[{'end':'2025-12-31','values':{'revenue':100,'grossProfit':None}}]},
            'quarterly':{}}
    cache.put('financials:'+ticker,bundle,{'fetched_at':bundle['fetched_at'],'available':True})
    return bundle


def mapping():
    rows={str(i):{'ticker':'T'+str(i),'cik_str':i+1,'title':'Fixture'} for i in range(100)}
    rows['AARD']={'ticker':'AARD','cik_str':1774857,'title':'Fixture'}
    return rows


def facts():
    value={'val':40,'start':'2025-01-01','end':'2025-12-31','filed':'2026-03-01',
           'form':'10-K','accn':'0001774857-26-000001'}
    return {'cik':1774857,'facts':{'us-gaap':{'GrossProfit':{'units':{'USD':[value]}}}}}


class Client:
    max_requests=100
    def __init__(self, *, deny=False, mismatch=False):
        self.calls=0;self.blocked=False;self.evidence=[];self.urls=[]
        self.deny=deny;self.mismatch=mismatch
    def get(self,url):
        self.calls+=1;self.urls.append(url)
        if self.deny:
            self.blocked=True
            raise RuntimeError('403 Access denied')
        if url==INDEX_URL:return mapping()
        if '/submissions/' in url:
            return {'cik':1774857,'tickers':['WRONG' if self.mismatch else 'AARD']}
        return facts()


def test_missing_cell_recovery_preserves_provider_date_and_schedules_separate_sec_attempt(tmp_path):
    cache=DashboardCache(tmp_path/'cache.db');before=seed(cache);client=Client()
    report=collect_batch(cache,['AARD'],set(),client=client)
    assert report['checked']==report['updated']==report['filled_cells']==1
    assert report['conflicting_cells']==0 and report['remaining_due']==0
    value,meta=cache.get('financials:AARD',request_remote=False)
    row=value['annual']['income'][0]
    assert row['values']=={'revenue':100,'grossProfit':40}
    assert row['field_provenance']['grossProfit']['source']=='SEC EDGAR'
    assert value['fetched_at']==before['fetched_at']
    assert value['sec_reconciliation']['checked_at']==meta['fetched_at']
    assert value['observations']['grossProfit']['value']==40
    assert cache.get('attempt:financials:AARD',request_remote=False)[0] is None
    again=collect_batch(cache,['AARD'],set(),client=Client())
    assert again['attempted']==0 and again['provider_requests']==0


def test_verified_ticker_identity_precedes_companyfacts_request(tmp_path):
    cache=DashboardCache(tmp_path/'cache.db');before=seed(cache);client=Client(mismatch=True)
    result=collect_batch(cache,['AARD'],set(),client=client)
    assert result['failed']==1 and result['filled_cells']==0
    assert not any('/companyfacts/' in u for u in client.urls)
    assert cache.get('financials:AARD',request_remote=False)[0]==before
    assert cache.get('attempt:sec-financials:AARD',request_remote=False)[1]['success'] is False


def test_access_denial_persists_shared_circuit_and_next_batch_makes_no_requests(tmp_path):
    cache=DashboardCache(tmp_path/'cache.db');before=seed(cache);client=Client(deny=True)
    result=collect_batch(cache,['AARD'],set(),client=client)
    assert result['provider_requests']==1 and result['cooldown_until']
    assert cache.get('external:sec-circuit',request_remote=False)[0]['next_attempt_after']==result['cooldown_until']
    next_client=Client()
    next_result=collect_batch(cache,['AARD'],set(),client=next_client)
    assert next_client.calls==next_result['provider_requests']==0
    assert cache.get('financials:AARD',request_remote=False)[0]==before


def test_funds_and_unknown_or_conflicting_statement_currency_never_receive_substitutions(tmp_path):
    cache=DashboardCache(tmp_path/'cache.db');before=seed(cache)
    seed(cache,'T1',None);seed(cache,'T2','EUR')
    cache.put('info:T2',{'financialCurrency':'USD'}, {})
    client=Client()
    result=collect_batch(cache,['AARD','T1','T2'],{'AARD'},client=client)
    assert result['attempted']==0 and client.calls==1
    assert cache.get('financials:AARD',request_remote=False)[0]==before


def test_source_conflicts_are_reported_without_overwriting_original_observations(tmp_path):
    cache=DashboardCache(tmp_path/'cache.db');before=seed(cache)
    before['annual']['income'][0]['values']['grossProfit']=42
    cache.put('financials:AARD',before,{'fetched_at':before['fetched_at']})
    result=collect_batch(cache,['AARD'],set(),client=Client())
    assert result['checked']==1 and result['updated']==0 and result['conflicting_cells']==1
    value=cache.get('financials:AARD',request_remote=False)[0]
    assert value['annual']['income'][0]['values']['grossProfit']==42
    assert value['sec_reconciliation']['conflicts'][0]['sec_value']==40


def test_observed_release_denial_expires_automatically_and_is_persisted_without_network(tmp_path,monkeypatch):
    incident=release_access_pause(now=datetime(2026,9,14,10,tzinfo=timezone.utc))
    assert incident['http_status']==403
    assert release_access_pause(now=datetime(2026,9,15,10,tzinfo=timezone.utc)) is None
    monkeypatch.setattr('sec_financials_job.release_access_pause',lambda:incident)
    monkeypatch.setattr('sec_financials_job.SecClient',lambda **_:(_ for _ in ()).throw(AssertionError('No provider access during pause')))
    cache=DashboardCache(tmp_path/'cache.db');seed(cache)
    result=collect_batch(cache,['AARD'],set())
    assert result['guard_updated'] and result['provider_requests']==0
    assert cache.get('external:sec-circuit',request_remote=False)[0]['next_attempt_after']==incident['next_attempt_after']


def test_fully_filled_bundle_keeps_sec_revision_checks_due(tmp_path, monkeypatch):
    import sec_financials_job as job
    cache=DashboardCache(tmp_path/'cache.db');seed(cache)
    first=collect_batch(cache,['AARD'],set(),client=Client())
    assert first['filled_cells']==1
    # Exhausted missing-cell work does not stop future amended-filing checks.
    monkeypatch.setattr(job,'statement_gaps',lambda value: [])
    expired=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    cache.put('attempt:sec-financials:AARD',{},
              {'fetched_at':expired,'retry_after':expired,'success':True})
    again=collect_batch(cache,['AARD'],set(),client=Client())
    assert again['attempted']==again['checked']==1
    assert again['filled_cells']==0


def test_existing_reconciliation_without_sec_fills_is_rechecked_even_without_gaps(tmp_path, monkeypatch):
    import sec_financials_job as job
    cache=DashboardCache(tmp_path/'cache.db');value=seed(cache)
    value['annual']['income'][0]['values']['grossProfit']=42
    value['sec_reconciliation']={'checked_at':'2026-09-01T00:00:00Z'}
    cache.put('financials:AARD',value,{'fetched_at':value['fetched_at']})
    monkeypatch.setattr(job,'statement_gaps',lambda value: [])
    result=collect_batch(cache,['AARD'],set(),client=Client())
    assert result['checked']==1 and result['conflicting_cells']==1
