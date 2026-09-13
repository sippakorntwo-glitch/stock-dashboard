"""Near-live display-only observations; never overwrite completed daily scoring.

One worker per server, bounded memory/queue, shared provider lock, selectable
per-symbol cadence, 120 requests/hour ceiling and circuit breaker. Provider delay
is not a refresh interval. No account, paid feed or new credentials required.
"""
from __future__ import annotations
from collections import OrderedDict, deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
import threading
import time

QUOTE_INTERVALS = (30, 60, 120)
DEFAULT_QUOTE_INTERVAL = 30
UNKNOWN_SESSION_INTERVAL = 300
CLOSED_SESSION_INTERVAL = 1800
MAX_REQUESTS_PER_HOUR = 120


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    """A quote/session timestamp must be timezone-aware, never a guessed local time."""
    import pandas as pd
    try:
        if value is None or isinstance(value, bool):
            return None
        stamp = (pd.Timestamp(value, unit='s', tz='UTC')
                 if isinstance(value, (int, float)) else pd.Timestamp(value))
        if pd.isna(stamp) or stamp.tzinfo is None:
            return None
        return stamp.tz_convert('UTC')
    except (TypeError, ValueError, OverflowError):
        return None


def session_periods(metadata):
    """Use metadata from the existing history response; never issue a calendar call."""
    current = metadata.get('currentTradingPeriod', {})
    result = {}
    if not isinstance(current, dict):
        return result
    for name in ('pre', 'regular', 'post'):
        values = current.get(name, {})
        if not isinstance(values, dict):
            continue
        start, end = timestamp(values.get('start')), timestamp(values.get('end'))
        if start is not None and end is not None and 0 < (end-start).total_seconds() <= 86400:
            result[name] = {'start':start.isoformat(), 'end':end.isoformat()}
    return result


def quote_session(value=None, now=None):
    """Provider window coverage, not an assumption that every weekday is tradable."""
    stamp = timestamp(now if now is not None else datetime.now(timezone.utc))
    periods = (value or {}).get('session_periods', {})
    if stamp is None or not isinstance(periods, dict):
        return 'unknown'
    valid = []
    for name in ('regular', 'pre', 'post'):
        period = periods.get(name, {})
        if not isinstance(period, dict):
            continue
        start, end = timestamp(period.get('start')), timestamp(period.get('end'))
        if start is None or end is None or end <= start:
            continue
        valid.append((start,end))
        if start <= stamp < end:
            return name
    # A dated future/current-day window is informative. Old metadata is not a
    # calendar for the next day, especially around holidays or an early close.
    if valid and any(start >= stamp or end.date() == stamp.date() for start,end in valid):
        return 'closed'
    return 'unknown'


def polling_interval(now=None, observation=None, interval=DEFAULT_QUOTE_INTERVAL):
    import pandas as pd
    stamp = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    interval = interval if interval in QUOTE_INTERVALS else DEFAULT_QUOTE_INTERVAL
    state = quote_session(observation, stamp)
    if state in ('pre','regular','post'):
        return interval
    local = stamp.tz_convert('America/New_York')
    # Unknown sessions only probe conservatively. Weekday hours never label a
    # holiday as open or enable the rapid cadence without provider evidence.
    delay = (UNKNOWN_SESSION_INTERVAL if state == 'unknown' and local.weekday() < 5
             and 4 <= local.hour < 20 else CLOSED_SESSION_INTERVAL)
    periods = (observation or {}).get('session_periods', {})
    for period in (periods.values() if isinstance(periods,dict) else ()):
        start = timestamp(period.get('start')) if isinstance(period, dict) else None
        if start is not None and start > stamp:
            delay = min(delay, max(1.0,(start-stamp).total_seconds()))
    return delay


def retry_delay(exc, now, minimum):
    """Never retry earlier than an explicit provider Retry-After response."""
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    raw = headers.get('Retry-After') or headers.get('retry-after')
    if raw is not None:
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            try:
                seconds = parsedate_to_datetime(str(raw)).timestamp()-now
            except (TypeError, ValueError, OverflowError):
                seconds = 0
        if math.isfinite(seconds):
            return max(minimum,seconds)
    return minimum


def fetch_observation(ticker):
    import pandas as pd
    import dashboard_runtime as a
    with a.core._PROVIDER_LOCK:
        source = a.yf.Ticker(ticker)
        bars = source.history(period='1d', interval='1m', auto_adjust=False,
                              actions=False, prepost=True, timeout=10, raise_errors=True)
        meta = source.get_history_metadata() or {}
    if bars is None or bars.empty or 'Close' not in bars:
        raise ValueError('Provider returned no minute observations')
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError('Provider minute observations have no timezone')
    bars = bars.sort_index()
    price = positive(bars.Close.iloc[-1])
    observed = bars.index[-1].tz_convert('UTC')
    now = pd.Timestamp.now(tz='UTC')
    if price is None or observed > now + pd.Timedelta(seconds=60):
        raise ValueError('Invalid price or future observation')
    previous = positive(meta.get('previousClose')) or positive(meta.get('chartPreviousClose'))
    return {'ticker':ticker, 'price':price, 'bar_time':observed.isoformat(),
            'fetched_at':now.isoformat(), 'currency':str(meta.get('currency') or ''),
            'change_pct':(price / previous - 1) * 100 if previous else None,
            'previous_close':previous, 'source':'Yahoo Finance',
            'interval':'1m', 'includes_extended_hours':True,
            'session_periods':session_periods(meta),
            'exchange_timezone':str(meta.get('exchangeTimezoneName') or '')}


class QuoteService:
    def __init__(self, fetcher=fetch_observation, clock=time.time):
        self.fetcher = fetcher
        self.clock = clock
        self.lock = threading.RLock()
        self.jobs = deque()
        self.pending = set()
        self.calls = deque()
        self.values = OrderedDict()
        self.attempts = OrderedDict()
        self.thread = None
        self.cooldown_until = 0.0
        self.rate_limits = 0
        self.intervals = {}

    def _due(self, ticker, interval):
        attempt = self.attempts.get(ticker, {})
        if not attempt:
            return 0.0
        if attempt.get('error'):
            return attempt.get('next_due', 0.0)
        # A faster UI setting can shorten a successful cadence, but never an
        # error/rate-limit guard. Crossing into an advertised session wakes up.
        attempted = attempt.get('attempted_at',0)
        value = self.values.get(ticker)
        due = attempted + polling_interval(datetime.fromtimestamp(attempted,timezone.utc),value,interval)
        if quote_session(value,datetime.fromtimestamp(self.clock(),timezone.utc)) in ('pre','regular','post'):
            due = min(due,attempted+interval)
        return due

    def read(self, ticker, interval=DEFAULT_QUOTE_INTERVAL):
        with self.lock:
            value = self.values.get(ticker)
            attempt = dict(self.attempts.get(ticker, {}))
            now = self.clock()
            while self.calls and self.calls[0] <= now - 3600:
                self.calls.popleft()
            attempt['next_due'] = self._due(ticker,interval)
            if self.cooldown_until > now:
                attempt.update(status='rate_limited', next_due=max(attempt['next_due'],self.cooldown_until))
            elif len(self.calls) >= MAX_REQUESTS_PER_HOUR:
                attempt.update(status='budget', next_due=max(attempt['next_due'],self.calls[0]+3600))
            else:
                attempt['status'] = 'retry' if attempt.get('error') else 'scheduled'
            return (dict(value) if value else None, dict(attempt), ticker in self.pending)

    def request(self, ticker, interval=DEFAULT_QUOTE_INTERVAL):
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,29}', str(ticker)):
            return False
        now = self.clock()
        interval = interval if interval in QUOTE_INTERVALS else DEFAULT_QUOTE_INTERVAL
        with self.lock:
            while self.calls and self.calls[0] <= now - 3600:
                self.calls.popleft()
            if (now < self.cooldown_until or now < self._due(ticker,interval)
                    or ticker in self.pending or len(self.pending) >= 4
                    or len(self.calls) + len(self.pending) >= MAX_REQUESTS_PER_HOUR):
                return False
            self.intervals[ticker] = interval
            self.pending.add(ticker)
            self.jobs.append(ticker)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name='selected-minute-quote', daemon=True)
                self.thread.start()
        return True

    def _run(self):
        while True:
            with self.lock:
                if not self.jobs or self.clock() < self.cooldown_until:
                    self.pending.difference_update(self.jobs)
                    self.jobs.clear()
                    self.thread = None
                    return
                ticker = self.jobs.popleft()
                self.calls.append(self.clock())
            error = ''
            ttl = UNKNOWN_SESSION_INTERVAL
            try:
                value = self.fetcher(ticker)
                if not isinstance(value, dict) or value.get('ticker') != ticker or positive(value.get('price')) is None:
                    raise ValueError('Invalid provider response')
                observed = timestamp(value.get('bar_time'))
                now = self.clock()
                if observed is None or observed.timestamp() > now + 60:
                    raise ValueError('Invalid source timestamp')
                with self.lock:
                    old = self.values.get(ticker)
                    old_stamp = timestamp((old or {}).get('bar_time'))
                    if old_stamp is not None and observed < old_stamp:
                        raise ValueError('Provider observation regressed')
                    self.values[ticker] = dict(value)
                    self.values.move_to_end(ticker)
                    while len(self.values) > 64:
                        self.values.popitem(last=False)
                    self.rate_limits = 0
                    ttl = polling_interval(datetime.fromtimestamp(now,timezone.utc),value,
                                           self.intervals.get(ticker,DEFAULT_QUOTE_INTERVAL))
            except Exception as exc:
                limited = any(s in str(exc).lower() for s in ('429','rate limit','too many')) or 'RateLimit' in type(exc).__name__
                if limited:
                    self.rate_limits = min(self.rate_limits+1,3)
                ttl = retry_delay(exc,self.clock(), min(3600,900*2**(self.rate_limits-1)) if limited else 300)
                error = ('แหล่งข้อมูลจำกัดคำขอ — พักตามเวลาที่กำหนดและเก็บราคาครั้งล่าสุดไว้' if limited
                         else 'ยังอัปเดตราคาไม่ได้ (' + type(exc).__name__ + ') — เก็บราคาและเวลาข้อมูลเดิมไว้')
                if limited:
                    with self.lock:
                        self.cooldown_until = self.clock() + ttl
            finally:
                with self.lock:
                    self.attempts[ticker] = {'next_due':self.clock()+ttl, 'error':error,
                                             'attempted_at':self.clock()}
                    self.attempts.move_to_end(ticker)
                    while len(self.attempts) > 128:
                        expired,_ = self.attempts.popitem(last=False)
                        self.intervals.pop(expired,None)
                    self.pending.discard(ticker)
            time.sleep(1)
