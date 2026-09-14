"""Live-smoke guard enforcement; synthetic data is confined to these tests."""
import hashlib
import shutil

import pytest
import requests

from dashboard_runtime import DashboardCache
import sec_financials_smoke as smoke


def test_manifest_guard_does_not_download_checkpoint():
    assert smoke._published_guard({'provider_circuits': {'sec': None}}) == (
        None, 'same-generation published SEC circuit')
    assert smoke._published_guard({'provider_circuits': {'sec': {'next_attempt_after': '2027-01-01T00:00:00Z'}}})[0] == '2027-01-01T00:00:00Z'


def test_legacy_manifest_requires_checked_checkpoint_guard(tmp_path, monkeypatch):
    path = tmp_path/'source.sqlite3'
    cache = DashboardCache(path)
    cache.put('external:sec-circuit', {'next_attempt_after': '2027-01-01T00:00:00Z'}, {})
    with cache.connect() as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    manifest = {'checkpoint': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
    calls = []
    def restore(store, selected, target):
        calls.append((store, selected)); shutil.copyfile(path, target)
    monkeypatch.setattr(smoke, 'restore_checkpoint', restore)
    until, method = smoke._published_guard(manifest, store='fixture-store')
    assert until == '2027-01-01T00:00:00Z'
    assert method == 'same-generation checked local checkpoint'
    assert len(calls) == 1
    with pytest.raises(ValueError, match='does not match'):
        smoke._published_guard({'checkpoint': {'sha256': 'bad'}}, path)


def test_active_durable_guard_stops_before_any_sec_access(monkeypatch):
    monkeypatch.setattr(smoke, 'ObjectStore', lambda _: object())
    monkeypatch.setattr(smoke, 'read_manifest', lambda _: {'generation': 'fixture',
        'provider_circuits': {'sec': {'next_attempt_after': '2099-01-01T00:00:00Z'}}})
    monkeypatch.setattr(smoke, '_shard_objects', lambda *_: pytest.fail('No shard or SEC access during cooldown'))
    report = smoke.run()
    assert report['result'] == 'unavailable' and report['provider_requests'] == 0
    assert report['cooldown_until'] == '2099-01-01T00:00:00Z'


def test_provider_denial_is_unavailable_and_does_not_retry(monkeypatch):
    monkeypatch.setattr(smoke, 'ObjectStore', lambda _: object())
    monkeypatch.setattr(smoke, 'read_manifest', lambda _: {'generation': 'fixture', 'provider_circuits': {'sec': None}})
    monkeypatch.setattr(smoke, '_shard_objects', lambda *_: {
        'financials:AARD': ({'schema': 1, 'ticker': 'AARD', 'currency': 'USD'}, {}),
        'info:AARD': ({'financialCurrency': 'USD'}, {}),
        'reference:AARD': ({'cik': 1774857}, {})})
    class DeniedClient:
        def __init__(self, *, max_requests):
            assert max_requests == 3
            self.calls = 0; self.blocked = False; self.evidence = []
        def get(self, url):
            assert self.calls == 0
            self.calls += 1; self.blocked = True
            self.evidence.append({'url': url, 'http_status': 403})
            raise requests.HTTPError('403 Forbidden')
    monkeypatch.setattr(smoke, 'SecClient', DeniedClient)
    report = smoke.run()
    assert report['result'] == 'unavailable' and report['provider_requests'] == 1
    assert report['blocked'] is True and report['http_evidence'][0]['http_status'] == 403
