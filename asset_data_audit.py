"""Whole-catalog semantic/arithmetic audit plus bounded independent references.

The original observations remain intact. SEC annual facts are stored separately;
only a missing company industry may gain a clearly labeled SEC SIC alternative.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import gzip
import json
import os
from pathlib import Path
import sqlite3
import zlib
import pandas as pd
from asset_semantics import field_state,kind_for,REVIEWED_INSTRUMENTS
from sec_reference import SecClient,INDEX_URL,INDEX_TTL,REFERENCE_TTL,ticker_index,collect_reference,normalized


def profile_audit(cache,universe,etfs):
    from data_quality import STOCK_FIELDS,ETF_FIELDS,read_objects,present
    profiles=read_objects(cache,('info:',));classes=cache.classifications();quotes=cache.quotes()
    fields=list(dict.fromkeys([*STOCK_FIELDS,*ETF_FIELDS,'forwardEps','trailingEps','annualReportExpenseRatio']))
    totals=Counter();by_field=defaultdict(Counter);rows=[];examples={}
    for ticker in universe:
        info,meta=profiles.get('info:'+ticker,({},{}));info=info if isinstance(info,dict) else {}
        etf=ticker in etfs;states={f:field_state(ticker,info,f,is_etf=etf) for f in fields}
        kind=kind_for(ticker,info,etf);totals[kind]+=1
        for field,state in states.items():by_field[('fund.' if etf else 'stock.')+field][state]+=1
        missing=[f for f,s in states.items() if s in ('pending','not_reported')]
        invalid=[f for f,s in states.items() if s=='invalid']
        totals['with_missing_applicable_fields']+=bool(missing);totals['with_invalid_fields']+=bool(invalid)
        rows.append({'Ticker':ticker,'Asset_Type':'ETF / ETP' if etf else 'Common Stock','Asset_Profile':kind,
            'Price_AsOf':quotes.get(ticker,{}).get('Price_AsOf'),'Profile_Fetched_At':meta.get('fetched_at'),
            'Industry_or_Category':classes.get(ticker,{}).get('Industry'),
            'Missing_Applicable_Fields':'; '.join(missing),'Invalid_Source_Fields':'; '.join(invalid),
            'Not_Meaningful':'; '.join(f for f,s in states.items() if s=='not_meaningful'),
            'Not_Applicable':'; '.join(f for f,s in states.items() if s=='not_applicable')})
        if ticker in ('AAAU','AAPL','MSFT','ORCL','SPY','QQQI','XLCU','GEMQ'):
            examples[ticker]={'asset_profile':kind,'field_states':states,
                'selected_values':{f:info.get(f) for f in ('category','industry','forwardPE','trailingPE','trailingEps','totalAssets','navPrice','beta3Year')},
                'profile_fetched_at':meta.get('fetched_at'),'price_asof':quotes.get(ticker,{}).get('Price_AsOf')}
    return {'catalog_members':len(universe),'counts':dict(totals),'field_counts':{k:dict(v) for k,v in by_field.items()},'examples':examples},rows,profiles


def enrich(cache,universe,etfs,profiles,limit=40):
    from data_quality import timestamp,present
    from data_sync import utc_now
    client=SecClient(max_requests=90)
    report={'mapping_source':INDEX_URL,'mapping_matched':0,'submissions_verified':0,'financial_reports':0,
            'industry_fallbacks':[],'reference_symbols':[],'errors':[],'provider_requests':0}
    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)
    circuit,_=cache.get('external:sec-circuit',request_remote=False)
    if isinstance(circuit,dict) and timestamp(circuit.get('next_attempt_after'))>datetime.now(timezone.utc).timestamp():
        client.blocked=True
        report['cooldown_until']=circuit.get('next_attempt_after')
    try:
        if not raw or datetime.now(timezone.utc).timestamp()-timestamp(meta.get('fetched_at'))>INDEX_TTL:
            raw=client.get(INDEX_URL);ticker_index(raw)
            cache.put('external:sec-ticker-map',raw,{'fetched_at':utc_now(),'source_url':INDEX_URL})
        index=ticker_index(raw)
    except Exception as exc:
        report['errors'].append({'source':'SEC ticker index','error':type(exc).__name__})
        try:index=ticker_index(raw) if raw else {}
        except (ValueError,TypeError):index={}
    references={}
    for ticker in universe:
        old,ometa=cache.get('reference:'+ticker,request_remote=False);old=old if isinstance(old,dict) else {}
        mapped=index.get(normalized(ticker))
        curated=REVIEWED_INSTRUMENTS.get(ticker)
        if mapped:
            report['mapping_matched']+=1
            value={**old,'cik':mapped['cik'],'mapping_name':mapped['name'],'mapping_source':INDEX_URL}
            if old.get('cik') and old['cik']!=mapped['cik']:
                value={k:v for k,v in value.items() if k in ('cik','mapping_name','mapping_source')}
            references[ticker]=value
        elif curated:references[ticker]={**old,'cik':curated['cik'],'reviewed_instrument':curated}
        elif old:references[ticker]=old
    classes=cache.classifications()
    missing_industry=[t for t in universe if t not in etfs and not present(classes.get(t,{}).get('Industry'))]
    missing_accounts=[t for t in universe if t not in etfs and any(not present((profiles.get('info:'+t,({},{}))[0] if isinstance(profiles.get('info:'+t,({},{}))[0],dict) else {}).get(f)) for f in ('operatingCashflow','freeCashflow','totalCash'))]
    candidates=list(dict.fromkeys(['AAAU','AAPL','MSFT','ORCL',*missing_industry,*missing_accounts]))
    candidates=[t for t in candidates if t in references and references[t].get('cik')]
    completed=0
    for ticker in candidates:
        previous=references[ticker]
        if datetime.now(timezone.utc).timestamp()-timestamp(previous.get('checked_at'))<REFERENCE_TTL:continue
        if completed>=limit or client.blocked:break
        completed+=1
        try:
            value=collect_reference(client,ticker,previous['cik'],include_facts=ticker not in etfs)
            value={**previous,**value}
            if ticker in REVIEWED_INSTRUMENTS:value['reviewed_instrument']=REVIEWED_INSTRUMENTS[ticker]
            references[ticker]=value
            report['submissions_verified']+=1;report['financial_reports']+=bool(value.get('facts'))
            report['reference_symbols'].append(ticker)
            description=value.get('sic_description')
            if ticker in missing_industry and description:
                record={'Industry':'SEC SIC: '+description,'Industry_Source':value['submissions_url'],
                        'Industry_Time':value['checked_at'],'Classification_System':'SEC SIC','SIC':value['sic']}
                with cache.connect() as db:
                    old=db.execute('SELECT body FROM classifications WHERE ticker=?',(ticker,)).fetchone()
                    if not old or not present(json.loads(old[0]).get('Industry')):
                        db.execute('INSERT INTO classifications VALUES (?,?) ON CONFLICT(ticker) DO UPDATE SET body=excluded.body',
                                   (ticker,json.dumps(record,ensure_ascii=False)))
                        report['industry_fallbacks'].append(ticker)
        except Exception as exc:
            report['errors'].append({'ticker':ticker,'error':type(exc).__name__})
    stamp=utc_now()
    # Batch the small reference records; do not change original profile fetch times.
    with cache.connect() as db:
        for ticker,value in references.items():
            db.execute('INSERT INTO objects VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body,metadata=excluded.metadata',
                ('reference:'+ticker,zlib.compress(json.dumps(value,ensure_ascii=False,allow_nan=False).encode()),
                 json.dumps({'fetched_at':stamp,'source':'SEC EDGAR / reviewed issuer filings'})))
    if client.blocked and client.calls:
        from datetime import timedelta
        until=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
        cache.put('external:sec-circuit',{'next_attempt_after':until,'reason':'access denied or rate limit'},
                  {'fetched_at':stamp})
        report['cooldown_until']=until
    report.update(provider_requests=client.calls,blocked=client.blocked,reference_records=len(references),http_evidence=client.evidence)
    report['automatic_financials_status']='available' if report['financial_reports'] else 'unavailable; primary observations retained' 
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--enrich',action='store_true');parser.add_argument('--publish',action='store_true');parser.add_argument('--repair',action='store_true')
    args=parser.parse_args()
    import dashboard_runtime as a
    from data_sync import ObjectStore,config_from,read_manifest,read_checked,restore_checkpoint,utc_now
    from audit_all_returns import audit
    from data_quality import checked_universe
    from verification_report import publish_report
    config=config_from() or {'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    if args.publish and (os.environ.get('GITHUB_ACTIONS')!='true' or config.get('DASHBOARD_DATA_VISIBILITY')!='public' or config.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')):
        raise RuntimeError('Only the authorized same-repository Actions collector may publish')
    store=ObjectStore(config,writable=args.publish);previous=read_manifest(store)
    if not previous:raise RuntimeError('No verified snapshot to audit')
    source=json.loads(gzip.decompress(read_checked(store,previous['summary'])))
    universe=checked_universe(source);Path('work').mkdir(exist_ok=True)
    path=Path('work/asset-audit.sqlite3');restore_checkpoint(store,previous,path);cache=a.DashboardCache(path)
    if cache.error:raise RuntimeError(cache.error)
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:arithmetic=audit(source,db)
    if arithmetic['error_count']:raise RuntimeError('Return consistency errors detected; no enrichment published')
    before,rows,profiles=profile_audit(cache,universe,set(a.ETF_NAMES))
    report={'started_at':utc_now(),'source_generation':previous['generation'],'arithmetic':arithmetic,'before':before}
    if args.repair:
        from repair_profile_validation import repair_invalid_profiles
        report['primary_repair']=repair_invalid_profiles(cache,universe,set(a.ETF_NAMES),profiles)
        before_references,rows,profiles=profile_audit(cache,universe,set(a.ETF_NAMES))
    if args.enrich:report['external_sources']=enrich(cache,universe,set(a.ETF_NAMES),profiles)
    # Existing primary labels can be recovered without requesting or fabricating data.
    from data_quality import prepare_cached_metadata
    prepare_cached_metadata(cache,universe,a.ETF_NAMES)
    after,rows,_=profile_audit(cache,universe,set(a.ETF_NAMES));report['after']=after
    pd.DataFrame(rows).to_csv('work/all-securities-data-audit.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([{'Field':f,**states} for f,states in after['field_counts'].items()]).fillna(0).to_csv('work/all-fields-data-audit.csv',index=False)
    if args.publish:
        from update_data import publish_snapshot
        current=read_manifest(store)
        if current['generation']!=previous['generation']:raise RuntimeError('Snapshot advanced; refusing to overwrite another collector')
        manifest=publish_snapshot(store,cache,universe,{'task':'asset-aware audit','secondary_reference_count':report.get('external_sources',{}).get('reference_records',0)},previous,watchlist_csv=source.get('watchlist_csv'))
        report.update(generation=manifest['generation'],coverage=manifest['coverage'],quality_counts=manifest['quality_counts'],published_at=manifest['published_at'])
    else:report.update(generation=previous['generation'],coverage=previous['coverage'],quality_counts=previous.get('quality_counts',{}))
    report.update(finished_at=utc_now(),result='passed',data_complete=not after['counts'].get('with_missing_applicable_fields',0) and not after['counts'].get('with_invalid_fields',0),scope='Every catalog member and return; primary field validation; bounded SEC reference cross-check, not external verification of every provider field')
    publish_report('v25-data-audit',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('before','after')},ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
