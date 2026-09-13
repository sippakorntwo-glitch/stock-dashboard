"""Replay actual Streamlit widget protobufs after a table changes the ticker."""
from collections.abc import MutableMapping
from types import SimpleNamespace
import dashboard_ui
from dashboard_selection import set_selected, manual_ticker_key
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState


class StateMapping(MutableMapping):
    def __init__(self, raw):
        self.raw = raw
    def __getitem__(self, key):
        return self.raw[key]
    def __setitem__(self, key, value):
        self.raw[key] = value
    def __delitem__(self, key):
        del self.raw[key]
    def __iter__(self):
        return iter(self.raw)
    def __len__(self):
        return len(self.raw)


def test_queued_old_manual_widget_cannot_undo_table_choice_but_new_manual_choice_works(monkeypatch):
    ThreadState.initialize()
    raw = SessionState()
    state = StateMapping(raw)
    monkeypatch.setattr(dashboard_ui, 'st', SimpleNamespace(session_state=state))

    def render_input():
        key = manual_ticker_key(state)
        state[key] = state['selected_ticker']
        revision = state['_selection_revision']
        metadata = WidgetMetadata(
            id='$$ID-fixture-' + key, deserializer=lambda value: value or '',
            serializer=lambda value: value, value_type='string_value',
            callback=dashboard_ui._manual_ticker, callback_args=(key, revision))
        raw.register_widget(metadata, key)
        return metadata.id

    def receive(widget, value):
        incoming = WidgetStates()
        incoming.widgets.add(id=widget, string_value=value)
        raw.on_script_will_rerun(incoming)

    set_selected(state, 'AAPL')
    old_input = render_input()
    receive(old_input, 'AAPL')
    set_selected(state, 'MSFT')  # The real table/board callback uses this function.
    current_input = render_input()
    assert old_input != current_input

    # A browser packet queued before the MSFT update still contains AAPL.
    # Streamlit dispatches these callbacks before executing fragment guards.
    receive(old_input, 'AAPL')
    assert state['selected_ticker'] == state['ticker_input'] == 'MSFT'
    # Even a changed old-widget value must be rejected by the callback revision.
    receive(old_input, 'TSLA')
    assert state['selected_ticker'] == state['ticker_input'] == 'MSFT'
    assert state['comparison_symbols'] == ['MSFT', 'SPY']

    # A fresh intentional AAPL entry on the current visible input remains valid.
    receive(current_input, 'aapl')
    assert state['selected_ticker'] == state['ticker_input'] == 'AAPL'
    assert state['comparison_symbols'] == ['AAPL', 'SPY']
    assert render_input() not in (old_input, current_input)
