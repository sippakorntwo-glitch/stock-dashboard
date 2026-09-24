"""Shared, bounded observations for the selected-stock briefing.

The UI can refresh every 30 seconds; provider quotes are checked at most once a
minute and news once per five minutes across this service, not per browser.
These are at most 60 quote + 12 news logical operations/hour in addition to the
Top 10 service. Provider authentication may involve extra internal requests.
Every network operation runs on one background worker. Neither cache receipt
time nor a page refresh is substituted for a price or article's source time.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache, partial
import math
import re
import threading
import time

from live_quotes import retry_delay, timestamp
from market_pulse import normalize_quotes, _number
from market_pulse_service import fetch_news, fetch_quotes, _is_rate_limit

QUOTE_TTL_SECONDS = 60
NEWS_TTL_SECONDS = 300
MAX_QUOTE_REQUESTS_PER_HOUR = 60
MAX_NEWS_REQUESTS_PER_HOUR = 12
MAX_CACHE_SYMBOLS = 32
MAX_PENDING_SYMBOLS = 4
PENDING_TTL_SECONDS = 120
QUOTE_FRESH_SECONDS = 180


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _ticker(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,29}', value) is not None


def _quote_age(value, now):
    """Recalculate freshness at read time, including known provider delay."""
    if not isinstance(value, dict):
        return None
    result = deepcopy(value)
    stamp = timestamp(result.get('quote_time'))
    current = timestamp(now)
    age = (current - stamp).total_seconds() if stamp is not None and current is not None else None
    delay = result.get('delay_minutes')
    recent = (age is not None and 0 <= age <= QUOTE_FRESH_SECONDS
              and (delay is None or 0 <= delay <= QUOTE_FRESH_SECONDS / 60))
    result['age_seconds'] = age
    result['freshness'] = 'recent' if recent else 'stale'
    expected = {'regular': 'REGULAR', 'pre': 'PRE', 'post': 'POST'}.get(result.get('session'))
    result['is_current_session'] = recent and result.get('market_state') == expected
    return result


def normalize_brief_quotes(raw, ticker, fetched_at):
    """Return independent regular and latest subsequent extended observations.

    Extended change is computed only against the regular price in the same
    validated response. Old pre-market prices from before the latest regular
    observation cannot be mixed with today's regular close. Missing, duplicate,
    unzoned and future observations remain missing, never zero or relabelled.
    """
    result = {'regular': None, 'extended': None}
    fetched = timestamp(fetched_at)
    if not _ticker(ticker) or fetched is None or fetched.year < 1970:
        return result
    if isinstance(raw, dict):
        envelope = raw.get('quoteResponse')
        if not isinstance(envelope, dict) or envelope.get('error') or raw.get('error'):
            return result
        raw = envelope.get('result')
    if not isinstance(raw, list):
        return result
    rows = [row for row in raw if isinstance(row, dict) and row.get('symbol') == ticker]
    if len(rows) != 1:
        return result
    row = rows[0]
    currency = row.get('currency')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Za-z]{3,8}', currency):
        return result
    market_state = str(row.get('marketState') or '').upper()
    regular = normalize_quotes([dict(row, marketState='REGULAR')], [ticker], fetched_at).get(ticker)
    if regular is None:
        return result
    regular['market_state'] = market_state
    if regular.get('previous_close') is None:
        regular['change_pct'] = None
    regular['change_abs'] = (_number(regular['price'] - regular['previous_close'])
                             if regular.get('previous_close') is not None else None)
    regular['basis_time'] = None  # The previous close's source time is not supplied.
    result['regular'] = _quote_age(regular, fetched_at)
    extended = []
    for state in ('PRE', 'POST'):
        quote = normalize_quotes([dict(row, marketState=state)], [ticker], fetched_at).get(ticker)
        if quote is None or timestamp(quote['quote_time']) <= timestamp(regular['quote_time']):
            continue
        quote['market_state'] = market_state
        quote['change_abs'] = _number(quote['price'] - regular['price'])
        quote['basis_time'] = regular['quote_time']
        extended.append(quote)
    if extended:
        latest = max(extended, key=lambda item: timestamp(item['quote_time']))
        result['extended'] = _quote_age(latest, fetched_at)
    return result


def _empty(ticker):
    return {
        'ticker': ticker, 'regular': None, 'extended': None, 'news': None,
        'quote_status': {'state': 'waiting', 'error': ''},
        'news_status': {'state': 'waiting', 'error': ''},
        'quote_checked_at': None, 'news_checked_at': None, 'last_attempt': None,
        'quote_due': 0.0, 'news_due': 0.0,
    }


class StockBriefService:
    """Nonblocking request/read API with one worker and cross-user budgets.

    Pending requests coalesce by ticker and expire after two minutes without a
    new UI request. At most four tickers wait; the most recent request displaces
    the oldest pending one when full. Provider work never waits in the UI thread.
    """

    def __init__(self, quote_fetcher=None, news_fetcher=None, clock=time.time):
        self.quote_fetcher = quote_fetcher or fetch_quotes
        self.news_fetcher = news_fetcher or partial(fetch_news, count=10)
        self.clock = clock
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.pending = OrderedDict()
        self.quote_calls = deque()
        self.news_calls = deque()
        self.active = set()
        self.busy = False
        self.thread = None
        self.cooldown_until = 0.0
        self.rate_limits = 0

    def _record(self, ticker):
        if ticker not in self.cache:
            self.cache[ticker] = _empty(ticker)
        self.cache.move_to_end(ticker)
        while len(self.cache) > MAX_CACHE_SYMBOLS:
            removed, _ = self.cache.popitem(last=False)
            self.pending.pop(removed, None)
        return self.cache[ticker]

    def _global_due(self, kind, now):
        calls = self.quote_calls if kind == 'quote' else self.news_calls
        interval = QUOTE_TTL_SECONDS if kind == 'quote' else NEWS_TTL_SECONDS
        limit = MAX_QUOTE_REQUESTS_PER_HOUR if kind == 'quote' else MAX_NEWS_REQUESTS_PER_HOUR
        while calls and calls[0] <= now - 3600:
            calls.popleft()
        due = max(self.cooldown_until, calls[-1] + interval if calls else now)
        if len(calls) >= limit:
            due = max(due, calls[0] + 3600)
        return due

    def _candidate(self, kind, now):
        if self._global_due(kind, now) > now:
            return None
        return next((ticker for ticker in self.pending
                     if self.cache.get(ticker, {}).get(kind + '_due', 0) <= now), None)

    def request(self, ticker):
        if not _ticker(ticker):
            return False
        now = self.clock()
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            return False
        with self.lock:
            self._record(ticker)
            for pending, requested in list(self.pending.items()):
                if now - requested > PENDING_TTL_SECONDS:
                    self.pending.pop(pending, None)
            self.pending[ticker] = now
            while len(self.pending) > MAX_PENDING_SYMBOLS:
                self.pending.popitem(last=False)
            if self.busy or now < self.cooldown_until:
                return False
            quote_ticker = self._candidate('quote', now)
            news_ticker = self._candidate('news', now)
            if not quote_ticker and not news_ticker:
                return False
            self.active = {symbol for symbol in (quote_ticker, news_ticker) if symbol}
            self.busy = True
            self.thread = threading.Thread(target=self._run, args=(quote_ticker, news_ticker),
                                           name='selected-stock-briefing', daemon=True)
            self.thread.start()
        return True

    def read(self, ticker):
        """Return a detached observation; no provider requests or cache insertion."""
        with self.lock:
            now = self.clock()
            value = deepcopy(self.cache.get(ticker, _empty(ticker)))
            for name in ('regular', 'extended'):
                value[name] = _quote_age(value[name], _iso(now))
            if value['regular'] is not None and value['extended'] is not None:
                expected = {'pre': 'PRE', 'post': 'POST'}.get(value['extended'].get('session'))
                if (timestamp(value['extended']['quote_time']) <= timestamp(value['regular']['quote_time'])
                        or value['regular'].get('market_state') != expected):
                    value['extended']['is_current_session'] = False
            states = [value[kind + '_status']['state'] for kind in ('quote', 'news')]
            has_quote = value['regular'] is not None
            has_news = isinstance(value['news'], dict) and value['news'].get('state') in ('available', 'empty')
            status = 'ready' if has_quote and has_news else ('partial' if has_quote or has_news else 'waiting')
            if any(state in ('error', 'rate_limited') for state in states):
                status = 'partial' if has_quote or has_news else 'error'
            if now < self.cooldown_until:
                status = 'rate_limited'
            elif ticker in self.active:
                status = 'refreshing'
            value.update({
                'status': status, 'busy': ticker in self.active,
                'queued': ticker in self.pending and ticker not in self.active,
                'cooldown_until': self.cooldown_until,
                'next_due': min(max(value[kind + '_due'], self._global_due(kind, now))
                                for kind in ('quote', 'news')),
                'error': ' · '.join(dict.fromkeys(value[kind + '_status'].get('error', '')
                                                  for kind in ('quote', 'news')
                                                  if value[kind + '_status'].get('error'))),
            })
            value.pop('quote_due', None)
            value.pop('news_due', None)
            return value

    def _begin(self, ticker, kind):
        with self.lock:
            now = self.clock()
            if self._global_due(kind, now) > now:
                return False
            record = self._record(ticker)
            if record[kind + '_due'] > now:
                return False
            calls = self.quote_calls if kind == 'quote' else self.news_calls
            calls.append(now)
            record[kind + '_due'] = now + (QUOTE_TTL_SECONDS if kind == 'quote' else NEWS_TTL_SECONDS)
            record['last_attempt'] = _iso(now)
            record[kind + '_status'] = {'state': 'refreshing', 'last_attempt': _iso(now), 'error': ''}
            return True

    def _failure(self, ticker, kind, exc):
        with self.lock:
            now = self.clock()
            limited = _is_rate_limit(exc)
            if limited:
                self.rate_limits = min(self.rate_limits + 1, 3)
            minimum = min(3600, 900 * 2 ** (self.rate_limits - 1)) if limited else 300
            delay = retry_delay(exc, now, minimum)
            if limited:
                self.cooldown_until = max(self.cooldown_until, now + delay)
            record = self._record(ticker)
            record[kind + '_due'] = max(record[kind + '_due'], now + delay)
            record[kind + '_status'] = {
                'state': 'rate_limited' if limited else 'error',
                'last_attempt': record[kind + '_status'].get('last_attempt'),
                'next_due': record[kind + '_due'],
                'error': ('ต้นทางจำกัดคำขอ พักตามเวลาที่กำหนดและเก็บข้อมูลเดิมไว้'
                          if limited else 'ยังตรวจข้อมูลจากต้นทางไม่ได้ เก็บข้อมูลและเวลาเดิมไว้'),
            }

    def _update_quotes(self, ticker, raw, checked):
        quotes = normalize_brief_quotes(raw, ticker, checked)
        if quotes['regular'] is None:
            raise ValueError('No usable regular quote')
        with self.lock:
            record = self._record(ticker)
            accepted = []
            for key in ('regular', 'extended'):
                incoming, old = quotes[key], record[key]
                if (key == 'extended' and incoming is not None and record['regular'] is not None
                        and timestamp(incoming['basis_time']) < timestamp(record['regular']['quote_time'])):
                    # A newer extended price cannot validate an older regular
                    # close as its baseline after we have accepted a later one.
                    continue
                if incoming is not None and (old is None or timestamp(incoming['quote_time']) >= timestamp(old['quote_time'])):
                    record[key] = incoming
                    accepted.append(key)
            if not accepted:
                raise ValueError('Only regressed observations')
            # Kept extended observations retain their original regular-close
            # basis. They must never borrow a newer regular price on later reads.
            record['quote_checked_at'] = checked
            record['quote_status'] = {
                'state': 'available' if 'regular' in accepted else 'kept',
                'last_attempt': record['last_attempt'], 'error': '',
            }

    def _update_news(self, ticker, raw, checked):
        from stock_news_analysis import normalize_stock_news
        incoming = normalize_stock_news(raw, ticker, checked)
        if incoming.get('state') not in ('available', 'empty'):
            raise ValueError('No usable news envelope')
        with self.lock:
            record = self._record(ticker)
            old = record['news']
            newest = lambda value: max((timestamp(item['published_at']) for item in (value or {}).get('items', [])), default=None)
            old_time, new_time = newest(old), newest(incoming)
            regressed = old_time is not None and new_time is not None and new_time < old_time
            if regressed:
                incoming = deepcopy(old)
                incoming['checked_at'] = checked
            record['news'] = incoming
            record['news_checked_at'] = checked
            record['news_status'] = {
                'state': 'kept' if regressed else incoming['state'],
                'last_attempt': record['last_attempt'],
                'error': 'ต้นทางส่งข่าวเก่ากว่าครั้งก่อน จึงเก็บข่าวเดิมไว้' if regressed else '',
            }

    def _run(self, quote_ticker, news_ticker):
        try:
            for kind, ticker in (('quote', quote_ticker), ('news', news_ticker)):
                if ticker is None or not self._begin(ticker, kind):
                    continue
                try:
                    raw = self.quote_fetcher((ticker,)) if kind == 'quote' else self.news_fetcher(ticker)
                    updater = self._update_quotes if kind == 'quote' else self._update_news
                    updater(ticker, raw, _iso(self.clock()))
                except Exception as exc:
                    self._failure(ticker, kind, exc)
                finally:
                    with self.lock:
                        if ticker in self.pending:
                            self.pending.move_to_end(ticker)
        finally:
            with self.lock:
                now = self.clock()
                for ticker in list(self.pending):
                    record = self.cache.get(ticker)
                    if record and record['quote_due'] > now and record['news_due'] > now:
                        self.pending.pop(ticker, None)
                self.active.clear()
                self.busy = False


@lru_cache(maxsize=1)
def get_service():
    return StockBriefService()
