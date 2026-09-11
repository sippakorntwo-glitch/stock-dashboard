"""Owner-requested, bounded catalog migration. No price synthesis or rate-limit evasion."""
from __future__ import annotations
import json, os, time
from pathlib import Path
import pandas as pd
import dashboard_runtime as app
import update_data as job
from data_sync import ObjectStore, config_from, read_manifest, restore_checkpoint, utc_now

PRIORITY = ('QQQI','SPYI','JEPQ','JEPI','SCHD','DIVO','GPIX','GPIQ','AAPL','MSFT','SPY','QQQ','MDY','DIA','GLD','OIH')

def main():
    config=config_from()
    if (os.environ.get('GITHUB_ACTIONS')!='true' or not config or config.get('DASHBOARD_DATA_VISIBILITY')!='public'
        or config.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')):
        raise RuntimeError('Only the authorized public repository Actions collector may publish')
    store=ObjectStore(config,writable=True);previous=read_manifest(store)
    if not previous:raise RuntimeError('Verified previous snapshot required')
    path=Path(os.environ.get('DASHBOARD_CACHE_FILE','work/complete.sqlite3'))
    restore_checkpoint(store,previous,path)
    cache=app.DashboardCache(path)
    if cache.error:raise RuntimeError(cache.error)
    data=app.WATCHLIST_FILE.read_bytes()
    original=app.parse_watchlist(data);universe=app.select_universe(original)
    report={'started_at':utc_now(),'universe':len(universe),'source_generation':previous['generation'],'recomputed':0,'rounds':[]}
    def publish(stage):
        nonlocal previous
        previous=job.publish_snapshot(store,cache,universe,{**report,'stage':stage},previous,watchlist_csv=data.decode('utf-8-sig'))
        report.update(coverage=previous['coverage'],quality_counts=previous['quality_counts'],bootstrap_pending=previous['bootstrap_pending'],generation=previous['generation'],published_at=previous['published_at'])
        from verification_report import publish_report
        publish_report('catalog',report)
    rows=cache.quotes()
    for ticker in universe:
        old=rows.get(ticker,{})
        if app.number(old.get('Metric_Calc_Version'))==app.METRIC_VERSION:continue
        history,meta=cache.history(ticker)
        if history is None:continue
        stamp=meta.get('fetched_at') or old.get('Data_Time')
        if not stamp:continue
        # A calculation-only migration must not promote a previously partial bar.
        history=app.completed_daily_history(history,now=stamp)
        if history.empty:continue
        row=app.scan_snapshot_row(ticker,history,stamp)
        row['History_Years_Loaded']=meta.get('years',old.get('History_Years_Loaded',0))
        cache.save_quotes(pd.DataFrame([row]));report['recomputed']+=1
    selected=tuple(t for t in PRIORITY if t in universe)
    report['rounds'].append(job.collect(cache,selected,'bootstrap',price_minutes=5,metadata_minutes=5,metadata_limit=64))
    publish('priority')
    report['rounds'].append(job.collect(cache,universe,'bootstrap',price_minutes=40,metadata_minutes=0,metadata_limit=0))
    publish('prices')
    for iteration in range(3):
        result=job.collect(cache,universe,'bootstrap',price_minutes=0,metadata_minutes=28,metadata_limit=4000)
        report['rounds'].append(result)
        publish('profiles-'+str(iteration+1))
        if result.get('rate_limited') or result.get('metadata_jobs_attempted',0)==0:break
    rows=cache.quotes();report['finished_at']=utc_now()
    report['priority']={t:{'price_asof':rows.get(t,{}).get('Price_AsOf'),'price':rows.get(t,{}).get('Close'),
        'metric_version':rows.get(t,{}).get('Metric_Calc_Version'),
        'info':cache.get('info:'+t,request_remote=False)[0] is not None,
        'dividends':cache.get('dividends:'+t,request_remote=False)[0] is not None,
        'observations':isinstance(rows.get(t,{}).get('Return_Observations'),dict)} for t in selected}
    publish('finished')
    if any(not r['price'] or not r['info'] or not r['dividends'] for r in report['priority'].values()):
        raise RuntimeError('A requested priority asset still lacks real data; see catalog report')
    print(json.dumps(report,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__':main()
