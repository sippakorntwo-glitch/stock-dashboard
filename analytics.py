"""Offline calculations on observed, positive, adjusted closing prices."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
TRADING_DAYS = 252
METRIC_VERSION = 3


def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def clean_close(history):
    if history is None or history.empty or 'Close' not in history:
        return pd.Series(dtype=float)
    s = pd.to_numeric(history.Close, errors='coerce').copy()
    s.index = pd.DatetimeIndex(pd.to_datetime(s.index)).tz_localize(None).normalize()
    s = s.loc[s.index.notna() & np.isfinite(s) & s.gt(0)]
    return s.loc[~s.index.duplicated(keep='last')].sort_index().astype(float)


def period_return(close, months):
    if close.empty:
        return None
    start = close.index[-1] - pd.DateOffset(months=months)
    if close.index[0] > start:
        return None
    window = close.loc[close.index >= start]
    return float((window.iloc[-1] / window.iloc[0] - 1) * 100) if len(window) >= 2 else None


def risk_metrics(history):
    close = clean_close(history)
    out = {k: None for k in ('return_pct', 'cagr_pct', 'volatility_pct', 'max_drawdown_pct', 'current_drawdown_pct', 'best_day_pct', 'worst_day_pct')}
    out.update(observations=len(close), start=None, end=None)
    if len(close) < 2:
        return out
    changes = close.pct_change(fill_method=None).dropna()
    dd = close / close.cummax() - 1
    days = (close.index[-1] - close.index[0]).days
    out.update(start=close.index[0].date().isoformat(), end=close.index[-1].date().isoformat(),
               return_pct=float((close.iloc[-1] / close.iloc[0] - 1) * 100),
               max_drawdown_pct=float(dd.min() * 100), current_drawdown_pct=float(dd.iloc[-1] * 100),
               best_day_pct=float(changes.max() * 100), worst_day_pct=float(changes.min() * 100))
    if len(changes) >= 20:
        out['volatility_pct'] = finite(changes.std(ddof=1) * math.sqrt(TRADING_DAYS) * 100)
    if days >= 365:
        out['cagr_pct'] = finite(((close.iloc[-1] / close.iloc[0]) ** (365.25 / days) - 1) * 100)
    return out


def extended_snapshot(history):
    close = clean_close(history)
    out = {'Metric_Calc_Version': METRIC_VERSION, 'Return_1D': None,
           'Return_1M': period_return(close, 1), 'Return_3M': period_return(close, 3),
           'Return_6M': period_return(close, 6), 'Volatility_20D': None,
           'Dollar_Volume_20D': None, 'Drawdown_52W': None}
    if len(close) >= 2:
        out['Return_1D'] = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
    if len(close) >= 21:
        out['Volatility_20D'] = finite(close.pct_change(fill_method=None).tail(20).std(ddof=1) * math.sqrt(TRADING_DAYS) * 100)
    if len(close) >= 252:
        out['Drawdown_52W'] = float((close.iloc[-1] / close.tail(252).max() - 1) * 100)
    if history is not None and len(history) >= 20 and 'Volume' in history:
        v = (pd.to_numeric(history.Close, errors='coerce') * pd.to_numeric(history.Volume, errors='coerce')).tail(20)
        if v.notna().all() and np.isfinite(v).all() and v.ge(0).all():
            out['Dollar_Volume_20D'] = float(v.mean())
    from return_periods import table_returns, return_observations
    out.update(table_returns(history))
    out['Return_Observations'] = return_observations(history)
    return out


def comparison(histories, months=12):
    series = [clean_close(h).rename(t) for t, h in histories.items()]
    if len(series) < 2:
        raise ValueError('ต้องมีอย่างน้อยสองสินทรัพย์')
    prices = pd.concat(series, axis=1, join='inner').dropna()
    if prices.empty:
        raise ValueError('ไม่มีวันที่ราคาครบพร้อมกัน')
    start = prices.index[-1] - pd.DateOffset(months=months)
    full = bool(prices.index[0] <= start)
    prices = prices.loc[prices.index >= start]
    if len(prices) < 2:
        raise ValueError('ข้อมูลวันที่ร่วมกันไม่พอ')
    returns = prices.pct_change(fill_method=None).dropna()
    return {'prices': prices, 'normalized': (prices / prices.iloc[0] - 1) * 100,
            'returns': returns, 'full_window': full,
            'correlation': returns.corr() if len(returns) >= 20 else pd.DataFrame()}


def beta_to_benchmark(prices, asset, benchmark='SPY'):
    if asset == benchmark:
        return 1.0
    changes = prices[[asset, benchmark]].dropna().pct_change(fill_method=None).dropna()
    if len(changes) < 60:
        return None
    variance = float(changes[benchmark].var(ddof=1))
    return finite(changes[asset].cov(changes[benchmark]) / variance) if variance > 0 else None


def quality_counts(frame, max_age_days=4, now=None):
    today = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz='America/New_York'))
    if today.tzinfo is not None:
        today = today.tz_convert('America/New_York').tz_localize(None)
    dates = pd.to_datetime(frame.get('Price_AsOf', pd.Series(index=frame.index, dtype=object)), errors='coerce', utc=True).dt.tz_localize(None)
    ages = (today.normalize() - dates.dt.normalize()).dt.days
    close = pd.to_numeric(frame.get('Close', pd.Series(index=frame.index, dtype=float)), errors='coerce')
    usable = close.gt(0) & np.isfinite(close)
    return {'total': len(frame), 'priced': int(usable.sum()),
            'recent': int((usable & ages.between(0, max_age_days)).sum()),
            'unknown_time': int((usable & dates.isna()).sum()),
            'old_or_future': int((usable & dates.notna() & ~ages.between(0, max_age_days)).sum())}
