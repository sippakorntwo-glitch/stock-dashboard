"""Selection state shared by the table and the single-page stock details.

The event refers to the immutable, displayed row order, never the full catalog.
This module has no provider or Streamlit imports and is independently testable.
"""
from __future__ import annotations
import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence


def table_key(tickers: Sequence[str], epoch: int = 0) -> str:
    digest = hashlib.sha256(json.dumps(list(tickers)).encode()).hexdigest()[:20]
    return f'stock_picker_{epoch}_{digest}'


def signature(event: Mapping | None) -> tuple[tuple, tuple]:
    selection = (event or {}).get('selection', {})
    rows = tuple(selection.get('rows') or ())
    cells = tuple(tuple(cell) for cell in (selection.get('cells') or ()))
    return rows, cells


def selected_symbol(event: Mapping | None, tickers: Sequence[str], previous=None) -> str | None:
    rows, cells = signature(event)
    old_rows, old_cells = signature(previous)
    # The last changed selection wins when both a row and a cell are retained.
    if cells and cells != old_cells:
        index = cells[-1][0] if len(cells[-1]) == 2 else None
    elif rows and rows != old_rows:
        index = rows[-1]
    else:
        return None
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(tickers):
        return str(tickers[index])
    return None


def set_selected(state: MutableMapping, ticker: str, *, reset_table: bool = False) -> None:
    changed = state.get('selected_ticker') != ticker
    state['selected_ticker'] = ticker
    state['ticker_input'] = ticker
    if changed or 'comparison_symbols' not in state:
        state['comparison_symbols'] = [ticker, 'SPY' if ticker != 'SPY' else 'QQQ']
    if reset_table:
        state['_table_epoch'] = state.get('_table_epoch', 0) + 1
        state.pop('_last_table_event', None)


def apply_table_selection(state: MutableMapping, key: str, tickers: Sequence[str]) -> None:
    event = state.get(key, {})
    last = state.get('_last_table_event', {})
    previous = last.get('event') if last.get('key') == key else None
    ticker = selected_symbol(event, tickers, previous)
    rows, cells = signature(event)
    state['_last_table_event'] = {'key': key, 'event': {'selection': {'rows': rows, 'cells': cells}}}
    if ticker:
        set_selected(state, ticker)
