"""Prime priority symbols; reuse an unchanged, verified snapshot on code-only releases."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd
from data_sync import ObjectStore, config_from, read_manifest, restore_checkpoint, utc_now
from update_data import app, collect, publish_snapshot

PRIORITY=('AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','SPY','QQQ','VOO','VTI','SCHD','JEPI','JEPQ','GLD','TLT','QQQI','SPYI')


def needs_publication(previous,report):
    # Failures change retry/checkpoint state and must also be persisted.
    return not previous or any(report.get(key,0) for key in ('price_attempted','metadata_success','metadata_failed'))


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true': raise RuntimeError('Deployment seed is intended for GitHub Actions only')
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    config=config_from()
    if (event.get('repository',{}).get('private') is not False or not config
            or config.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')
            or config.get('DASHBOARD_DATA_VISIBILITY')!='public'):
        raise RuntimeError('Seed only publishes to its own public repository')
    store=ObjectStore(config,writable=True)
    previous=read_manifest(store)
    path=Path(os.environ.get('DASHBOARD_CACHE_FILE','work/dashboard_cache.sqlite3'))
    restore_checkpoint(store,previous,path)
    cache=app.DashboardCache(path)
    if cache.error: raise RuntimeError('Cannot persist local cache')
    data=app.WATCHLIST_FILE.read_bytes() if app.WATCHLIST_FILE.exists() else None
    original=app.parse_watchlist(data) if data else pd.DataFrame(columns=['Ticker'])
    if not previous and not original.empty: cache.save_quotes(original)
    universe=app.select_universe(original)
    selected=tuple(t for t in PRIORITY if t in universe)
    report=collect(cache,selected,'daily',price_minutes=3,metadata_minutes=5,metadata_limit=40)
    report.update(deployment_seed=True,priority_symbols=list(selected),finished_at=utc_now())
    from catalog_extension import fingerprint
    if needs_publication(previous,report) or (previous or {}).get('catalog_fingerprint') != fingerprint(universe):
        manifest=publish_snapshot(store,cache,universe,report,previous,watchlist_csv=data.decode('utf-8-sig') if data else None)
    else:
        manifest=previous
        print('Reused verified existing snapshot; no prices or metadata changed.',flush=True)
    missing=[]
    for ticker in ('AAPL','SPY'):
        history,_=cache.history(ticker)
        if history is None: missing.append(ticker+':history')
        for kind in ('info','dividends'):
            value,_=cache.get(kind+':'+ticker,request_remote=False)
            if value is None: missing.append(ticker+':'+kind)
    print('DEPLOYMENT_SEED',json.dumps({'generation':manifest['generation'],'coverage':manifest['coverage'],'remaining':manifest['bootstrap_pending'],'report':report,'missing_required':missing},ensure_ascii=False),flush=True)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as f:
            f.write('### Deployment data seed\n\n'+json.dumps(manifest['coverage'])+'\n\nPriority report: '+json.dumps(report,ensure_ascii=False)+'\n\nMissing required data: '+json.dumps(missing)+'\n')
    if missing: raise RuntimeError('Required initial data missing: '+', '.join(missing))


if __name__=='__main__': main()
