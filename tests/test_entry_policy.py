"""Strict model entry tests: missing fields, timing and market data fail closed."""
from copy import deepcopy
import pytest
from ranking_policy import entry_checks,apply_entry_policy,is_entry,POLICY
from ranking_board import split_entries
NOW='2026-09-11T14:00:00Z'


def good():
    return {'ticker':'TEST','score':90,'coverage':100,'qualified':True,'ready_at_calculation':True,
        'rr':3,'distance_pct':0,'quote':100,'zone_low':99,'zone_high':101,'stop':95,'target':115,
        'quote_time':1789135200,'info_fetched_at':NOW,'asset_type':'Common Stock','blockers':[],
        'info':{'bid':99.9,'ask':100.1,'trailingEps':5,'profitMargins':.1,'operatingCashflow':100,
        'freeCashflow':80,'revenueGrowth':.1,'totalDebt':250,'totalCash':100,'sector':'Technology',
        'earningsTimestampStart':1791705600}}


def feed(row,now=NOW):
    return {'computed_at':now,'items':apply_entry_policy([row],now)}


def test_confirmed_entry_requires_every_check():
    p=feed(good());r=p['items'][0]
    assert r['entry_audit']['policy']==POLICY and r['entry_audit']['passed']
    assert r['ready_at_calculation'] and is_entry(r,p,NOW)
    assert len(split_entries(p,NOW)[0])==1


@pytest.mark.parametrize('key',['bid','ask','trailingEps','profitMargins','operatingCashflow','freeCashflow','revenueGrowth','totalDebt','totalCash','sector','earningsTimestampStart'])
def test_missing_domain_never_becomes_a_buy(key):
    r=good();del r['info'][key];p=feed(r)
    assert not p['items'][0]['ready_at_calculation']
    assert not split_entries(p,NOW)[0] and len(split_entries(p,NOW)[1])==1


@pytest.mark.parametrize('updates',[{'quote':120},{'quote_time':0},{'coverage':80},{'score':79},
                                  {'stop':101},{'target':101},{'info_fetched_at':'2020-01-01'}])
def test_price_quality_and_freshness_gates(updates):
    r=good();r.update(updates);p=feed(r);assert not p['items'][0]['ready_at_calculation']


def test_current_status_expires_not_just_calculation_status():
    p=feed(good());r=p['items'][0]
    assert not is_entry(r,p,'2026-09-11T14:16:00Z')
    assert not is_entry(r,p,'2026-09-12T14:00:00Z')
    assert not is_entry({**r,'entry_audit':{}},p,NOW)
    p['computed_at']='2026-09-11T13:00:00Z';assert not is_entry(r,p,NOW)


def test_cashflow_debt_earnings_and_spread_veto():
    for update in [{'freeCashflow':-1},{'totalDebt':10000},{'sector':'Financial Services'},
                   {'ask':103},{'earningsTimestampStart':1789221600}]:
        r=good();r['info'].update(update);assert not entry_checks(r,NOW)['passed']


def test_does_not_promote_watch_or_pad_list():
    r=good();r['ready_at_calculation']=False
    p=feed(r);assert not is_entry(p['items'][0],p,NOW)
    assert split_entries({'computed_at':NOW,'items':[]},NOW)==([],[])


def test_inputs_not_mutated_and_etf_has_separate_rules():
    r=good();old=deepcopy(r);apply_entry_policy([r],NOW);assert old==r
    r['asset_type']='ETF';r['info']={'bid':99.9,'ask':100.1,'category':'Large Blend','totalAssets':1e9}
    p=feed(r);assert is_entry(p['items'][0],p,NOW)
