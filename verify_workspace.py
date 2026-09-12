"""Run the same strict checks on a real local server or the actual production URL."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import requests
import production_smoke
from verification_report import publish_report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--production',action='store_true');args=parser.parse_args()
    Path('work').mkdir(exist_ok=True)
    process=None;output=None;captured=io.StringIO();result={'result':'failure'};error=None
    name='production-browser' if args.production else 'ci-browser'
    try:
        if not args.production:
            from quality_smoke import public_summary
            deadline=time.monotonic()+900
            while True:
                manifest,summary=public_summary()
                if len(summary['universe'])>4900 and summary.get('quotes',{}).get('QQQI',{}).get('Close'):break
                if time.monotonic()>deadline:raise RuntimeError('Expanded priority snapshot not published yet')
                time.sleep(45)
            clean=dict(os.environ)
            for key in ('GH_TOKEN','DASHBOARD_GITHUB_TOKEN','GITHUB_TOKEN'):clean.pop(key,None)
            with open('work/ranking-verification.log','w') as log:
                subprocess.run([sys.executable,'ranking_job.py','--no-quote-refresh','--output','work/verification-top10.json'],check=True,env=clean,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            clean.update(DASHBOARD_CACHE_FILE='work/verification-reader.sqlite3',DASHBOARD_RANKING_FILE='work/verification-top10.json',DASHBOARD_ALLOW_LIVE_UPDATES='false')
            output=open('work/verification-server.log','w')
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','app.py','--server.address=127.0.0.1','--server.port=8501','--server.headless=true'],env=clean,stdout=output,stderr=subprocess.STDOUT)
            for _ in range(60):
                if process.poll() is not None:raise RuntimeError('App server exited before becoming healthy')
                try:
                    if requests.get('http://127.0.0.1:8501/_stcore/health',timeout=2).status_code==200:break
                except requests.RequestException:pass
                time.sleep(1)
            else:raise RuntimeError('App server health deadline exceeded')
            production_smoke.URL='http://127.0.0.1:8501/'
        with contextlib.redirect_stdout(captured):
            production_smoke.run()
        reports=[line.split('BROWSER_SMOKE_REPORT:',1)[1].strip() for line in captured.getvalue().splitlines() if line.startswith('BROWSER_SMOKE_REPORT:')]
        if not reports:raise RuntimeError('The strict verifier produced no completion report')
        result=json.loads(reports[-1])
        if result.get('result')!='passed':raise RuntimeError('Strict browser checks did not pass')
    except Exception:
        error=traceback.format_exc();result.update(result='failure',error=error,diagnostic=captured.getvalue()[-22000:])
    finally:
        if process:
            try:
                status=Path(f'/proc/{process.pid}/status').read_text()
                result['server_memory']={line.split(':')[0]:line.split(':',1)[1].strip() for line in status.splitlines() if line.startswith(('VmRSS:','VmHWM:'))}
            except OSError:pass
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if output:output.close()
        result.update(target=production_smoke.URL,tested_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
        serverlog=Path('work/verification-server.log')
        if serverlog.exists():result['server_log_tail']=serverlog.read_text(errors='replace')[-6000:]
        publish_report(name,result)
        Path('work/browser-output.log').write_text(captured.getvalue(),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,default=str))
    if error:raise RuntimeError('Browser verification failed; see the dated '+name+' report')

if __name__=='__main__':main()
