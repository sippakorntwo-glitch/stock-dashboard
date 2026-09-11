"""Ranking integrity and UI-state regressions; no real providers in these tests."""
import json
from pathlib import Path
import pandas as pd
import pytest
from ranking_engine import (SCHEMA, MODEL, utc, fresh, next_scheduled, candidate_exclusion,
                            display_status, sort_candidates, make_payload, rank_all)
from ranking_board import validate_payload, read_ranking
from ranking_job import refresh_shortlist

NOW = '2026-09-11T14:00:00Z'  # Friday 10:00 New York.


def item(ticker='MSFT', **updates):
    row = dict(ticker=ticker, name=ticker+' unit-test fixture', score=85, coverage=100,
               qualified=True, ready_at_calculation=True, rr=2.2, distance_pct=0,
               liquidity=2_000_000, quote_time=utc(NOW).timestamp(), price_asof='2026-09-10',
               reasons=['ราคา > EMA20 > EMA50'], blockers=[])
    row.update(updates)
    return row


def payload(rows=None, now=NOW):
    return make_payload([item()] if rows is None else rows,
                        {'total':4900,'scanned':4900,'evaluated':30,'candidates':20},
                        {}, {'generation':'unit-test-fixture','published_at':NOW}, now=now)


def test_schedule_and_freshness_are_different_clocks():
    assert next_scheduled('2026-09-11T14:08:00Z') == '2026-09-11T14:37:00+00:00'
    assert next_scheduled('2026-09-11T14:38:00Z') == '2026-09-11T15:07:00+00:00'
    assert fresh(NOW, NOW, 900)
    assert not fresh(None, NOW, 900)
    assert not fresh('2026-09-11T14:02:00Z', NOW, 900)


def test_readiness_expires_before_the_next_half_hour_ranking():
    assert display_status(item(), payload(), NOW)[1]
    assert not display_status(item(), payload(), '2026-09-11T14:16:00Z')[1]
    assert 'เก่า' in display_status(item(), payload(), '2026-09-11T14:36:00Z')[0]
    assert not display_status(item(), payload(now='2026-09-12T14:00:00Z'), '2026-09-12T14:00:00Z')[1]
    assert not display_status(item(ready_at_calculation=False), payload(), NOW)[1]


def test_strict_quality_filters():
    row=dict(Asset_Type='Common Stock',Price_AsOf='2026-09-10',Close=10,
             Dollar_Volume_20D=2_000_000,Security_Name='Example',Industry='Technology')
    info={'currency':'USD'}
    assert candidate_exclusion(row,info,NOW)==''
    for field,value in [('Close',.5),('Dollar_Volume_20D',None),('Price_AsOf','2026-01-01'),
                        ('Price_AsOf','2026-09-12'),('Industry','Shell Companies')]:
        assert candidate_exclusion({**row,field:value},info,NOW)
    assert candidate_exclusion(row,{},NOW)
    assert candidate_exclusion(row,{'currency':'THB'},NOW)
    assert candidate_exclusion({**row,'Asset_Type':'ETF','Security_Name':'Example 3x Leveraged'},info,NOW)


def test_ranking_keeps_gaps_and_is_deterministic():
    assert make_payload([],{}, {},{}, now=NOW)['items']==[]
    candidates=[item('Z',ready_at_calculation=False,qualified=False,score=100),item('B'),item('A')]
    ordered=sort_candidates(candidates)
    assert [r['ticker'] for r in ordered]==['A','B','Z']
    assert len(make_payload([item(str(i)) for i in range(12)],{}, {},{},now=NOW)['items'])==10


def test_all_catalog_members_checked_not_only_local_watchlist(monkeypatch):
    import ranking_engine as r
    seen=[]
    class Cache:
        def quotes(self):return {t:{'Ticker':t} for t in ['A','B','C']}
        def classifications(self):return {}
        def history(self,t):return None,{}
        def get(self,*args,**kwargs):return {},{}
    monkeypatch.setattr(r,'candidate_exclusion',lambda *args:'')
    def evaluate(t,*args):seen.append(t);return item(t)
    monkeypatch.setattr(r,'evaluate',evaluate)
    rows,counts,excluded=rank_all(Cache(),['A','B','C','MISSING'],now=NOW)
    assert seen==['A','B','C'] and counts['scanned']==counts['total']==4
    assert excluded['missing_summary']==1 and len(rows)==3


def test_payload_rejects_corruption_and_duplicate_symbols():
    assert validate_payload(payload())['model']==MODEL
    for update in [{'schema':99},{'items':[item(),item()]},{'computed_at':'invalid'},
                   {'items':[item(score=101)]},{'items':[item(ticker='<script>')]}]:
        with pytest.raises(ValueError):validate_payload({**payload(),**update})


def test_reader_handles_missing_file_without_fabrication(tmp_path):
    data,error=read_ranking('sippakorntwo-glitch/stock-dashboard',str(tmp_path/'missing.json'))
    assert data is None and error
    path=tmp_path/'valid.json';path.write_text(json.dumps(payload()))
    data,error=read_ranking('sippakorntwo-glitch/stock-dashboard',str(path))
    assert not error and data['items'][0]['ticker']=='MSFT'


def test_closed_market_does_not_fetch_provider(monkeypatch):
    import ranking_job
    monkeypatch.setattr(ranking_job.a.yf,'Ticker',lambda *args:pytest.fail('No closed-clock provider calls'))
    assert refresh_shortlist(None,[item()],now='2026-09-12T14:00:00Z')['attempted']==0


def test_info_refresh_keeps_actual_exchange_timestamp(tmp_path,monkeypatch):
    import ranking_job
    cache=ranking_job.a.DashboardCache(tmp_path/'cache.sqlite3')
    stamp=utc(NOW).timestamp()-1800
    class Provider:
        def get_info(self):return {'currency':'USD','regularMarketPrice':100,'regularMarketTime':stamp}
    monkeypatch.setattr(ranking_job.a.yf,'Ticker',lambda *args:Provider())
    monkeypatch.setattr(ranking_job.time,'sleep',lambda *args:None)
    report=refresh_shortlist(cache,[item()],now=NOW,maximum=1)
    info,meta=cache.get('info:MSFT',request_remote=False)
    assert report['success']==1 and info['regularMarketTime']==stamp
    assert not fresh(info['regularMarketTime'],NOW,900)
    assert meta['fetched_at'] and not cache.quotes()


def test_existing_model_is_used_and_missing_info_not_rescaled(monkeypatch):
    import ranking_engine as r
    f=pd.DataFrame({'Close':[10]*220},index=pd.bdate_range(end='2026-09-10',periods=220))
    ctx={'history':f,'metrics':{'Close':10},'quote':10,'quote_time':utc(NOW).timestamp()}
    monkeypatch.setattr(r.a,'decision_context',lambda *args,**kwargs:dict(ctx))
    recorded=[]
    def score(ctx,info,etf):
        recorded.append(info)
        return {'score':75,'coverage':80,'upper':95,'trend':True,'rows':pd.DataFrame()}
    monkeypatch.setattr(r.a,'criteria_score',score)
    monkeypatch.setattr(r.a,'build_entry_plan',lambda *args,**kwargs:{'ready':False,'rr':2.5,'entry':10,'blockers':[]})
    result=r.evaluate('TEST',{'Asset_Type':'Common Stock'},f,{'forwardPE':20,'targetMeanPrice':12},
                      {'fetched_at':'2026-01-01T00:00:00Z'},None,NOW)
    assert result['score']==75 and result['coverage']==80 and not result['qualified']
    assert 'forwardPE' not in recorded[0] and 'targetMeanPrice' not in recorded[0]
