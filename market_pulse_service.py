"""Bounded, shared market/news polling; all provider work runs off the UI thread.

A round makes one Yahoo quote request for at most twelve symbols, followed by
at most one eligible news request.  The limits count logical provider operations;
yfinance may make additional authentication requests internally.  A 30-second
display refresh is not a guarantee that a provider publishes a new observation.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import math
import re
import threading
import time

from live_quotes import retry_delay, timestamp

POLL_SECONDS = 30
NEWS_TTL_SECONDS = 300
MAX_SYMBOLS = 12
MAX_NEWS_SYMBOLS = 10
MAX_CACHE_SYMBOLS = 64
MAX_REQUESTS_PER_HOUR = 240
MAX_QUOTE_REQUESTS_PER_HOUR = 120
MAX_NEWS_REQUESTS_PER_HOUR = 120
QUOTE_URL = 'https://query1.finance.yahoo.com/v7/finance/quote'
NEWS_URL = 'https://finance.yahoo.com/xhr/ncp?queryRef=latestNews&serviceKey=ncp_fin'


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _symbols(values, limit):
    if not isinstance(values, (list, tuple)) or len(values) > limit:
        return None
    result = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,29}', value):
            return None
        if value not in result:
            result.append(value)
    return tuple(result)


def fetch_quotes(symbols):
    """Use yfinance's normal authentication path and one multi-symbol endpoint."""
    from yfinance.data import YfData
    import dashboard_runtime as a
    with a.core._PROVIDER_LOCK:
        return YfData().get_raw_json(
            QUOTE_URL, params={'symbols': ','.join(symbols), 'formatted': 'false'},
            timeout=10,
        )


def fetch_news(ticker):
    """Use get_news's normal endpoint, but validate failures before calling it empty.

    yfinance 1.7's Ticker.get_news memoizes each instance and converts some
    malformed responses into [].  This equivalent uncached request validates
    the HTTP status and stream envelope so errors cannot erase good news.
    """
    from yfinance.data import YfData
    import dashboard_runtime as a
    with a.core._PROVIDER_LOCK:
        response = YfData().post(
            NEWS_URL, body={'serviceConfig': {'snippetCount': 5, 's': [ticker]}},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get('errors') or payload.get('error'):
        raise ValueError('Invalid news envelope')
    data = payload.get('data')
    stream = data.get('tickerStream') if isinstance(data, dict) else None
    articles = stream.get('stream') if isinstance(stream, dict) else None
    if not isinstance(articles, list):
        raise ValueError('Invalid news stream')
    return [article for article in articles if not isinstance(article, dict) or not article.get('ad')]


def _is_rate_limit(exc):
    response = getattr(exc, 'response', None)
    return (getattr(response, 'status_code', None) == 429
            or 'RateLimit' in type(exc).__name__
            or any(part in str(exc).lower() for part in ('429', 'rate limit', 'too many')))


def _newest_news(value):
    stamps = [timestamp(item.get('published_at')) for item in value.get('items', [])
              if isinstance(item, dict)]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


class PulseService:
    """One worker per service, shared results, fair news rotation and backoff.

    Injected quote/news fetchers return raw provider payloads, like the default
    fetchers.  ``request`` only starts work; ``read`` never calls the network.
    Numeric ``next_due``/``cooldown_until`` use Unix seconds, while observation
    and receipt timestamps are timezone-aware ISO strings.
    """

    def __init__(self, quote_fetcher=None, news_fetcher=None, clock=time.time):
        self.quote_fetcher = quote_fetcher or fetch_quotes
        self.news_fetcher = news_fetcher or fetch_news
        self.clock = clock
        self.lock = threading.RLock()
        self.quotes = OrderedDict()
        self.news = OrderedDict()
        self.quote_status = OrderedDict()
        self.news_status = OrderedDict()
        self.news_attempts = OrderedDict()
        self.calls = deque()
        self.quote_calls = deque()
        self.news_calls = deque()
        self.busy = False
        self.thread = None
        self.last_attempt = None
        self.checked_at = None
        self.next_due = 0.0
        self.cooldown_until = 0.0
        self.rate_limits = 0
        self.status = 'waiting'
        self.error = ''

    def _prune(self, now):
        for calls in (self.calls, self.quote_calls, self.news_calls):
            while calls and calls[0] <= now - 3600:
                calls.popleft()

    def _budget_due(self, kind, now):
        self._prune(now)
        due = now
        if len(self.calls) >= MAX_REQUESTS_PER_HOUR:
            due = max(due, self.calls[0] + 3600)
        calls, limit = ((self.quote_calls, MAX_QUOTE_REQUESTS_PER_HOUR)
                        if kind == 'quote' else (self.news_calls, MAX_NEWS_REQUESTS_PER_HOUR))
        if len(calls) >= limit:
            due = max(due, calls[0] + 3600)
        return due

    def _record_call(self, kind, now):
        self.calls.append(now)
        (self.quote_calls if kind == 'quote' else self.news_calls).append(now)

    @staticmethod
    def _put(cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > MAX_CACHE_SYMBOLS:
            cache.popitem(last=False)

    def request(self, symbols, news_symbols=None):
        wanted = _symbols(symbols, MAX_SYMBOLS)
        if not wanted:
            return False
        if news_symbols is None:
            news_symbols = [symbol for symbol in wanted if symbol not in ('SPY', 'QQQ')][:MAX_NEWS_SYMBOLS]
        news_wanted = _symbols(news_symbols, MAX_NEWS_SYMBOLS)
        if news_wanted is None or not set(news_wanted).issubset(wanted):
            return False
        now = self.clock()
        if not math.isfinite(now):
            return False
        with self.lock:
            if self.busy or now < max(self.next_due, self.cooldown_until):
                return False
            budget_due = self._budget_due('quote', now)
            if budget_due > now:
                self.next_due = budget_due
                self.status = 'budget'
                self.error = 'พักการตรวจข้อมูลตามจำนวนคำขอที่กำหนด เก็บข้อมูลครั้งล่าสุดไว้'
                return False
            self.busy = True
            self.last_attempt = _iso(now)
            self.next_due = now + POLL_SECONDS
            self.error = ''
            self._record_call('quote', now)
            self.thread = threading.Thread(
                target=self._run, args=(wanted, news_wanted),
                name='top10-market-pulse', daemon=True,
            )
            self.thread.start()
        return True

    def read(self):
        with self.lock:
            now = self.clock()
            state = self.status
            if now < self.cooldown_until:
                state = 'rate_limited'
            elif self.busy:
                state = 'refreshing'
            return deepcopy({
                'quotes': dict(self.quotes), 'news': dict(self.news),
                'quote_status': dict(self.quote_status), 'news_status': dict(self.news_status),
                'status': state, 'busy': self.busy, 'last_attempt': self.last_attempt,
                'checked_at': self.checked_at, 'next_due': max(self.next_due, self.cooldown_until),
                'cooldown_until': self.cooldown_until, 'error': self.error,
            })

    def _failure(self, exc, kind, ticker=None):
        now = self.clock()
        limited = _is_rate_limit(exc)
        with self.lock:
            if limited:
                self.rate_limits = min(self.rate_limits + 1, 3)
            minimum = min(3600, 900 * 2 ** (self.rate_limits - 1)) if limited else 300
            wait = retry_delay(exc, now, minimum)
            message = ('แหล่งข้อมูลจำกัดคำขอ พักตามเวลาที่กำหนดและเก็บข้อมูลครั้งล่าสุดไว้'
                       if limited else 'ยังตรวจข้อมูลจากผู้ให้ข้อมูลไม่ได้ เก็บข้อมูลและเวลาเดิมไว้')
            if limited:
                self.cooldown_until = max(self.cooldown_until, now + wait)
                self.status = 'rate_limited'
            elif kind == 'quote':
                self.status = 'error'
            else:
                self.status = 'partial'
            if kind == 'quote':
                self.next_due = max(self.next_due, now + wait)
            if ticker is not None:
                self._put(self.news_attempts, ticker, {'attempted_at': now, 'next_due': now + wait})
                self._put(self.news_status, ticker, {
                    'state': 'rate_limited' if limited else 'error',
                    'last_attempt': _iso(now), 'next_due': now + wait, 'error': message,
                })
            self.error = message

    def _update_quotes(self, raw, symbols, fetched_at):
        from market_pulse import normalize_quotes
        values = normalize_quotes(raw, symbols, fetched_at)
        if not isinstance(values, dict) or not values:
            raise ValueError('No usable quote observations')
        accepted = 0
        with self.lock:
            for symbol in symbols:
                value = values.get(symbol)
                old = self.quotes.get(symbol)
                observed = timestamp((value or {}).get('quote_time'))
                old_time = timestamp((old or {}).get('quote_time'))
                usable = (isinstance(value, dict) and value.get('ticker') == symbol
                          and observed is not None
                          and (old_time is None or observed >= old_time))
                if usable:
                    self._put(self.quotes, symbol, deepcopy(value))
                    accepted += 1
                self._put(self.quote_status, symbol, {
                    'state': 'available' if usable else ('kept' if old else 'missing'),
                    'last_attempt': fetched_at,
                    'error': '' if usable else 'ต้นทางยังไม่ส่งข้อมูลใหม่ที่ใช้ได้สำหรับหุ้นนี้',
                })
            self.status = 'ready' if accepted == len(symbols) else 'partial'
            if accepted:
                self.checked_at = fetched_at
            if accepted < len(symbols):
                self.error = 'บางหุ้นยังไม่มีข้อมูลใหม่ที่ใช้ได้ แสดงเวลาและข้อมูลครั้งล่าสุดแยกแต่ละหุ้น'
        if not accepted:
            raise ValueError('Only regressed quote observations')

    def _choose_news(self, symbols, now):
        eligible = [symbol for symbol in symbols
                    if self.news_attempts.get(symbol, {}).get('next_due', 0) <= now]
        if not eligible:
            return None
        # Oldest attempt first is fair even if shortlist order changes each round.
        return min(eligible, key=lambda symbol: self.news_attempts.get(symbol, {}).get('attempted_at', -1))

    def _update_news(self, raw, ticker, fetched_at):
        from market_pulse import normalize_news
        value = normalize_news(raw, ticker, fetched_at)
        if not isinstance(value, dict) or value.get('state') not in ('available', 'empty'):
            raise ValueError('Unusable news response')
        with self.lock:
            old = self.news.get(ticker)
            old_time = _newest_news(old or {})
            new_time = _newest_news(value)
            regressed = old_time is not None and new_time is not None and new_time < old_time
            if regressed:
                # A successful check is distinct from an older article publication.
                retained = deepcopy(old)
                retained['checked_at'] = fetched_at
                self._put(self.news, ticker, retained)
            else:
                self._put(self.news, ticker, deepcopy(value))
            now = self.clock()
            self._put(self.news_attempts, ticker, {'attempted_at': now, 'next_due': now + NEWS_TTL_SECONDS})
            self._put(self.news_status, ticker, {
                'state': 'kept' if regressed else value['state'],
                'last_attempt': fetched_at, 'next_due': now + NEWS_TTL_SECONDS,
                'error': 'ต้นทางส่งข่าวเก่ากว่าครั้งก่อน จึงเก็บข่าวเดิมไว้' if regressed else '',
            })

    def _run(self, symbols, news_symbols):
        try:
            try:
                raw = self.quote_fetcher(symbols)
                self._update_quotes(raw, symbols, _iso(self.clock()))
            except Exception as exc:
                self._failure(exc, 'quote')
                with self.lock:
                    for symbol in symbols:
                        self._put(self.quote_status, symbol, {
                            'state': 'kept' if symbol in self.quotes else 'missing',
                            'last_attempt': self.last_attempt, 'error': self.error,
                        })
            with self.lock:
                now = self.clock()
                if now < self.cooldown_until:
                    return
                ticker = self._choose_news(news_symbols, now)
                if ticker is None:
                    return
                news_due = self._budget_due('news', now)
                if news_due > now:
                    self._put(self.news_status, ticker, {
                        'state': 'budget', 'last_attempt': None, 'next_due': news_due,
                        'error': 'พักการตรวจข่าวตามจำนวนคำขอที่กำหนด เก็บข่าวครั้งล่าสุดไว้',
                    })
                    return
                self._record_call('news', now)
                self._put(self.news_attempts, ticker, {'attempted_at': now, 'next_due': now + NEWS_TTL_SECONDS})
            try:
                raw_news = self.news_fetcher(ticker)
                self._update_news(raw_news, ticker, _iso(self.clock()))
            except Exception as exc:
                self._failure(exc, 'news', ticker)
        finally:
            with self.lock:
                self.busy = False


@lru_cache(maxsize=1)
def get_service():
    """The app shares this worker/cache across reruns and browser sessions."""
    return PulseService()
