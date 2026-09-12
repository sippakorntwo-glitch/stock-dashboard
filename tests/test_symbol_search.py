import pandas as pd
from screening import search_frame


def catalog():
    return pd.DataFrame([
        {'Ticker':'MSFT','Security_Name':'Microsoft Corporation','Industry':'Software'},
        {'Ticker':'MSFU','Security_Name':'Daily MSFT Bull ETF','Industry':'Trading'},
        {'Ticker':'BRK-B','Security_Name':'Berkshire Class B','Industry':'Insurance'},
        {'Ticker':'QQQI','Security_Name':'NEOS Nasdaq 100 High Income ETF','Industry':'Derivative Income'},
    ])


def test_exact_symbol_does_not_match_single_stock_funds():
    frame=catalog();before=frame.copy(deep=True)
    assert search_frame(frame,' msft ').Ticker.tolist()==['MSFT']
    pd.testing.assert_frame_equal(frame,before)


def test_name_prefix_deliberately_includes_related_funds():
    assert search_frame(catalog(),'name:MSFT').Ticker.tolist()==['MSFU']
    assert search_frame(catalog(),'Microsoft').Ticker.tolist()==['MSFT']


def test_sector_keywords_and_literal_regex_characters():
    assert search_frame(catalog(),'income').Ticker.tolist()==['QQQI']
    assert search_frame(catalog(),'[').empty
    assert len(search_frame(catalog(),''))==4


def test_class_separator_alias_does_not_misidentify_ticker():
    assert search_frame(catalog(),'brk.b').Ticker.tolist()==['BRK-B']
