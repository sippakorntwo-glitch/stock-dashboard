"""Check the actual exported eight-period table against public daily observations.

Uses only the standard library and Playwright, independent of the app's return
calculator. No synthetic data or session-state injection in production checks.
"""
from __future__ import annotations
import calendar
from datetime import date
import gzip
import hashlib
import json
import math
from urllib.parse import urlsplit
from playwright.sync_api import expect
from quality_smoke import public_summary,read_download,fetch_public,REPO

LABELS=['1 Day (%)','3 Days (%)','7 Days (%)','1 Month (%)','6 Months (%)','1 Year (%)','3 Years (%)','5 Years (%)']
SPECS=[('Return_1D',1,None),('Return_3D',3,None),('Return_7D',7,None),('Return_1M',None,1),('Return_6M',None,6),('Historical_Return',None,12),('Return_3Y',None,36),('Return_5Y',None,60)]


def expected_return(rows,sessions,months):
    end=date.fromisoformat(rows[-1][0]);last=rows[-1][1]
    if sessions is not None:
        if len(rows)<=sessions:return None
        first=rows[-sessions-1][1]
    else:
        serial=end.year*12+end.month-1-months;year,month=divmod(serial,12);month+=1
        cutoff=date(year,month,min(end.day,calendar.monthrange(year,month)[1]))
        if date.fromisoformat(rows[0][0])>cutoff:return None
        window=[row for row in rows if date.fromisoformat(row[0])>=cutoff]
        if len(window)<2 or (date.fromisoformat(window[0][0])-cutoff).days>7:return None
        first=window[0][1]
    if first is None or last is None or not math.isfinite(float(first)) or not math.isfinite(float(last)) or first<=0 or last<=0:return None
    return (last/first-1)*100


def verify_return_table(page,app):
    from production_smoke import URL,no_exception
    manifest,summary=public_summary()
    migrated=all(all(field in row for field,_,_ in SPECS) and row.get('Metric_Calc_Version')==2 for row in summary['quotes'].values())
    if not migrated:
        assert urlsplit(URL).hostname in ('localhost','127.0.0.1'),'Production snapshot has not recalculated all return fields'
        return {'awaiting_real_backfill_on_CI_only':True}
    search=app.get_by_role('textbox',name='ค้นหา Ticker / บริษัท / อุตสาหกรรม',exact=True)
    search.fill('');search.press('Enter')
    expect(app.get_by_text('Cumulative Return (%)',exact=False).first).to_be_visible(timeout=60000)
    button=app.get_by_role('button',name='ดาวน์โหลดผลกรองครบทุกแถว',exact=True)
    records=read_download(page,button)
    assert len(records)==len(summary['universe'])==4900
    headers=list(records[0]);assert headers[6:14]==LABELS,headers
    assert not any(label in headers for label in ['Return_2Y','Return_3M','2Y Return (%)','3M (%)'])
    exports={r['Ticker']:r for r in records}
    checks=[];parts={}
    for ticker in ['AAPL','MSFT','SPY','AAC']:
        slot=str(int(hashlib.sha256(ticker.encode()).hexdigest()[:8],16)%128)
        if slot not in parts:
            tag='dashboard-data-'+manifest['generation'].split('/')[1]
            raw=fetch_public(f'https://github.com/{REPO}/releases/download/{tag}/details--{slot}.jsonl.gz')
            assert hashlib.sha256(raw).hexdigest()==manifest['details'][slot]['sha256']
            parts[slot]=[json.loads(line) for line in gzip.decompress(raw).splitlines()]
        item=next(record for record in parts[slot] if record[1]=='history:1d:'+ticker)
        body=json.loads(item[2]);index=body['columns'].index('Close')
        quote=summary['quotes'][ticker];asof=exports[ticker]['Price As Of']
        assert asof==quote['Price_AsOf']
        prices=sorted([(str(d)[:10],v[index]) for d,v in zip(body['index'],body['data']) if str(d)[:10]<=asof])
        verified={}
        for label,(field,sessions,months) in zip(LABELS,SPECS):
            calculated=expected_return(prices,sessions,months);text=exports[ticker][label]
            if calculated is None:
                assert text.strip()=='',(ticker,field,text)
            else:
                actual=float(text)
                assert math.isclose(actual,calculated,rel_tol=1e-8,abs_tol=1e-7),(ticker,field,actual,calculated)
            verified[label]=calculated
        if ticker!='AAC':assert all(v is not None for v in verified.values())
        checks.append({'ticker':ticker,'price_asof':asof,'returns':verified})
    no_exception(app)
    return {'headers':LABELS,'all_filtered_rows':len(records),'source_generation':manifest['generation'],
            'independent_daily_price_checks':checks,'result':'passed'}
