"""One owner-authorized repair pass; all repaired values come from the provider.

Use the published universe, preserve checkpoints, verify both before and after,
and publish only after the available progress and explicit quality states are saved.
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
from pathlib import Path
import tempfile
import pandas as pd
import dashboard_runtime as a
from data_sync import ObjectStore, config_from, read_manifest, read_checked, restore_checkpoint, utc_now
from data_quality import checked_universe, prepare_cached_metadata
from audit_dashboard import inspect_cache
from update_data import collect, publish_snapshot, prune_old_generations


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--minutes',type=float,default=65);parser.add_argument('--limit',type=int,default=6500)
    parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    if not 0<=args.minutes<=110 or not 0<=args.limit<=10000:parser.error('Invalid bounded repair budget')
    config=config_from() or {'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    if args.publish:
        if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('Publication needs the owner workflow')
        event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        if (event.get('repository',{}).get('private') is not False or config.get('DASHBOARD_DATA_REPO','').lower()!=os.environ.get('GITHUB_REPOSITORY','').lower()
                or config.get('DASHBOARD_DATA_VISIBILITY')!='public'):raise RuntimeError('Write only to the same public owner repository')
    reader=ObjectStore(config);previous=read_manifest(reader)
    if not previous:raise RuntimeError('No verified checkpoint; cannot overwrite an unknown source')
    summary=json.loads(gzip.decompress(read_checked(reader,previous['summary'])))
    universe=checked_universe(summary)
    with tempfile.TemporaryDirectory(prefix='repair-complete-data-') as tmp:
        path=Path(tmp)/'source.sqlite3';restore_checkpoint(reader,previous,path);cache=a.DashboardCache(path)
        if cache.error:raise RuntimeError(cache.error)
        before,issues=inspect_cache(cache,universe,previous,summary)
        prepare_cached_metadata(cache,universe,a.ETF_NAMES)
        print('DATA_REPAIR_BEFORE:',json.dumps(before['counts']),flush=True)
        report=collect(cache,universe,'bootstrap',price_minutes=0,metadata_minutes=args.minutes,metadata_limit=args.limit)
        after,issues=inspect_cache(cache,universe,previous,summary)
        audit={'before':before,'after':after,'collection':report,'finished_at':utc_now()}
        Path('work').mkdir(exist_ok=True);Path('work/data_repair_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
        pd.DataFrame(issues).to_csv('work/data_repair_remaining.csv',index=False,encoding='utf-8-sig')
        if args.publish:
            writer=ObjectStore(config,writable=True)
            current=read_manifest(writer)
            if current.get('generation')!=previous.get('generation'):raise RuntimeError('Snapshot advanced during repair; refusing to overwrite newer work')
            manifest=publish_snapshot(writer,cache,universe,{**report,'repair_before':before['counts'],'repair_after':after['counts']},current,watchlist_csv=summary.get('watchlist_csv'))
            audit['published_generation']=manifest['generation']
            # Compact audit is independent of market data; no user-uploaded holdings are exported.
            cache.put('audit:last-repair',{'before':before['counts'],'after':after['counts']},{'fetched_at':utc_now()})
        print('DATA_REPAIR_RESULT:',json.dumps({'before':before['counts'],'after':after['counts'],'quote_missing':after['quote_missing'],'information_missing':after['information_missing'],'samples':after['samples'],'collection':report,'published_generation':audit.get('published_generation')},ensure_ascii=False),flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('### Data repair verification\n```json\n'+json.dumps({'before':before['counts'],'after':after['counts'],'collection':report},ensure_ascii=False,indent=2)+'\n```\n')
        if report.get('rate_limited'):print('::warning::Provider rate limit: stop requests, retain progress, respect retry timestamps.')

if __name__=='__main__':main()
