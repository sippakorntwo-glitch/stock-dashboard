"""One render reads one SQLite WAL snapshot; downloads and writers keep running.

The context is local to the rendering thread. A resource that retained this
adapter delegates back to the real cache after the render or on another thread.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import sqlite3
import threading
import zlib

_ACTIVE = ContextVar('dashboard_read_view', default=None)


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
    def __init__(self, cache, ticker=None):
        self.base = cache
        self.owner = threading.get_ident()
        self.closed = False
        self.connection = None
        self.error = cache.error
        self._lock = threading.RLock()
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
            self.reader_state = deepcopy(reader.status(ticker)) if reader else {}

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
        if request_remote and remote and key.startswith(('history:1d:','info:','dividends:','reference:','financials:')):
            remote.request(key.rsplit(':',1)[-1])
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
def consistent_read(cache, ticker=None):
    view = CacheReadView(cache,ticker)
    token = _ACTIVE.set(view)
    try:
        yield view
    finally:
        _ACTIVE.reset(token)
        view.close()
