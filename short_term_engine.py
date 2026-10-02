"""Long-only, conditional intraday plans. Pure calculations, no broker orders.

The daily investment score is deliberately not an input. Unknown observations
fail closed. Volume is traded volume, not buy/sell order flow. All thresholds are
versioned research rules; none are fitted to, or proof of, profitable results.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
import re
from zoneinfo import ZoneInfo

import pandas as pd

MODEL = 'news-volume-intraday-v1'
UTC = timezone.utc
NY = ZoneInfo('America/New_York')
MIN_DOLLARS = 50_000_000
MIN_SHARES = 1_000_000
MAX_POOL = 200
MAX_QUOTE_AGE = 180
MAX_SPREAD = .002  # 0.20%; execution must be checked in the broker.
# Paid Dime stock commissions (0.15% each way) + spread budget + slippage
# + rounded regulatory-fee allowance. Do not assume a monthly free trade.
COST_RATE = .003 + MAX_SPREAD + .001 + .0001


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def instant(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        t = pd.Timestamp(value, unit='s', tz='UTC') if isinstance(value, (int, float)) else pd.Timestamp(value)
        return None if pd.isna(t) or t.tzinfo is None else t.tz_convert('UTC').to_pydatetime()
    except (ValueError, TypeError, OverflowError):
        return None


@lru_cache(maxsize=16)
def calendar(day):
    import pandas_market_calendars as mcal
    date = datetime.fromisoformat(day).date()
    return mcal.get_calendar('NYSE').schedule(start_date=date - timedelta(days=60),
                                             end_date=date + timedelta(days=10))


def session_context(now):
    now = instant(now)
    if now is None:
        raise ValueError('A timezone-aware analysis clock is required')
    day = now.astimezone(NY).date()
    sessions = calendar(day.isoformat())
    before = sessions[sessions.index.date < day]
    after = sessions[sessions.index.date > day]
    today = sessions[sessions.index.date == day]
    result = {'session': 'closed', 'trading_date': day.isoformat(),
              'previous_day': before.index[-1].date().isoformat(),
              'next_day': after.index[0].date().isoformat()}
    if today.empty:
        return result
    opening = today.iloc[0].market_open.to_pydatetime()
    closing = today.iloc[0].market_close.to_pydatetime()
    pre = opening.astimezone(NY).replace(hour=4, minute=0).astimezone(UTC)
    result.update(open=opening, close=closing, pre=pre)
    result['session'] = 'pre' if pre <= now < opening else 'regular' if opening <= now < closing else 'closed'
    return result


def build_pool(cache, universe, now):
    """Independent liquid-common-stock universe from a verified daily checkpoint."""
    context = session_context(now)
    quotes, classifications = cache.quotes(), cache.classifications()
    eligible, rejected = [], Counter()
    for ticker in universe:
        row = quotes.get(ticker, {})
        if row.get('Asset_Type') != 'Common Stock':
            rejected['not_common_stock'] += 1
            continue
        if (number(row.get('Close')) or 0) < 10 or (number(row.get('Dollar_Volume_20D')) or 0) < MIN_DOLLARS:
            rejected['daily_liquidity_or_price'] += 1
            continue
        info, _ = cache.get('info:' + ticker, request_remote=False)
        info = info if isinstance(info, dict) else {}
        if info.get('currency') != 'USD' or re.search(r'shell compan|blank check', str(info.get('industry', '')), re.I):
            rejected['currency_or_shell'] += 1
            continue
        eligible.append((ticker, row, info))
    eligible.sort(key=lambda x: -(number(x[1].get('Dollar_Volume_20D')) or 0))
    rows = []
    for ticker, row, info in eligible:
        if len(rows) >= MAX_POOL:
            break
        frame, _ = cache.history(ticker)
        if frame is None or frame.empty:
            rejected['missing_daily_history'] += 1
            continue
        # Never use the unfinished current day as a volume/range baseline.
        frame = frame.loc[frame.index.date <= datetime.fromisoformat(context['previous_day']).date()].tail(20)
        if len(frame) < 20 or frame.index[-1].date().isoformat() != context['previous_day']:
            rejected['daily_baseline_not_previous_session'] += 1
            continue
        shares = number(frame.Volume.mean())
        dollars = number((frame.Close * frame.Volume).mean())
        adr = number((frame.High - frame.Low).mean())
        if not shares or shares < MIN_SHARES or not dollars or dollars < MIN_DOLLARS or not adr or adr <= 0:
            rejected['completed_daily_liquidity'] += 1
            continue
        rows.append({'ticker': ticker, 'name': str(info.get('shortName') or row.get('Security_Name') or ticker),
                     'asset_type': 'Common Stock', 'currency': 'USD',
                     'sector': str(info.get('sector') or 'ไม่ระบุ'),
                     'industry': str(classifications.get(ticker, {}).get('Industry') or info.get('industry') or 'ไม่ระบุ'),
                     'baseline_day': context['previous_day'], 'average_shares_20d': shares,
                     'average_dollars_20d': dollars, 'adr_20d': adr,
                     'previous_close': float(frame.Close.iloc[-1]),
                     'previous_high': float(frame.High.iloc[-1])})
    return {'model': MODEL, 'computed_at': instant(now).isoformat(), 'scope': 'most-liquid-common-stocks',
            'universe_checked': len(universe), 'eligible_before_cap': len(eligible),
            'limit': MAX_POOL, 'excluded': dict(rejected), 'items': rows}


def validate_pool(pool, now):
    if not isinstance(pool, dict) or pool.get('model') != MODEL or not isinstance(pool.get('items'), list):
        raise ValueError('Missing independent short-term stock universe')
    at = instant(pool.get('computed_at'))
    if at is None or not 0 <= (now - at).total_seconds() <= 35 * 60 or len(pool['items']) > MAX_POOL:
        raise ValueError('Short-term universe is stale or oversized')
    seen = set()
    previous = session_context(now)['previous_day']
    for row in pool['items']:
        ticker = row.get('ticker') if isinstance(row, dict) else None
        if (not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}', ticker)
                or ticker in seen or row.get('asset_type') != 'Common Stock' or row.get('currency') != 'USD'
                or row.get('baseline_day') != previous
                or (number(row.get('average_shares_20d')) or 0) < MIN_SHARES
                or (number(row.get('average_dollars_20d')) or 0) < MIN_DOLLARS
                or (number(row.get('adr_20d')) or 0) <= 0):
            raise ValueError('Invalid short-term stock identity or baseline')
        seen.add(ticker)
    return pool['items']


def quote_observation(raw, ticker, now, session):
    if not isinstance(raw, dict) or raw.get('symbol') != ticker or raw.get('currency') != 'USD':
        return None
    if raw.get('marketState') != ('PRE' if session == 'pre' else 'REGULAR'):
        return None
    if raw.get('quoteType') not in ('EQUITY', 'ETF'):
        return None
    delay = number(raw.get('exchangeDataDelayedBy'))
    if delay is not None and delay > 0:
        return None
    prefix = 'preMarket' if session == 'pre' else 'regularMarket'
    price, at = number(raw.get(prefix + 'Price')), instant(raw.get(prefix + 'Time'))
    if not price or price <= 0 or at is None or not 0 <= (now - at).total_seconds() <= MAX_QUOTE_AGE:
        return None
    previous = number(raw.get('regularMarketPrice' if session == 'pre' else 'regularMarketPreviousClose'))
    if session == 'pre':
        regular_at = instant(raw.get('regularMarketTime'))
        if regular_at is None or regular_at.astimezone(NY).date().isoformat() != session_context(now)['previous_day']:
            return None
    if not previous or previous <= 0:
        return None
    bid, ask = number(raw.get('bid')), number(raw.get('ask'))
    spread = (ask - bid) / ((ask + bid) / 2) if bid and ask and 0 < bid <= ask else None
    # Yahoo commonly supplies no independent time for the bid/ask fields.
    # A recent last trade cannot authenticate an old displayed order book.
    return {'price': price, 'quote_time': at.isoformat(), 'change_pct': (price / previous - 1) * 100,
            'quote_previous_close': previous,
            'day_volume': number(raw.get('regularMarketVolume')), 'quote_type': raw['quoteType'],
            'spread_observation': spread, 'spread_verified': False,
            'bid_ask_note': 'ต้องตรวจ Bid/Ask ใน Dime; ฟีดไม่มีเวลาของ Bid/Ask แยกต่างหาก'}


def intraday_metrics(frame, now, session):
    """Compare cumulative volume with the SAME clock interval of >=10 sessions."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        return None, 'missing_intraday_bars'
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not set(required) <= set(frame.columns) or frame.index.has_duplicates:
        return None, 'invalid_intraday_bars'
    f = frame[required].sort_index().copy()
    if any(not pd.api.types.is_numeric_dtype(f[c]) for c in required):
        return None, 'invalid_intraday_bars'
    if f[required].isna().any().any() or not all(f[c].map(lambda x: number(x) is not None).all() for c in required):
        return None, 'invalid_intraday_bars'
    if ((f.High < f[['Open', 'Close', 'Low']].max(axis=1)) | (f.Low > f[['Open', 'Close']].min(axis=1))
            | (f[['Open', 'High', 'Low', 'Close']] <= 0).any(axis=1) | (f.Volume < 0)).any():
        return None, 'invalid_intraday_bars'
    # Yahoo bars are START-stamped. In-progress bars must not trigger a plan.
    f = f.loc[f.index + pd.Timedelta(minutes=5) <= now].tz_convert(NY)
    minute = f.index.hour * 60 + f.index.minute
    begin, end = (240, 570) if session == 'pre' else (570, 960)
    f = f.loc[(minute >= begin) & (minute < end)]
    today = now.astimezone(NY).date()
    current = f.loc[f.index.date == today]
    if len(current) < 6:
        return None, 'wait_for_six_closed_bars'
    if session == 'regular':
        expected = (current.index[-1].hour * 60 + current.index[-1].minute - 570) // 5 + 1
        if len(current) < expected * .9:
            return None, 'recent_bar_gap'
    latest_end = current.index[-1].to_pydatetime() + timedelta(minutes=5)
    if not 0 <= (now - latest_end).total_seconds() <= 360:
        return None, 'stale_intraday_bars'
    # Require continuous regular-session observations; zero-volume pre bars
    # can be omitted by the provider but an unobserved live gap blocks entry.
    if (current.index[-1] - current.index[-2]).total_seconds() > 600:
        return None, 'recent_bar_gap'
    minute_end = current.index[-1].hour * 60 + current.index[-1].minute
    valid_days = {i.date() for i in calendar(today.isoformat()).index if i.date() < today}
    historical = f.loc[(f.index.date < today) & (f.index.hour * 60 + f.index.minute <= minute_end)]
    volumes = []
    for day, group in historical.groupby(historical.index.date):
        if day not in valid_days:
            continue
        observed_end = group.index[-1].hour * 60 + group.index[-1].minute
        # Avoid dividing by a partial/missing historical session.
        if observed_end < minute_end - 5 or (session == 'regular' and len(group) < len(current) * .9):
            continue
        value = float(group.Volume.sum())
        if value > 0:
            volumes.append(value)
    volumes = volumes[-20:]
    if len(volumes) < 10:
        return None, 'insufficient_same_time_volume_history'
    volume = float(current.Volume.sum())
    dollars = float((current.Close * current.Volume).sum())
    if not volume:
        return None, 'no_session_volume'
    typical = (current.High + current.Low + current.Close) / 3
    vwap = float((typical * current.Volume).sum() / volume)
    previous = current.Close.shift(1)
    tr = pd.concat([current.High - current.Low, (current.High - previous).abs(),
                    (current.Low - previous).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    if atr <= 0:
        return None, 'no_price_range'
    return {'session_volume': volume, 'session_dollars': dollars,
            'rvol': volume / (sum(volumes) / len(volumes)), 'rvol_sessions': len(volumes),
            'vwap': vwap, 'atr_5m': atr, 'last_closed': float(current.Close.iloc[-1]),
            'bar_end': latest_end.astimezone(UTC).isoformat(),
            'ema9': float(current.Close.ewm(span=9, adjust=False).mean().iloc[-1]),
            'ema20': float(current.Close.ewm(span=20, adjust=False).mean().iloc[-1]),
            'trigger': float(current.High.iloc[-7:-1].max()),
            'swing_low': float(current.Low.tail(3).min()),
            'session_low': float(current.Low.min()), 'session_high': float(current.High.max())}, ''


def make_plan(row, quote, metrics, news, benchmark, now, session):
    """Conditional levels plus explicit entry invalidation; never an auto-buy flag."""
    reasons = []
    if not news:
        reasons.append('no_fresh_company_catalyst')
    if (quote['quote_type'] != 'EQUITY' or quote['price'] < 10):
        reasons.append('not_eligible_common_stock')
    if abs(quote['quote_previous_close'] / row['previous_close'] - 1) > .02:
        reasons.append('daily_price_scale_mismatch')
    minimum_rvol = 2.0 if session == 'pre' else 1.5
    if metrics['rvol'] < minimum_rvol:
        reasons.append('same_time_rvol_too_low')
    if metrics['session_dollars'] < (5_000_000 if session == 'pre' else 10_000_000):
        reasons.append('session_liquidity_too_low')
    if session == 'pre' and metrics['session_volume'] < 200_000:
        reasons.append('premarket_volume_too_low')
    if quote['price'] <= metrics['vwap'] or metrics['last_closed'] <= metrics['vwap'] or metrics['ema9'] <= metrics['ema20']:
        reasons.append('price_trend_not_confirmed')
    if benchmark is None or benchmark['change_pct'] < -.75 or quote['change_pct'] - benchmark['change_pct'] < .75:
        reasons.append('market_or_relative_strength')
    context = session_context(now)
    if context['session'] != session or context.get('close', now) - now < timedelta(minutes=45):
        reasons.append('outside_entry_window')
    atr = metrics['atr_5m']
    entry = math.ceil((metrics['trigger'] + .05 * atr) * 100) / 100
    maximum_entry = round(entry + max(.10 * atr, entry * .0005), 2)
    stop = math.floor((min(metrics['swing_low'], entry - .7 * atr) - .01) * 100) / 100
    risk = maximum_entry - stop
    if not .0015 <= risk / maximum_entry <= (.02 if session == 'pre' else .015):
        reasons.append('stop_distance_unsuitable')
    if quote['price'] > maximum_entry or quote['price'] < entry - .7 * atr:
        reasons.append('outside_entry_zone_or_chasing')
    # Consistent worst entry, paid round trip and spread/slippage allowance.
    costs = maximum_entry * COST_RATE
    net_risk = risk + costs
    target1 = math.ceil((maximum_entry + net_risk + costs) * 100) / 100
    target2 = math.ceil((maximum_entry + 2 * net_risk + costs) * 100) / 100
    # Required reward must fit inside a typical completed daily range and
    # the nearest known previous-day resistance. ADR is a budget, not a forecast.
    ceiling = metrics['session_low'] + row['adr_20d']
    if row.get('previous_high', 0) > maximum_entry:
        ceiling = min(ceiling, row['previous_high'])
    if target2 > ceiling:
        reasons.append('insufficient_room_after_costs')
    if reasons:
        return None, reasons
    expires = min(instant(quote['quote_time']) + timedelta(seconds=MAX_QUOTE_AGE),
                  now + timedelta(minutes=3), context['open'] if session == 'pre' else context['close'] - timedelta(minutes=10))
    return {**row, **quote, **metrics, 'news': news[:2], 'status': 'conditional_plan',
            'horizon': 'intraday', 'session': session, 'entry': entry, 'max_entry': maximum_entry,
            'stop': stop, 'target1': target1, 'target2': target2, 'range_ceiling': round(ceiling, 2),
            'cost_pct': COST_RATE * 100, 'net_rr': (target2 - maximum_entry - costs) / net_risk,
            'net_upside_pct': (target2 - maximum_entry - costs) / maximum_entry * 100,
            'next_trading_day': context['next_day'], 'expires_at': expires.isoformat(),
            'valid_until': min(now + timedelta(minutes=15), context['open'] if session == 'pre' else
                               context['close'] - timedelta(minutes=30)).isoformat(),
            'exit_by': (context['close'] - timedelta(minutes=10)).isoformat(),
            'entry_rule': 'รอแท่ง 5 นาทีปิดเหนือจุดเข้า แล้วใช้ Limit ไม่เกินเพดาน; ตรวจ Spread ไม่เกิน 0.20% ใน Dime',
            'cancel_rule': 'ยกเลิกเมื่อหลุด VWAP/จุดหยุดขาดทุน ราคาเกินเพดาน หรือแผนหมดอายุ',
            'order_flow': 'วอลุ่มซื้อขายรวม ไม่ใช่ยอดซื้อสุทธิ'}, []
