"""Pending comparison data wakes its page without refreshing other viewers."""
from types import SimpleNamespace
import pytest
import dashboard_ui
from dashboard_runtime import DashboardCache
from data_sync import SnapshotReader, shard_number
from read_view import page_dependencies


def setup_page(tmp_path, monkeypatch):
    cache = DashboardCache(tmp_path / 'dependency-page.sqlite3')
    reader = SnapshotReader(object(), cache)
    cache.remote = reader
    reader.manifest = {'generation': 'fixture', 'details': {}}
    monkeypatch.setattr(reader, '_start', lambda: None)
    monkeypatch.setattr(reader, 'refresh', lambda **kwargs: None)
    for symbol in ('AAPL', 'SPY', 'MSFT'):
        reader.shards.setdefault(str(shard_number(symbol)), {})[symbol] = [
            ('info:' + symbol, {'name': symbol}, {'fetched_at': '2026-09-10T00:00:00Z'})]
    reader._details('AAPL')
    state = {'selected_ticker': 'AAPL', 'comparison_symbols': ['AAPL', 'SPY'],
             'stock_search': 'Apple', 'chart_period': '3 ปี'}
    messages = []
    class Rerun(Exception):
        pass
    def rerun():
        raise Rerun()
    monkeypatch.setattr(dashboard_ui, 'st', SimpleNamespace(
        session_state=state, caption=messages.append, warning=messages.append, rerun=rerun))
    idle = SimpleNamespace(state=lambda: {'revision': 0, 'busy': False})
    monkeypatch.setattr(dashboard_ui.a, 'get_updater', lambda: idle)
    monkeypatch.setattr(dashboard_ui, 'get_chart_service', lambda: idle)
    dependencies = page_dependencies('AAPL', state['comparison_symbols'])
    rendered = reader.page_status(dependencies)['page_revision']
    def poll():
        dashboard_ui._poll_data.__wrapped__(reader, rendered, 0, 0, 'AAPL', dependencies)
    return reader, state, Rerun, poll


def test_completed_comparison_requests_one_rerender_and_preserves_page_state(tmp_path, monkeypatch):
    reader, state, Rerun, poll = setup_page(tmp_path, monkeypatch)
    poll()
    reader._details('MSFT')
    poll()  # A separate viewer's completion has no effect on this page.
    reader._details('SPY')
    with pytest.raises(Rerun):
        poll()
    poll()  # An old fragment cannot repeatedly consume the same completion.
    assert state['selected_ticker'] == 'AAPL'
    assert state['comparison_symbols'] == ['AAPL', 'SPY']
    assert state['stock_search'] == 'Apple'
    assert state['chart_period'] == '3 ปี'


@pytest.mark.parametrize('changes', [
    {'selected_ticker': 'MSFT'},
    {'comparison_symbols': ['AAPL', 'QQQ']},
])
def test_old_fragment_does_not_renew_or_observe_a_changed_page(tmp_path, monkeypatch, changes):
    reader, state, _, poll = setup_page(tmp_path, monkeypatch)
    state.update(changes)
    def forbidden(*args):
        raise AssertionError('a stale fragment touched reader dependencies')
    monkeypatch.setattr(reader, 'select_page', forbidden)
    monkeypatch.setattr(reader, 'page_status', forbidden)
    poll()
