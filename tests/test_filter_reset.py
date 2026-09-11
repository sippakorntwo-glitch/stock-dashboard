from types import SimpleNamespace
import pytest


def test_reset_explicitly_writes_defaults_instead_of_reusing_frontend_values(monkeypatch):
    import filters_ui as ui
    state={'screen_asset':'ETF','screen_status':'FAIL','screen_cat_Industry':['Derivative Income'],
           'screen_periods':['Return_1M'],'screen_min_Return_1M':10.0,'screen_max_Return_1M':0.0,
           'screen_return_mode':'Annualized (3Y / 5Y only)','screen_favourites':True,
           'screen_fresh':True,'screen_price_age':0,'screen_profile_age':99,
           'selected_ticker':'QQQI','favourites':['QQQI'],'stock_search':'OLD',
           '_filter_reset_version':4,'private_upload':'session-only'}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    ui.reset_filters()
    assert state['screen_asset']==state['screen_status']=='All'
    assert state['screen_cat_Industry']==state['screen_periods']==[]
    assert state['screen_min_Return_1M'] is None and state['screen_max_Return_1M'] is None
    assert state['screen_return_mode']==ui.RETURN_MODES[0]
    assert not state['screen_favourites'] and not state['screen_fresh']
    assert state['screen_price_age']==4 and state['screen_profile_age']==14
    assert state['stock_search']=='' and state['table_page']==1
    assert state['selected_ticker']=='QQQI' and state['favourites']==['QQQI']
    assert state['private_upload']=='session-only' and state['_filter_reset_version']==5
    ui.reset_filters()
    assert state['_filter_reset_version']==6
    assert all(state['screen_min_'+field] is None and state['screen_max_'+field] is None
               for field in (*ui.RETURN_FIELDS,*ui.METRICS))
