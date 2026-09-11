"""One source of truth for watchlist return periods, English labels and exports.

Input is completed, adjusted DAILY history. Day periods count observed trading
sessions; months and years use calendar boundaries, not fixed 21/252 multiples.
Invalid endpoint prices stay unavailable and never shift the requested period.
"""
from __future__ import annotations
import math
import pandas as pd

# Keep legacy keys used by scoring and stored snapshots; only the UI is renamed.
RETURN_SPECS = (
    ('Return_1D', '1 Day', 1, None),
    ('Return_3D', '3 Days', 3, None),
    ('Return_7D', '7 Days', 7, None),
    ('Return_1M', '1 Month', None, 1),
    ('Return_6M', '6 Months', None, 6),
    ('Historical_Return', '1 Year', None, 12),
    ('Return_3Y', '3 Years', None, 36),
    ('Return_5Y', '5 Years', None, 60),
)
RETURN_FIELDS = tuple(item[0] for item in RETURN_SPECS)
RETURN_LABELS = {field: period + ' (%)' for field, period, _, _ in RETURN_SPECS}
RETURN_CAPTION = (
    'Cumulative Return (%) = (latest adjusted close / starting adjusted close - 1) × 100. '
    '1/3/7 Days use 1/3/7 completed trading-session changes. Months and years use '
    'calendar periods and the first observed close on or after the start date. '
    'Returns end on Price As Of, not the current clock time. Not CAGR; fees, taxes '
    'and currency conversion are excluded. — means unavailable, not zero.'
)
EXPORT_LABELS = {
    'Ticker': 'Ticker', 'Security_Name': 'Company / ETF',
    'Industry': 'Industry / ETF Category', 'Asset_Type': 'Asset Type',
    'Status': 'Status', 'Close': 'Watchlist Price', **RETURN_LABELS,
    'RSI_14': 'RSI (14)', 'ATR_Pct': 'ATR / Price (%)',
    'Volatility_20D': '20-Day Volatility (%)',
    'Dollar_Volume_20D': '20-Day Average Price × Volume',
    'Price_AsOf': 'Price As Of', 'Data_Status': 'Data Status',
}
TABLE_FIELDS = ('Ticker', 'Security_Name', 'Industry', 'Asset_Type', 'Status',
                'Close', *RETURN_FIELDS, 'RSI_14', 'ATR_Pct', 'Volatility_20D',
                'Dollar_Volume_20D', 'Price_AsOf', 'Data_Status')


def positive_price(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def daily_closes(history):
    if history is None or history.empty or 'Close' not in history:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history['Close'], errors='coerce').copy()
    index = pd.DatetimeIndex(pd.to_datetime(close.index))
    close.index = index.tz_localize(None).normalize()
    close = close.loc[close.index.notna()]
    # Do not drop invalid prices: that would silently change session offsets.
    return close.loc[~close.index.duplicated(keep='last')].sort_index().astype(float)


def period_observation(close, *, sessions=None, months=None):
    if (sessions is None) == (months is None):
        raise ValueError('Specify exactly one of sessions or months')
    amount = sessions if sessions is not None else months
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        raise ValueError('The return period must be a positive integer')
    result = {'value': None, 'start': None, 'end': None,
              'start_price': None, 'end_price': None, 'state': 'short_history'}
    if close.empty:
        return result
    result['end'] = close.index[-1].date().isoformat()
    result['end_price'] = positive_price(close.iloc[-1])
    if sessions is not None:
        if len(close) <= sessions:
            return result
        first = len(close) - sessions - 1
    else:
        cutoff = close.index[-1] - pd.DateOffset(months=months)
        if close.index[0] > cutoff:
            return result
        first = int(close.index.searchsorted(cutoff, side='left'))
        if first >= len(close) - 1:
            return result
        if (close.index[first] - cutoff).days > 7:
            result['state'] = 'missing_inputs'
            return result
    result['start'] = close.index[first].date().isoformat()
    result['start_price'] = positive_price(close.iloc[first])
    if result['start_price'] is None or result['end_price'] is None:
        result['state'] = 'missing_inputs'
        return result
    value = (result['end_price'] / result['start_price'] - 1) * 100
    if not math.isfinite(value):
        result['state'] = 'missing_inputs'
        return result
    result.update(value=float(value), state='available')
    return result


def table_returns(history):
    close = daily_closes(history)
    return {field: period_observation(close, sessions=sessions, months=months)['value']
            for field, _, sessions, months in RETURN_SPECS}


def return_help(field):
    field = str(field).removeprefix('price.')
    item = next((spec for spec in RETURN_SPECS if spec[0] == field), None)
    if item is None:
        return None
    _, period, sessions, months = item
    basis = (f'The latest completed daily close divided by the close {sessions} '
             f'completed trading session(s) earlier' if sessions else
             f'The latest completed daily close divided by the first observed '
             f'close on or after the date {months} calendar month(s) earlier; '
             f'history must cover that starting date')
    return (f'{period} cumulative return (%). {basis}, minus 1, multiplied by 100. '
            'Uses adjusted prices. Not CAGR or revenue growth. '
            'Insufficient history or an invalid endpoint is shown as —, not 0%.')


def return_column_config():
    import streamlit as st
    return {field: st.column_config.NumberColumn(RETURN_LABELS[field],
                format='%+.2f%%', help=return_help(field)) for field in RETURN_FIELDS}


def export_watchlist(frame):
    """Same eight periods and order as the visible table, for ALL filtered rows."""
    return frame.reindex(columns=TABLE_FIELDS).rename(columns=EXPORT_LABELS)
