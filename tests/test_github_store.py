"""API-contract and end-to-end tests with a fake GitHub server. No real credentials."""
import base64
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import data_sync as sync
import github_store as gh
import update_data as worker
import test_prepared_data as fixtures


class Response:
    def __init__(self, status, data=None, raw=b''):
        self.status_code, self.data, self.content = status, data, raw
    def json(self): return self.data
    def close(self): pass
    def iter_content(self, chunk_size):
        yield self.content


class FakeGitHub:
    def __init__(self):
        self.private = True
        self.repo = 'owner/private-data'
        self.branches = {'main': 'initial-commit'}
        self.pointer_branch = None
        self.pointer = None
        self.sha = None
        self.releases = {}
        self.assets = {}
        self.serial = 0
        self.fail_name = None
        self.watchlist = None
        self.calls = []
    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.netloc in ('api.github.com','uploads.github.com'), 'Unexpected service'
        prefix = '/repos/' + self.repo
        assert parsed.path.startswith(prefix)
        path = unquote(parsed.path[len(prefix):])
        self.calls.append((method, path))
        headers = kwargs.get('headers', {})
        assert headers['Authorization'] in ('Bearer writer', 'Bearer reader')
        if method != 'GET' and headers['Authorization'] != 'Bearer writer': return Response(403)
        data = kwargs.get('json', {})
        params = kwargs.get('params', {})
        if path in ('', '/') and method == 'GET': return Response(200, {'private':self.private,'default_branch':'main'})
        if path.startswith('/git/ref/heads/') and method == 'GET':
            branch = path.removeprefix('/git/ref/heads/')
            return Response(200, {'object': {'sha': self.branches[branch]}}) if branch in self.branches else Response(404)
        if path == '/git/refs' and method == 'POST':
            assert data['ref'].startswith('refs/heads/')
            branch = data['ref'].removeprefix('refs/heads/')
            self.branches[branch] = data['sha']
            return Response(201, {'ref': data['ref']})
        if path == '/contents/daily_watchlist.csv':
            assert headers['Accept']=='application/vnd.github.raw+json'
            return Response(404) if self.watchlist is None else Response(200,raw=self.watchlist)
        if path == '/contents/dashboard/latest.json':
            if method == 'GET':
                return Response(404) if self.pointer is None or params['ref'] != self.pointer_branch else Response(200, {'type':'file','encoding':'base64','sha':self.sha,'content':base64.b64encode(self.pointer).decode()})
            if method == 'PUT':
                if data.get('sha') != self.sha: return Response(409)
                assert data['branch'] in self.branches
                self.pointer_branch = data['branch']
                self.pointer = base64.b64decode(data['content'])
                self.sha = hashlib.sha256(self.pointer).hexdigest()
                return Response(200, {'content': {'sha': self.sha}})
        if path == '/releases' and method == 'POST':
            self.serial += 1
            release = {**data, 'id':self.serial, 'created_at':'2026-09-10T00:00:00Z'}
            self.releases[self.serial] = release
            return Response(201, release.copy())
        if path == '/releases' and method == 'GET':
            start=(int(params.get('page',1))-1)*int(params.get('per_page',30))
            return Response(200, [r.copy() for r in self.releases.values()][start:start+int(params.get('per_page',30))])
        if path.startswith('/releases/tags/'):
            tag=path.removeprefix('/releases/tags/')
            release=next((r for r in self.releases.values() if r['tag_name']==tag), None)
            return Response(404) if release is None else Response(200,release.copy())
        if path.startswith('/releases/assets/'):
            asset=self.assets[int(path.rsplit('/',1)[-1])]
            assert headers['Accept']=='application/octet-stream'
            return Response(200,raw=asset['raw'])
        if path.startswith('/releases/'):
            rid=int(path.split('/')[2])
            if path.endswith('/assets'):
                if method=='POST':
                    if params['name']==self.fail_name: return Response(502)
                    raw=kwargs['data'].read()
                    self.serial += 1
                    asset={'id':self.serial,'name':params['name'],'size':len(raw),'state':'uploaded','release':rid,'raw':raw}
                    self.assets[asset['id']]=asset
                    return Response(201,{k:v for k,v in asset.items() if k!='raw'})
                start=(int(params['page'])-1)*int(params['per_page'])
                assets=[{k:v for k,v in a.items() if k!='raw'} for a in self.assets.values() if a['release']==rid]
                return Response(200,assets[start:start+int(params['per_page'])])
            if method=='PATCH':
                self.releases[rid].update(data)
                return Response(200,self.releases[rid].copy())
            if method=='DELETE':
                del self.releases[rid]
                self.assets={k:a for k,a in self.assets.items() if a['release']!=rid}
                return Response(204)
        if path.startswith('/git/refs/tags/') and method=='DELETE': return Response(204)
        raise AssertionError((method,path))


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeGitHub()
        self.store=gh.GitHubReleaseStore({'DASHBOARD_DATA_REPO':self.api.repo,'DASHBOARD_GITHUB_TOKEN':'writer','DASHBOARD_DATA_VISIBILITY':'private'},session=self.api)
        self.pace=patch.object(gh.GitHubReleaseStore,'_pace_mutation');self.pace.start()
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.fixture=fixtures.PreparedDataTests(methodName='test_worker_restart_restores_full_checkpoint_and_returns')
        self.fixture.setUp()
        self.cache=self.fixture.cache
        self.assertIsNone(sync.read_manifest(self.store))
    def tearDown(self):
        self.pace.stop();self.temp.cleanup();self.fixture.tearDown()
    def test_private_release_publish_restore_and_reader(self):
        manifest=worker.publish_snapshot(self.store,self.cache,('AAPL','MSFT'),{})
        self.assertTrue(all(not r['draft'] for r in self.api.releases.values()))
        reader_store=gh.GitHubReleaseStore({'DASHBOARD_DATA_REPO':self.api.repo,'DASHBOARD_GITHUB_TOKEN':'reader','DASHBOARD_DATA_VISIBILITY':'private'},session=self.api)
        self.assertEqual(sync.read_manifest(reader_store)['generation'],manifest['generation'])
        local=app.DashboardCache(self.root/'web.sqlite3')
        reader=sync.SnapshotReader(reader_store,local)
        reader._sync();reader._details('AAPL')
        self.assertEqual(len(local.history('AAPL')[0]),1000)
        self.assertEqual(local.classifications()['AAPL']['Industry'],'Consumer Electronics')
        sync.restore_checkpoint(reader_store,manifest,self.root/'new-worker.sqlite3')
        self.assertEqual(len(app.DashboardCache(self.root/'new-worker.sqlite3').history('AAPL')[0]),1000)
    def test_original_csv_stays_in_private_data_repository_and_reaches_dashboard(self):
        self.api.watchlist=b'Ticker,Close,Industry\nMSFT,99,Software\n'
        manifest=worker.publish_snapshot(self.store,self.cache,('AAPL','MSFT'),{},watchlist_csv=self.store.read_watchlist_csv().decode())
        local=app.DashboardCache(self.root/'csv-web.sqlite3')
        reader=sync.SnapshotReader(self.store,local)
        reader._sync()
        original=app.parse_watchlist(local.get('remote:watchlist')[0].encode())
        frame,_=app.build_universe_frame(original,local.quotes(),local.classifications())
        self.assertEqual(frame.set_index('Ticker').loc['MSFT','Close'],99)
        self.assertEqual(frame.set_index('Ticker').loc['MSFT','Industry'],'Software')
    def test_data_repo_must_stay_private(self):
        api=FakeGitHub();api.private=False
        store=gh.GitHubReleaseStore({'DASHBOARD_DATA_REPO':api.repo,'DASHBOARD_GITHUB_TOKEN':'writer','DASHBOARD_DATA_VISIBILITY':'private'},session=api)
        with self.assertRaisesRegex(gh.GitHubStoreError,'Private'): sync.read_manifest(store)
        self.assertTrue(all(method=='GET' for method,_ in api.calls))
    def test_failed_upload_never_changes_previous_pointer(self):
        old=worker.publish_snapshot(self.store,self.cache,('AAPL',),{})
        before=self.api.pointer
        self.api.fail_name='checkpoint.sqlite3'
        with self.assertRaises(gh.GitHubStoreError): worker.publish_snapshot(self.store,self.cache,('AAPL',),{},old)
        self.assertEqual(self.api.pointer,before)
        self.assertTrue(any(r['draft'] for r in self.api.releases.values()))
    def test_concurrent_pointer_update_is_rejected(self):
        old=worker.publish_snapshot(self.store,self.cache,('AAPL',),{})
        self.api.sha='changed-by-another-writer'
        before=self.api.pointer
        with self.assertRaisesRegex(gh.GitHubStoreError,'409'): worker.publish_snapshot(self.store,self.cache,('AAPL',),{},old)
        self.assertEqual(self.api.pointer,before)
    def test_asset_pagination_and_size_limit(self):
        tag=gh.TAG_PREFIX+'20260910T000000Z-abcdef01'
        release=self.store._release(tag,create=True)
        for i in range(120):
            self.api.assets[1000+i]={'id':1000+i,'name':str(i),'size':1,'state':'uploaded','release':release['id'],'raw':b'x'}
        self.store.assets.clear()
        self.assertEqual(len(self.store._index(tag)),120)
        with self.assertRaisesRegex(gh.GitHubStoreError,'2 GiB'):
            self.store._upload('generations/20260910T000000Z-abcdef01/checkpoint.sqlite3',io.BytesIO(),gh.ASSET_LIMIT)
    def test_cleanup_keeps_current_previous_and_unrelated_releases(self):
        old=worker.publish_snapshot(self.store,self.cache,('AAPL',),{})
        middle=worker.publish_snapshot(self.store,self.cache,('AAPL',),{},old)
        current=worker.publish_snapshot(self.store,self.cache,('AAPL',),{},middle)
        for r in self.api.releases.values(): r['created_at']='2020-01-01T00:00:00Z'
        self.api.releases[9999]={'id':9999,'tag_name':'unrelated-release','created_at':'2020-01-01T00:00:00Z'}
        self.store.prune_generations(current)
        tags={r['tag_name'] for r in self.api.releases.values()}
        self.assertNotIn(gh.TAG_PREFIX+old['generation'].split('/')[-1],tags)
        self.assertIn(gh.TAG_PREFIX+middle['generation'].split('/')[-1],tags)
        self.assertIn(gh.TAG_PREFIX+current['generation'].split('/')[-1],tags)
        self.assertIn('unrelated-release',tags)
    def test_local_mode_ignores_cloud_credentials(self):
        with patch.dict('os.environ',{'DASHBOARD_LOCAL_ONLY':'1','DASHBOARD_SNAPSHOT_DIR':str(self.root/'disk')}):
            cfg=sync.config_from({'DASHBOARD_DATA_REPO':'owner/private','DASHBOARD_GITHUB_TOKEN':'must-not-be-used'})
            self.assertIsInstance(sync.ObjectStore(cfg),sync.DirectoryStore)
    def test_local_collectors_cannot_overlap(self):
        lock=worker.local_collector_lock(self.root/'collector.lock')
        self.assertIsNotNone(lock)
        try:
            self.assertIsNone(worker.local_collector_lock(self.root/'collector.lock'))
        finally:
            lock.close()
    def test_new_app_version_gets_new_cache_without_losing_disk_data(self):
        app.get_data_cache.clear()
        with patch.dict('os.environ', {'DASHBOARD_CACHE_FILE': str(self.root/'upgrade.sqlite3')}):
            old=app.get_data_cache('test-old')
            old.put('test:value',{'saved':True},{})
            new=app.get_data_cache('test-new')
            self.assertIsNot(old,new)
            self.assertTrue(new.get('test:value')[0]['saved'])
        app.get_data_cache.clear()
    def test_workflow_has_no_billable_runner_or_storage_fallback(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        workflow=yaml.load((root/'.github/workflows/five_min_update.yml').read_text(),Loader=yaml.BaseLoader)
        job=workflow['jobs']['update']
        self.assertEqual(job['if'],"${{ toJSON(github.event.repository.private) == 'false' }}")
        self.assertEqual(job['runs-on'],'ubuntu-latest')
        self.assertEqual(workflow['permissions'],{'contents':'write'})
        self.assertEqual(job['env']['DASHBOARD_GITHUB_TOKEN'], '${{ secrets.GITHUB_TOKEN }}')
        self.assertEqual(job['env']['DASHBOARD_DATA_REPO'], '${{ github.repository }}')
        self.assertEqual(job['env']['DASHBOARD_DATA_BRANCH'], 'dashboard-data')
        self.assertFalse(any('cache' in step.get('with',{}) for step in job['steps']))
        self.assertFalse(any('upload-artifact' in step.get('uses','') for step in job['steps']))
        self.assertNotIn('boto3',(root/'requirements.txt').read_text())
        self.assertNotIn('R2_',json.dumps(job['env']))

if __name__=='__main__': unittest.main(verbosity=2)
