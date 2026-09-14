"""Behavior of removable criteria and useful numeric result columns."""
import copy
import os

import numpy as np
import pandas as pd
import pytest

from screening import filter_frame, filter_removal_effects, search_frame, UNKNOWN
from return_periods import RETURN_FIELDS, RETURN_LABELS, TABLE_FIELDS, RETURN_MODES
from screener_view import result_fields


def universe():
    rows = [
        ('A', 'Common Stock', 15., 2., 'available'),
        ('B', 'Common Stock', 6., 2., 'available'),
        ('C', 'Common Stock', 17., None, 'source_disagreement'),
        ('D', 'Common Stock', None, 2., 'available'),
        ('E', 'ETF', 99., 2., 'available'),
        ('F', 'Common Stock', None, None, 'not_reported'),
        ('G', 'Common Stock', np.inf, 2., 'available'),
        ('H', 'Common Stock', 15., 0., 'available'),
    ]
    result = pd.DataFrame(rows, columns=['Ticker', 'Asset_Type', 'ROE', 'Dividend_Yield', 'Dividend_Yield_State'])
    result['Security_Name'] = ['A fixture', 'A competitor', 'Other', 'Other', 'A fund', 'Other', 'Other', 'Other']
    result['Industry'] = ['Software', 'Software', 'Hardware', None, 'Large Blend', 'Software', 'Software', 'Software']
    result['Return_1D'] = [1., 2., 3., None, 1., 1., 1., 1.]
    result['Return_5Y'] = [20., None, 20., None, 20., 20., 20., 20.]
    result['Close'] = 100.
    result['SMA200'] = [90., 110., 90., 90., 90., 90., 90., 90.]
    result['EMA20'], result['EMA50'] = 95., 90.
    result['Price_AsOf'] = ['2026-09-10'] * 6 + ['2026-09-01', '2026-09-11']
    result['Profile_AsOf'] = ['2026-09-09T12:00:00Z'] * 7 + [None]
    # Production normally has unique indices, but restored counts must count
    # rows correctly even when a filtered/uploaded frame retains duplicate IDs.
    result.index = [9, 9, 5, 5, 5, 2, 1, 0]
    return result


def effect_map(frame, **options):
    return {row['id']: row for row in filter_removal_effects(frame, **options)}


def test_restored_count_keeps_missing_policy_and_quarantines_disputed_yield():
    frame = universe()
    before = frame.copy(deep=True)
    options = {'bounds': {'ROE': (10., None), 'Dividend_Yield': (1., None)}, 'include_missing': True}
    effects = effect_map(frame, **options)
    assert filter_frame(frame, **options).Ticker.tolist() == ['A', 'D', 'F']
    assert effects['bound:ROE']['current_count'] == 3
    assert effects['bound:ROE']['without_count'] == 6
    assert effects['bound:ROE']['restored_count'] == 3
    # Dropping the yield criterion can restore C. Removing ROE cannot silently
    # bypass the remaining yield-source conflict or manufacture a zero yield.
    assert effects['bound:Dividend_Yield']['without_count'] == 5
    assert effects['bound:Dividend_Yield']['restored_count'] == 2
    pd.testing.assert_frame_equal(frame, before)


def test_conflicting_asset_scope_explains_two_independent_ways_to_restore_rows():
    effects = effect_map(universe(), categories={'Asset_Type': ['ETF']},
                         bounds={'ROE': (10., None)}, include_missing=True)
    assert effects['category:Asset_Type']['current_count'] == 0
    assert effects['category:Asset_Type']['restored_count'] == 5
    assert effects['bound:ROE']['restored_count'] == 1


@pytest.mark.parametrize('query', ['', 'A', 'name:A'])
@pytest.mark.parametrize('include_missing', [False, True])
def test_each_removal_matches_independent_full_refilter_with_other_rules_unchanged(query, include_missing):
    frame = universe()
    options = {
        'categories': {'Asset_Type': ['Common Stock'], 'Industry': ['Software', UNKNOWN]},
        'bounds': {'ROE': (10., None), 'Dividend_Yield': (1., None), 'Close': (None, None)},
        'require_returns': ['Return_1D', 'Return_5Y'], 'include_missing': include_missing,
        'above_sma': True, 'bullish_ema': True, 'favourites': ['A', 'C', 'D', 'F', 'H'],
        'max_price_age': 0, 'max_profile_age': 7, 'now': '2026-09-10T22:00:00Z',
    }
    source_options = copy.deepcopy(options)
    current = len(filter_frame(search_frame(frame, query), **options))
    for effect in filter_removal_effects(frame, query=query, **options):
        changed = copy.deepcopy(options)
        next_query = query
        kind, field = effect['kind'], effect['field']
        if kind == 'search':
            next_query = ''
        elif kind == 'category':
            del changed['categories'][field]
        elif kind == 'bound':
            del changed['bounds'][field]
        elif kind == 'required':
            changed['require_returns'].remove(field)
        else:
            del changed[field]
        expected = len(filter_frame(search_frame(frame, next_query), **changed))
        assert effect['current_count'] == current
        assert effect['without_count'] == expected
        assert effect['restored_count'] == expected - current
    assert options == source_options


def test_search_removal_restores_the_original_universe_and_exact_symbol_wins():
    frame = universe()
    effects = effect_map(frame, query='A', bounds={'Close': (50., 150.)})
    assert effects['search:query']['current_count'] == 1
    assert effects['search:query']['restored_count'] == 7
    assert effects['bound:Close']['without_count'] == 1
    assert effect_map(frame, query='name:A')['search:query']['current_count'] == 3
    assert filter_removal_effects(frame, bounds={'Close': (None, None)}, categories={'Industry': []}) == []
    assert effect_map(frame, favourites=[])['option:favourites']['restored_count'] == 8


def test_default_returns_and_custom_column_order_preserve_identity_and_source_context():
    assert tuple(result_fields()) == TABLE_FIELDS
    assert tuple(result_fields('invalid_saved_preset')) == TABLE_FIELDS
    fields = result_fields('custom', selected_fields=['ROE', 'Free_Cash_Flow', 'ROE', 'Currency', 'unsafe_field'])
    assert fields[:5] == ['Ticker', 'Security_Name', 'ROE', 'Free_Cash_Flow', 'Currency']
    assert len(fields) == len(set(fields))
    assert 'Financial_Currency' in fields and 'Profile_AsOf' in fields
    assert 'unsafe_field' not in fields
    active = result_fields('custom', active_fields=['Trailing_PE', 'ROE'], selected_fields=[])
    assert active[:4] == ['Ticker', 'Security_Name', 'Trailing_PE', 'ROE']
    assert 'Profile_AsOf' in active


def test_purpose_views_and_active_filter_columns_keep_units_and_yield_status():
    fundamental = result_fields('fundamentals')
    assert {'ROE', 'Trailing_PE', 'Revenue_Growth', 'Financial_Currency', 'Currency', 'Profile_AsOf'} <= set(fundamental)
    etf = result_fields('etf')
    assert {'Fund_Family', 'Fund_Assets_Millions', 'Dividend_Yield_State', 'Dividend_Yield_Conflict_Date', 'Currency'} <= set(etf)
    assert 'ROE' not in etf
    momentum = result_fields('momentum')
    assert {'EMA20', 'EMA50', 'SMA200', 'Vol_Ratio', 'ATR_Pct'} <= set(momentum)
    automatic = result_fields(active_fields=['ROE', 'Forward_PE', 'Dividend_Yield'])
    assert automatic[:5] == ['Ticker', 'Security_Name', 'ROE', 'Forward_PE', 'Dividend_Yield']
    assert set(RETURN_FIELDS) <= set(automatic)
    assert 'Dividend_Yield_State' in automatic


real_streamlit = pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS') == '1', reason='Requires real Streamlit')


@real_streamlit
def test_column_config_preserves_percent_points_annualized_headers_and_source_units():
    from screener_view import result_column_config
    config = result_column_config([*RETURN_FIELDS, 'ROE', 'Debt_To_Equity', 'Currency', 'Financial_Currency'], RETURN_MODES[1])
    assert config['ROE']['type_config']['format'] == '%.2f%%'
    assert config['Debt_To_Equity']['type_config']['format'] == '%.2f'
    assert 'Financial' not in config['Currency']['label']
    assert 'งบ' in config['Financial_Currency']['label']
    for field in RETURN_FIELDS:
        if field in ('Return_3Y', 'Return_5Y'):
            assert 'Annualized' in config[field]['label']
        else:
            assert config[field]['label'] == RETURN_LABELS[field]


@real_streamlit
def test_live_filter_removal_and_column_choices_keep_selected_stock_and_numeric_values():
    from streamlit.testing.v1 import AppTest
    script = '''
import pandas as pd
import streamlit as st
from filters_ui import filter_universe
from screener_view import render_result_columns, result_column_config
st.session_state.setdefault('selected_ticker', 'A')
st.session_state.setdefault('chart_range', '5 Years')
f = pd.DataFrame([
 {'Ticker':'A', 'Security_Name':'A fixture', 'Asset_Type':'Common Stock', 'Industry':'Software', 'ROE':15., 'Trailing_PE':12., 'Currency':'USD', 'Status':'PASS'},
 {'Ticker':'B', 'Security_Name':'B fixture', 'Asset_Type':'Common Stock', 'Industry':'Hardware', 'ROE':6., 'Trailing_PE':20., 'Currency':'USD', 'Status':'PASS'},
 {'Ticker':'E', 'Security_Name':'ETF fixture', 'Asset_Type':'ETF', 'Industry':'Large Blend', 'ROE':None, 'Trailing_PE':None, 'Currency':'USD', 'Status':'PASS'}])
w = filter_universe(f)
if w is not None:
    fields = render_result_columns(w)
    st.dataframe(w.reindex(columns=fields), column_config=result_column_config(fields))
'''
    at = AppTest.from_string(script, default_timeout=30).run()
    assert not at.exception, str(at.exception)
    assert tuple(at.dataframe[0].value.columns) == TABLE_FIELDS
    at.multiselect(key='screen_metrics').set_value(['ROE']).run()
    at.number_input(key='screen_min_ROE').set_value(10.).run()
    assert at.dataframe[0].value.Ticker.tolist() == ['A']
    assert at.dataframe[0].value.ROE.tolist() == [15.]
    assert 'เพิ่ม 2 รายการ' in at.button(key='remove_screen_bound:ROE').label
    at.selectbox(key='result_view_preset').set_value('custom').run()
    at.multiselect(key='result_custom_columns').set_value(['Trailing_PE', 'ROE']).run()
    assert at.dataframe[0].value.columns[:4].tolist() == ['Ticker', 'Security_Name', 'Trailing_PE', 'ROE']
    at.selectbox(key='result_view_preset').set_value('etf').run()
    assert at.dataframe[0].value.Ticker.tolist() == ['A']  # a view never filters rows
    at.selectbox(key='result_view_preset').set_value('custom').run()
    assert at.multiselect(key='result_custom_columns').value == ['Trailing_PE', 'ROE']
    at.button(key='remove_screen_bound:ROE').click().run()
    assert at.dataframe[0].value.Ticker.tolist() == ['A', 'B', 'E']
    assert at.multiselect(key='screen_metrics').value == []
    assert at.session_state['selected_ticker'] == 'A'
    assert at.session_state['chart_range'] == '5 Years'
    assert not at.exception, str(at.exception)
