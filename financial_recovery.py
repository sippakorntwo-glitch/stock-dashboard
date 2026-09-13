"""Data-only recovery for this repository's interrupted statement publications.

Only finance records from a failed or cancelled main-branch run of our own collection workflow
can be restored, and only over the exact snapshot from which they were collected.
No artifact is extracted or executed; the checksum and every record are checked
before the local cache is changed. Existing newer records and retry dates win.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile

REPOSITORY = 'sippakorntwo-glitch/stock-dashboard'
PAYLOAD = 'company-financials-recovery.json.gz'
MANIFEST = 'company-financials-recovery.manifest.json'
MAX_BYTES = 64 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
PREFIXES = ('financials:', 'attempt:financials:', 'external:financials-circuit')


def save_recovery(cache, generation, directory='work'):
    from data_quality import read_objects
    from data_sync import utc_now
    records = [[key, value, meta] for key,(value,meta) in read_objects(cache,PREFIXES).items()]
    raw = gzip.compress(json.dumps(records,ensure_ascii=False,allow_nan=False).encode())
    manifest = {'schema':1, 'repository':os.environ.get('GITHUB_REPOSITORY'),
        'run_id':os.environ.get('GITHUB_RUN_ID'), 'source_sha':os.environ.get('GITHUB_SHA'),
        'source_generation':generation, 'created_at':utc_now(),
        'payload':PAYLOAD, 'sha256':hashlib.sha256(raw).hexdigest(), 'records':len(records)}
    folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    (folder/PAYLOAD).write_bytes(raw)
    (folder/MANIFEST).write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


def restore_records(cache, universe, generation, manifest, raw, *, run_id, source_sha):
    from data_quality import timestamp
    from financial_statements import SCHEMA
    if (manifest.get('schema')!=1 or manifest.get('repository')!=REPOSITORY
            or str(manifest.get('run_id'))!=str(run_id) or manifest.get('source_sha')!=source_sha
            or manifest.get('payload')!=PAYLOAD or manifest.get('source_generation')!=generation):
        return {'restored':0,'reason':'Recovery does not match the failed run and current snapshot'}
    if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=manifest.get('sha256'):
        raise ValueError('Financial recovery checksum or size is invalid')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded=stream.read(MAX_DECODED_BYTES+1)
    if len(decoded)>MAX_DECODED_BYTES:raise ValueError('Financial recovery exceeds the data limit')
    records=json.loads(decoded)
    if not isinstance(records,list) or len(records)!=manifest.get('records'):
        raise ValueError('Financial recovery record count is invalid')
    names=set(universe);keys=set()
    for row in records:
        if not isinstance(row,list) or len(row)!=3:raise ValueError('Invalid financial recovery row')
        key,value,meta=row
        if not isinstance(key,str) or key in keys or not isinstance(value,dict) or not isinstance(meta,dict):
            raise ValueError('Invalid or duplicate financial recovery record')
        keys.add(key)
        if key=='external:financials-circuit':
            if not timestamp(value.get('retry_after')):raise ValueError('Invalid financial circuit')
        elif key.startswith(('financials:','attempt:financials:')):
            ticker=key.rsplit(':',1)[-1]
            if ticker not in names:raise ValueError('Financial recovery ticker is outside this catalog')
            if key.startswith('financials:') and (value.get('schema')!=SCHEMA or value.get('ticker')!=ticker or not value.get('currency')):
                raise ValueError('Financial recovery identity is invalid')
        else:raise ValueError('Non-financial recovery record rejected')
        if not timestamp(meta.get('fetched_at')):raise ValueError('Financial recovery timestamp is invalid')
    restored=0
    for key,value,meta in records:
        old,oldmeta=cache.get(key,request_remote=False)
        if timestamp(oldmeta.get('fetched_at'))>=timestamp(meta.get('fetched_at')):continue
        if key=='external:financials-circuit' and isinstance(old,dict) and timestamp(old.get('retry_after'))>=timestamp(value.get('retry_after')):continue
        if key.startswith('attempt:') and timestamp(oldmeta.get('retry_after'))>timestamp(meta.get('retry_after')):continue
        if key.startswith('financials:') and isinstance(old,dict) and old.get('observations') and not value.get('observations'):continue
        cache.put(key,value,meta);restored+=1
    return {'restored':restored,'run_id':str(run_id),'source_generation':generation}


def recover_recent_failure(cache, universe, generation, *, session=None):
    """Inspect at most five own failed or cancelled runs; restore one compatible artifact."""
    token=os.environ.get('DASHBOARD_GITHUB_TOKEN')
    if os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY or not token:
        return {'restored':0,'reason':'Recovery only runs in the repository collector'}
    import requests
    client=session or requests.Session()
    base='https://api.github.com/repos/'+REPOSITORY
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
             'X-GitHub-Api-Version':'2022-11-28'}
    def get(path, **kwargs):
        response=client.get(base+path,headers=headers,timeout=(10,30),**kwargs)
        response.raise_for_status()
        return response
    try:
        with get('/actions/workflows/company_financials.yml/runs',params={'branch':'main','status':'completed','per_page':20}) as response:
            runs=response.json().get('workflow_runs',[])
        candidates=[r for r in runs if r.get('conclusion') in ('failure','cancelled')][:5]
        for run in candidates:
            if (run.get('head_branch')!='main' or run.get('conclusion') not in ('failure','cancelled')
                    or run.get('head_repository',{}).get('full_name')!=REPOSITORY
                    or run.get('path')!='.github/workflows/company_financials.yml'
                    or not re.fullmatch(r'[0-9a-f]{40}',run.get('head_sha',''))):continue
            rid=int(run['id'])
            with get(f'/actions/runs/{rid}/artifacts',params={'per_page':100}) as response:
                artifacts=response.json().get('artifacts',[])
            for artifact in sorted(artifacts,key=lambda a:a['id'],reverse=True):
                if (artifact.get('expired') or not re.fullmatch(r'company-financials-audit-\d+',artifact.get('name',''))
                        or not 0<artifact.get('size_in_bytes',0)<=MAX_BYTES):continue
                with get(f"/actions/artifacts/{int(artifact['id'])}/zip",stream=True) as response:
                    archive=bytearray()
                    for chunk in response.iter_content(1024*1024):
                        archive.extend(chunk)
                        if len(archive)>MAX_BYTES:raise ValueError('Recovery artifact exceeds data limit')
                with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                    names=zipped.namelist()
                    if PAYLOAD not in names or MANIFEST not in names:continue
                    if names.count(PAYLOAD)!=1 or names.count(MANIFEST)!=1:raise ValueError('Duplicate recovery files')
                    if zipped.getinfo(MANIFEST).file_size>65536 or zipped.getinfo(PAYLOAD).file_size>MAX_BYTES:
                        raise ValueError('Recovery files exceed data limit')
                    manifest=json.loads(zipped.read(MANIFEST))
                    result=restore_records(cache,universe,generation,manifest,zipped.read(PAYLOAD),run_id=rid,source_sha=run['head_sha'])
                if result['restored']:return result
        return {'restored':0,'reason':'No compatible financial recovery artifact'}
    except requests.RequestException as exc:
        # A provider cooldown may exist only in the unpublished recovery. Do not
        # recollect blindly when its status cannot be inspected.
        raise RuntimeError('Cannot inspect failed financial recovery; provider collection was not started') from exc
