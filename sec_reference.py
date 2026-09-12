"""Read SEC public JSON, not a price feed or a forecast service.

One request/second, bounded response size and hard stop on 403/429. No keys,
proxy rotation or retry loops. Original Yahoo/market observations are not replaced.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
import requests
from asset_semantics import number

INDEX_URL='https://www.sec.gov/files/company_tickers.json'
INDEX_TTL=7*86400
REFERENCE_TTL=7*86400
DOCS_URL='https://www.sec.gov/search-filings/edgar-application-programming-interfaces'


def normalized(ticker):return str(ticker).strip().upper().replace('.','-')


def ticker_index(payload):
    if not isinstance(payload,dict):raise ValueError('SEC ticker index is not an object')
    rows={};ambiguous=set()
    for row in payload.values():
        if not isinstance(row,dict):continue
        symbol=normalized(row.get('ticker',''));cik=row.get('cik_str')
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,29}',symbol):continue
        if isinstance(cik,bool) or not isinstance(cik,int) or not 0<cik<10**10:continue
        value={'cik':cik,'name':str(row.get('title',''))}
        if symbol in rows and rows[symbol]['cik']!=cik:ambiguous.add(symbol)
        rows[symbol]=value
    for symbol in ambiguous:rows.pop(symbol,None)
    if len(rows)<100:raise ValueError('SEC ticker index unexpectedly small')
    return rows


def allowed_url(url):
    part=urlsplit(url)
    return (part.scheme=='https' and part.netloc in ('www.sec.gov','data.sec.gov')
            and not part.query and not part.fragment
            and (url==INDEX_URL or bool(re.fullmatch(r'/submissions/CIK\d{10}\.json',part.path))
                 or bool(re.fullmatch(r'/api/xbrl/companyfacts/CIK\d{10}\.json',part.path))))


class SecClient:
    def __init__(self,session=None,max_requests=90):
        self.session=session or requests.Session()
        self.session.trust_env=False
        self.max_requests=max_requests;self.calls=0;self.last=0.;self.blocked=False
        self.evidence=[]
    def get(self,url):
        if not allowed_url(url):raise ValueError('Only reviewed SEC JSON endpoints are allowed')
        if self.blocked or self.calls>=self.max_requests:raise RuntimeError('SEC access budget/circuit is closed')
        time.sleep(max(0.,1.05-(time.monotonic()-self.last)))
        self.last=time.monotonic();self.calls+=1
        with self.session.get(url,headers={'User-Agent':'StockResearchWorkspace/25 contact https://github.com/sippakorntwo-glitch/stock-dashboard',
            'Accept':'application/json'},timeout=(10,30),stream=True,allow_redirects=False) as response:
            if response.status_code in (403,429):self.blocked=True
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('Unexpected SEC redirect or response')
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>20_000_000:raise ValueError('SEC document exceeds bounded size')
                chunks.append(chunk)
        raw=b''.join(chunks);payload=json.loads(raw)
        self.evidence.append({'url':url,'received_at':datetime.now(timezone.utc).isoformat(),
                              'sha256':hashlib.sha256(raw).hexdigest(),'bytes':size})
        return payload


def identity(submission,ticker,cik):
    if int(submission.get('cik',0))!=int(cik):raise ValueError('SEC CIK mismatch')
    if normalized(ticker) not in {normalized(t) for t in submission.get('tickers',[])}:
        raise ValueError('SEC filing ticker identity did not match; no data substituted')
    sic=str(submission.get('sic') or '')
    description=str(submission.get('sicDescription') or '').strip()
    result={'cik':int(cik),'legal_name':str(submission.get('name') or ''),
            'sic':sic if re.fullmatch(r'\d{4}',sic) and sic!='0000' else None,
            'sic_description':description or None,
            'filings_url':f'https://www.sec.gov/edgar/browse/?CIK={int(cik):010d}&owner=exclude'}
    if not result['sic']:result['sic_description']=None
    return result


TAGS={
 'Revenue':('RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'),
 'Net income':('NetIncomeLoss',),
 'Operating cash flow':('NetCashProvidedByUsedInOperatingActivities',),
 'Capital expenditure':('PaymentsToAcquirePropertyPlantAndEquipment',),
 'Total assets':('Assets',), 'Total liabilities':('Liabilities',),
 'Cash and cash equivalents':('CashAndCashEquivalentsAtCarryingValue',),
}
INSTANT={'Total assets','Total liabilities','Cash and cash equivalents'}


def filing_facts(payload,cik,as_of=None):
    """Extract GAAP fiscal-year and point-in-time facts with per-record metadata.

    Deliberately do not turn annual earnings into TTM/forward P/E or combine
    current ratios, ADR units, amended periods or different currencies silently.
    """
    if int(payload.get('cik',0))!=int(cik):raise ValueError('SEC Company Facts CIK mismatch')
    today=date.fromisoformat(str(as_of or date.today())[:10])
    gaap=payload.get('facts',{}).get('us-gaap',{})
    records=[]
    for label,tags in TAGS.items():
        candidates=[]
        for priority,tag in enumerate(tags):
            units=gaap.get(tag,{}).get('units',{})
            for unit,values in units.items():
                if not re.fullmatch('[A-Z]{3}',unit):continue
                for value in values:
                    try:
                        end=date.fromisoformat(value['end']);filed=date.fromisoformat(value['filed'])
                        start=date.fromisoformat(value['start']) if value.get('start') else None
                    except (KeyError,TypeError,ValueError):continue
                    n=number(value.get('val'));form=value.get('form');accn=value.get('accn','')
                    if n is None or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accn):continue
                    if end>today or filed>today or filed<end:continue
                    if label in INSTANT:
                        if start is not None or form not in ('10-K','10-K/A','10-Q','10-Q/A'):continue
                    else:
                        if form not in ('10-K','10-K/A') or start is None or not 330<=(end-start).days<=380:continue
                    candidates.append((end,filed,-priority,{'metric':label,'value':n,'currency':unit,
                        'period_start':str(start) if start else None,'period_end':str(end),
                        'filed':str(filed),'form':form,'accession':accn,'tag':tag,
                        'basis':'point-in-time' if label in INSTANT else 'fiscal-year (not TTM)',
                        'url':f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace("-","")}/'}))
        if candidates:
            key=max((x[0],x[1],x[2]) for x in candidates)
            latest=[x[3] for x in candidates if (x[0],x[1],x[2])==key]
            # Different values in the same latest context are ambiguous; do not guess.
            if len({(r['value'],r['currency'],r['period_start'],r['accession']) for r in latest})==1:
                records.append(latest[0])
    def aligned(a,b):
        return all(a.get(k)==b.get(k) for k in ('currency','period_start','period_end','accession')) and a.get('period_start')
    indexed={r['metric']:r for r in records}
    revenue,income=indexed.get('Revenue'),indexed.get('Net income')
    if revenue and income and aligned(revenue,income) and revenue['value']>0:
        records.append({**income,'metric':'Net margin (calculated FY)','value':income['value']/revenue['value']*100,
                        'currency':'%','tag':'NetIncomeLoss / Revenue × 100','calculated':True})
    cash,capex=indexed.get('Operating cash flow'),indexed.get('Capital expenditure')
    if cash and capex and aligned(cash,capex) and capex['value']>=0:
        records.append({**cash,'metric':'Free cash flow (calculated FY)','value':cash['value']-capex['value'],
                        'tag':'Operating cash flow − capital expenditure','calculated':True})
    return records


def collect_reference(client,ticker,cik,include_facts=True):
    url=f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'
    payload=client.get(url);result=identity(payload,ticker,cik)
    result.update(source='SEC EDGAR',submissions_url=url,checked_at=datetime.now(timezone.utc).isoformat())
    result['facts']=[]
    if include_facts:
        facts_url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json'
        try:
            facts=client.get(facts_url)
            result['facts']=filing_facts(facts,cik)
            result['facts_url']=facts_url
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            result['facts_error']=type(exc).__name__
    result['evidence']=client.evidence[-2:]
    return result
