"""Owner-authorized financial enrichment and complete catalog review.

One official SEC bulk download rather than thousands of API requests. Runs only
in Actions under the existing publication lock. No requests from the public UI.
Unreported/custom-taxonomy figures remain missing, never manufactured.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from zipfile import ZipFile
import zlib
import requests
from financial_statements import parse_statements,METHOD
from company_research import build_review
from company_metrics import METRICS

BULK_URL='https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip'
MAX_ARCHIVE_BYTES=4*1024**3
MAX_COMPANY_BYTES=20_000_000


def download_bulk(path,user_agent):
    if '\n' in user_agent or '\r' in user_agent:raise ValueError('Invalid declared SEC contact')
    start=time.monotonic();size=0;digest=hashlib.sha256()
    with requests.Session() as session:
        session.trust_env=False
        with session.get(BULK_URL,headers={'User-Agent':user_agent,'Accept':'application/zip'},
                         timeout=(15,90),stream=True,allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('Unexpected bulk redirect/response')
            with path.open('wb') as output:
                for block in response.iter_content(1024*1024):
                    size+=len(block)
                    if size>MAX_ARCHIVE_BYTES or time.monotonic()-start>900:raise ValueError('SEC bulk size/time budget exceeded')
                    output.write(block);digest.update(block)
    return {'url':BULK_URL,'received_at':datetime.now(timezone.utc).isoformat(),'bytes':size,'sha256':digest.hexdigest()}


def enrich_bulk(cache,universe,etfs,profiles):
    from sec_reference import SecClient,ticker_index,INDEX_URL,INDEX_TTL
    from data_quality import timestamp
    from data_sync import utc_now
    report={'available':False,'mapped_companies':0,'documents_checked':0,'statements_loaded':0,'missing_from_archive':[],
            'empty_standard_statements':[],'errors':[]}
    circuit,_=cache.get('external:sec-circuit',request_remote=False)
    if isinstance(circuit,dict) and timestamp(circuit.get('next_attempt_after'))>time.time():
        report['error']='SEC persistent cooldown still active';return report
    signature=hashlib.sha256(chr(10).join(sorted(universe)).encode()).hexdigest()
    previous,pmeta=cache.get('external:financial-bulk-success',request_remote=False)
    if (isinstance(previous,dict) and previous.get('method')==METHOD
            and previous.get('catalog_signature')==signature and time.time()-timestamp(pmeta.get('fetched_at'))<20*3600):
        return {**previous['report'],'reused_verified_archive':True}
    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)
    client=SecClient(max_requests=1)
    try:
        if not raw or time.time()-timestamp(meta.get('fetched_at'))>INDEX_TTL:
            raw=client.get(INDEX_URL);ticker_index(raw)
            cache.put('external:sec-ticker-map',raw,{'fetched_at':utc_now(),'source_url':INDEX_URL})
        index=ticker_index(raw)
        mapped={t:index[t] for t in universe if t not in etfs and t in index}
        report['mapped_companies']=len(mapped)
        if not mapped:raise ValueError('No verified company-to-CIK mappings')
        with tempfile.TemporaryDirectory(prefix='official-financials-') as tmp:
            path=Path(tmp)/'companyfacts.zip'
            report['archive']=download_bulk(path,client.user_agent)
            now=utc_now()
            with ZipFile(path) as archive:
                members={}
                for item in archive.infolist():
                    match=re.fullmatch(r'CIK(\d{10})\.json',item.filename)
                    if match and item.file_size<=MAX_COMPANY_BYTES:members[int(match[1])]=item
                memo={}
                for ticker,mapping in mapped.items():
                    cik=mapping['cik'];member=members.get(cik)
                    if member is None:report['missing_from_archive'].append(ticker);continue
                    try:
                        info=profiles.get('info:'+ticker,({},{}))[0]
                        info=info if isinstance(info,dict) else {}
                        currency=info.get('financialCurrency')
                        key=(cik,currency)
                        if key not in memo:
                            raw_company=archive.read(member)
                            document=json.loads(raw_company)
                            package=parse_statements(document,cik,as_of=now,currency=currency)
                            memo[key]=(package,hashlib.sha256(raw_company).hexdigest())
                        package,checksum=memo[key]
                        report['documents_checked']+=1
                        if not package['annual']:
                            report['empty_standard_statements'].append(ticker);continue
                        previous,_=cache.get('reference:'+ticker,request_remote=False)
                        previous=previous if isinstance(previous,dict) else {}
                        if previous.get('cik') and int(previous['cik'])!=cik:raise ValueError('Existing reference CIK conflicts')
                        updated={**previous,'cik':cik,'mapping_name':mapping['name'],'mapping_source':INDEX_URL,
                                 'financial_statements':package,'financial_checked_at':now,
                                 'financial_evidence':{'source':BULK_URL,'member':member.filename,'sha256':checksum,'received_at':now}}
                        cache.put('reference:'+ticker,updated,{'fetched_at':now,'source':'SEC EDGAR official bulk financial statements'})
                        report['statements_loaded']+=1
                    except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                        report['errors'].append({'ticker':ticker,'error':type(exc).__name__})
            report['available']=True
            cache.put('external:financial-bulk-success',{'method':METHOD,'catalog_signature':signature,'report':dict(report)},
                      {'fetched_at':now})
    except (requests.RequestException,ValueError,OSError) as exc:
        report['error']=type(exc).__name__+': '+str(exc)[:250]
        status=getattr(getattr(exc,'response',None),'status_code',None)
        if status in (403,429) or client.blocked:
            until=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
            cache.put('external:sec-circuit',{'next_attempt_after':until,'reason':'SEC access denied/rate limit'},{'fetched_at':utc_now()})
            report['cooldown_until']=until
    report['not_mapped']=len([t for t in universe if t not in etfs])-report['mapped_companies']
    return report


def audit_reviews(cache,universe,etfs):
    from data_quality import read_objects
    import csv
    objects=read_objects(cache,('info:','reference:'));states=Counter();fields=defaultdict(Counter)
    totals=Counter(catalog_members=len(universe),company_members=sum(t not in etfs for t in universe))
    examples={};failures=[]
    Path('work').mkdir(exist_ok=True)
    with open('work/company-financial-audit.csv','w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['Ticker','Asset_Type','Fiscal_Period','Available','Not_Applicable','Not_Meaningful','Missing','Invalid','Missing_Metrics','Invalid_Metrics'])
        writer.writeheader()
        for ticker in universe:
            info,meta=objects.get('info:'+ticker,({},{}));info=dict(info) if isinstance(info,dict) else {}
            info.setdefault('_Fetched_At_UTC',meta.get('fetched_at'))
            reference=objects.get('reference:'+ticker,({},{}))[0]
            review=build_review(ticker,info,reference,is_etf=ticker in etfs)
            if len(review['rows'])!=len(METRICS):raise RuntimeError('Metric coverage contract failed')
            from financial_review_validation import validate_review
            validation=validate_review(review)
            totals['arithmetic_values_checked']+=validation['checked_values']
            failures.extend({'ticker':ticker,**error} for error in validation['errors'])
            counts=review['counts'];states.update(counts)
            if ticker not in etfs:
                totals['companies_with_filed_statements']+=bool(review['fiscal_period'])
                totals['companies_with_missing_metrics']+=bool(counts.get('missing'))
                totals['companies_with_invalid_metrics']+=bool(counts.get('invalid'))
            for row in review['rows']:
                fields[row['key']][row['status']]+=1
                if row['status']!='available' and row['value'] is not None:failures.append((ticker,row['key'],'unavailable value is numeric'))
                if row['status']=='available' and (row['value'] is None or not row['formula']):failures.append((ticker,row['key'],'available without provenance'))
            writer.writerow({'Ticker':ticker,'Asset_Type':'ETF/ETP' if ticker in etfs else 'Company','Fiscal_Period':review['fiscal_period'] or '',
                'Available':counts.get('available',0),'Not_Applicable':counts.get('not_applicable',0),'Not_Meaningful':counts.get('not_meaningful',0),
                'Missing':counts.get('missing',0),'Invalid':counts.get('invalid',0),
                'Missing_Metrics':'; '.join(r['metric'] for r in review['rows'] if r['status']=='missing'),
                'Invalid_Metrics':'; '.join(r['metric'] for r in review['rows'] if r['status']=='invalid')})
            if ticker in ('AAPL','MSFT','ORCL','TSLA','AMZN','NVDA','JPM','O','AAAU','QQQI'):examples[ticker]={'counts':review['counts'],'fiscal_period':review['fiscal_period'],'metrics':{r['key']:{k:r[k] for k in ('value','unit','status','basis','grade')} for r in review['rows']}}
    field_report={k:dict(v) for k,v in fields.items()}
    with open('work/company-metric-coverage.csv','w',newline='',encoding='utf-8-sig') as f:
        names=['Metric','Available','Missing','Invalid','Not_Meaningful','Not_Applicable'];writer=csv.DictWriter(f,fieldnames=names);writer.writeheader()
        for spec in METRICS:
            values=field_report[spec.key]
            writer.writerow({'Metric':spec.label,**{label:values.get(label.lower(),0) for label in names[1:]}})
    return {'result':'passed' if not failures else 'failure','method':METHOD,'counts':dict(totals),
            'metric_count':len(METRICS),'cells_reviewed':len(universe)*len(METRICS),'states':dict(states),
            'field_counts':field_report,'validation_errors':failures[:20],'examples':examples,
            'data_complete':not totals['companies_with_missing_metrics'] and not totals['companies_with_invalid_metrics'],
            'scope':'Every member and metric checked for availability, unit/period handling and deterministic validation; not an independent certification of every upstream figure.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--enrich',action='store_true');parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    import dashboard_runtime as a
    from data_sync import ObjectStore,config_from,read_manifest,read_checked,restore_checkpoint,utc_now
    from data_quality import checked_universe,read_objects
    from audit_all_returns import audit
    from verification_report import publish_report
    cfg=config_from()
    if args.publish and (os.environ.get('GITHUB_ACTIONS')!='true' or not cfg or cfg.get('DASHBOARD_DATA_VISIBILITY')!='public' or cfg.get('DASHBOARD_DATA_REPO')!=os.environ.get('GITHUB_REPOSITORY')):
        raise RuntimeError('Only authorized same-repository public Actions may publish')
    cfg=cfg or {'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    store=ObjectStore(cfg,writable=args.publish);manifest=read_manifest(store)
    if not manifest:raise RuntimeError('Verified source snapshot required')
    source=json.loads(gzip.decompress(read_checked(store,manifest['summary'])));universe=checked_universe(source);etfs=set(a.ETF_NAMES)
    Path('work').mkdir(exist_ok=True);path=Path('work/financial-review.sqlite3');restore_checkpoint(store,manifest,path);cache=a.DashboardCache(path)
    if cache.error:raise RuntimeError(cache.error)
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:arithmetic=audit(source,db)
    if arithmetic['error_count']:raise RuntimeError('Existing return audit failed; refusing financial publication')
    report={'started_at':utc_now(),'source_generation':manifest['generation'],'return_audit':arithmetic}
    if args.enrich:report['sec_bulk']=enrich_bulk(cache,universe,etfs,read_objects(cache,('info:',)))
    report.update(audit_reviews(cache,universe,etfs))
    if report['validation_errors']:raise RuntimeError('Financial validation errors must be fixed before publication')
    if args.publish:
        from update_data import publish_snapshot
        if read_manifest(store)['generation']!=manifest['generation']:raise RuntimeError('Data advanced; refusing overwrite')
        updated=publish_snapshot(store,cache,universe,{'task':'full-catalog financial statements','financial_method':METHOD},manifest,watchlist_csv=source.get('watchlist_csv'))
        report['published_generation']=updated['generation'];report['published_at']=updated['published_at']
    report['finished_at']=utc_now()
    publish_report('v28-financial-audit' if args.enrich else 'v28-financial-recheck',report)
    print(json.dumps({k:v for k,v in report.items() if k!='examples'},ensure_ascii=False,allow_nan=False),flush=True)

if __name__=='__main__':main()
