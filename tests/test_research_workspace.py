"""Private saved views round-trip without restoring arbitrary app state."""
import copy
import json
from types import SimpleNamespace

import pytest

from dashboard_selection import apply_table_selection, table_key
from research_workspace import (
    MAX_DOCUMENT_BYTES, capture_document, dumps_document, loads_document,
    restore_document, validate_document, validate_research, hydrate_research,
    evaluate_condition, research_digest,
)


def sample_state():
    return {
        'selected_ticker': 'MSFT', 'comparison_symbols': ['MSFT', 'GOOG', 'SPY'],
        'peer_selection_MSFT': ['GOOG', 'ORCL'], 'favourites': ['MSFT', 'AAPL'],
        'research_mode': 'ลงทุนระยะยาว', 'result_view_preset': 'custom',
        'result_custom_columns': ['ROE', 'Forward_PE', 'Profile_AsOf'],
        'stock_search': 'name:technology', 'screen_asset': 'Common Stock',
        'screen_metrics': ['ROE', 'Revenue_Growth'], 'screen_min_ROE': 12.5,
        'screen_sort': 'ROE', 'screen_descending': True,
        '_research_notes': {'MSFT': 'รายได้คลาวด์และกระแสเงินสด ต้องเติบโตต่อเนื่อง'},
        '_research_tracking': {'MSFT': [{'metric': 'ROE', 'op': '>=', 'value': 15.0}]},
        '_research_baselines': {'MSFT': {'profile_asof': '2026-09-13', 'revenue': 100.5}},
        '_private_token': 'do-not-export', 'password': 'do-not-export',
    }


def test_named_document_roundtrip_restores_views_notes_and_resets_retired_selection():
    source = sample_state()
    doc = loads_document(dumps_document(capture_document(source, 'หุ้นที่ติดตาม')))
    assert b'do-not-export' not in dumps_document(doc)
    target = {'selected_ticker': 'AAPL', 'screen_min_Profit_Margin': 50,
              'screen_metrics': ['Profit_Margin'], '_table_epoch': 3,
              'peer_selection_AAPL': ['TSLA'], 'research_note_MSFT': 'previous widget'}
    old_key = table_key(('AAPL',), 3)
    target['_active_table_key'] = old_key
    restore_document(target, doc)
    assert target['selected_ticker'] == target['ticker_input'] == 'MSFT'
    assert target['comparison_symbols'] == ['MSFT', 'GOOG', 'SPY']
    assert target['peer_selection_MSFT'] == ['GOOG', 'ORCL']
    assert 'peer_selection_AAPL' not in target and 'research_note_MSFT' not in target
    assert target['screen_min_Profit_Margin'] is None
    assert target['screen_metrics'] == ['ROE', 'Revenue_Growth']
    assert target['screen_min_ROE'] == 12.5 and target['screen_sort'] == 'ROE'
    assert target['research_mode'] == 'ลงทุนระยะยาว'
    assert target['_research_notes'] == source['_research_notes']
    assert target['_research_tracking'] == source['_research_tracking']
    assert target['_research_baselines'] == source['_research_baselines']
    assert target['_table_epoch'] == 4 and target['table_page'] == 1
    target[old_key] = {'selection': {'rows': [0]}}
    apply_table_selection(target, old_key, ('AAPL',))
    assert target['selected_ticker'] == 'MSFT'


@pytest.mark.parametrize('key,value', [
    ('selected_ticker', '<script>alert(1)</script>'), ('selected_ticker', 'AAPL\x00'),
    ('screen_min_ROE', float('nan')), ('screen_min_ROE', True),
    ('screen_min_ROE', 10 ** 999), ('screen_price_age', -1),
    ('screen_metrics', ['NotARealMetric']), ('screen_return_mode', 'bogus'),
    ('result_custom_columns', ['Ticker']), ('peer_selection_AAPL', ['A', 'B', 'C', 'D', 'E', 'F']),
])
def test_malformed_known_preferences_are_rejected_atomically(key, value):
    doc = capture_document(sample_state())
    doc['preferences'][key] = value
    target = {'selected_ticker': 'AAPL'}
    before = copy.deepcopy(target)
    with pytest.raises(ValueError): restore_document(target, doc)
    assert target == before


def test_unknown_or_internal_state_cannot_be_restored_from_file():
    doc = capture_document(sample_state())
    doc['preferences'].update(_active_table_key='malicious', selected_widget='AAPL',
                              _research_notes={'MSFT': 'injected'}, arbitrary_secret='secret')
    state = {}
    restore_document(state, doc)
    assert 'arbitrary_secret' not in state and 'selected_widget' not in state
    assert state['_research_notes'] == sample_state()['_research_notes']


@pytest.mark.parametrize('data', [b'bad-json', b'{"schema":1,"preferences":{"screen_min_ROE":NaN}}',
    b'{"schema":2}', b'{"schema":true}', b'[]', b'x' * (MAX_DOCUMENT_BYTES + 1)])
def test_import_rejects_corrupt_unsupported_or_oversized_documents(data):
    with pytest.raises(ValueError): loads_document(data)


@pytest.mark.parametrize('research', [
    {'notes': {'MSFT': 'a' * 6001}}, {'notes': {'msft': 'invalid ticker'}},
    {'tracking': {'MSFT': [{'metric': ['ROE'], 'op': '>=', 'value': 1}]}},
    {'tracking': {'MSFT': [{'metric': 'ROE', 'op': '>=', 'value': float('inf')}]}},
    {'baselines': {'MSFT': {'nested': {'not': 'allowed'}}}},
    {'baselines': {'MSFT': {str(i): i for i in range(65)}}},
])
def test_notes_conditions_and_baselines_have_bounded_validated_schemas(research):
    with pytest.raises(ValueError): validate_research(research)


def test_hydration_retains_new_edits_and_does_not_change_current_ticker_or_filters():
    state = {'selected_ticker': 'AAPL', 'stock_search': 'apple',
             '_research_notes': {'MSFT': 'edited while browser loaded'}}
    local = {'notes': {'MSFT': 'old saved note', 'GOOG': 'other saved note'},
             'baselines': {'GOOG': {'revenue': 200.0}}}
    hydrate_research(state, local)
    assert state['_research_notes'] == {'MSFT': 'edited while browser loaded', 'GOOG': 'other saved note'}
    assert state['selected_ticker'] == 'AAPL' and state['stock_search'] == 'apple'
    assert local['notes']['MSFT'] == 'old saved note'


def test_sessions_are_independent_and_documents_do_not_alias_live_state():
    first, second = sample_state(), {}
    doc = capture_document(first)
    restore_document(second, doc)
    second['_research_notes']['MSFT'] = 'different browser/session'
    second['favourites'].append('GOOG')
    assert first['_research_notes']['MSFT'] != second['_research_notes']['MSFT']
    assert 'GOOG' not in first['favourites']
    assert doc['research']['notes']['MSFT'] == first['_research_notes']['MSFT']


def test_tracking_evaluates_zero_and_negative_values_but_never_missing_or_disputed():
    condition = {'metric': 'Dividend_Yield', 'op': '>=', 'value': 0.0}
    assert evaluate_condition(condition, {'Dividend_Yield': 0.0})['triggered'] is True
    for data in ({}, {'Dividend_Yield': float('nan')},
                 {'Dividend_Yield': 0.0, 'Dividend_Yield_State': 'source_disagreement'}):
        assert evaluate_condition(condition, data) == {'status': 'ข้อมูลไม่พอ', 'value': None, 'triggered': False}
    condition = {'metric': 'Revenue_Growth', 'op': '<=', 'value': -5.0}
    assert evaluate_condition(condition, {'Revenue_Growth': -6.0})['triggered'] is True
    assert evaluate_condition(condition, {'Revenue_Growth': 3.0})['triggered'] is False


def test_digest_does_not_depend_on_dict_order_or_saved_at_timestamp():
    assert research_digest({'notes': {'MSFT': 'note'}, 'tracking': {}}) == research_digest({'tracking': {}, 'notes': {'MSFT': 'note'}})


def test_hydration_and_load_are_processed_before_widgets_once(monkeypatch):
    import research_workspace_ui as ui
    state = {'research_note_MSFT': '', 'selected_ticker': 'AAPL'}
    monkeypatch.setattr(ui, 'st', SimpleNamespace(session_state=state))
    event = {'id': 'hydrate-1', 'action': 'hydrate', 'research': {'notes': {'MSFT': 'saved note'}}}
    assert ui._component_event(event) is True
    assert '_research_notes' not in state  # deferred until next startup
    ui.startup_before_widgets()
    assert state['research_note_MSFT'] == 'saved note'
    assert state['_research_hydrated'] is True
    assert ui._component_event(event) is False
    assert ui._component_event({'id': 'load-2', 'action': 'load', 'document': capture_document(sample_state())})
    assert state['selected_ticker'] == 'AAPL'
    ui.startup_before_widgets()
    assert state['selected_ticker'] == 'MSFT'
    epoch = state['_table_epoch']
    ui.startup_before_widgets()
    assert state['_table_epoch'] == epoch


def test_bad_hydration_finishes_once_without_touching_existing_notes(monkeypatch):
    import research_workspace_ui as ui
    state = {'_research_notes': {'AAPL': 'keep'}}
    monkeypatch.setattr(ui, 'st', SimpleNamespace(session_state=state))
    ui._component_event({'id': 'broken', 'action': 'hydrate', 'research': {'notes': ['bad']}})
    ui.startup_before_widgets()
    assert state['_research_hydrated'] and state['_research_notes'] == {'AAPL': 'keep'}
    assert '_research_error' in state


def test_cleared_note_is_not_resurrected_by_delayed_hydration(monkeypatch):
    import research_workspace_ui as ui
    state={'research_note_MSFT':'', '_research_notes':{'MSFT':'old'}}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    ui._save_note('MSFT','research_note_MSFT')
    ui._component_event({'id':'late','action':'hydrate','research':{'notes':{'MSFT':'stored old'}}})
    ui.startup_before_widgets()
    assert state['_research_notes']['MSFT']==state['research_note_MSFT']==''


def test_etf_comparisons_roundtrip_with_other_preferences():
    source=sample_state()
    source.update(etf_compare_symbols=['VTI','QQQ'],etf_benchmark_symbol='SPY')
    restored={}
    restore_document(restored,capture_document(source))
    assert restored['etf_compare_symbols']==['VTI','QQQ']
    assert restored['etf_benchmark_symbol']=='SPY'
