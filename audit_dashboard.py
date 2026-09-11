"""Read-only coverage audit against the checksum-verified public snapshot.
No market requests, generated prices, or writes to the data branches.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import tempfile
import zlib
import pandas as pd
import dashboard_runtime as a
from data_sync import ObjectStore, config_from, read_manifest, read_checked, restore_checkpoint

QUOTE_FIELDS = ['Close','Return_1D','Return_1M','Return_3M','Return_6M','Historical_Return','Return_2Y','Return_3Y','EMA20','EMA50','SMA200','RSI_14','MACD','MACD_Signal','Vol_Ratio','ATR','ATR_Pct','Dollar_Volume_20D','Volatility_20D','Drawdown_52W','Suggested_Stop']
STOCK_FIELDS = ['currency','industry','sector','country','marketCap','forwardPE','trailingPE','priceToBook','enterpriseToEbitda','revenueGrowth','earningsGrowth','profitMargins','operatingMargins','returnOnEquity','returnOnAssets','operatingCashflow','freeCashflow','totalCash','totalDebt','targetMeanPrice','numberOfAnalystOpinions','regularMarketPrice','regularMarketTime','beta','bid','ask','earningsTimestampStart']
ETF_FIELDS = ['currency','category','fundFamily','totalAssets','navPrice','beta3Year','regularMarketPrice','regularMarketTime']


def usable(value):
    if value is None:return False
    if isinstance(value,str):return value.strip().lower() not in ('','none','null','nan','n/a','—')
    return a.number(value) is not None


def inspect_cache(cache, universe, manifest=None, source_summary=None):
    universe=tuple(dict.fromkeys(universe));quotes=cache.quotes();cls=cache.classifications()
    with cache.connect() as db:
        objects={}
        for key,body,meta in db.execute('SELECT key,body,metadata FROM objects'):
            if key.startswith(('info:','dividends:','history:1d:','attempt:')):
                objects[key]=(json.loads(zlib.decompress(body)),json.loads(meta))
    counts=Counter(universe=len(universe)); q_missing=Counter(); info_missing={'Common Stock':Counter(),'ETF':Counter()}
    samples=[]; bad_history=[]; issues=[]
    for t in universe:
        row=quotes.get(t,{});typ='ETF' if t in a.ETF_NAMES else 'Common Stock'
        info,imeta=objects.get('info:'+t,({},{}));info=info or {}
        hist,hmeta=objects.get('history:1d:'+t,(None,{}))
        div,dmeta=objects.get('dividends:'+t,(None,{}))
        n=0;start=end=None
        if hist is not None:
            try:
                data=json.loads(hist) if isinstance(hist,str) else hist
                n=len(data['data']);start=data['index'][0];end=data['index'][-1]
                counts['daily_histories']+=1
                counts['history_ge_200']+=int(n>=200)
            except (ValueError,KeyError,TypeError,IndexError):bad_history.append(t)
        counts['prices']+=int(usable(row.get('Close')))
        counts['information_objects']+=bool(info)
        counts['industry']+=int(usable(cls.get(t,{}).get('Industry')))
        raw_industry=info.get('category') if typ=='ETF' else info.get('industry')
        counts['classification_recoverable_from_info']+=int(usable(raw_industry) and not usable(cls.get(t,{}).get('Industry')))
        counts['dividend_objects']+=div is not None
        counts['dividend_empty_success']+=bool(isinstance(div,dict) and div.get('records')==[] and not div.get('error'))
        counts['stock' if typ=='Common Stock' else 'etf']+=1
        for key in QUOTE_FIELDS:
            if not usable(row.get(key)):q_missing[key]+=1
        for key in STOCK_FIELDS if typ=='Common Stock' else ETF_FIELDS:
            if not usable(info.get(key)):info_missing[typ][key]+=1
        reasons=[]
        if not row:reasons.append('summary_missing')
        if hist is None:reasons.append('history_missing')
        if not info:reasons.append('info_missing')
        if not usable(cls.get(t,{}).get('Industry')):reasons.append('classification_missing')
        if div is None:reasons.append('dividends_unchecked')
        if reasons:issues.append({'Ticker':t,'Asset_Type':typ,'Missing':','.join(reasons),'History_Bars':n,'Start':start,'End':end})
        if t in ['AEON','AESP','AAPL','ORCL','SPY','QQQ','AEMD','AAC','MSFT']:
            samples.append({'ticker':t,'type':typ,'summary_date':row.get('Price_AsOf'),'classification':cls.get(t), 'history_bars':n,'history_first':start,'history_last':end,'history_meta':hmeta,'info_keys':len(info),'industry':info.get('industry'),'category':info.get('category'),'info_meta':imeta,'first_trade':info.get('firstTradeDateMilliseconds'),'regularMarketTime':info.get('regularMarketTime'),'dividend_meta':dmeta,'dividend_rows':len((div or {}).get('records',[])), 'attempts':{k:objects.get(f'attempt:{k}:{t}',(None,{})) for k in ['history','info','dividends']}})
    default=set(a.select_universe(pd.DataFrame(columns=['Ticker'])))
    registry=set(universe)
    result={'audited_at':pd.Timestamp.now(tz='UTC').isoformat(),'generation':(manifest or {}).get('generation'),'counts':dict(counts),'quote_missing':dict(q_missing),'information_missing':{k:dict(v) for k,v in info_missing.items()},'bad_history':bad_history,'ranking_universe_only':len(default-registry),'dashboard_universe_only':len(registry-default),'missing_ranking_summary':len(default-set(quotes)),'ranking_only_examples':sorted(default-registry)[:12],'samples':samples}
    if source_summary is not None:
        result['snapshot_summary_members']=len(source_summary.get('universe',[]))
        result['checkpoint_vs_summary_missing']=len(set(source_summary.get('quotes',{}))-set(quotes))
    return result,issues


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='work/audit_before.json');args=parser.parse_args()
    config=config_from() or {'backend':'github','DASHBOARD_DATA_REPO':a.DEFAULT_REPO,'DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'}
    store=ObjectStore(config);manifest=read_manifest(store)
    if not manifest:raise RuntimeError('No published snapshot')
    summary=json.loads(gzip.decompress(read_checked(store,manifest['summary'])))
    universe=summary['universe']
    with tempfile.TemporaryDirectory(prefix='audit-dashboard-') as tmp:
        path=Path(tmp)/'source.sqlite3';restore_checkpoint(store,manifest,path)
        result,issues=inspect_cache(a.DashboardCache(path),universe,manifest,summary)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    pd.DataFrame(issues).to_csv(out.with_suffix('.csv'),index=False,encoding='utf-8-sig')
    print('DASHBOARD_DATA_AUDIT:',json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
