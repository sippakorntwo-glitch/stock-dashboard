"""Visible comparison inputs trigger one page refresh; unrelated symbols do not."""
import unittest
from unittest.mock import patch

import app
import data_sync as sync
import update_data as collector
import test_prepared_data as prepared


class PageDependencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = prepared.PreparedDataTests(methodName='test_worker_restart_restores_full_checkpoint_and_returns')
        self.fixture.setUp()
        self.fixture.cache.save_history('SPY', self.fixture.history * .75, self.fixture.stamp, years=5)
        collector.publish_snapshot(self.fixture.store, self.fixture.cache,
                                   ('AAPL', 'SPY', 'MSFT'), {}, self.fixture.manifest)
        local = app.DashboardCache(self.fixture.root / 'page-dependencies.sqlite3')
        self.reader = sync.SnapshotReader(self.fixture.store, local)
        self.reader._sync()
        self.reader._details('AAPL')

    def tearDown(self):
        self.fixture.tearDown()

    def test_spy_comparison_load_changes_aapl_page_once_but_unrelated_msft_does_not(self):
        dependencies = ('AAPL', 'SPY')
        before = self.reader.page_status(dependencies)['page_revision']
        self.reader._details('SPY')
        after = self.reader.page_status(dependencies)['page_revision']
        self.assertNotEqual(after, before)
        self.assertEqual(dict(after[1])['SPY'], dict(before[1])['SPY'] + 1)
        self.reader._details('SPY')
        self.assertEqual(self.reader.page_status(dependencies)['page_revision'], after)
        self.reader._details('MSFT')
        self.assertEqual(self.reader.page_status(dependencies)['page_revision'], after)
        self.reader._sync()
        self.assertEqual(self.reader.page_status(dependencies)['page_revision'], after)

    def test_changed_comparison_dependencies_change_identity_before_their_load(self):
        first = self.reader.page_status(('AAPL', 'SPY'))['page_revision']
        changed = self.reader.page_status(('AAPL', 'MSFT'))['page_revision']
        self.assertNotEqual(first, changed)
        self.assertEqual(first[0], changed[0])
        self.assertEqual(dict(first[1])['SPY'], dict(changed[1])['MSFT'])
        self.assertEqual(first, self.reader.page_status(('AAPL', 'SPY', 'SPY'))['page_revision'])

    def test_dependency_errors_are_scoped_and_summary_errors_apply_to_the_page(self):
        self.reader.detail_errors['MSFT'] = 'Unrelated failure'
        self.reader._update_error()
        before = self.reader.page_status(('AAPL', 'SPY'))['page_revision']
        self.assertFalse(self.reader.page_status(('AAPL', 'SPY'))['error'])
        self.reader.detail_errors['SPY'] = 'Comparison unavailable'
        self.assertEqual(self.reader.page_status(('AAPL', 'SPY'))['error'], 'Comparison unavailable')
        self.assertEqual(self.reader.page_status(('AAPL', 'SPY'))['page_revision'], before)
        self.reader.summary_error = 'Summary unavailable'
        self.assertEqual(self.reader.page_status(('AAPL', 'SPY'))['error'], 'Summary unavailable')

    def test_page_status_reads_under_one_lock_without_changing_leases_or_requests(self):
        real_lock = self.reader.lock
        class CountedLock:
            entries = 0
            def __enter__(self):
                self.entries += 1
                real_lock.acquire()
            def __exit__(self, *args):
                real_lock.release()
        lock = CountedLock()
        self.reader.lock = lock
        state = self.reader.page_status(('AAPL', 'SPY'))
        self.assertEqual(lock.entries, 1)
        self.assertEqual(state['detail_generation'], self.reader.manifest['generation'])
        self.assertFalse(self.reader.active_tickers)
        self.assertFalse(self.reader.queue)

    def test_dependency_input_is_bounded(self):
        dependencies = ('AAPL', 'SPY', 'MSFT', 'AMD', 'NVDA', 'META', 'GOOGL', 'AMZN')
        self.assertEqual(len(self.reader.page_status(dependencies)['page_revision'][1]), 8)
        with self.assertRaisesRegex(ValueError, 'eight'):
            self.reader.page_status((*dependencies, 'TSLA'))
        with self.assertRaises(ValueError):
            self.reader.page_status('AAPL')
        with self.assertRaisesRegex(ValueError, 'eight'):
            self.reader.select_page((*dependencies, 'TSLA'))

    def test_select_page_registers_all_leases_before_worker_captures_active_symbols(self):
        captured = []
        original_sync = self.reader._sync
        def capture_active():
            with self.reader.lock:
                captured.append(tuple(self.reader.active_tickers))
            original_sync()
        dependencies = ('AAPL', 'SPY', 'MSFT')
        with patch.object(self.reader, '_sync', side_effect=capture_active):
            self.reader.select_page(dependencies)
            prepared.wait_reader(self.reader)
        self.assertTrue(captured)
        self.assertEqual(captured[0], dependencies)
        self.assertEqual(tuple(self.reader.active_tickers), dependencies)
        for ticker in dependencies:
            self.assertEqual(self.reader.status(ticker)['detail_generation'], self.reader.manifest['generation'])


if __name__ == '__main__':
    unittest.main()
