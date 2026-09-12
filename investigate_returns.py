"""Read-only reconciliation: saved snapshot versus newly fetched Yahoo Close/Adj Close.
No recommendation, no fabricated endpoint and no production data writes.
"""
from __future__ import annotations
import gzip, json, math, tempfile, re
from pathlib import Path
from io import StringIO
from datetime import datetime, timezone
import pandas as pd
import requests
import yfinance as yf
import dashboard_runtime as a
from data_sync import ObjectStore,read_manifest,read_checked,restore_checkpoint
from return_periods import RETURN_SPECS,period_observation,daily_closes

URLS=['https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt','https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt']
SAMPLE=['MDY','DIA','OIH','GLD','MMTM','IWM','MGC','GRIN','BBH','DGT','LGLV','DXJ','MGV','SPY','QQQ','QQQI']


def official_etfs():
    rows={};sources=[]
    for url in URLS:
        response=requests.get(url,timeout=45);response.raise_for_status()
        text=response.text
        frame=pd.read_csv(StringIO(text),sep='|',dtype=str).fillna('')
        if not {'ETF','Test Issue','Security Name'}.issubset(frame.columns):raise ValueError('Unexpected directory schema')
        frame=frame.loc[frame['ETF'].eq('Y') & frame['Test Issue'].eq('N')]
        symbol_col='Symbol' if 'Symbol' in frame else 'ACT Symbol'
        for _,r in frame.iterrows():
            t=str(r[symbol_col]).strip()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}',t):continue
            rows[t]={'name':r['Security Name'],'source':url,'exchange_code':r.get('Exchange',r.get('Market Category',''))}
        sources.append({'url':url,'etag':response.headers.get('ETag'),'footer':text.splitlines()[-1][:140]})
    if len(rows)<700 or 'QQQI' not in rows:raise ValueError('Directory incomplete or QQQI not found')
    return {'fetched_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'funds':dict(sorted(rows.items()))}


def main():
    Path('work').mkdir(exist_ok=True)
    cfg={'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    store=ObjectStore(cfg);m=read_manifest(store)
    summary=json.loads(gzip.decompress(read_checked(store,m['summary'])))
    result={'audited_at':datetime.now(timezone.utc).isoformat(),'version':a.APP_VERSION,'generation':m['generation'],'catalog':{'snapshot':len(summary['universe']),'etf_pool':len(a.ETF_POOL),'etf_names':len(a.ETF_NAMES),'etf_limit':a.ETF_LIMIT,'QQQI_in_pool':'QQQI' in a.ETF_NAMES,'QQQI_in_snapshot':'QQQI' in summary['universe'],'source':str(a.CATALOG_SOURCE)},'samples':[]}
    directory=official_etfs();result['official_directory']={'etfs':len(directory['funds']),'new_to_snapshot':len(set(directory['funds'])-set(summary['universe'])),'QQQI':directory['funds']['QQQI'],'sources':directory['sources']}
    Path('work/official_etfs.json').write_text(json.dumps(directory,ensure_ascii=False,indent=2),encoding='utf-8')
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'audit.sqlite3';restore_checkpoint(store,m,path);cache=a.DashboardCache(path)
        new=yf.download(SAMPLE,period='6y',interval='1d',auto_adjust=False,actions=True,group_by='ticker',threads=False,progress=False,timeout=30)
        for t in SAMPLE:
            entry={'ticker':t};row=summary.get('quotes',{}).get(t,{})
            h,_=cache.history(t);entry['saved_asof']=row.get('Price_AsOf');entry['saved_close']=row.get('Close')
            try:
                f=new[t].dropna(subset=['Close']).copy() if isinstance(new.columns,pd.MultiIndex) else new.copy()
                f.index=pd.DatetimeIndex(f.index).tz_localize(None).normalize()
                if f.empty:raise ValueError('Empty response')
                end=pd.Timestamp(entry['saved_asof']) if entry['saved_asof'] else f.index[-1]
                f=f.loc[f.index<=end];entry['provider_asof']=str(f.index[-1].date())
                entry['close']=float(f.Close.iloc[-1]);entry['adjusted_close']=float(f['Adj Close'].iloc[-1])
                observations=[]
                for field,label,sessions,months in RETURN_SPECS:
                    prices=f.Close;adj=f['Adj Close']
                    old=period_observation(daily_closes(h.loc[h.index.tz_localize(None).normalize()<=end]),sessions=sessions,months=months) if h is not None else {}
                    obs=period_observation(adj,sessions=sessions,months=months)
                    pobs=period_observation(prices,sessions=sessions,months=months)
                    stored=row.get(field);v=obs.get('value')
                    independent=None
                    if obs.get('start') and obs.get('end') and float(adj.loc[obs['start']])>0:
                        independent=(float(adj.loc[obs['end']])/float(adj.loc[obs['start']])-1)*100
                    item={'field':field,'label':label,'stored':stored,'saved_recalculated':old.get('value'),'fresh_adjusted':v,'independent_adjusted':independent,'fresh_price':pobs['value'],'start':obs.get('start'),'end':obs.get('end'),'start_adjusted':obs.get('start_price'),'end_adjusted':obs.get('end_price'),'difference_pp':float(stored-v) if stored is not None and v is not None else None}
                    if months and months>=12 and v is not None:item['annualized']=((1+v/100)**(12/months)-1)*100
                    observations.append(item)
                entry['periods']=observations
                # Exact comparable date for issuer month-end performance pages.
                previous_month_end=end.replace(day=1)-pd.Timedelta(days=1)
                month_end=f.loc[f.index<=previous_month_end,'Adj Close']
                entry['previous_month_end']=str(month_end.index[-1].date()) if len(month_end) else None
                entry['month_end_returns']={label:period_observation(month_end,sessions=sessions,months=months) for _,label,sessions,months in RETURN_SPECS if months}
            except Exception as exc:entry['error']=type(exc).__name__+': '+str(exc)[:200]
            result['samples'].append(entry)
    Path('work/return_reconciliation.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print('RETURN_RECONCILIATION:',json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
    # Relevant source anchors for the following narrowly-scoped patch.
    source=Path('dashboard_core.py').read_text()
    for pattern in ['ETF_LIMIT =','ETF_POOL =','ETF_NAMES =','def select_universe','def completed_daily_history']:
        lines=source.splitlines();indices=[i for i,l in enumerate(lines) if pattern in l]
        for i in indices[:1]:print('CORE_ANCHOR:',pattern,i+1,'\n'+'\n'.join(lines[max(0,i-2):i+20]),flush=True)

if __name__=='__main__':main()
