"""Fast, equivalent catalog joins and idempotent session refresh coordination.

No provider calls, score changes, or synthetic market values. The completion
receipt is emitted only after this session's complete research page is built.
"""
from __future__ import annotations
import html
from typing import MutableMapping
import pandas as pd


def merge_classifications(frame: pd.DataFrame, classifications: dict | None) -> pd.DataFrame:
    """Vectorized equivalent of the original per-ticker timestamp comparison."""
    records = {
        ticker: {field: row.get(field, '') for field in ('Industry','Industry_Source','Industry_Time')}
        for ticker, row in (classifications or {}).items()
        if ticker in frame.index and row.get('Industry')
    }
    if not records:
        return frame
    incoming = pd.DataFrame.from_dict(records, orient='index')
    old = pd.to_datetime(frame.loc[incoming.index,'Industry_Time'], utc=True, errors='coerce', format='mixed')
    new = pd.to_datetime(incoming['Industry_Time'], utc=True, errors='coerce', format='mixed')
    eligible = old.isna() | (new.notna() & old.le(new))
    indices = incoming.index[eligible]
    for field in ('Industry','Industry_Source','Industry_Time'):
        # Preserve provider None and unknown source fields; never invent a label.
        frame[field] = frame[field].astype(object)
        frame.loc[indices,field] = incoming.loc[indices,field]
    return frame


def claim_refresh(state: MutableMapping, observed: tuple, rendered: tuple) -> bool:
    """Consume a changed data revision BEFORE requesting a full rerun.

    A queued automatic fragment can retain the old rendered arguments. It must
    not cancel successive user reruns by requesting the same revision again.
    """
    if observed == rendered or state.get('_claimed_data_refresh') == observed:
        return False
    state['_claimed_data_refresh'] = observed
    return True


def page_receipt(version: str, ticker: str, query: str, elapsed: float) -> str:
    values = [html.escape(str(value), quote=True) for value in (version,ticker,query)]
    return (f'<span class="workspace-ready" data-version="{values[0]}" '
            f'data-ticker="{values[1]}" data-search="{values[2]}" '
            f'data-render-seconds="{elapsed:.3f}"></span>')
