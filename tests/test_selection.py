"""Regression coverage for stock selection after filtering, sorting and paging."""
import pytest
from dashboard_selection import table_key, selected_symbol, set_selected, apply_table_selection


def event(rows=(),cells=()):
    return {'selection':{'rows':list(rows),'cells':list(cells)}}


def test_cell_uses_displayed_position_not_original_index():
    assert selected_symbol(event(cells=[(1,'Security_Name')]),('SPY','MSFT'))=='MSFT'
    assert selected_symbol(event(rows=[0]),('MSFT','AAPL'))=='MSFT'


def test_second_page_and_reversed_sort_have_independent_identity():
    catalog=tuple(f'S{i:03}' for i in range(200))
    page1,page2=catalog[:100],catalog[100:]
    assert selected_symbol(event(rows=[4]),page2)=='S104'
    assert table_key(page1)!=table_key(page2)
    assert table_key(page1)!=table_key(tuple(reversed(page1)))
    assert table_key(page1)==table_key(page1)
    assert table_key(page1,1)!=table_key(page1,2)


@pytest.mark.parametrize('selection',[event(),event(rows=[-1]),event(rows=[5]),event(rows=[True]),event(cells=[(99,'Ticker')])])
def test_empty_or_invalid_selection_does_not_select_another_stock(selection):
    assert selected_symbol(selection,('AAPL','MSFT')) is None


def test_last_changed_cell_or_row_wins():
    old=event(rows=[0],cells=[(0,'Ticker')])
    new=event(rows=[0],cells=[(1,'Ticker')])
    assert selected_symbol(new,('AAPL','MSFT'),old)=='MSFT'
    latest=event(rows=[0],cells=[(1,'Ticker')])
    assert selected_symbol(latest,('AAPL','MSFT'),event(rows=[1],cells=[(1,'Ticker')]))=='AAPL'
    assert selected_symbol(latest,('AAPL','MSFT'),latest) is None


def test_table_syncs_sidebar_and_comparison_but_clear_preserves_selection():
    state={}
    set_selected(state,'AAPL')
    key=table_key(('AAPL','MSFT'))
    state[key]=event(cells=[(1,'Security_Name')])
    apply_table_selection(state,key,('AAPL','MSFT'))
    assert state['selected_ticker']==state['ticker_input']=='MSFT'
    assert state['comparison_symbols']==['MSFT','SPY']
    state[key]=event()
    apply_table_selection(state,key,('AAPL','MSFT'))
    assert state['selected_ticker']=='MSFT'


def test_manual_symbol_resets_table_and_spy_uses_a_different_benchmark():
    state={}
    set_selected(state,'MSFT')
    key=table_key(('MSFT',))
    state[key]=event(cells=[(0,'Ticker')])
    apply_table_selection(state,key,('MSFT',))
    set_selected(state,'SPY',reset_table=True)
    assert state['comparison_symbols']==['SPY','QQQ']
    assert table_key(('MSFT',),state['_table_epoch'])!=key
    assert '_last_table_event' not in state


def test_unchanged_ticker_retains_custom_comparison():
    state={}
    set_selected(state,'AAPL')
    state['comparison_symbols']=['AAPL','QQQ','MSFT']
    set_selected(state,'AAPL')
    assert state['comparison_symbols']==['AAPL','QQQ','MSFT']
