"""Small audit reports on a non-deploying branch; token stays inside Actions."""
from __future__ import annotations
import base64,json,os,re,time
from datetime import datetime,timezone
from pathlib import Path
import requests

def publish_report(name,value):
    if not re.fullmatch(r'[a-z0-9_-]{1,60}',name):raise ValueError('Invalid report name')
    repo=os.environ.get('GITHUB_REPOSITORY','')
    if os.environ.get('GITHUB_ACTIONS')!='true' or repo!='sippakorntwo-glitch/stock-dashboard':
        raise RuntimeError('Reports may only be written by this repository Actions')
    token=os.environ.get('DASHBOARD_GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if not token:raise RuntimeError('Actions token required for report publication')
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'run_id':os.environ.get('GITHUB_RUN_ID'),
            'source_sha':os.environ.get('GITHUB_SHA'),**value}
    raw=json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2,default=str).encode()
    if len(raw)>300000:raise ValueError('Report exceeds bounded audit size')
    branch='verify/v22-results';url=f'https://api.github.com/repos/{repo}/contents/reports/{name}.json'
    with requests.Session() as s:
        s.trust_env=False;s.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
        for attempt in range(3):
            old=s.get(url,params={'ref':branch},timeout=30)
            if old.status_code not in (200,404):old.raise_for_status()
            body={'branch':branch,'message':'Record '+name+' verification','content':base64.b64encode(raw).decode()}
            if old.status_code==200:body['sha']=old.json()['sha']
            response=s.put(url,json=body,timeout=45)
            if response.status_code in (409,422) and attempt<2:time.sleep(2);continue
            response.raise_for_status();break
    Path('work').mkdir(exist_ok=True)
    Path('work/'+name+'-report.json').write_bytes(raw)
