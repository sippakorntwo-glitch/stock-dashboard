"""Backfill queue and persisted provider failure behavior; no live requests."""
from datetime import datetime, timezone
from copy import deepcopy
import pytest
import company_financials_job as job
from dashboard_runtime import DashboardCache


def populated(ticker='OLD'):
    return {'schema':1,'ticker':ticker,'currency':'USD','errors':[],
            'annual':{'income':[{'end':'2025-12-31','values':{'revenue':100}}]},
            'quarterly':{},'observations':{'revenue':{'value':100,'basis':'FY'}}}


def test_backfill_skips_existing_statements_even_when_their_refresh_is_due():
    names=('OLD','NEW','RETRY','NOCCY','FUND')
    profiles={'info:'+t:({'financialCurrency':'USD'}, {}) for t in names}
    profiles['info:NOCCY']=({}, {})
    statements={'financials:OLD':(populated(),{'fetched_at':'2025-01-01T00:00:00Z','available':True})}
    attempts={'attempt:financials:RETRY':({}, {'retry_after':'2026-10-01T00:00:00Z'})}
    now=datetime(2026,9,13,tzinfo=timezone.utc).timestamp()
    assert job.due_symbols(names,profiles,statements,attempts,{'FUND'},now=now,only_missing=True)==['NEW']
    assert job.due_symbols(names,profiles,statements,attempts,{'FUND'},now=now)==['NEW','OLD']


def test_rate_limit_is_persisted_and_stops_later_batches(tmp_path,monkeypatch):
    cache=DashboardCache(tmp_path/'data.sqlite3')
    for t in ('AAPL','MSFT'):
        cache.put('info:'+t,{'financialCurrency':'USD'}, {})
    calls=[]
    def limited(ticker,info):
        calls.append(ticker)
        raise RuntimeError('429 Too Many Requests')
    monkeypatch.setattr(job,'collect',limited)
    report=job.collect_batch(cache,('AAPL','MSFT'),set(),only_missing=True)
    assert calls==['AAPL'] and report['failed']==1 and report['remaining_due']==1
    assert report['errors'][0]['rate_limited'] is True
    assert cache.get('external:financials-circuit',request_remote=False)[0]['retry_after']==report['cooldown_until']
    retry=job.collect_batch(cache,('AAPL','MSFT'),set(),only_missing=True)
    assert retry['attempted']==0 and calls==['AAPL']
    assert cache.get('financials:AAPL',request_remote=False)[0] is None


def test_partial_refresh_does_not_replace_populated_statements(tmp_path,monkeypatch):
    cache=DashboardCache(tmp_path/'data.sqlite3')
    previous=populated('AAPL')
    cache.put('info:AAPL',{'financialCurrency':'USD'}, {})
    cache.put('financials:AAPL',previous,{'fetched_at':'2020-01-01T00:00:00Z','available':True})
    partial=deepcopy(previous);partial['errors']=['Missing balance sheet']
    partial['annual']['income'][0]['values']['revenue']=999
    monkeypatch.setattr(job,'collect',lambda *args:partial)
    monkeypatch.setattr(job.time,'sleep',lambda _:None)
    report=job.collect_batch(cache,('AAPL',),set())
    assert report['updated']==0 and report['partial_preserved']==['AAPL']
    assert cache.get('financials:AAPL',request_remote=False)[0]==previous


def test_audit_explains_currency_blockers_separately_from_pending_and_funds(tmp_path):
    cache=DashboardCache(tmp_path/'data.sqlite3')
    cache.put('info:PENDING',{'financialCurrency':'USD'}, {})
    cache.put('info:FAILED',{'financialCurrency':'USD'}, {})
    cache.put('attempt:financials:FAILED',{}, {'retry_after':'2026-10-01T00:00:00Z'})
    report,rows=job.audit_all(cache,('NOCCY','PENDING','FAILED','FUND'),{'FUND'})
    status={r['Ticker']:r['Collection Status'] for r in rows}
    assert status=={'NOCCY':'Missing financial currency','PENDING':'Not yet attempted',
                    'FAILED':'Attempted; no usable observations','FUND':'Not applicable'}
    assert report['counts']['companies_without_financial_currency']==1
    assert report['counts']['securities']==4 and report['data_complete'] is False
