"""Prepared-data adapter. Public web readers never receive a writing token."""
from __future__ import annotations
import inspect
import os
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st
import dashboard_core as core
from analytics import extended_snapshot, METRIC_VERSION
from data_sync import ObjectStore, SnapshotReader, config_from
APP_VERSION = '2026-09-10.12'
DEFAULT_REPO = 'sippakorntwo-glitch/stock-dashboard'
BaseCache = core.DashboardCache
base_snapshot = core.scan_snapshot_row
base_is_current = core.summary_is_current
base_build_frame = core.build_universe_frame
BASE_HAS_REMOTE = 'request_remote' in inspect.signature(BaseCache.get).parameters
EXTRA_NUMERIC = ['Return_1D','Return_1M','Return_3M','Return_6M','Volatility_20D','Dollar_Volume_20D','Drawdown_52W','ATR_Pct','Metric_Calc_Version']


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, kind, value, traceback):
        try:
            return super().__exit__(kind, value, traceback)
        finally:
            self.close()


class DashboardCache(BaseCache):
    def connect(self):
        return sqlite3.connect(str(self.path), timeout=10, factory=ClosingConnection)

    def get(self, key, request_remote=True):
        remote = getattr(self, 'remote', None)
        if request_remote and remote and key.startswith(('history:1d:', 'info:', 'dividends:')):
            remote.request(key.rsplit(':', 1)[-1])
        return super().get(key, request_remote=False) if BASE_HAS_REMOTE else super().get(key)

    def save_classification(self, ticker, info):
        is_etf = ticker in core.ETF_NAMES or info.get('quoteType') == 'ETF'
        value = core.clean_industry(info.get('category') if is_etf else info.get('industry'))
        if value is not None:
            super().save_classification(ticker, info)


def scan_snapshot_row(ticker, history, stamp):
    row = base_snapshot(ticker, history, stamp)
    row.update(extended_snapshot(core.completed_daily_history(history)))
    atr, close = core.number(row.get('ATR')), core.number(row.get('Close'))
    row['ATR_Pct'] = atr / close * 100 if atr is not None and close else None
    stop = close - 2 * atr if close and atr is not None else None
    row['Suggested_Stop'] = stop if stop is not None and stop > 0 else None
    return row


def summary_is_current(row, now=None):
    return base_is_current(row, now) and core.number(row.get('Metric_Calc_Version')) == METRIC_VERSION


def build_universe_frame(csv_frame, saved=None, classifications=None):
    frame, outside = base_build_frame(csv_frame, saved, classifications)
    # Clear obsolete CSV indicators only when the newer saved observation is eligible.
    computed = list(dict.fromkeys([*core.WATCHLIST_NUMERIC_COLUMNS, 'Suggested_Stop', *EXTRA_NUMERIC]))
    indexed = frame.set_index('Ticker')
    rows = [r for t,r in (saved or {}).items() if t in indexed.index and r.get('Data_Status') == 'โหลดสำเร็จ']
    if rows:
        incoming = pd.DataFrame(rows).drop_duplicates('Ticker', keep='last').set_index('Ticker')
        old_dates = pd.to_datetime(indexed.loc[incoming.index,'Data_Time'], utc=True, errors='coerce')
        new_dates = pd.to_datetime(incoming.get('Data_Time'), utc=True, errors='coerce')
        eligible = new_dates.notna() & (old_dates.isna() | new_dates.ge(old_dates))
        for col in computed:
            if col in incoming:
                if col not in indexed:
                    indexed[col] = float('nan')
                indexed[col] = core.numeric_watchlist_series(indexed[col])
                indexed.loc[incoming.index[eligible],col] = core.numeric_watchlist_series(incoming.loc[eligible,col])
    return indexed.reset_index(), outside


def settings():
    try:
        values = dict(st.secrets)
    except (FileNotFoundError, KeyError):
        values = {}
    if os.environ.get('DASHBOARD_LOCAL_ONLY') == '1':
        return config_from(values)
    if not values.get('DASHBOARD_SNAPSHOT_DIR') and not os.environ.get('DASHBOARD_SNAPSHOT_DIR'):
        values.setdefault('DASHBOARD_DATA_REPO', os.environ.get('DASHBOARD_DATA_REPO', DEFAULT_REPO))
        values.setdefault('DASHBOARD_DATA_VISIBILITY', 'public')
        values.setdefault('DASHBOARD_DATA_BRANCH', 'dashboard-data')
    config = config_from(values)
    if config and config.get('backend') == 'github':
        if config.get('DASHBOARD_DATA_VISIBILITY') != 'public':
            raise ValueError('เว็บรุ่นนี้อ่านข้อมูล Public เท่านั้น')
        config['DASHBOARD_GITHUB_TOKEN'] = ''
    return config


@st.cache_resource
def get_data_cache(version=APP_VERSION):
    return DashboardCache(Path(os.environ.get('DASHBOARD_CACHE_FILE', str(Path(__file__).parent/'dashboard_cache.sqlite3'))))


@st.cache_resource
def get_remote_reader(version=APP_VERSION):
    try:
        config = settings()
        if config is None:
            return None, 'ยังไม่ได้ตั้งค่าแหล่งข้อมูล'
        cache = get_data_cache(version)
        reader = SnapshotReader(ObjectStore(config), cache)
        cache.remote = reader
        return reader, ''
    except Exception as exc:
        return None, f'ตั้งค่าแหล่งข้อมูลไม่สำเร็จ ({type(exc).__name__})'


class ReadOnlyUpdater:
    def request(self, ticker, kind='history', interval='1d'):
        reader, _ = get_remote_reader()
        if reader:
            reader.request(ticker)
        return False
    def state(self):
        return {'busy':False,'revision':0,'scan_running':False,'current':'','cooldown_until':0}
    def start_scan(self, tickers): return False
    def stop(self): pass


def live_enabled():
    try:
        value = st.secrets.get('DASHBOARD_ALLOW_LIVE_UPDATES', False)
    except FileNotFoundError:
        value = False
    return str(os.environ.get('DASHBOARD_ALLOW_LIVE_UPDATES', value)).lower() in ('1','true')


@st.cache_resource
def get_updater(version=APP_VERSION):
    return core.BackgroundUpdates(get_data_cache(version)) if live_enabled() else ReadOnlyUpdater()


core.WATCHLIST_NUMERIC_COLUMNS = list(dict.fromkeys([*core.WATCHLIST_NUMERIC_COLUMNS, *EXTRA_NUMERIC]))
core.DashboardCache = DashboardCache
core.scan_snapshot_row = scan_snapshot_row
core.summary_is_current = summary_is_current
core.build_universe_frame = build_universe_frame
core.get_data_cache = get_data_cache
core.get_updater = get_updater
core.APP_VERSION = APP_VERSION


def __getattr__(name):
    return getattr(core, name)
