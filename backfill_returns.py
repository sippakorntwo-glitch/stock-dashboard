"""Recalculate requested table returns, extend real history, publish atomically.

No invented pre-listing candles, no new account or provider token, no change to
rank filters. The checked checkpoint is the only seed. Raw observations retain
their original fetched_at when only calculations are refreshed.
"""
from __future__ import annotations
import argparse
import base64
import gzip
import json
import os
from pathlib import Path
import time
import pandas as pd
import dashboard_runtime as app
import update_data as collector
from data_sync import (ObjectStore, config_from, read_manifest, read_checked,
                       restore_checkpoint, utc_now)
from data_quality import checked_universe
from return_periods import RETURN_FIELDS, RETURN_LABELS, table_returns


def counts(cache,universe):
    rows=cache.quotes()
    return {RETURN_LABELS[field]:sum(app.number(rows.get(t,{}).get(field)) is not None for t in universe)
            for field in RETURN_FIELDS}


def publish_audit(writer,manifest,report):
    writer._ensure_data_branch()
    path='dashboard/returns-backfill-latest.json'
    previous=writer._json('GET','/contents/'+path,missing=True,params={'ref':writer.branch})
    value={**report,'generation':manifest['generation'],'app_version':app.APP_VERSION,'published_at':manifest['published_at']}
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode()
    body={'message':'Record verified English return-period backfill','branch':writer.branch,'content':base64.b64encode(raw).decode()}
    if previous:body['sha']=previous['sha']
    writer._json('PUT','/contents/'+path,json=body)
    Path('work').mkdir(exist_ok=True)
    Path('work/returns_backfill.json').write_bytes(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes',type=float,default=45)
    args=parser.parse_args()
    if not 0 <= args.minutes <= 55:parser.error('minutes must be in [0, 55]')
    config=config_from()
    if (os.environ.get('GITHUB_ACTIONS')!='true' or not config
            or config.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')
            or config.get('DASHBOARD_DATA_VISIBILITY')!='public'):
        raise RuntimeError('Backfill is restricted to its own public GitHub Actions repository')
    store=ObjectStore(config,writable=True);previous=read_manifest(store)
    if not previous:raise RuntimeError('No verified snapshot; refuse to replace missing source')
    summary=json.loads(gzip.decompress(read_checked(store,previous['summary'])))
    universe=checked_universe(summary)
    path=Path(os.environ.get('DASHBOARD_CACHE_FILE','work/return_backfill.sqlite3'))
    restore_checkpoint(store,previous,path)
    cache=app.DashboardCache(path)
    if cache.error:raise RuntimeError(cache.error)
    before=counts(cache,universe);saved=cache.quotes();recomputed=0;failures=[]
    for t in universe:
        try:
            h,meta=cache.history(t)
            if h is None:continue
            stamp=meta.get('fetched_at') or saved.get(t,{}).get('Data_Time')
            if not stamp:raise ValueError('No source observation time')
            row=app.scan_snapshot_row(t,h,stamp)
            row['History_Years_Loaded']=meta.get('years',saved.get(t,{}).get('History_Years_Loaded',0))
            cache.save_quotes(pd.DataFrame([row]));recomputed+=1
        except (ValueError,TypeError,KeyError) as exc:
            failures.append({'ticker':t,'error':type(exc).__name__})
    if failures:raise RuntimeError('Recalculation failures: '+json.dumps(failures[:20]))
    print('RETURN_BACKFILL_START:',json.dumps({'recomputed':recomputed,'before':before,'after_recalculation':counts(cache,universe)},ensure_ascii=False),flush=True)
    # Previously stored history remains usable while full six-year requests run.
    collection=collector.collect(cache,universe,'bootstrap',price_minutes=args.minutes,
                                  metadata_minutes=0,metadata_limit=0)
    report={'started_from':previous['generation'],'calculated_at':utc_now(),'universe':len(universe),
            'recomputed':recomputed,'before':before,'after':counts(cache,universe),
            'source_history_years_requested':app.HISTORY_YEARS,'collection':collection}
    rows=cache.quotes();report['remaining_depth_or_metric_jobs']=sum(collector.history_missing(rows.get(t,{})) for t in universe)
    # Independently require at least known long-history benchmark examples to
    # have all requested returns. A provider outage must not pass as a full fix.
    report['samples']={}
    for t in ('AAPL','MSFT','SPY','ORCL','AAC'):
        h,meta=cache.history(t)
        expected=table_returns(app.completed_daily_history(h)) if h is not None else {}
        report['samples'][t]={'returns':{RETURN_LABELS[f]:rows.get(t,{}).get(f) for f in RETURN_FIELDS},
                              'price_asof':rows.get(t,{}).get('Price_AsOf'),
                              'history_start':str(h.index[0]) if h is not None else None,
                              'history_end':str(h.index[-1]) if h is not None else None}
        for field in RETURN_FIELDS:
            actual=app.number(rows.get(t,{}).get(field));value=expected.get(field)
            if actual is None and value is None:continue
            if actual is None or value is None or abs(actual-value)>1e-7:raise RuntimeError('Snapshot return mismatch: '+t+'/'+field)
    manifest=collector.publish_snapshot(store,cache,universe,collection,previous,
                                        watchlist_csv=summary.get('watchlist_csv'))
    publish_audit(store,manifest,report)
    print('RETURN_BACKFILL_REPORT:',json.dumps(report,ensure_ascii=False,allow_nan=False),flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('### English return periods: verified real-data backfill\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')
    if collection['rate_limited'] or collection['price_failed']:
        print('::warning::Some real-provider history requests did not succeed; retain honest gaps and retry timestamps.')
    if report['remaining_depth_or_metric_jobs']:
        print('::warning::Backfill is partial; inspect the report rather than calling it complete.')
    for t in ('AAPL','MSFT','SPY'):
        if any(app.number(rows.get(t,{}).get(field)) is None for field in RETURN_FIELDS):
            raise RuntimeError('Required long-history example is incomplete: '+t)


if __name__=='__main__':main()
