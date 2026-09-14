"""Numerical and source-boundary checks for editable price scenarios."""
from copy import deepcopy
import math

import pytest

from valuation import (market_comparison, price_scenario, sensitivity,
                       valuation_basis, verified_basis)


INFO = {'quoteType': 'EQUITY', 'currency': 'USD', 'financialCurrency': 'USD',
        'trailingEps': 7.0, 'sector': 'Technology'}
ROW = {'Close': 100.0, 'Price_AsOf': '2025-12-31', 'Asset_Type': 'Stock'}
BUNDLE = {'schema': 1, 'ticker': 'TEST', 'currency': 'USD',
          'annual': {'income': [{'end': '2025-12-31', 'values':
                    {'revenue': 1000.0, 'netIncome': 100.0, 'dilutedEPS': 2.0}}]},
          'quarterly': {}}


def basis():
    return valuation_basis('TEST', INFO, ROW, BUNDLE)


def scenario(value=None, **overrides):
    args = dict(growth=0.10, multiple=20.0, required_return=0.10, years=5,
                dilution=0.0, share_unit_confirmed=True)
    args.update(overrides)
    return price_scenario(value or basis(), **args)


def test_discounted_terminal_price_and_reverse_growth_round_trip():
    value = basis()
    result = scenario(value)
    assert result['terminal_price'] == pytest.approx(2 * 1.1 ** 5 * 20)
    assert result['present_price'] == pytest.approx(40)
    assert result['price_gap'] == pytest.approx(-0.6)
    assert result['price_cagr'] == pytest.approx((result['terminal_price'] / 100) ** .2 - 1)
    implied = scenario(value, growth=result['implied_growth'])
    assert implied['present_price'] == pytest.approx(value['quote_price'])


def test_dilution_and_margin_have_separate_auditable_effects():
    original = scenario()
    diluted = scenario(dilution=0.10)
    assert diluted['terminal_base'] == pytest.approx(2.0)
    assert diluted['present_price'] < original['present_price']
    adjusted = scenario(terminal_margin=0.20)
    assert adjusted['present_price'] == pytest.approx(original['present_price'] * 2)
    assert scenario(growth=adjusted['implied_growth'], terminal_margin=.2)['present_price'] == pytest.approx(100)


def test_margin_uses_eps_fiscal_year_even_when_ttm_income_is_newer():
    bundle = deepcopy(BUNDLE)
    bundle['quarterly']['income'] = [
        {'end': end, 'values': {'revenue': 500, 'netIncome': 100}}
        for end in ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30']]
    value = valuation_basis('TEST', INFO, ROW, bundle)
    assert value['value'] == 2
    assert value['margin'] == .1
    assert value['period'] == '2025-12-31'


def test_missing_same_year_margin_is_not_replaced_by_profile_or_other_year():
    bundle = deepcopy(BUNDLE)
    del bundle['annual']['income'][0]['values']['netIncome']
    bundle['annual']['income'].append({'end': '2024-12-31', 'values': {'netIncome': 50, 'revenue': 100}})
    value = valuation_basis('TEST', {**INFO, 'profitMargins': .2}, ROW, bundle)
    assert value['margin'] is None
    assert scenario(value, terminal_margin=.1)['state'] == 'invalid'


def test_foreign_bundle_rejected_and_profile_eps_keeps_provider_basis():
    bundle = {**BUNDLE, 'ticker': 'OTHER'}
    value = valuation_basis('TEST', INFO, ROW, bundle)
    assert value['value'] == 7
    assert value['period'] == 'Provider period'
    assert value['margin'] is None


@pytest.mark.parametrize('eps', [0, -1.5])
def test_nonpositive_reported_eps_preserved_not_valued(eps):
    bundle = deepcopy(BUNDLE)
    bundle['annual']['income'][0]['values']['dilutedEPS'] = eps
    value = valuation_basis('TEST', INFO, ROW, bundle)
    assert value['value'] == eps
    assert value['state'] == 'not_meaningful'
    assert scenario(value)['present_price'] is None


def test_unknown_eps_does_not_turn_into_zero():
    value = valuation_basis('TEST', {'currency': 'USD'}, ROW)
    assert value['value'] is None
    assert scenario(value)['state'] == 'invalid'


@pytest.mark.parametrize('currency', ['EUR', None])
def test_fx_or_missing_currency_blocks_price_gap_and_implied_growth(currency):
    value = {**basis(), 'currency': currency}
    result = scenario(value)
    assert result['present_price'] is not None
    assert not result['comparable']
    assert result['price_gap'] is result['price_cagr'] is result['implied_growth'] is None


def test_quote_date_and_share_unit_required_for_market_comparison():
    assert not market_comparison(basis())[0]
    for as_of in ('', 'invalid', '2999-12-31'):
        value = valuation_basis('TEST', INFO, {**ROW, 'Price_AsOf': as_of}, BUNDLE)
        assert scenario(value)['price_gap'] is None


def test_extreme_positive_market_price_cannot_export_infinite_results():
    result = scenario({**basis(), 'quote_price': 1e-320})
    assert result['present_price'] is not None
    assert not result['comparable']
    assert result['price_gap'] is result['price_cagr'] is result['implied_growth'] is None


@pytest.mark.parametrize('changes', [dict(growth=-1), dict(dilution=-1), dict(multiple=0),
                                    dict(years=0), dict(years=2.5), dict(required_return=-1),
                                    dict(growth=float('inf')), dict(multiple=float('nan'))])
def test_invalid_assumptions_fail_without_infinity(changes):
    result = scenario(**changes)
    assert result['state'] == 'invalid'
    assert result['present_price'] is None


def test_specialized_models_never_auto_substitute_eps():
    for info, model in [({**INFO, 'industry': 'REIT - Retail'}, 'ffo'),
                        ({**INFO, 'sector': 'Financial Services'}, 'book')]:
        value = valuation_basis('TEST', info, ROW, BUNDLE)
        assert value['model'] == model
        assert value['value'] is None
        assert scenario(value)['state'] == 'invalid'


def test_verified_manual_input_is_labelled_and_preserves_original():
    original = valuation_basis('TEST', {**INFO, 'industry': 'REIT - Retail'}, ROW, BUNDLE)
    args = dict(value=6, currency='usd', period='2025-12-31', source='Annual report p 42', confirmed=True)
    value = verified_basis(original, **args)
    assert value['manual'] and value['state'] == 'available' and value['currency'] == 'USD'
    assert original['value'] is None
    assert scenario(value)['present_price'] == pytest.approx(120)
    for changes in [dict(confirmed=False), dict(source=''), dict(currency=''),
                    dict(value=-2), dict(period='2999-01-01')]:
        assert verified_basis(original, **{**args, **changes})['state'] == 'unverified'


def test_funds_cannot_be_converted_to_corporate_model_by_manual_input():
    value = valuation_basis('TEST', INFO, {**ROW, 'Asset_Type': 'ETF'}, BUNDLE)
    assert value['state'] == 'not_applicable'
    assert verified_basis(value, value=1, currency='USD', period='2025-01-01',
                          source='test', confirmed=True)['state'] == 'unverified'


def test_sensitivity_center_matches_base_and_changes_monotonically():
    grid = sensitivity(basis(), growths=[0, .1, .2], multiples=[10, 20, 30],
                       required_return=.1, years=5)
    assert len(grid) == 9
    assert grid[4]['present_price'] == pytest.approx(scenario()['present_price'])
    assert grid[0]['present_price'] < grid[4]['present_price'] < grid[8]['present_price']
    assert all(math.isfinite(item['present_price']) for item in grid)


def test_streamlit_scenarios_update_and_survive_ticker_switch():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from valuation_ui import render_valuation
ticker = st.selectbox('Symbol', ['TEST', 'NEXT'], key='test_symbol')
render_valuation(ticker, {'quoteType':'EQUITY', 'currency':'USD', 'trailingEps':2},
                 {'Close':100., 'Price_AsOf':'2025-12-31', 'Asset_Type':'Stock'})
''').run(timeout=30)
    assert not app.exception
    app.number_input(key='valuation_TEST_s1_growth').set_value(25.0).run()
    assert not app.exception
    app.checkbox(key='valuation_TEST_share_units').check().run()
    assert any('ภายใต้จำนวนหุ้น' in item.value for item in app.info)
    before = app.dataframe[0].value.iloc[1]['ราคาคิดลด ณ วันนี้']
    app.selectbox(key='test_symbol').select('NEXT').run()
    app.selectbox(key='test_symbol').select('TEST').run()
    assert not app.exception
    assert app.number_input(key='valuation_TEST_s1_growth').value == 25.0
    assert app.checkbox(key='valuation_TEST_share_units').value
    assert app.dataframe[0].value.iloc[1]['ราคาคิดลด ณ วันนี้'] == before


def test_streamlit_manual_ffo_validation_and_currency_gate():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
from valuation_ui import render_valuation
render_valuation('REIT', {'quoteType':'EQUITY', 'currency':'USD', 'industry':'REIT - Retail'},
                 {'Close':100., 'Price_AsOf':'2025-12-31', 'Asset_Type':'Stock'})
''').run(timeout=30)
    assert not app.exception
    assert not app.dataframe
    app.number_input(key='valuation_REIT_manual_value').set_value(6)
    app.text_input(key='valuation_REIT_manual_currency').set_value('EUR')
    app.text_input(key='valuation_REIT_manual_period').set_value('2025-12-31')
    app.text_input(key='valuation_REIT_manual_source').set_value('Annual report FFO reconciliation')
    app.checkbox(key='valuation_REIT_manual_confirmed').check().run()
    assert not app.exception
    app.checkbox(key='valuation_REIT_share_units').check().run()
    assert not app.exception
    assert app.dataframe[0].value['ส่วนต่างราคาคิดลด (%)'].isna().all()
    assert any('สกุลเงิน' in value.value for value in app.info)
