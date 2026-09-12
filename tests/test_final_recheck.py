from datetime import date
import sqlite3
import pytest
from audit_all_returns import reference, audit


@pytest.mark.parametrize('state,current,rendered,expected',[
    ({'selected_ticker':'SPY'},2,1,False),
    ({'selected_ticker':'SPY','_chart_first_load_waiting':'SPY'},2,1,True),
    ({'selected_ticker':'SPY','_chart_first_load_waiting':'SPY'},1,1,False),
    ({'selected_ticker':'MSFT','_chart_first_load_waiting':'SPY'},2,1,False),
])
def test_only_an_awaited_initial_chart_can_wake_the_whole_page(state,current,rendered,expected):
    from chart_ranges import first_chart_load_finished
    assert first_chart_load_finished(state,current,rendered) is expected


def test_independent_audit_uses_prior_calendar_boundary():
    prices=[(date(2023,9,8),100.),(date(2023,9,11),110.),(date(2026,9,10),200.)]
    assert reference(prices,months=36)==pytest.approx(100.)
    assert reference(prices,months=60) is None


def test_independent_audit_counts_session_changes_and_invalid_endpoints():
    prices=[(date(2026,9,d),p) for d,p in [(3,100.),(4,105.),(8,110.),(9,120.)]]
    assert reference(prices,sessions=3)==pytest.approx(20.)
    assert reference(prices[-3:],sessions=3) is None
    prices[-1]=(prices[-1][0],float('nan'))
    assert reference(prices,sessions=1) is None


def test_unpriced_listing_is_reported_not_filled_or_counted_as_checked():
    with sqlite3.connect(':memory:') as db:
        result=audit({'universe':['NEW'],'quotes':{}},db)
    assert result['unpriced_tickers']==['NEW']
    assert result['priced_members']==result['periods_checked']==0
    assert result['errors']==[]
