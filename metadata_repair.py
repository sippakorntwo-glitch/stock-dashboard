"""Bounded, paced metadata collection; partial failures retain successful data."""
from __future__ import annotations
import time
from data_quality import metadata_jobs, prepare_cached_metadata


def collect_metadata(cache, universe, mode, minutes, limit, report, *, app, get_metadata, record_attempt):
    prepare_cached_metadata(cache, universe, app.ETF_NAMES)
    metadata=get_metadata(cache)
    jobs=metadata_jobs(universe,metadata,app.ETF_NAMES,time.time(),mode)
    report['metadata_jobs_due']=len(jobs)
    report['metadata_jobs_attempted']=0
    if report.get('rate_limited') or minutes<=0 or limit<=0:return
    worker=app.BackgroundUpdates(cache)
    deadline=time.monotonic()+minutes*60
    failures=0
    for kind,ticker in jobs[:limit]:
        if time.monotonic()>=deadline:break
        start=time.monotonic()
        report['metadata_jobs_attempted']+=1
        try:
            worker._job(kind,ticker,'1d')
            record_attempt(cache,kind,ticker,True)
            report['metadata_success']+=1
            failures=0
        except Exception as exc:
            record_attempt(cache,kind,ticker,False)
            report['metadata_failed']+=1;failures+=1
            report['errors']=(report.get('errors',[])+[f'{ticker}/{kind}: {type(exc).__name__}'])[-20:]
            if failures>=5 or any(term in str(exc).lower() for term in ('429','rate limit','too many')):
                report['rate_limited']=True
                break
        if report['metadata_jobs_attempted']%100==0:
            print('METADATA_PROGRESS:',report['metadata_jobs_attempted'],'/',min(len(jobs),limit),
                  'success',report['metadata_success'],'failed',report['metadata_failed'],flush=True)
        # Single worker. At most two jobs start per second, without retries/proxy rotation.
        time.sleep(max(0.0,0.5-(time.monotonic()-start)))
    report['metadata_jobs_remaining_in_round']=max(0,len(jobs)-report['metadata_jobs_attempted'])
