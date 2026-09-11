"""Near-live display-only observations; never overwrite completed daily scoring.

One worker per server, bounded memory/queue, shared provider lock, sixty-second
per-symbol cache, 120 requests/hour ceiling and circuit breaker. Provider delay
is not a refresh interval. No account, paid feed or new credentials required.
"""
from __future__ import annotations
from collections import OrderedDict, deque
from datetime import datetime, timezone
import math
import re
import threading
import time


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def polling_interval(now=None):
    import pandas as pd
    stamp = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    local = stamp.tz_convert('America/New_York')
    # This is a request budget window, NOT a claim that the exchange is open.
    return 60 if local.weekday() < 5 and 4 <= local.hour < 20 else 1800


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
            'interval':'1m', 'includes_extended_hours':True}


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

    def read(self, ticker):
        with self.lock:
            value = self.values.get(ticker)
            attempt = self.attempts.get(ticker, {})
            return (dict(value) if value else None, dict(attempt), ticker in self.pending)

    def request(self, ticker):
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,29}', str(ticker)):
            return False
        now = self.clock()
        with self.lock:
            while self.calls and self.calls[0] <= now - 3600:
                self.calls.popleft()
            if (now < self.cooldown_until or now < self.attempts.get(ticker, {}).get('next_due', 0)
                    or ticker in self.pending or len(self.pending) >= 4
                    or len(self.calls) + len(self.pending) >= 120):
                return False
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
            ttl = polling_interval(datetime.fromtimestamp(self.clock(), timezone.utc))
            try:
                value = self.fetcher(ticker)
                if not isinstance(value, dict) or value.get('ticker') != ticker or positive(value.get('price')) is None:
                    raise ValueError('Invalid provider response')
                with self.lock:
                    self.values[ticker] = dict(value)
                    self.values.move_to_end(ticker)
                    while len(self.values) > 64:
                        self.values.popitem(last=False)
            except Exception as exc:
                limited = any(s in str(exc).lower() for s in ('429','rate limit','too many')) or 'RateLimit' in type(exc).__name__
                ttl = 900 if limited else 300
                error = ('Provider rate limit: paused for 15 minutes; previous observation retained.' if limited
                         else 'Refresh unavailable (' + type(exc).__name__ + '); previous observation retained. Retry after 5 minutes.')
                if limited:
                    with self.lock:
                        self.cooldown_until = self.clock() + ttl
            finally:
                with self.lock:
                    self.attempts[ticker] = {'next_due':self.clock()+ttl, 'error':error,
                                             'attempted_at':self.clock()}
                    self.attempts.move_to_end(ticker)
                    while len(self.attempts) > 128:
                        self.attempts.popitem(last=False)
                    self.pending.discard(ticker)
            time.sleep(1)
