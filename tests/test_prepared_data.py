"""Offline end-to-end tests: real SQLite + real app calculations; fake object store."""
import gzip
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import data_sync as sync
import update_data as collector


class MemoryStore:
    def __init__(self):
        self.files = {}
        self.reads = []
        self.fail_key = None
    def read(self, key, optional=False):
        self.reads.append(key)
        if self.fail_key and self.fail_key in key:
            raise ConnectionError('simulated network failure')
        if optional:
            return self.files.get(key)
        return self.files[key]
    def write(self, key, raw):
        if self.fail_key and self.fail_key in key:
            raise ConnectionError('simulated upload failure')
        self.files[key] = raw
    def upload(self, key, path): self.write(key, Path(path).read_bytes())
    def download(self, key, path): Path(path).write_bytes(self.read(key))
    def list(self, prefix):
        for key in list(self.files):
            if key.startswith(prefix): yield key, 0
    def delete(self, keys):
        for key in keys: del self.files[key]


def wait_reader(reader):
    deadline = time.monotonic() + 10
    while reader.status()['busy'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert not reader.status()['busy'], 'reader thread stuck'


class PreparedDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = app.DashboardCache(self.root / 'collector.sqlite3')
        idx = pd.bdate_range(end=pd.Timestamp.now(tz='America/New_York').date() - pd.Timedelta(days=1), periods=1000)
        prices = 100 + np.arange(len(idx)) * .1
        self.history = pd.DataFrame({'Open': prices-.1, 'High': prices+1, 'Low': prices-1,
                                     'Close': prices, 'Volume': 10000.}, index=idx)
        self.stamp = sync.utc_now()
        self.cache.save_history('AAPL', self.history, self.stamp, years=5)
        info = {'industry': 'Consumer Electronics', 'quoteType': 'EQUITY', '_Fetched_At_UTC': self.stamp}
        self.cache.put('info:AAPL', info, {'fetched_at': self.stamp})
        self.cache.save_classification('AAPL', info)
        self.cache.put('dividends:AAPL', {'records': [], 'error': None, 'fetched_at': self.stamp,
                                       'coverage_start': '2020-01-01', 'coverage_end': '2026-09-09'}, {'fetched_at': self.stamp})
        self.store = MemoryStore()
        self.manifest = collector.publish_snapshot(self.store, self.cache, ('AAPL', 'MSFT'), {'mode': 'test'})
    def tearDown(self):
        self.tmp.cleanup()
    def test_fresh_server_reads_summary_and_selected_details_without_yahoo_or_database_download(self):
        local = app.DashboardCache(self.root / 'empty-server.sqlite3')
        reader = sync.SnapshotReader(self.store, local)
        local.remote = reader
        with patch.object(app.yf, 'download', side_effect=AssertionError('Yahoo must not run')), patch.object(app.yf, 'Ticker', side_effect=AssertionError('Yahoo must not run')):
            reader.refresh(); wait_reader(reader)
            self.assertIn('AAPL', local.quotes())
            self.assertEqual(local.classifications()['AAPL']['Industry'], 'Consumer Electronics')
            local.history('AAPL'); wait_reader(reader)
            restored, _ = local.history('AAPL')
            pd.testing.assert_frame_equal(restored, self.history, check_freq=False, check_dtype=False)
            self.assertEqual(local.get('dividends:AAPL')[0]['records'], [])
            calls = len(self.store.reads)
            for _ in range(5): local.history('AAPL')
            wait_reader(reader)
            self.assertEqual(len(self.store.reads), calls)
            self.assertFalse(any('checkpoint' in key for key in self.store.reads))
            frame, _ = app.build_universe_frame(pd.DataFrame(columns=['Ticker']), local.quotes(), local.classifications())
            self.assertEqual(len(frame), app.COMMON_STOCK_LIMIT + app.ETF_LIMIT)
            self.assertEqual(frame.Asset_Type.value_counts().to_dict(), {'Common Stock': 4200, 'ETF': app.ETF_LIMIT})
            row = frame.set_index('Ticker').loc['AAPL']
            self.assertGreater(row.Return_3Y, 0)
    def test_worker_restart_restores_full_checkpoint_and_returns(self):
        path = self.root / 'fresh-worker.sqlite3'
        sync.restore_checkpoint(self.store, self.manifest, path)
        cache = app.DashboardCache(path)
        self.assertEqual(len(cache.history('AAPL')[0]), 1000)
        self.assertEqual(cache.quotes()['AAPL']['Return_3Y'], self.cache.quotes()['AAPL']['Return_3Y'])
        self.assertIsNotNone(cache.get('info:AAPL')[0])
    def test_partial_upload_keeps_previous_generation(self):
        previous = self.store.files['latest.json']
        self.store.fail_key = '/checkpoint.sqlite3'
        with self.assertRaises(ConnectionError):
            collector.publish_snapshot(self.store, self.cache, ('AAPL', 'MSFT'), {}, self.manifest)
        self.assertEqual(self.store.files['latest.json'], previous)
    def test_corrupt_checkpoint_is_rejected_without_replacing_local_file(self):
        path = self.root / 'must-survive.sqlite3'
        path.write_bytes(b'old data')
        self.store.files[self.manifest['checkpoint']['key']] = b'corrupted'
        with self.assertRaises(ValueError): sync.restore_checkpoint(self.store, self.manifest, path)
        self.assertEqual(path.read_bytes(), b'old data')
    def test_outage_keeps_last_success_and_original_timestamp(self):
        local = app.DashboardCache(self.root / 'reader.sqlite3')
        reader = sync.SnapshotReader(self.store, local)
        reader.refresh(); wait_reader(reader)
        old = local.quotes()['AAPL'].copy()
        self.store.fail_key = 'latest.json'
        reader.refresh(force=True); wait_reader(reader)
        self.assertTrue(reader.status()['error'])
        self.assertEqual(local.quotes()['AAPL'], old)
        self.assertEqual(reader.manifest, self.manifest)
    def test_older_remote_details_cannot_overwrite_fresh_selected_update(self):
        local = app.DashboardCache(self.root / 'reader.sqlite3')
        reader = sync.SnapshotReader(self.store, local)
        reader.refresh(); wait_reader(reader)
        later = (pd.Timestamp(self.stamp) + pd.Timedelta(hours=1)).isoformat()
        local.put('info:AAPL', {'industry': 'New industry'}, {'fetched_at': later})
        reader.request('AAPL'); wait_reader(reader)
        self.assertEqual(local.get('info:AAPL')[0]['industry'], 'New industry')
        newer = dict(self.cache.quotes()['AAPL'], Close=999, Data_Time=later)
        local.save_quotes(pd.DataFrame([newer]))
        summary = json.loads(gzip.decompress(self.store.files[self.manifest['summary']['key']]))
        sync.apply_summary(local, summary)
        self.assertEqual(local.quotes()['AAPL']['Close'], 999)
    def test_cleanup_preserves_current_previous_even_if_ancient(self):
        self.store.files['generations/orphan/detail.gz'] = b'unused'
        latest = collector.publish_snapshot(self.store, self.cache, ('AAPL',), {}, self.manifest)
        collector.prune_old_generations(self.store, latest, keep_days=7)
        self.assertNotIn('generations/orphan/detail.gz', self.store.files)
        self.assertIn(self.manifest['checkpoint']['key'], self.store.files)
        self.assertIn(latest['checkpoint']['key'], self.store.files)
    def test_failed_metadata_keeps_old_values_and_cooldown(self):
        with patch.object(app.BackgroundUpdates, '_job', side_effect=ValueError('429 rate limit')), patch.object(collector.time, 'sleep'):
            report = collector.collect(self.cache, ('AAPL', 'MSFT'), 'bootstrap', price_minutes=0, metadata_minutes=.1)
        self.assertTrue(report['rate_limited'])
        self.assertEqual(self.cache.get('info:AAPL')[0]['industry'], 'Consumer Electronics')
        metadata = collector.object_metadata(self.cache)
        self.assertTrue(any(k.startswith('attempt:') and sync.stamp_seconds(v['retry_after']) > time.time() for k,v in metadata.items()))
    def test_local_backend_works_without_any_cloud_requests(self):
        cfg = sync.config_from({'DASHBOARD_SNAPSHOT_DIR': str(self.root/'local-data')})
        store = sync.ObjectStore(cfg)
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Cloud request in local mode')):
            manifest = collector.publish_snapshot(store, self.cache, ('AAPL', 'MSFT'), {})
            self.assertEqual(sync.read_manifest(store)['generation'], manifest['generation'])
            sync.restore_checkpoint(store, manifest, self.root/'local-restored.sqlite3')
        self.assertEqual(len(app.DashboardCache(self.root/'local-restored.sqlite3').history('AAPL')[0]), 1000)
        with self.assertRaises(ValueError): store.read('../escape')



if __name__ == '__main__': unittest.main(verbosity=2)
