"""Synthetic accounting fixtures; no market-data request is made by these tests."""
from copy import deepcopy

import pandas as pd
import pytest

from peer_analysis import (benchmark_metric, build_peer_analysis, comparable_reason,
                           peer_candidates, selected_peer_symbols)
from peer_analysis_ui import peer_tables


def catalog():
    rows = []
    for symbol, kind, industry, cap, quote, reporting in [
        ('A', 'Common Stock', 'Software', 100, 'USD', 'USD'),
        ('B', 'Common Stock', 'Software', 105, 'USD', 'USD'),
        ('C', 'Common Stock', 'Software', 200, 'USD', 'USD'),
        ('D', 'Common Stock', 'Software', 50, 'USD', 'USD'),
        ('E', 'Common Stock', 'Software', 101, 'GBP', 'GBP'),
        ('F', 'ETF', 'Software', 100, 'USD', 'USD'),
        ('G', 'Common Stock', 'Banks', 100, 'USD', 'USD'),
        ('H', 'Common Stock', 'Software', None, 'USD', 'USD'),
        ('I', 'Common Stock', 'Software', 110, 'USD', 'USD'),
    ]:
        rows.append({'Ticker': symbol, 'Asset_Type': kind, 'Industry': industry,
                     'Market_Cap': cap, 'Currency': quote, 'Financial_Currency': reporting})
    return pd.DataFrame(rows)


def observation(value=.2, end='2025-12-31', **changes):
    return {'value': value, 'state': 'available', 'basis': 'FY', 'end': end,
            'currency': 'USD', 'source': 'Yahoo Finance financial statements',
            'formula': 'operatingIncome / revenue', **changes}


def bundle(symbol, margin=.2, currency='USD', end='2025-12-31'):
    return {'schema': 1, 'ticker': symbol, 'currency': currency,
            'annual': {'income': [
                {'end': end, 'values': {'revenue': 100, 'operatingIncome': margin * 100, 'netIncome': 10}},
                {'end': '2024-12-31', 'values': {'revenue': 80, 'netIncome': 8}},
            ]}, 'quarterly': {}}


def test_candidates_respect_exact_industry_common_stock_and_currency_size():
    frame = catalog()
    original = frame.copy(deep=True)
    candidates = [r['Ticker'] for r in peer_candidates('A', frame)]
    assert candidates[:2] == ['B', 'I']
    assert 'F' not in candidates and 'G' not in candidates and 'A' not in candidates
    assert candidates[-1] == 'E', 'Nominal GBP cap must not be compared with USD cap'
    assert len(selected_peer_symbols('A', frame)) == 4
    assert peer_candidates('F', frame) == []
    pd.testing.assert_frame_equal(frame, original)


def test_unknown_or_duplicate_classification_never_becomes_inferred_peer():
    frame = catalog()
    frame.loc[frame.Ticker.eq('A'), 'Industry'] = None
    assert peer_candidates('A', frame) == []
    assert selected_peer_symbols('OUTSIDE', frame, info={'industry': 'Software', 'currency': 'USD'})
    duplicate = pd.concat([catalog(), catalog().iloc[[1]]], ignore_index=True)
    assert 'B' not in selected_peer_symbols('A', duplicate)
    bad_symbol = catalog().replace({'Ticker': {'B': 'BAD SYMBOL'}})
    assert 'BAD SYMBOL' not in selected_peer_symbols('A', bad_symbol)


def test_explicit_selection_is_bounded_deduplicated_pruned_and_empty_stays_empty():
    frame = catalog()
    assert selected_peer_symbols('A', frame, []) == []
    assert selected_peer_symbols('A', frame, ['A', 'F', 'B', 'B', 'G', 'C']) == ['B', 'C']
    assert len(selected_peer_symbols('A', frame, ['B', 'C', 'D', 'E', 'H', 'I'])) == 5
    assert selected_peer_symbols('A', frame, 'B') == []


def test_median_and_midrank_exclude_researched_company_and_keep_zero():
    peers = {'B': observation(0), 'C': observation(.2), 'D': observation(.4), 'E': observation(.8)}
    result = benchmark_metric(observation(.2), peers)
    assert result['median'] == pytest.approx(.3)
    assert result['percentile'] == 37.5
    assert result['count'] == 4 and result['eligible']['B'] == 0
    assert result['excluded'] == {}


def test_small_sample_no_zero_fills_or_artificial_rank():
    result = benchmark_metric(observation(.2), {
        'B': observation(.3), 'C': observation(None, state='missing_inputs'),
        'D': observation(float('nan')), 'E': observation(.4),
    })
    assert result['count'] == 2 and result['selected_count'] == 4
    assert result['median'] is None and result['percentile'] is None
    assert set(result['excluded']) == {'C', 'D'}


@pytest.mark.parametrize(('changes', 'reason'), [
    ({'basis': 'Provider period', 'end': None}, 'unknown_period'),
    ({'basis': 'FY', 'end': '2024-12-31'}, 'period_mismatch'),
    ({'basis': 'Balance sheet'}, 'basis_mismatch'),
    ({'currency': 'GBP'}, 'currency_mismatch'),
    ({'currency': None}, 'unknown_currency'),
    ({'currency': 'Currency not reported'}, 'unknown_currency'),
    ({'source': None}, 'unknown_source'),
    ({'formula': 'different formula'}, 'method_mismatch'),
    ({'state': 'not_meaningful'}, 'unavailable'),
])
def test_explicit_comparability_exclusions(changes, reason):
    assert comparable_reason(observation(), observation(**changes)) == reason


def test_reference_unknown_period_cannot_produce_a_benchmark_from_known_peers():
    reference = observation(basis='Provider period', end=None)
    reference['_Fetched_At_UTC'] = '2026-09-14T00:00:00Z'
    result = benchmark_metric(reference, {s: observation() for s in ('B', 'C', 'D')})
    assert result['median'] is None
    assert set(result['excluded'].values()) == {'reference_unknown_period'}


def test_endpoint_tolerance_is_bounded_and_does_not_mix_ttm_windows():
    assert comparable_reason(observation(), observation(end='2026-01-31')) is None
    assert comparable_reason(observation(), observation(end='2026-02-01')) == 'period_mismatch'
    dates = ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30']
    reference = observation(end=dates[0], basis='TTM (4 reported quarters)', period_ends=dates)
    assert comparable_reason(reference, deepcopy(reference)) is None
    missing = deepcopy(reference)
    del missing['period_ends']
    assert comparable_reason(reference, missing) == 'unknown_window'
    incomplete = deepcopy(reference)
    incomplete['period_ends'] = dates[:3]
    assert comparable_reason(reference, incomplete) == 'unknown_window'
    mismatch = deepcopy(reference)
    mismatch['period_ends'] = ['2026-06-30', '2026-04-25', '2026-02-04', '2025-10-31']
    assert comparable_reason(reference, mismatch) == 'window_mismatch'


def test_canonical_statement_values_not_screener_or_profile_fallbacks_and_export_agrees():
    records = {s: {'info': {'operatingMargins': .99, 'trailingPE': 15, 'financialCurrency': 'USD'},
                   'bundle': bundle(s, margin)} for s, margin in [('A', .2), ('B', .1), ('C', .3), ('D', .4)]}
    original = deepcopy(records)
    analysis = build_peer_analysis('A', records, ['B', 'C', 'D'])
    margin = next(row for row in analysis['rows'] if row['key'] == 'operatingMargins')
    assert margin['observations']['A']['value'] == .2
    assert margin['benchmark']['median'] == .3
    pe = next(row for row in analysis['rows'] if row['key'] == 'trailingPE')
    assert pe['observations']['A']['value'] == 15
    assert pe['benchmark']['median'] is None, 'An undated provider P/E is displayed but not given an invented accounting period'
    visible, exported = peer_tables(analysis, records)
    label = visible.iloc[4]['ตัวชี้วัด']
    rows = exported.loc[exported['ตัวชี้วัด'].eq(label)]
    assert rows.loc[rows['หุ้น'].eq('A'), 'ค่าก่อนปัดเศษ'].iloc[0] == .2
    assert set(rows['ค่ากลางกลุ่ม (ค่าดิบ)']) == {.3}
    assert '20.00%' in visible.iloc[4]['A']
    assert records == original


def test_wrong_ticker_statement_does_not_contaminate_peer_results():
    records = {'A': {'info': {}, 'bundle': bundle('FOREIGN')}}
    analysis = build_peer_analysis('A', records, ['B', 'C', 'D'])
    assert all(row['benchmark']['median'] is None for row in analysis['rows'])
    assert next(r for r in analysis['rows'] if r['key'] == 'operatingMargins')['observations']['A']['value'] is None


def test_new_default_peers_rerun_before_reading_outside_the_pinned_dependency_vector(monkeypatch):
    import peer_analysis_ui as ui

    class Rerun(Exception):
        pass

    class FakeStreamlit:
        session_state = {}
        def subheader(self, *args, **kwargs):
            pass
        def rerun(self):
            raise Rerun()

    class PinnedCache:
        dependencies = ('A', 'SPY')
        def get(self, key):
            pytest.fail('Must rerun before any peer read when dependencies are not frozen')

    stub = FakeStreamlit()
    monkeypatch.setattr(ui, 'st', stub)
    with pytest.raises(Rerun):
        ui.render_peer_analysis('A', catalog(), PinnedCache(), {})
    assert stub.session_state['peer_selection_A'] == selected_peer_symbols('A', catalog())


def test_real_streamlit_peer_controls_initial_rerun_exports_and_empty_selection():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
import pandas as pd
import streamlit as st
from peer_analysis_ui import render_peer_analysis
frame = pd.DataFrame([{'Ticker': symbol, 'Asset_Type': 'Common Stock',
    'Industry': 'Software', 'Currency': 'USD', 'Financial_Currency': 'USD',
    'Market_Cap': 100 + index} for index, symbol in enumerate('ABCDE')])
class Cache:
    dependencies = ('A', *st.session_state.get('peer_selection_A', []))
    def get(self, key):
        symbol = key.rsplit(':', 1)[-1]
        assert symbol in self.dependencies, 'unfrozen peer read'
        if key.startswith('info:'):
            return {'financialCurrency': 'USD', 'industry': 'Software', 'trailingPE': 15}, {}
        return {'schema': 1, 'ticker': symbol, 'currency': 'USD', 'annual': {
            'income': [{'end': '2025-12-31', 'values': {'revenue': 100, 'operatingIncome': 20}}]
            }, 'quarterly': {}}, {}
render_peer_analysis('A', frame, Cache(), {'financialCurrency': 'USD'})
''', default_timeout=20).run()
    assert not app.exception
    assert app.multiselect[0].value == ['B', 'C', 'D', 'E']
    assert app.multiselect[0].proto.max_selections == 5
    assert len(app.dataframe) == 2
    app.multiselect[0].set_value(['B', 'C', 'D']).run()
    assert not app.exception
    assert app.multiselect[0].value == ['B', 'C', 'D']
    assert len(app.dataframe) == 2
    app.multiselect[0].set_value([]).run()
    assert not app.exception
    assert app.multiselect[0].value == []
    assert len(app.dataframe) == 0
