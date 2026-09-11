"""Post-repair, read-only verification of residual gaps and asset identities."""
import gzip
import json
from collections import defaultdict
from pathlib import Path
from data_sync import ObjectStore,read_manifest,read_checked,shard_number

store=ObjectStore({'backend':'github','DASHBOARD_DATA_REPO':'sippakorntwo-glitch/stock-dashboard','DASHBOARD_DATA_VISIBILITY':'public','DASHBOARD_DATA_BRANCH':'dashboard-data'})
m=read_manifest(store)
s=json.loads(gzip.decompress(read_checked(store,m['summary'])))
q=s['quality']
groups=defaultdict(set)
for t,r in q['symbols'].items():
    if r['industry_state']!='available':groups[str(shard_number(t))].add(t)
rows=[]
for slot,tickers in sorted(groups.items()):
    records=gzip.decompress(read_checked(store,m['details'][slot]))
    for line in records.splitlines():
        t,key,value,meta=json.loads(line)
        if t not in tickers or key!='info:'+t:continue
        rows.append({'ticker':t,'catalog_type':q['symbols'][t]['asset_type'],
                     'provider_symbol':value.get('symbol'),'provider_type':value.get('quoteType'),
                     'name':value.get('longName') or value.get('shortName'),
                     'industry':value.get('industry'),'industryDisp':value.get('industryDisp'),
                     'sector':value.get('sector'),'category':value.get('category'),
                     'fundFamily':value.get('fundFamily'),'totalAssets':value.get('totalAssets'),
                     'info_fetched_at':meta.get('fetched_at')})
invalid_stops=[]
for t,meta in q['symbols'].items():
    if 'Suggested_Stop' not in meta.get('missing_metrics',{}):continue
    r=s.get('quotes',{}).get(t,{})
    if isinstance(r.get('Close'),(int,float)) and isinstance(r.get('ATR'),(int,float)):
        if r['Close']-2*r['ATR']<=0:invalid_stops.append(t)
result={'generation':m['generation'],'counts':q['counts'],'remaining_classifications':sorted(rows,key=lambda r:r['ticker']),
        'price_gap_reasons':{k:v for k,v in q['columns'].items() if k.startswith('price.') and any(n for state,n in v.items() if state!='available')},
        'nonpositive_suggested_stop_symbols':invalid_stops}
Path('work').mkdir(exist_ok=True)
Path('work/remaining_data.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('POST_REPAIR_GAPS:',json.dumps(result,ensure_ascii=False),flush=True)
