"""Finance-only recovery guards and persisted provider cooldowns."""
import gzip
import hashlib
import json
from copy import deepcopy
import pytest
from dashboard_runtime import DashboardCache
from financial_recovery import save_recovery,restore_records,PAYLOAD,MANIFEST

GENERATION='generations/20260913T083117Z-285cede3'
SHA='a'*40
STAMP='2026-09-13T10:00:00Z'


def prepared(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','sippakorntwo-glitch/stock-dashboard')
    monkeypatch.setenv('GITHUB_RUN_ID','123')
    monkeypatch.setenv('GITHUB_SHA',SHA)
    source=DashboardCache(tmp_path/'source.sqlite3')
    value={'schema':1,'ticker':'TEST','currency':'USD','observations':{'revenue':{'value':100}},'annual':{},'quarterly':{}}
    source.put('financials:TEST',value,{'fetched_at':STAMP})
    source.put('attempt:financials:TEST',{}, {'fetched_at':STAMP,'retry_after':'2026-09-20T10:00:00Z','success':False})
    source.put('external:financials-circuit',{'retry_after':'2026-09-14T10:00:00Z'},{'fetched_at':STAMP})
    source.put('info:TEST',{'must_not_be_copied':True},{'fetched_at':STAMP})
    manifest=save_recovery(source,GENERATION,tmp_path)
    raw=(tmp_path/PAYLOAD).read_bytes()
    return manifest,raw


def restore(cache,manifest,raw,generation=GENERATION):
    return restore_records(cache,('TEST',),generation,manifest,raw,run_id=123,source_sha=SHA,now=1789293600)


def test_failed_publication_recovery_restores_financials_and_provider_cooldown(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    assert restore(cache,manifest,raw)['restored']==3
    assert cache.get('financials:TEST',request_remote=False)[0]['observations']['revenue']['value']==100
    assert cache.get('external:financials-circuit',request_remote=False)[0]['retry_after']=='2026-09-14T10:00:00Z'
    assert cache.get('info:TEST',request_remote=False)[0] is None
    assert restore(cache,manifest,raw)['restored']==0,'Recovery must be idempotent'


@pytest.mark.parametrize('change',[{'source_generation':'unverified'}, {'repository':'other/repo'}, {'run_id':'124'}, {'source_sha':'b'*40}])
def test_recovery_requires_exact_snapshot_repository_run_and_source(tmp_path,monkeypatch,change):
    manifest,raw=prepared(tmp_path,monkeypatch);manifest.update(change)
    cache=DashboardCache(tmp_path/'target.sqlite3')
    assert restore(cache,manifest,raw)['restored']==0
    assert cache.get('financials:TEST',request_remote=False)[0] is None


def test_recovery_validates_checksum_and_every_key_before_mutating_cache(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    with pytest.raises(ValueError,match='checksum'):restore(cache,manifest,raw+b'corrupt')
    records=json.loads(gzip.decompress(raw));records.append(['info:TEST',{}, {'fetched_at':STAMP}])
    raw=gzip.compress(json.dumps(records).encode());manifest.update(sha256=hashlib.sha256(raw).hexdigest(),records=len(records))
    with pytest.raises(ValueError,match='Non-financial'):restore(cache,manifest,raw)
    assert cache.get('financials:TEST',request_remote=False)[0] is None


def test_recovery_preserves_newer_observations_and_longer_retry_dates(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    newer={'schema':1,'ticker':'TEST','currency':'USD','observations':{'revenue':{'value':200}}}
    cache.put('financials:TEST',newer,{'fetched_at':'2026-09-13T11:00:00Z'})
    cache.put('attempt:financials:TEST',{}, {'fetched_at':'2026-09-13T09:00:00Z','retry_after':'2026-10-01T00:00:00Z'})
    cache.put('external:financials-circuit',{'retry_after':'2026-09-15T00:00:00Z'},{'fetched_at':'2026-09-13T09:00:00Z'})
    assert restore(cache,manifest,raw)['restored']==0
    assert cache.get('financials:TEST',request_remote=False)[0]==newer


@pytest.mark.parametrize('workflow',['company_financials.yml','sec_financials.yml'])
@pytest.mark.parametrize('conclusion',['failure','cancelled'])
def test_automatic_recovery_only_reads_own_failed_workflow_data(tmp_path,monkeypatch,conclusion,workflow):
    import io,zipfile
    from financial_recovery import recover_recent_failure
    manifest,raw=prepared(tmp_path,monkeypatch)
    monkeypatch.setenv('DASHBOARD_GITHUB_TOKEN','fixture-token')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as zipped:
        zipped.writestr(PAYLOAD,raw);zipped.writestr(MANIFEST,json.dumps(manifest))
        zipped.writestr('../never_execute.py','raise RuntimeError("must never execute")')
    class Response:
        def __init__(self,body=None,binary=None):self.body,self.binary=body,binary
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def json(self):return self.body
        def iter_content(self,size):yield self.binary
    class Session:
        def __init__(self):self.calls=[]
        def get(self,url,**kwargs):
            self.calls.append(url)
            if url.endswith('/runs'):
                return Response({'workflow_runs':[
                    {'id':122,'head_branch':'main','conclusion':'failure','head_repository':{'full_name':'other/repo'},'path':'.github/workflows/company_financials.yml','head_sha':SHA},
                    {'id':124,'head_branch':'main','conclusion':'failure','head_repository':{'full_name':'sippakorntwo-glitch/stock-dashboard'},'path':'.github/workflows/unreviewed.yml','head_sha':SHA},
                    {'id':123,'head_branch':'main','conclusion':conclusion,'head_repository':{'full_name':'sippakorntwo-glitch/stock-dashboard'},'path':'.github/workflows/'+workflow,'head_sha':SHA}]})
            if url.endswith('/123/artifacts'):
                prefix='sec-financials' if workflow=='sec_financials.yml' else 'company-financials'
                return Response({'artifacts':[{'id':457,'name':'unreviewed-audit-4','expired':False,'size_in_bytes':len(archive.getvalue())},
                    {'id':456,'name':prefix+'-audit-4','expired':False,'size_in_bytes':len(archive.getvalue())}]})
            if url.endswith('/456/zip'):return Response(binary=archive.getvalue())
            raise AssertionError(url)
    session=Session();cache=DashboardCache(tmp_path/'target.sqlite3')
    result=recover_recent_failure(cache,('TEST',),GENERATION,workflow_name=workflow,session=session)
    assert result['restored']==3 and len(session.calls)==3
    assert session.calls[0].endswith('/actions/workflows/'+workflow+'/runs')
    assert not (tmp_path/'never_execute.py').exists()


def test_inaccessible_recovery_stops_before_provider_collection(tmp_path,monkeypatch):
    import requests
    from financial_recovery import recover_recent_failure
    prepared(tmp_path,monkeypatch);monkeypatch.setenv('DASHBOARD_GITHUB_TOKEN','fixture-token')
    class Session:
        def get(self,*args,**kwargs):raise requests.ConnectionError('unavailable')
    with pytest.raises(RuntimeError,match='provider collection was not started'):
        recover_recent_failure(DashboardCache(tmp_path/'target.sqlite3'),('TEST',),GENERATION,session=Session())


def test_changed_snapshot_recovers_only_active_provider_guards(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    result=restore(cache,manifest,raw,generation='generations/new-price-snapshot')
    assert result['guards_only'] is True and result['restored']==2
    assert cache.get('financials:TEST',request_remote=False)[0] is None
    assert cache.get('external:financials-circuit',request_remote=False)[0]['retry_after']=='2026-09-14T10:00:00Z'
    assert cache.get('attempt:financials:TEST',request_remote=False)[1]['retry_after']=='2026-09-20T10:00:00Z'


def test_changed_snapshot_does_not_restore_expired_or_successful_refresh_guards(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    records=json.loads(gzip.decompress(raw))
    for key,value,meta in records:
        if key=='external:financials-circuit':value['retry_after']='2026-09-12T10:00:00Z'
        if key.startswith('attempt:'):meta['success']=True
    raw=gzip.compress(json.dumps(records).encode());manifest['sha256']=hashlib.sha256(raw).hexdigest()
    assert restore(cache,manifest,raw,generation='generations/new-price-snapshot')['restored']==0
    assert cache.get('financials:TEST',request_remote=False)[0] is None
    assert cache.get('attempt:financials:TEST',request_remote=False)[0] is None
    assert cache.get('external:financials-circuit',request_remote=False)[0] is None


def test_changed_snapshot_preserves_later_existing_provider_retry(tmp_path,monkeypatch):
    manifest,raw=prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    cache.put('attempt:financials:TEST',{}, {'fetched_at':'2026-09-13T09:00:00Z','retry_after':'2026-10-01T00:00:00Z','success':False})
    cache.put('external:financials-circuit',{'retry_after':'2026-09-15T00:00:00Z'},{'fetched_at':'2026-09-13T09:00:00Z'})
    assert restore(cache,manifest,raw,generation='generations/new-price-snapshot')['restored']==0
    assert cache.get('attempt:financials:TEST',request_remote=False)[1]['retry_after']=='2026-10-01T00:00:00Z'
    assert cache.get('external:financials-circuit',request_remote=False)[0]['retry_after']=='2026-09-15T00:00:00Z'


def sec_prepared(tmp_path,monkeypatch):
    prepared(tmp_path,monkeypatch)
    source=DashboardCache(tmp_path/'source.sqlite3')
    source.put('attempt:sec-financials:TEST',{},
               {'fetched_at':STAMP,'success':False,'retry_after':'2026-09-14T12:00:00Z'})
    source.put('external:sec-circuit',{'next_attempt_after':'2026-09-14T12:00:00Z'},
               {'fetched_at':STAMP})
    source.put('external:sec-circuit-unreviewed',{'next_attempt_after':'2026-09-14T12:00:00Z'},
               {'fetched_at':STAMP})
    manifest=save_recovery(source,GENERATION,tmp_path)
    return manifest,(tmp_path/PAYLOAD).read_bytes()


def repack(manifest,records):
    raw=gzip.compress(json.dumps(records).encode())
    manifest.update(sha256=hashlib.sha256(raw).hexdigest(),records=len(records))
    return raw


def test_sec_attempts_and_shared_circuit_saved_without_unknown_prefixes(tmp_path,monkeypatch):
    manifest,raw=sec_prepared(tmp_path,monkeypatch)
    keys={r[0] for r in json.loads(gzip.decompress(raw))}
    assert {'attempt:sec-financials:TEST','external:sec-circuit'}<=keys
    assert 'external:sec-circuit-unreviewed' not in keys
    cache=DashboardCache(tmp_path/'target.sqlite3')
    assert restore(cache,manifest,raw)['restored']==5
    assert cache.get('external:sec-circuit',request_remote=False)[0]['next_attempt_after']=='2026-09-14T12:00:00Z'
    assert cache.get('attempt:sec-financials:TEST',request_remote=False)[1]['success'] is False


def test_sec_guards_survive_price_generation_change_without_restoring_observations(tmp_path,monkeypatch):
    manifest,raw=sec_prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    result=restore(cache,manifest,raw,generation='generations/20260914T083117Z-285cede3')
    assert result['guards_only'] and result['restored']==4
    assert cache.get('financials:TEST',request_remote=False)[0] is None
    assert cache.get('external:sec-circuit',request_remote=False)[0]['next_attempt_after']=='2026-09-14T12:00:00Z'
    assert cache.get('attempt:sec-financials:TEST',request_remote=False)[1]['retry_after']=='2026-09-14T12:00:00Z'


@pytest.mark.parametrize('deadline',[None,True,1789293600,'invalid','NaT','2026-09-14T12:00:00'])
@pytest.mark.parametrize('key',['external:sec-circuit','attempt:sec-financials:TEST'])
def test_invalid_sec_deadline_rejects_whole_artifact_before_writes(tmp_path,monkeypatch,deadline,key):
    manifest,raw=sec_prepared(tmp_path,monkeypatch)
    records=json.loads(gzip.decompress(raw))
    for record_key,value,meta in records:
        if record_key==key:
            if key=='external:sec-circuit':value['next_attempt_after']=deadline
            else:meta['retry_after']=deadline
    cache=DashboardCache(tmp_path/'target.sqlite3')
    with pytest.raises(ValueError,match='deadline'):
        restore(cache,manifest,repack(manifest,records))
    assert cache.get('financials:TEST',request_remote=False)[0] is None
    assert cache.get('external:sec-circuit',request_remote=False)[0] is None


def test_sec_success_and_expired_circuit_do_not_postpone_missing_data_after_generation_change(tmp_path,monkeypatch):
    manifest,raw=sec_prepared(tmp_path,monkeypatch)
    records=json.loads(gzip.decompress(raw))
    for key,value,meta in records:
        if key=='external:sec-circuit':value['next_attempt_after']='2026-09-12T10:00:00Z'
        if key=='attempt:sec-financials:TEST':meta['success']=True
    cache=DashboardCache(tmp_path/'target.sqlite3')
    result=restore(cache,manifest,repack(manifest,records),generation='generations/20260914T083117Z-285cede3')
    assert result['restored']==2
    assert cache.get('external:sec-circuit',request_remote=False)[0] is None
    assert cache.get('attempt:sec-financials:TEST',request_remote=False)[0] is None


def test_sec_existing_longer_cooldown_wins_across_generations(tmp_path,monkeypatch):
    manifest,raw=sec_prepared(tmp_path,monkeypatch);cache=DashboardCache(tmp_path/'target.sqlite3')
    longer='2026-10-01T00:00:00Z'
    cache.put('attempt:sec-financials:TEST',{},
               {'fetched_at':'2026-09-13T09:00:00Z','retry_after':longer,'success':False})
    cache.put('external:sec-circuit',{'next_attempt_after':longer},{'fetched_at':'2026-09-13T09:00:00Z'})
    assert restore(cache,manifest,raw,generation='generations/20260914T083117Z-285cede3')['restored']==2
    assert cache.get('external:sec-circuit',request_remote=False)[0]['next_attempt_after']==longer
    assert cache.get('attempt:sec-financials:TEST',request_remote=False)[1]['retry_after']==longer


@pytest.mark.parametrize('key',['external:sec-circuit-extra','attempt:sec-profile:TEST','attempt:sec-financials:OUTSIDE'])
def test_unknown_sec_record_or_catalog_symbol_rejects_artifact(tmp_path,monkeypatch,key):
    manifest,raw=sec_prepared(tmp_path,monkeypatch)
    records=json.loads(gzip.decompress(raw));records.append([key,{}, {'fetched_at':STAMP}])
    cache=DashboardCache(tmp_path/'target.sqlite3')
    with pytest.raises(ValueError):restore(cache,manifest,repack(manifest,records))
    assert cache.get('financials:TEST',request_remote=False)[0] is None


@pytest.mark.parametrize('change',[{'repository':'other/repo'},{'source_sha':'b'*40},{'run_id':'124'}])
def test_sec_cross_generation_guards_still_require_failed_run_provenance(tmp_path,monkeypatch,change):
    manifest,raw=sec_prepared(tmp_path,monkeypatch);manifest.update(change)
    cache=DashboardCache(tmp_path/'target.sqlite3')
    assert restore(cache,manifest,raw,generation='generations/20260914T083117Z-285cede3')['restored']==0
    assert cache.get('external:sec-circuit',request_remote=False)[0] is None


@pytest.mark.parametrize('workflow',['unreviewed.yml','../company_financials.yml','https://example.com/workflow.yml'])
def test_unapproved_workflow_cannot_be_requested(tmp_path,monkeypatch,workflow):
    from financial_recovery import recover_recent_failure
    prepared(tmp_path,monkeypatch);monkeypatch.setenv('DASHBOARD_GITHUB_TOKEN','fixture-token')
    class Session:
        def get(self,*args,**kwargs):pytest.fail('Unreviewed workflow must not be requested')
    with pytest.raises(ValueError,match='not approved'):
        recover_recent_failure(DashboardCache(tmp_path/'target.sqlite3'),('TEST',),GENERATION,
                               workflow_name=workflow,session=Session())
