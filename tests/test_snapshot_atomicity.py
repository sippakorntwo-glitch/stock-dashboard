"""Offline publication failures and interleavings must keep one coherent view."""
import gzip
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

import pandas as pd

import app
import data_sync as sync
import update_data as collector
import test_prepared_data as prepared

wait_reader = prepared.wait_reader


class SnapshotAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = prepared.PreparedDataTests(methodName='test_worker_restart_restores_full_checkpoint_and_returns')
        self.fixture.setUp()
        self.store = self.fixture.store
        self.local = app.DashboardCache(self.fixture.root / 'atomic-reader.sqlite3')
        self.reader = sync.SnapshotReader(self.store, self.local)
        self.reader.select('AAPL')
        self.reader._sync()
        self.old = self.reader.manifest

    def tearDown(self):
        wait_reader(self.reader)
        self.fixture.tearDown()

    def new_generation(self):
        stamp = (pd.Timestamp(self.fixture.stamp) + pd.Timedelta(hours=1)).isoformat()
        self.fixture.cache.save_history('AAPL', self.fixture.history * 2, stamp, years=5)
        self.fixture.cache.put('info:AAPL', {'industry': 'New industry', 'quoteType': 'EQUITY'}, {'fetched_at': stamp})
        return collector.publish_snapshot(self.store, self.fixture.cache, ('AAPL', 'MSFT'), {}, self.old)

    def contents(self):
        with self.local.connect() as db:
            return {table: db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                    for table in ('objects', 'quotes', 'classifications')}

    def test_selected_download_failure_does_not_publish_new_summary_or_pointer(self):
        before = self.contents()
        incoming = self.new_generation()
        self.store.fail_key = incoming['details'][str(sync.shard_number('AAPL'))]['key']
        with self.assertRaises(ConnectionError):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)
        self.assertEqual(self.reader.status('AAPL')['detail_generation'], self.old['generation'])

    def test_sql_failure_rolls_back_summary_details_and_manifest_together(self):
        before = self.contents()
        self.new_generation()
        with self.local.connect() as db:
            db.execute("CREATE TRIGGER fail_classification BEFORE INSERT ON classifications BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)
        self.assertFalse(self.local.error, 'Snapshot errors must not replace healthy disk data with an empty fallback')

    def test_success_adopts_selected_history_info_summary_and_generation_together(self):
        incoming = self.new_generation()
        self.reader._sync()
        self.assertEqual(self.reader.manifest, incoming)
        self.assertEqual(self.local.get('remote:manifest', request_remote=False)[0], incoming)
        history, meta = self.local.history('AAPL')
        self.assertEqual(history.Close.iloc[-1], self.local.quotes()['AAPL']['Close'])
        self.assertEqual(meta['snapshot_generation'], incoming['generation'])
        self.assertEqual(self.local.get('info:AAPL', request_remote=False)[1]['snapshot_generation'], incoming['generation'])
        self.assertEqual(self.local.classifications()['AAPL']['Industry'], 'New industry')
        self.assertEqual(self.reader.status('AAPL')['detail_generation'], incoming['generation'])

    def test_cached_old_pointer_never_rolls_back_newer_summary_or_details(self):
        incoming = self.new_generation()
        self.reader._sync()
        before = self.contents()
        self.store.files['latest.json'] = json.dumps(self.old).encode()
        with self.assertRaisesRegex(ValueError, 'backwards'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, incoming)

    def test_correct_checksum_cannot_bind_a_previous_generations_summary(self):
        incoming = self.new_generation()
        incoming['summary'] = self.old['summary']
        self.store.files['latest.json'] = json.dumps(incoming).encode()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, 'another generation'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)

    def test_late_mismatched_detail_record_is_rejected_before_any_write(self):
        incoming = self.new_generation()
        item = incoming['details'][str(sync.shard_number('AAPL'))]
        raw = gzip.decompress(self.store.files[item['key']])
        raw += json.dumps(['AAPL', 'info:MSFT', {'industry': 'Wrong company'}, {}]).encode() + b'\n'
        self.store.files[item['key']] = gzip.compress(raw)
        item['sha256'] = sync.digest(self.store.files[item['key']])
        self.store.files['latest.json'] = json.dumps(incoming).encode()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)

    def test_selected_input_omission_keeps_last_complete_view(self):
        incoming = self.new_generation()
        item = incoming['details'][str(sync.shard_number('AAPL'))]
        lines = [line for line in gzip.decompress(self.store.files[item['key']]).splitlines()
                 if json.loads(line)[1] != 'info:AAPL']
        self.store.files[item['key']] = gzip.compress(b'\n'.join(lines))
        item['sha256'] = sync.digest(self.store.files[item['key']])
        self.store.files['latest.json'] = json.dumps(incoming).encode()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)

    def test_selection_change_while_staging_keeps_old_generation(self):
        self.new_generation()
        read_shard = self.reader._read_shard
        def switch_selection(manifest, ticker):
            result = read_shard(manifest, ticker)
            self.reader.select('MSFT')
            return result
        before = self.contents()
        # Keep the test's synchronous _sync owner; production requests are queued
        # on the one already-running worker during the same interleaving.
        with patch.object(self.reader, '_start'), patch.object(self.reader, '_read_shard', side_effect=switch_selection):
            with self.assertRaisesRegex(ValueError, 'tickers changed'):
                self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)
        self.assertIsNone(self.reader.status('MSFT')['detail_generation'])

    def test_worker_waiting_for_render_lock_does_not_hold_reader_lock_or_overlap(self):
        incoming = self.new_generation()
        staged = threading.Event()
        read_shard = self.reader._read_shard
        def record_staged(manifest, ticker):
            result = read_shard(manifest, ticker)
            staged.set()
            return result
        with patch.object(self.reader, '_read_shard', side_effect=record_staged):
            with self.local._lock:
                self.reader.refresh(force=True)
                worker = self.reader.thread
                self.assertTrue(staged.wait(5), 'Worker should download without needing the rendering lock')
                # status/select must remain available while the worker waits for
                # the render's cache lock, and repeated refreshes cannot overlap.
                self.assertTrue(self.reader.lock.acquire(timeout=1), 'Reader/cache lock inversion')
                self.reader.lock.release()
                self.reader.select('AAPL')
                self.reader.refresh(force=True)
                self.assertIs(self.reader.thread, worker)
                self.assertEqual(self.local.get('remote:manifest', request_remote=False)[0], self.old)
            wait_reader(self.reader)
        self.assertEqual(self.reader.manifest, incoming)

    def test_two_sessions_keep_independent_leases_and_adopt_both_visible_tickers(self):
        stamp = (pd.Timestamp(self.fixture.stamp) + pd.Timedelta(hours=1)).isoformat()
        self.fixture.cache.save_history('MSFT', self.fixture.history * 3, stamp, years=5)
        self.fixture.cache.put('info:MSFT', {'industry': 'Software'}, {'fetched_at': stamp})
        with patch.object(self.reader, '_start'):
            self.reader.select('MSFT')
            self.reader.select('AAPL')
            self.reader.select('MSFT')
        incoming = self.new_generation()
        self.reader._sync()
        self.assertEqual(set(self.reader.status()['active_tickers']), {'AAPL', 'MSFT'})
        for ticker in ('AAPL', 'MSFT'):
            self.assertEqual(self.reader.status(ticker)['detail_generation'], incoming['generation'])
            self.assertEqual(self.local.get('remote:detail:' + ticker, request_remote=False)[0]['generation'], incoming['generation'])
            self.assertEqual(self.local.history(ticker)[1]['snapshot_generation'], incoming['generation'])

    def test_unrelated_detail_requests_do_not_lease_or_rerender_other_session(self):
        before = self.reader.status('AAPL')['view_revision']
        with patch.object(self.reader, '_start'):
            self.reader.request('MSFT')
        self.reader._details('MSFT')
        self.assertEqual(self.reader.status()['active_tickers'], ['AAPL'])
        self.assertEqual(self.reader.status('AAPL')['view_revision'], before)
        self.assertGreater(self.reader.status('MSFT')['view_revision'][1], 0)

    def test_older_prepared_input_cannot_be_relabeled_as_new_generation(self):
        info, meta = self.local.get('info:AAPL', request_remote=False)
        later = (pd.Timestamp(self.fixture.stamp) + pd.Timedelta(hours=2)).isoformat()
        self.local.put('info:AAPL', info, dict(meta, fetched_at=later))
        before = self.contents()
        self.new_generation()
        with self.assertRaisesRegex(ValueError, 'timestamp moved backwards'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)

    def test_genuinely_newer_local_input_preserves_explicit_source_provenance(self):
        later = (pd.Timestamp(self.fixture.stamp) + pd.Timedelta(hours=2)).isoformat()
        self.local.put('info:AAPL', {'industry': 'Independent latest source'},
                       {'fetched_at': later, 'source': 'Authorized local refresh'})
        incoming = self.new_generation()
        self.reader._sync()
        info, meta = self.local.get('info:AAPL', request_remote=False)
        marker, _ = self.local.get('remote:detail:AAPL', request_remote=False)
        self.assertEqual(info['industry'], 'Independent latest source')
        self.assertEqual(meta['fetched_at'], later)
        self.assertNotIn('snapshot_generation', meta)
        self.assertEqual(marker['generation'], incoming['generation'])
        self.assertEqual(marker['retained_newer_local']['info:AAPL']['source'], 'Authorized local refresh')
        self.assertEqual(marker['retained_newer_local']['info:AAPL']['fetched_at'], later)

    def test_other_prepared_source_cannot_be_misclassified_as_independent_local(self):
        later = (pd.Timestamp(self.fixture.stamp) + pd.Timedelta(hours=2)).isoformat()
        self.local.put('info:AAPL', {'industry': 'Different prepared repository'},
                       {'fetched_at': later, 'snapshot_source': 'another-prepared-repository',
                        'snapshot_generation': 'generations/another-source'})
        before = self.contents()
        self.new_generation()
        with self.assertRaisesRegex(ValueError, 'another prepared source'):
            self.reader._sync()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.reader.manifest, self.old)

    def test_detail_failures_are_scoped_and_only_their_own_success_clears_them(self):
        self.fixture.cache.put('info:MSFT', {'industry': 'Software'}, {'fetched_at': self.fixture.stamp})
        incoming = self.new_generation()
        self.reader._sync()
        self.store.fail_key = incoming['details'][str(sync.shard_number('MSFT'))]['key']
        before = self.reader.status('MSFT')['view_revision']
        self.reader.request('MSFT')
        wait_reader(self.reader)
        self.assertIn('MSFT', self.reader.status('MSFT')['error'])
        self.assertFalse(self.reader.status('AAPL')['error'])
        self.assertTrue(self.reader.status()['error'], 'Legacy status retains aggregate errors')
        self.assertEqual(self.reader.status('MSFT')['view_revision'], before,
                         'A fragment can show the error without triggering an expensive page rerender')
        self.reader._details('AAPL')
        self.assertIn('MSFT', self.reader.status('MSFT')['error'])
        self.store.fail_key = 'latest.json'
        self.reader.refresh(force=True)
        wait_reader(self.reader)
        self.assertTrue(self.reader.status('AAPL')['error'], 'Summary failure applies to every session')
        self.store.fail_key = None
        self.reader.refresh(force=True)
        wait_reader(self.reader)
        self.assertFalse(self.reader.status('AAPL')['error'])
        self.assertIn('MSFT', self.reader.status('MSFT')['error'], 'A manifest check cannot clear a detail failure')
        self.reader._details('MSFT')
        self.assertFalse(self.reader.status('MSFT')['error'])
        self.assertFalse(self.reader.status()['error'])


if __name__ == '__main__':
    unittest.main()
