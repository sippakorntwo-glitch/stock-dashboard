"""One render reads one SQLite WAL snapshot; downloads and writers keep running.

The context is local to the rendering thread. A resource that retained this
adapter delegates back to the real cache after the render or on another thread.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import re
import sqlite3
import threading
import zlib

_ACTIVE = ContextVar('dashboard_read_view', default=None)


def page_dependencies(ticker, comparisons=None, research=None):
    """Only the selected research, visible comparisons and fixed benchmark."""
    if comparisons is None:
        comparisons = (ticker, 'SPY' if ticker != 'SPY' else 'QQQ')
    symbols = (ticker, *tuple(comparisons)[:6], *tuple(research or ())[:5], 'SPY')
    return tuple(dict.fromkeys(symbol for symbol in symbols
                               if isinstance(symbol, str)
                               and re.fullmatch(r'[A-Z0-9.^=/_-]{1,30}', symbol)))


def scoped_cache(cache):
    view = _ACTIVE.get()
    return view if view is not None and view.base is cache and view.active else cache


class _BorrowedConnection:
    def __init__(self, connection):
        self.connection = connection
    def __enter__(self):
        return self.connection
    def __exit__(self, *args):
        return False
    def __getattr__(self, name):
        return getattr(self.connection,name)


class CacheReadView:
    def __init__(self, cache, ticker=None, dependencies=None):
        self.base = cache
        self.owner = threading.get_ident()
        self.closed = False
        self.connection = None
        self.error = cache.error
        self._lock = threading.RLock()
        self.dependencies = tuple(dependencies) if dependencies is not None else None
        self._detail_ready = {}
        # Only opening/pinning the read transaction uses the shared lock. SQLite
        # WAL retains that read version without blocking later writer commits.
        with cache._lock:
            if not cache.error:
                self.connection = sqlite3.connect(str(cache.path),timeout=10)
                try:
                    self.connection.execute('PRAGMA query_only=ON')
                    self.connection.execute('BEGIN')
                    self.connection.execute("SELECT key FROM objects WHERE key='remote:manifest'").fetchone()
                except BaseException:
                    self.connection.close()
                    raise
            else:
                self._objects = deepcopy(cache._fallback)
                self._quotes = deepcopy(cache._fallback_quotes)
                self._classifications = deepcopy(cache._fallback_classifications)
            reader = getattr(cache,'remote',None)
            self.reader_state = deepcopy(reader.page_status(self.dependencies)
                                         if self.dependencies is not None else reader.status(ticker)) if reader else {}
            manifest, _ = self.get('remote:manifest', request_remote=False)
            generation = (manifest or {}).get('generation')
            if reader and generation and self.dependencies is not None:
                for symbol in self.dependencies:
                    marker, _ = self.get('remote:detail:' + symbol, request_remote=False)
                    self._detail_ready[symbol] = (marker or {}).get('generation') == generation

    def page_revision(self, dependencies):
        """Project the frozen vector if the comparison widget pruned a choice."""
        revision = self.reader_state.get('page_revision')
        if revision is None:
            return self.reader_state.get('view_revision', self.reader_state.get('revision', 0))
        summary, details = revision
        frozen = dict(details)
        return summary, tuple((symbol, frozen[symbol]) for symbol in dependencies)

    @property
    def active(self):
        return not self.closed and self.owner == threading.get_ident()

    def __getattr__(self, name):
        return getattr(self.base,name)

    def connect(self):
        if not self.active or self.connection is None:
            return self.base.connect()
        return _BorrowedConnection(self.connection)

    def get(self, key, request_remote=True):
        if not self.active:
            return self.base.get(key,request_remote=request_remote)
        remote = getattr(self.base,'remote',None)
        if remote and key.startswith(('history:1d:','info:','dividends:','reference:','financials:','etf_research:')):
            symbol = key.rsplit(':',1)[-1]
            if request_remote:
                remote.request(symbol)
            # A new comparison can still have records from a previous prepared
            # generation. Wait for its matching shard, just like selected data.
            if self._detail_ready.get(symbol) is False:
                return None, {}
        if self.connection is None:
            return deepcopy(self._objects.get(key,(None,{})))
        row = self.connection.execute('SELECT body,metadata FROM objects WHERE key=?',(key,)).fetchone()
        return (json.loads(zlib.decompress(row[0])),json.loads(row[1])) if row else (None,{})

    def history(self, ticker, interval='1d'):
        return type(self.base).history(self,ticker,interval)

    def quotes(self):
        if not self.active:
            return self.base.quotes()
        if self.connection is None:
            return deepcopy(self._quotes)
        return {ticker:json.loads(body) for ticker,body in self.connection.execute('SELECT ticker,body FROM quotes')}

    def classifications(self):
        if not self.active:
            return self.base.classifications()
        if self.connection is None:
            return deepcopy(self._classifications)
        return {ticker:json.loads(body) for ticker,body in self.connection.execute('SELECT ticker,body FROM classifications')}

    def close(self):
        self.closed = True
        if self.connection is not None:
            self.connection.rollback()
            self.connection.close()


@contextmanager
def consistent_read(cache, ticker=None, dependencies=None):
    view = CacheReadView(cache,ticker,dependencies)
    token = _ACTIVE.set(view)
    try:
        yield view
    finally:
        _ACTIVE.reset(token)
        view.close()
