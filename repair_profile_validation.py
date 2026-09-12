"""One paced recheck of invalid profiles; unavailable/structural gaps are not retries.

Original provider objects remain in the cache. A failed call preserves the old
observation; new raw values retain their true fetch timestamp and are validated
again before use. No network requests are made by the UI through this module.
"""
from __future__ import annotations
from datetime import datetime, timezone
import time
from asset_semantics import field_state, POSITIVE_FIELDS, NONNEGATIVE_FIELDS, RATIO_FIELDS


def repair_invalid_profiles(cache, universe, etfs, profiles, *, limit=40, now=None):
    import dashboard_runtime as app
    from data_quality import timestamp
    from update_data import record_attempt
    clock=(now or datetime.now(timezone.utc)).timestamp()
    targets=[]
    for ticker in universe:
        info,metadata=profiles.get('info:'+ticker,({},{}))
        if not isinstance(info,dict) or not info:continue
        invalid=[f for f in POSITIVE_FIELDS|NONNEGATIVE_FIELDS|RATIO_FIELDS
                 if f in info and field_state(ticker,info,f,is_etf=ticker in etfs)=='invalid']
        if not invalid:continue
        previous,attempt=cache.get('attempt:profile-validation:'+ticker,request_remote=False)
        if clock-timestamp(attempt.get('fetched_at'))<6*3600:continue
        targets.append((ticker,invalid))
    report={'eligible':len(targets),'attempted':0,'refreshed':0,'resolved':[],
            'still_invalid':{},'failures':{},'rate_limited':False,'limit':limit}
    worker=app.BackgroundUpdates(cache)
    for ticker,old_fields in targets[:limit]:
        report['attempted']+=1
        try:
            worker._job('info',ticker,'1d')
            current,_=cache.get('info:'+ticker,request_remote=False)
            remaining=[f for f in old_fields if field_state(ticker,current or {},f,is_etf=ticker in etfs)=='invalid']
            report['refreshed']+=1
            if remaining:report['still_invalid'][ticker]=remaining
            else:report['resolved'].append(ticker)
            record_attempt(cache,'profile-validation',ticker,not remaining)
        except Exception as exc:
            record_attempt(cache,'profile-validation',ticker,False)
            report['failures'][ticker]=type(exc).__name__
            if any(term in str(exc).lower() for term in ('429','too many','rate limit')) or 'RateLimit' in type(exc).__name__:
                report['rate_limited']=True
                break
        time.sleep(1.1)
    report['remaining_beyond_budget']=max(0,len(targets)-report['attempted'])
    return report
