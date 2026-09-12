"""Prepared-data adapter. Public web readers never receive a writing token."""
from __future__ import annotations
import inspect
import os
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st
import dashboard_core as core
from catalog_extension import install as install_catalog
install_catalog(core)
from analytics import extended_snapshot, METRIC_VERSION
from data_sync import ObjectStore, SnapshotReader, config_from
APP_VERSION = '2026-09-12.26'
DEFAULT_REPO = 'sippakorntwo-glitch/stock-dashboard'
BaseCache = core.DashboardCache
base_snapshot = core.scan_snapshot_row
base_is_current = core.summary_is_current
base_build_frame = core.build_universe_frame
base_select_universe = core.select_universe
BASE_HAS_REMOTE = 'request_remote' in inspect.signature(BaseCache.get).parameters
from return_periods import RETURN_FIELDS
EXTRA_NUMERIC = list(dict.fromkeys([*RETURN_FIELDS,'Return_3M','Volatility_20D','Dollar_Volume_20D','Drawdown_52W','ATR_Pct','Metric_Calc_Version']))


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
        if request_remote and remote and key.startswith(('history:1d:', 'info:', 'dividends:', 'reference:')):
            remote.request(key.rsplit(':', 1)[-1])
        return super().get(key, request_remote=False) if BASE_HAS_REMOTE else super().get(key)

    def put(self, key, value, meta):
        from data_quality import industry_value, timestamp, VERSION
        meta = dict(meta)
        if key.startswith('info:') and isinstance(value, dict):
            old, oldmeta = self.get(key, request_remote=False)
            stamp = meta.get('fetched_at') or value.get('_Fetched_At_UTC')
            if old and timestamp(oldmeta.get('fetched_at')) > timestamp(stamp):
                return
            ticker = key.split(':', 1)[1]
            meta.update(quality_version=VERSION, classification_available=industry_value(value, ticker in core.ETF_NAMES or value.get('quoteType')=='ETF') is not None)
            super().put(key, value, meta)
            self.save_classification(ticker, {**value, '_Fetched_At_UTC':stamp or ''})
            return
        return super().put(key, value, meta)

    def save_classification(self, ticker, info):
        from data_quality import industry_value, timestamp
        is_etf = ticker in core.ETF_NAMES or info.get('quoteType') == 'ETF'
        value = industry_value(info, is_etf)
        if value is None:
            return
        import json
        with self._lock:
            old = self._fallback_classifications.get(ticker, {})
            if not self.error:
                with self.connect() as db:
                    saved = db.execute('SELECT body FROM classifications WHERE ticker=?', (ticker,)).fetchone()
                    if saved: old = json.loads(saved[0])
            if timestamp(old.get('Industry_Time')) > timestamp(info.get('_Fetched_At_UTC')):
                return
            normalized = {**info, 'category' if is_etf else 'industry':value}
            super().save_classification(ticker, normalized)


def select_universe(csv_frame=None):
    # Empty/default callers (including tests and rankers) use the same deployed CSV
    # as the dashboard, not a different truncated 4,200-stock alphabetical pool.
    if csv_frame is None or csv_frame.empty:
        if core.WATCHLIST_FILE.exists():
            csv_frame = pd.read_csv(core.WATCHLIST_FILE, usecols=['Ticker'], dtype=str)
        else:
            csv_frame = pd.DataFrame(columns=['Ticker'])
    return base_select_universe(csv_frame)


def scan_snapshot_row(ticker, history, stamp):
    history = core.completed_daily_history(history, now=stamp)
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
    # Parse classification timestamps in two vectorized operations instead
    # of roughly 20,000 scalar parses on every user interaction.
    frame, outside = base_build_frame(csv_frame, saved, None)
    computed = list(dict.fromkeys([*core.WATCHLIST_NUMERIC_COLUMNS, 'Suggested_Stop', *EXTRA_NUMERIC]))
    from ui_stability import merge_classifications
    indexed = merge_classifications(frame.set_index('Ticker'), classifications)
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
    if rows:
        observations = {}
        for t in incoming.index[eligible]:
            source = (saved or {}).get(t, {})
            if (core.number(source.get('Metric_Calc_Version')) == METRIC_VERSION
                    and isinstance(source.get('Return_Observations'), dict)):
                observations[t] = source['Return_Observations']
        indexed['Return_Observations'] = pd.Series(observations, dtype=object)
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


def _cache_path():
    return str(Path(os.environ.get('DASHBOARD_CACHE_FILE', str(Path(__file__).parent/'dashboard_cache.sqlite3'))).resolve())


@st.cache_resource
def _cached_data_cache(version, cache_path):
    return DashboardCache(Path(cache_path))


def get_data_cache(version=APP_VERSION):
    # Always hash explicit arguments, including the release version.
    return _cached_data_cache(version, _cache_path())


get_data_cache.clear = _cached_data_cache.clear


@st.cache_resource
def _cached_remote_reader(version, cache_path, config):
    cache = _cached_data_cache(version, cache_path)
    reader = SnapshotReader(ObjectStore(config), cache)
    cache.remote = reader
    return reader, ''


def get_remote_reader(version=APP_VERSION):
    # An omitted default must not reuse a reader from a previous release.
    try:
        config = settings()
        if config is None:
            return None, 'ยังไม่ได้ตั้งค่าแหล่งข้อมูล'
        return _cached_remote_reader(version, _cache_path(), config)
    except Exception as exc:
        return None, f'ตั้งค่าแหล่งข้อมูลไม่สำเร็จ ({type(exc).__name__})'


get_remote_reader.clear = _cached_remote_reader.clear


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
def _cached_updater(version, cache_path, enabled):
    return core.BackgroundUpdates(_cached_data_cache(version, cache_path)) if enabled else ReadOnlyUpdater()


def get_updater(version=APP_VERSION):
    return _cached_updater(version, _cache_path(), live_enabled())


get_updater.clear = _cached_updater.clear
# Preserve original functions once; the coherent release loader replaces this
# module together with core, so wrappers never stack across releases.
_base_decision_context = core.decision_context
_base_criteria_score = core.criteria_score
_base_build_entry_plan = core.build_entry_plan
_base_build_analysis = core.build_analysis


def decision_context(history, info, benchmark=None, now=None):
    from asset_semantics import safe_numeric_profile
    safe=safe_numeric_profile(info, str(info.get('symbol') or ''), info.get('quoteType')=='ETF')
    return _base_decision_context(history,safe,benchmark,now)


def criteria_score(ctx, info, is_etf):
    from asset_semantics import safe_numeric_profile
    return _base_criteria_score(ctx,safe_numeric_profile(info,str(info.get('symbol') or ''),is_etf),is_etf)


def build_entry_plan(ctx, info, scored, is_etf, min_rr=2.0, now=None):
    from asset_semantics import safe_numeric_profile
    return _base_build_entry_plan(ctx,safe_numeric_profile(info,str(info.get('symbol') or ''),is_etf),scored,is_etf,min_rr,now)


def build_analysis(snapshot, selected_row, info):
    from asset_semantics import safe_numeric_profile
    ticker=str(selected_row.get('Ticker') or info.get('symbol') or '')
    safe=safe_numeric_profile(info,ticker,core.asset_is_etf(ticker,selected_row,info))
    return _base_build_analysis(snapshot,selected_row,safe)


core.decision_context=decision_context
core.criteria_score=criteria_score
core.build_entry_plan=build_entry_plan
core.build_analysis=build_analysis
core.WATCHLIST_NUMERIC_COLUMNS = list(dict.fromkeys([*core.WATCHLIST_NUMERIC_COLUMNS, *EXTRA_NUMERIC]))
core.DashboardCache = DashboardCache
core.scan_snapshot_row = scan_snapshot_row
core.summary_is_current = summary_is_current
core.build_universe_frame = build_universe_frame
core.select_universe = select_universe
core.get_data_cache = get_data_cache
core.get_updater = get_updater
core.APP_VERSION = APP_VERSION


def __getattr__(name):
    return getattr(core, name)
