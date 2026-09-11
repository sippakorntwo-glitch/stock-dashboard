"""Public writer -> anonymous downloads -> existing full dashboard, offline."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import data_sync as sync
import github_store as gh
import update_data as worker
from test_github_store import FakeGitHub, Response
import test_prepared_data as fixtures


class PublicFiles:
    def __init__(self, api):
        self.api = api
        self.calls = []
        self.fail_assets = False

    def request(self, method, url, **kwargs):
        assert method == 'GET'
        assert kwargs['headers'].get('Authorization') is None
        parsed = urlsplit(url)
        self.calls.append(url)
        if parsed.netloc == 'raw.githubusercontent.com':
            expected = f'/{self.api.repo}/dashboard-data/dashboard/latest.json'
            assert unquote(parsed.path) == expected
            if self.api.private or self.api.pointer is None or self.api.pointer_branch != 'dashboard-data':
                return Response(404)
            return Response(200, raw=self.api.pointer)
        assert parsed.netloc == 'github.com', 'Public reader must never use the REST API'
        prefix = f'/{self.api.repo}/releases/download/'
        assert parsed.path.startswith(prefix)
        tag, name = parsed.path.removeprefix(prefix).split('/')
        if self.fail_assets:
            return Response(503)
        release = next((r for r in self.api.releases.values() if r['tag_name'] == tag and not r['draft']), None)
        if release is None or self.api.private:
            return Response(404)
        asset = next((a for a in self.api.assets.values() if a['release'] == release['id'] and a['name'] == name), None)
        return Response(200, raw=asset['raw']) if asset else Response(404)


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PreparedDataTests(methodName='test_worker_restart_restores_full_checkpoint_and_returns')
        self.fixture.setUp()
        self.cache = self.fixture.cache
        self.api = FakeGitHub()
        self.api.private = False
        self.api.repo = 'owner/public-dashboard'
        self.config = {'DASHBOARD_DATA_REPO': self.api.repo, 'DASHBOARD_GITHUB_TOKEN': 'writer',
                       'DASHBOARD_DATA_VISIBILITY': 'public', 'DASHBOARD_DATA_BRANCH': 'dashboard-data'}
        self.writer = gh.GitHubReleaseStore(self.config, session=self.api)
        self.files = PublicFiles(self.api)
        self.public = gh.PublicGitHubStore(self.config, session=self.files)
        self.pace = patch.object(gh.GitHubReleaseStore, '_pace_mutation')
        self.pace.start()
        self.assertIsNone(sync.read_manifest(self.writer))

    def tearDown(self):
        self.pace.stop()
        self.fixture.tearDown()

    def publish(self, previous=None):
        return worker.publish_snapshot(self.writer, self.cache, ('AAPL', 'MSFT'), {}, previous)

    def test_end_to_end_anonymous_reader_preserves_features_without_yahoo(self):
        manifest = self.publish()
        self.assertEqual(self.api.pointer_branch, 'dashboard-data')
        self.assertEqual(self.api.branches['main'], 'initial-commit')
        local = app.DashboardCache(self.fixture.root / 'public-ui.sqlite3')
        reader = sync.SnapshotReader(self.public, local)
        api_calls_before = len(self.api.calls)
        with patch.object(app.yf, 'download', side_effect=AssertionError('No Yahoo on page open')), patch.object(app.yf, 'Ticker', side_effect=AssertionError('No Yahoo on page open')):
            reader._sync()
            reader._details('AAPL')
            frame, _ = app.build_universe_frame(__import__('pandas').DataFrame(columns=['Ticker']), local.quotes(), local.classifications())
        self.assertEqual(len(frame), app.COMMON_STOCK_LIMIT + app.ETF_LIMIT)
        self.assertEqual(frame.Asset_Type.value_counts().to_dict(), {'Common Stock': 4200, 'ETF': app.ETF_LIMIT})
        row = frame.set_index('Ticker').loc['AAPL']
        self.assertEqual(row.Industry, 'Consumer Electronics')
        self.assertTrue(all(row[c] > 0 for c in ['Historical_Return', 'Return_2Y', 'Return_3Y']))
        self.assertEqual(local.get('dividends:AAPL')[0]['records'], [])
        self.assertEqual(reader.manifest['generation'], manifest['generation'])
        self.assertEqual(len(self.api.calls), api_calls_before)
        self.assertFalse(any('checkpoint' in u for u in self.files.calls))
        self.assertEqual(len(self.files.calls), 3)  # pointer, summary, selected shard

    def test_failed_new_download_keeps_previous_summary_and_pointer(self):
        old = self.publish()
        local = app.DashboardCache(self.fixture.root / 'failure-ui.sqlite3')
        reader = sync.SnapshotReader(self.public, local)
        reader._sync()
        self.publish(old)
        self.files.fail_assets = True
        with self.assertRaisesRegex(gh.GitHubStoreError, '503'):
            reader._sync()
        self.assertEqual(reader.manifest['generation'], old['generation'])
        self.assertIn('AAPL', local.quotes())

    def test_read_public_without_token_and_never_mutate(self):
        with patch.dict('os.environ', {}, clear=True):
            cfg = sync.config_from({'DASHBOARD_DATA_REPO': self.api.repo})
            store = sync.ObjectStore(cfg)
            self.assertIsInstance(store, gh.PublicGitHubStore)
            # A stale token from v8 is ignored by the public web reader.
            cfg['DASHBOARD_GITHUB_TOKEN'] = 'must-not-be-used'
            self.assertIsInstance(sync.ObjectStore(cfg), gh.PublicGitHubStore)
            self.assertIsInstance(sync.ObjectStore({**cfg, 'DASHBOARD_GITHUB_TOKEN':'writer'}, writable=True), gh.GitHubReleaseStore)
        with self.assertRaisesRegex(gh.GitHubStoreError, 'cannot write'):
            self.public.write('latest.json', b'{}')
        self.assertEqual(self.files.calls, [])
        self.assertIsNone(self.public.read('latest.json', optional=True))

    def test_visibility_mismatch_fails_before_writes(self):
        self.api.private = True
        self.writer.verified = False
        with self.assertRaisesRegex(gh.GitHubStoreError, 'Public'):
            sync.read_manifest(self.writer)
        self.assertTrue(all(m == 'GET' for m, _ in self.api.calls))

    def test_default_data_branch_is_created_once_and_checkpoint_restores(self):
        old = self.publish()
        current = self.publish(old)
        self.assertEqual(sum(path == '/git/refs' and method == 'POST' for method, path in self.api.calls), 1)
        path = self.fixture.root / 'restart.sqlite3'
        sync.restore_checkpoint(self.writer, current, path)
        self.assertEqual(len(app.DashboardCache(path).history('AAPL')[0]), 1000)

    def test_public_reader_rejects_path_injection_and_removes_credentials(self):
        for repo in ['../evil', 'https://evil/x', 'owner/repo?x=1']:
            with self.assertRaises(ValueError):
                gh.PublicGitHubStore({'DASHBOARD_DATA_REPO':repo})
        for branch in ['../main', 'main?token=x', '.hidden', 'main.lock']:
            with self.assertRaises(ValueError):
                gh.PublicGitHubStore({**self.config, 'DASHBOARD_DATA_BRANCH':branch})
        with self.assertRaises(ValueError):
            self.public.read('https://evil/asset')
        session = requests.Session()
        session.headers['Authorization'] = 'Bearer old-secret'
        gh.PublicGitHubStore(self.config, session=session)
        prepared = session.prepare_request(requests.Request('GET', 'https://github.com/x', headers={'Authorization':None}))
        self.assertNotIn('Authorization', prepared.headers)
        self.assertFalse(session.trust_env)

    def test_workflow_cannot_write_to_a_different_repo_or_start_paid_private_job(self):
        import yaml
        wf = yaml.load((Path(__file__).resolve().parents[1] / '.github/workflows/five_min_update.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(wf['on']), {'workflow_dispatch', 'schedule'})
        self.assertEqual(wf['permissions'], {'contents':'write'})
        self.assertEqual(wf['jobs']['update']['env']['DASHBOARD_DATA_REPO'], '${{ github.repository }}')
        self.assertEqual(wf['jobs']['update']['env']['DASHBOARD_GITHUB_TOKEN'], '${{ secrets.GITHUB_TOKEN }}')
        self.assertEqual(wf['jobs']['update']['if'], "${{ toJSON(github.event.repository.private) == 'false' }}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
