"""Auditable availability, not fabricated data or an investment quality score.

A zero observation is valid. Absent estimates, insufficient price histories,
failed requests and unattempted requests are deliberately different states.
"""
from __future__ import annotations
from collections import Counter, deque
import json
import math
import re
import zlib
import pandas as pd

VERSION = 1
LABELS = {'available':'มีข้อมูล','pending':'รอโหลดข้อมูล','failed':'โหลดไม่สำเร็จ — รอลองใหม่',
          'not_reported':'แหล่งข้อมูลไม่รายงาน','short_history':'ประวัติไม่ยาวพอ',
          'missing_inputs':'ข้อมูลต้นทางไม่พอคำนวณ','no_payments':'ตรวจแล้ว ไม่พบรายการในช่วงข้อมูล',
          'not_applicable':'ไม่ใช้กับสินทรัพย์นี้'}
STOCK_FIELDS = ['currency','industry','sector','country','marketCap','forwardPE','trailingPE','priceToBook','enterpriseToEbitda','revenueGrowth','earningsGrowth','profitMargins','operatingMargins','returnOnEquity','returnOnAssets','operatingCashflow','freeCashflow','totalCash','totalDebt','targetMeanPrice','numberOfAnalystOpinions','regularMarketPrice','regularMarketTime','beta','bid','ask','earningsTimestampStart']
ETF_FIELDS = ['currency','category','fundFamily','totalAssets','navPrice','beta3Year','regularMarketPrice','regularMarketTime']
BARS_REQUIRED = {'Close':1,'Return_1D':2,'Return_3D':4,'Return_7D':8,'EMA20':20,'EMA50':50,'SMA200':200,'RSI_14':15,'MACD':26,'MACD_Signal':34,'Vol_Ratio':21,'ATR':14,'ATR_Pct':14,'Dollar_Volume_20D':20,'Volatility_20D':21,'Drawdown_52W':252,'Suggested_Stop':14}
MONTHS_REQUIRED = {'Return_1M':1,'Return_3M':3,'Return_6M':6,'Historical_Return':12,'Return_2Y':24,'Return_3Y':36,'Return_5Y':60}
QUOTE_FIELDS = list(BARS_REQUIRED) + list(MONTHS_REQUIRED)


def present(value):
    if value is None:return False
    if isinstance(value,str):return value.strip().casefold() not in ('','none','null','nan','n/a','—','ไม่ระบุ')
    if isinstance(value,bool):return False
    try:return math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError):return False


def timestamp(value):
    try:
        t=pd.Timestamp(value)
        if pd.isna(t):return 0.0
        if t.tzinfo is None:t=t.tz_localize('UTC')
        return t.timestamp()
    except (ValueError,TypeError,OverflowError):return 0.0


def industry_value(info, is_etf=False):
    keys=('category',) if is_etf else ('industry','industryDisp')
    return next((str(info[k]).strip() for k in keys if present(info.get(k))),None)


def checked_universe(summary):
    raw=summary.get('universe')
    if (not isinstance(raw,list) or not raw or len(raw)>20000
            or any(not isinstance(t,str) or not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}',t) for t in raw)
            or len(raw)!=len(set(raw))):
        raise ValueError('Snapshot has an invalid or ambiguous symbol universe')
    return tuple(raw)


def read_objects(cache, prefixes=('info:','dividends:','history:1d:','attempt:')):
    result={}
    with cache.connect() as db:
        for key,body,meta in db.execute('SELECT key,body,metadata FROM objects'):
            if key.startswith(prefixes):result[key]=(json.loads(zlib.decompress(body)),json.loads(meta))
    return result


def history_shape(body):
    if body is None:return {'bars':0,'first':None,'last':None,'valid':False}
    try:
        obj=json.loads(body) if isinstance(body,str) else body
        idx=obj['index'];data=obj['data'];cols=obj['columns']
        valid=bool(idx and len(idx)==len(data) and set(['Open','High','Low','Close']).issubset(cols))
        return {'bars':len(idx) if valid else 0,'first':str(idx[0])[:10] if valid else None,'last':str(idx[-1])[:10] if valid else None,'valid':valid}
    except (ValueError,TypeError,KeyError,IndexError):return {'bars':0,'first':None,'last':None,'valid':False}


def missing_metric(field, row, shape):
    if present(row.get(field)):return 'available'
    if not shape['valid']:return 'pending'
    if shape['bars'] < BARS_REQUIRED.get(field,0):return 'short_history'
    if field in MONTHS_REQUIRED:
        try:
            end=pd.Timestamp(row.get('Price_AsOf') or shape['last'])
            if pd.Timestamp(shape['first']) > end-pd.DateOffset(months=MONTHS_REQUIRED[field]):return 'short_history'
        except (ValueError,TypeError):pass
    return 'missing_inputs'


def missing_state(objects,kind,ticker):
    if kind+':'+ticker in objects:return 'not_reported'
    attempt=objects.get('attempt:'+kind+':'+ticker,({},{}))[1]
    return 'failed' if attempt.get('success') is False else 'pending'


def make_quality(cache, universe, *, etfs=(), now=None):
    universe=tuple(universe);etfs=set(etfs);objects=read_objects(cache)
    quotes=cache.quotes();classifications=cache.classifications();counts=Counter(universe=len(universe))
    columns={};symbols={}
    def count(field,state):columns.setdefault(field,Counter())[state]+=1
    for t in universe:
        row=quotes.get(t,{});is_etf=t in etfs
        info,imeta=objects.get('info:'+t,({},{}));info=info if isinstance(info,dict) else {}
        h,hmeta=objects.get('history:1d:'+t,(None,{}));shape=history_shape(h)
        div,dmeta=objects.get('dividends:'+t,(None,{}))
        industry=classifications.get(t,{}).get('Industry')
        istate='available' if present(industry) else missing_state(objects,'info',t)
        info_state='available' if info else missing_state(objects,'info',t)
        if info_state=='not_reported' and not info:info_state='not_reported'
        dstate=missing_state(objects,'dividends',t)
        if isinstance(div,dict) and div.get('error'):dstate='failed'
        elif isinstance(div,dict) and isinstance(div.get('records'),list):dstate='available' if div['records'] else 'no_payments'
        counts['prices']+=int(present(row.get('Close')))
        counts['histories']+=int(shape['valid']);counts['info']+=int(bool(info));counts['industry']+=int(istate=='available')
        counts['dividends_checked']+=int(dstate in ('available','no_payments'))
        counts['dividends_with_payments']+=int(dstate=='available');counts['dividends_no_payments']+=int(dstate=='no_payments')
        count('history', 'available' if shape['valid'] else missing_state(objects,'history',t))
        count('industry_or_category',istate);count('info',info_state);count('dividends',dstate)
        missing_metrics={}
        for field in QUOTE_FIELDS:
            status=missing_metric(field,row,shape);count('price.'+field,status)
            if status!='available':missing_metrics[field]=status
        missing_fields=[]
        for field in ETF_FIELDS if is_etf else STOCK_FIELDS:
            state='available' if present(info.get(field)) else missing_state(objects,'info',t)
            count(('etf.' if is_etf else 'stock.')+field,state)
            if state!='available':missing_fields.append(field)
        counts['unattempted_info']+=int(info_state=='pending')
        counts['unattempted_dividends']+=int(dstate=='pending')
        symbols[t]={'asset_type':'ETF' if is_etf else 'Common Stock','industry_state':istate,
                    'info_state':info_state,'info_fetched_at':imeta.get('fetched_at'),
                    'dividend_state':dstate,'dividend_fetched_at':dmeta.get('fetched_at'),
                    'dividend_coverage_start':(div or {}).get('coverage_start'),
                    'dividend_coverage_end':(div or {}).get('coverage_end'),
                    'history':shape,'history_fetched_at':hmeta.get('fetched_at'),
                    'missing_metrics':missing_metrics,'missing_info_fields':missing_fields,
                    'next_info_retry':objects.get('attempt:info:'+t,({},{}))[1].get('retry_after')}
    return {'version':VERSION,'audited_at':str(now or pd.Timestamp.now(tz='UTC').isoformat()),
            'counts':dict(counts),'columns':{k:dict(v) for k,v in columns.items()},'symbols':symbols}


def metadata_due(kind,ticker,metadata,now,mode='bootstrap'):
    old=metadata.get(kind+':'+ticker)
    retry=timestamp(metadata.get('attempt:'+kind+':'+ticker,{}).get('retry_after'))
    if retry>now:return False
    if old is None:return True
    age=now-timestamp(old.get('fetched_at'))
    if mode=='daily' and age>=7*86400:return True
    # A successful partial profile must not suppress classification repair for a week.
    if kind=='info' and old.get('classification_available') is False:
        return age>=86400
    return False


def metadata_jobs(universe,metadata,etfs,now,mode='bootstrap'):
    # Rotate four queues so ETFs and dividend checks cannot starve behind 4,200 stocks.
    etfs=set(etfs);groups={('info',False):deque(),('info',True):deque(),('dividends',False):deque(),('dividends',True):deque()}
    for t in universe:
        for kind in ('info','dividends'):
            if metadata_due(kind,t,metadata,now,mode):groups[(kind,t in etfs)].append((kind,t))
    result=[]
    while any(groups.values()):
        for queue in groups.values():
            if queue:result.append(queue.popleft())
    return result


def prepare_cached_metadata(cache,universe,etfs=()):
    """Recover existing real labels and annotate profiles without changing fetch times."""
    etfs=set(etfs);rows=read_objects(cache,('info:',))
    for t in universe:
        info,meta=rows.get('info:'+t,(None,{}))
        if isinstance(info,dict) and info:
            classification=industry_value(info,t in etfs)
            if meta.get('quality_version')!=VERSION or meta.get('classification_available')!=(classification is not None):
                cache.put('info:'+t,info,{**meta,'quality_version':VERSION,'classification_available':classification is not None})
            cache.save_classification(t,{**info,'_Fetched_At_UTC':meta.get('fetched_at') or info.get('_Fetched_At_UTC','')})
