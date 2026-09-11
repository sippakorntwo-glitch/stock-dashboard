"""Read-only whole-catalog arithmetic audit, independent of the app calculator.

A passed audit means observed values reconcile, not that unavailable upstream
prices or pre-inception returns have magically become available.
"""
from __future__ import annotations
import argparse
from bisect import bisect_right
import calendar
from datetime import date, datetime, timezone
import gzip
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import zlib

SPECS=(('Return_1D',1,None),('Return_3D',3,None),('Return_7D',7,None),
       ('Return_1M',None,1),('Return_6M',None,6),('Historical_Return',None,12),
       ('Return_3Y',None,36),('Return_5Y',None,60))


def finite(value):
    if isinstance(value,bool):return None
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError,OverflowError):return None


def reference(prices,sessions=None,months=None):
    if not prices:return None
    if sessions:
        if len(prices)<=sessions:return None
        first=prices[-sessions-1]
    else:
        end=prices[-1][0]
        serial=end.year*12+end.month-1-months
        year,month=divmod(serial,12);month+=1
        cutoff=date(year,month,min(end.day,calendar.monthrange(year,month)[1]))
        position=bisect_right([p[0] for p in prices],cutoff)-1
        if position<0 or position>=len(prices)-1:return None
        first=prices[position]
        if (cutoff-first[0]).days>7:return None
    start,end=finite(first[1]),finite(prices[-1][1])
    if start is None or end is None or start<=0 or end<=0:return None
    return (end/start-1)*100


def audit(summary,db):
    universe=summary['universe'];quotes=summary.get('quotes',{})
    report={'catalog_members':len(universe),'priced_members':0,'periods_checked':0,
            'numeric_periods':0,'unavailable_periods':0,'max_difference_pp':0.0,
            'errors':[],'unpriced_tickers':[]}
    for ticker in universe:
        row=quotes.get(ticker,{})
        close=finite(row.get('Close'))
        if close is None or close<=0 or row.get('Data_Status')!='โหลดสำเร็จ':
            report['unpriced_tickers'].append(ticker);continue
        report['priced_members']+=1
        saved=db.execute('SELECT body FROM quotes WHERE ticker=?',(ticker,)).fetchone()
        history=db.execute('SELECT body FROM objects WHERE key=?',('history:1d:'+ticker,)).fetchone()
        if not saved or json.loads(saved[0])!=row or not history:
            report['errors'].append({'ticker':ticker,'error':'summary/checkpoint mismatch'});continue
        body=json.loads(zlib.decompress(history[0]))
        if isinstance(body,str):body=json.loads(body)
        position=body['columns'].index('Close')
        asof=row.get('Price_AsOf')
        prices=sorted((date.fromisoformat(str(d)[:10]),v[position]) for d,v in zip(body['index'],body['data']) if asof and str(d)[:10]<=asof)
        if not prices or str(prices[-1][0])!=asof or not math.isclose(float(prices[-1][1]),close,rel_tol=1e-9,abs_tol=1e-7):
            report['errors'].append({'ticker':ticker,'error':'close/as-of mismatch'});continue
        if row.get('Metric_Calc_Version')!=3:
            report['errors'].append({'ticker':ticker,'error':'old method version'})
        for field,sessions,months in SPECS:
            report['periods_checked']+=1
            calculated=reference(prices,sessions,months);actual=finite(row.get(field))
            if calculated is None and actual is None:
                report['unavailable_periods']+=1;continue
            report['numeric_periods']+=1
            if calculated is None or actual is None:
                report['errors'].append({'ticker':ticker,'field':field,'actual':actual,'expected':calculated});continue
            difference=abs(actual-calculated)
            report['max_difference_pp']=max(report['max_difference_pp'],difference)
            observation=row.get('Return_Observations',{}).get(field,{})
            bad=not math.isclose(actual,calculated,rel_tol=1e-8,abs_tol=1e-7)
            bad=bad or observation.get('end')!=asof or finite(observation.get('value')) is None
            if months in (36,60):
                annual=((1+calculated/100)**(12/months)-1)*100
                expected=finite(observation.get('annualized'))
                bad=bad or expected is None or not math.isclose(expected,annual,rel_tol=1e-8,abs_tol=1e-7)
            if bad:report['errors'].append({'ticker':ticker,'field':field,'actual':actual,'expected':calculated,'audit_record':observation})
    report['error_count']=len(report['errors']);report['errors']=report['errors'][:20]
    report['result']='passed' if not report['error_count'] else 'failure'
    return report


def probe_missing(tickers):
    import yfinance as yf
    import time
    result={}
    for ticker in tickers[:20]:
        try:
            h=yf.Ticker(ticker).history(period='1mo',interval='1d',auto_adjust=False,actions=True,timeout=10,raise_errors=True)
            rows=[]
            for stamp,row in h.tail(3).iterrows():
                rows.append({'date':str(stamp),'values':{field:finite(row.get(field)) for field in ('Open','High','Low','Close','Adj Close','Volume')}})
            result[ticker]={'rows':len(h),'last_observations':rows,'note':'Diagnostic only; no raw close substituted for adjusted returns.'}
        except Exception as exc:
            result[ticker]={'error_type':type(exc).__name__,'message':str(exc)[:300]}
            if any(term in str(exc).lower() for term in ('429','rate limit','too many')):break
        time.sleep(1)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--probe-missing',action='store_true');args=parser.parse_args()
    from data_sync import ObjectStore,config_from,read_manifest,read_checked,restore_checkpoint
    from verification_report import publish_report
    config=config_from() or dict(backend='github',DASHBOARD_DATA_REPO='sippakorntwo-glitch/stock-dashboard',DASHBOARD_DATA_VISIBILITY='public',DASHBOARD_DATA_BRANCH='dashboard-data')
    store=ObjectStore(config);manifest=read_manifest(store)
    if not manifest:raise RuntimeError('Verified snapshot required')
    summary=json.loads(gzip.decompress(read_checked(store,manifest['summary'])))
    with tempfile.TemporaryDirectory(prefix='all-returns-audit-') as directory:
        path=Path(directory)/'source.sqlite3';restore_checkpoint(store,manifest,path)
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:report=audit(summary,db)
    report.update(audited_at=datetime.now(timezone.utc).isoformat(),generation=manifest['generation'],published_at=manifest['published_at'],quality_counts=manifest.get('quality_counts',{}))
    if args.probe_missing:report['missing_price_diagnostic']=probe_missing(report['unpriced_tickers'])
    publish_report('all-returns',report)
    print(json.dumps(report,ensure_ascii=False,allow_nan=False))
    if report['error_count']:raise RuntimeError('Published return mismatches remain; see all-returns report')

if __name__=='__main__':main()
