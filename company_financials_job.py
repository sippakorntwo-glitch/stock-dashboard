"""Incremental financial-statement collection and every-security metric audit.

The existing prepared-data publication lock serializes this collector with price
jobs. Provider rate limits stop the batch and preserve a persistent retry date.
No request to Yahoo is made by an interactive dashboard page.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import time
import pandas as pd
from company_metrics import audit_profile, metric_observations
from financial_statements import collect, SCHEMA

PRIORITY = ('AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','BRK-B','JPM','ORCL')


def due_symbols(universe, profiles, statements, attempts, etfs, *, now=None, only_missing=False):
    from data_quality import timestamp
    clock = now or datetime.now(timezone.utc).timestamp()
    priority = {ticker:index for index,ticker in enumerate(PRIORITY)}
    result = []
    for ticker in universe:
        info = profiles.get('info:'+ticker, ({},{}))[0] or {}
        if ticker in etfs or info.get('quoteType') == 'ETF' or not info.get('financialCurrency'):
            continue
        value, meta = statements.get('financials:'+ticker, (None,{}))
        if only_missing and value and value.get('schema') == SCHEMA and value.get('observations'):
            continue
        attempt = attempts.get('attempt:financials:'+ticker, ({},{}))[1]
        if timestamp(attempt.get('retry_after')) > clock:
            continue
        stamp = timestamp(meta.get('fetched_at'))
        # Successful observations refresh weekly, independently of price updates.
        refresh_days = 7 if value and meta.get('available') and not value.get('errors') else 1
        if value and value.get('schema') == SCHEMA and clock-stamp < refresh_days*86400:
            continue
        result.append((stamp > 0, priority.get(ticker, 999), stamp, ticker))
    return [entry[-1] for entry in sorted(result)]


def collect_batch(cache, universe, etfs, *, limit=150, minutes=12, only_missing=False):
    from data_quality import read_objects, timestamp
    from data_sync import utc_now
    profiles = read_objects(cache, ('info:',))
    statements = read_objects(cache, ('financials:',))
    attempts = read_objects(cache, ('attempt:financials:',))
    queue = due_symbols(universe, profiles, statements, attempts, etfs, only_missing=only_missing)
    report = {'due_before':len(queue), 'attempted':0, 'updated':0, 'not_reported':0,
              'failed':0, 'errors':[], 'symbols_updated':[]}
    report['only_missing'] = only_missing
    circuit, _ = cache.get('external:financials-circuit', request_remote=False)
    if isinstance(circuit,dict) and timestamp(circuit.get('retry_after')) > time.time():
        report.update(cooldown_until=circuit['retry_after'], remaining_due=len(queue))
        return report
    deadline = time.monotonic()+minutes*60
    # yfinance otherwise swallows statement HTTP failures as empty frames. This
    # setting is confined to the separate collector process, never the web app.
    import yfinance as yf
    yf.config.debug.hide_exceptions = False
    for ticker in queue[:limit]:
        if time.monotonic() >= deadline:
            break
        info = profiles['info:'+ticker][0]
        report['attempted'] += 1
        stamp = utc_now()
        try:
            value = collect(ticker, info)
            has_records = any(value.get(period, {}).get(kind) for period in ('annual','quarterly') for kind in ('income','balance','cashflow'))
            previous = statements.get('financials:'+ticker,(None,{}))[0]
            # A failed/empty refresh never replaces an already populated statement.
            if (has_records and not value['errors']) or not previous:
                cache.put('financials:'+ticker, value, {'fetched_at':stamp, 'schema':SCHEMA,
                          'available':has_records, 'source':'Yahoo Finance financial statements'})
                report['updated'] += 1
                report['symbols_updated'].append(ticker)
            elif has_records:
                report.setdefault('partial_preserved',[]).append(ticker)
            if not has_records:
                report['not_reported'] += 1
            retry = (datetime.now(timezone.utc)+timedelta(days=7 if has_records and not value['errors'] else 1)).isoformat()
            cache.put('attempt:financials:'+ticker, {}, {'fetched_at':stamp,'success':has_records,'retry_after':retry})
        except Exception as exc:
            report['failed'] += 1
            limited = any(s in str(exc).lower() for s in ('429','rate limit','too many'))
            retry = (datetime.now(timezone.utc)+timedelta(hours=24 if limited else 6)).isoformat()
            cache.put('attempt:financials:'+ticker, {}, {'fetched_at':stamp,'success':False,'retry_after':retry,'error':type(exc).__name__})
            report['errors'].append({'ticker':ticker,'error':type(exc).__name__,'rate_limited':limited})
            if limited:
                cache.put('external:financials-circuit', {'retry_after':retry}, {'fetched_at':stamp})
                report['cooldown_until'] = retry
                break
        time.sleep(.6)
        if report['attempted'] % 25 == 0:
            print(json.dumps({'financials_progress':report['attempted'], 'updated':report['updated'],
                              'failed':report['failed'], 'due_before':len(queue)}), flush=True)
    report['remaining_due'] = max(0,len(queue)-report['attempted'])
    return report


def audit_all(cache, universe, etfs):
    from data_quality import read_objects
    profiles=read_objects(cache,('info:',));financials=read_objects(cache,('financials:',))
    attempts=read_objects(cache,('attempt:financials:',))
    counts=Counter();columns=defaultdict(Counter);rows=[];examples={}
    for ticker in universe:
        info=profiles.get('info:'+ticker,({},{}))[0] or {}
        bundle=financials.get('financials:'+ticker,(None,{}))[0]
        etf=ticker in etfs or info.get('quoteType')=='ETF'
        states=audit_profile(ticker,info,bundle,is_etf=etf)
        counts['securities']+=1;counts['funds' if etf else 'companies']+=1
        counts['statements_available']+=int(bool(bundle and bundle.get('observations')))
        counts['companies_without_financial_currency']+=int(not etf and not info.get('financialCurrency'))
        missing=[key for key,state in states.items() if state in ('pending','not_reported','missing_inputs')]
        invalid=[key for key,state in states.items() if state=='invalid']
        counts['with_missing_applicable_metrics']+=bool(missing)
        counts['with_invalid_source_metrics']+=bool(invalid)
        for key,state in states.items():columns[key][state]+=1
        attempt=attempts.get('attempt:financials:'+ticker,({},{}))[1]
        collection_status=('Not applicable' if etf else 'Statements available' if bundle and bundle.get('observations')
                           else 'Missing financial currency' if not info.get('financialCurrency')
                           else 'Attempted; no usable observations' if attempt else 'Not yet attempted')
        rows.append({'Ticker':ticker,'Asset Type':'ETF / ETP' if etf else 'Company',
                     'Financial Currency':info.get('financialCurrency'), 'Collection Status':collection_status,
                     'Collection Retry After':attempt.get('retry_after'),
                     'Statements Fetched':(bundle or {}).get('fetched_at'),
                     'Missing Applicable Metrics':'; '.join(missing),'Invalid Source Metrics':'; '.join(invalid),
                     'Not Meaningful':'; '.join(k for k,s in states.items() if s=='not_meaningful'),
                     'Not Applicable':'; '.join(k for k,s in states.items() if s=='not_applicable')})
        if ticker in (*PRIORITY,'AAAU','SPY','QQQI'):
            values=metric_observations(ticker,info,bundle,is_etf=etf)
            examples[ticker]={k:values[k] for k in ('debtToEquity','returnOnEquity','roic','grossProfit','ebit','netIncome','freeCashflow')}
    return {'counts':dict(counts),'field_counts':{k:dict(v) for k,v in columns.items()},
            'examples':examples,'data_complete':not counts['with_missing_applicable_metrics'] and not counts['with_invalid_source_metrics']},rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--audit-only',action='store_true')
    parser.add_argument('--backfill',action='store_true',help='Only collect missing statements; do not republish a no-op batch')
    parser.add_argument('--limit',type=int,default=150)
    parser.add_argument('--minutes',type=float,default=12)
    args=parser.parse_args()
    import dashboard_runtime as a
    from data_sync import ObjectStore, config_from, read_manifest, read_checked, restore_checkpoint, utc_now
    from data_quality import checked_universe
    from update_data import publish_snapshot
    config=config_from() or {'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,
                             'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    if args.publish and (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REF')!='refs/heads/main'
                         or config.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')
                         or config.get('DASHBOARD_DATA_VISIBILITY')!='public'):
        raise RuntimeError('Only this repository main-branch collector may publish financial statements')
    store=ObjectStore(config,writable=args.publish);previous=read_manifest(store)
    if not previous:raise RuntimeError('No verified prepared snapshot')
    summary=json.loads(gzip.decompress(read_checked(store,previous['summary'])))
    universe=checked_universe(summary);etfs=set(a.ETF_NAMES)
    path=Path('work/company-financials.sqlite3');path.parent.mkdir(exist_ok=True)
    restore_checkpoint(store,previous,path);cache=a.DashboardCache(path)
    if cache.error:raise RuntimeError('Cannot persist financial observations')
    report={'started_at':utc_now(),'source_generation':previous['generation'],
            'scope':'Every catalog member; source validation, period alignment and formula audit. Not external verification of every company filing.'}
    report['before'],_=audit_all(cache,universe,etfs)
    report['collection']={} if args.audit_only else collect_batch(cache,universe,etfs,limit=max(0,args.limit),minutes=max(0,args.minutes),only_missing=args.backfill)
    report['after'],rows=audit_all(cache,universe,etfs)
    pd.DataFrame(rows).to_csv('work/company-financials-all-securities.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([{'Metric':k,**v} for k,v in report['after']['field_counts'].items()]).fillna(0).to_csv('work/company-financials-all-metrics.csv',index=False)
    if args.publish and (not args.backfill or report['collection'].get('attempted',0)>0):
        if read_manifest(store)['generation']!=previous['generation']:
            raise RuntimeError('Prepared snapshot advanced; refusing to overwrite another collector')
        manifest=publish_snapshot(store,cache,universe,{'task':'company financial statements',**report['collection']},previous,watchlist_csv=summary.get('watchlist_csv'))
        report.update(generation=manifest['generation'],coverage=manifest['coverage'])
    else:
        report.update(generation=previous['generation'],coverage=previous['coverage'],snapshot_unchanged=True)
    report.update(finished_at=utc_now(),result='audit_completed',data_complete=report['after']['data_complete'])
    Path('work/company-financials-report.json').write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2))
    if args.publish:
        from verification_report import publish_report
        publish_report('company-fundamentals-v28',report)
    print(json.dumps({'result':report['result'],'data_complete':report['data_complete'],
                      'collection':report['collection'],'counts':report['after']['counts']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
