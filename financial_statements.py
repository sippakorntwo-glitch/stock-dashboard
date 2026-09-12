"""Strict SEC annual-statement contexts; never relabel FY as TTM or forecasts.

No network or UI dependencies. Ratios use one filing, currency and fiscal period.
Beginning balances must be comparative observations in that SAME filing.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
import math
import re

METHOD='filed-financials-v1'
TAGS={
 'revenue':('RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'),
 'cost_of_revenue':('CostOfRevenue','CostOfGoodsAndServicesSold','CostOfGoodsSold'),
 'gross_profit':('GrossProfit',),
 'operating_income':('OperatingIncomeLoss',),
 'net_income':('NetIncomeLoss',),
 'pretax_income':('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest','IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments','IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic'),
 'tax_expense':('IncomeTaxExpenseBenefit',),
 'interest_expense':('InterestExpenseNonOperating','InterestAndDebtExpense','InterestExpense'),
 'ocf':('NetCashProvidedByUsedInOperatingActivities',),
 'capex':('PaymentsToAcquirePropertyPlantAndEquipment',),
 'da':('DepreciationDepletionAndAmortization','DepreciationDepletionAndAmortizationPropertyPlantAndEquipment','DepreciationDepletionAndAmortizationExpense'),
 'dividends_paid':('PaymentsOfDividendsCommonStock','PaymentsOfDividends'),
 'buybacks':('PaymentsForRepurchaseOfCommonStock',),
 'sbc':('ShareBasedCompensation',),
 'assets':('Assets',),'liabilities':('Liabilities',),
 'equity':('StockholdersEquity',),
 'cash':('CashAndCashEquivalentsAtCarryingValue',),
 'current_assets':('AssetsCurrent',),'current_liabilities':('LiabilitiesCurrent',),
 'inventory':('InventoryNet',),'receivables':('AccountsReceivableNetCurrent',),
 'short_investments':('ShortTermInvestments','MarketableSecuritiesCurrent'),
 'debt_current':('LongTermDebtCurrent',),'debt_long':('LongTermDebtNoncurrent',),
 'debt_short':('ShortTermBorrowings','CommercialPaper'),
 'goodwill':('Goodwill',),
}
# A domestic-only pretax amount is NOT consolidated pretax earnings.
TAGS['pretax_income']=TAGS['pretax_income'][:2]
INSTANT=frozenset(('assets','liabilities','equity','cash','current_assets','current_liabilities','inventory','receivables','short_investments','debt_current','debt_long','debt_short','goodwill'))
NONNEGATIVE=frozenset(('assets','liabilities','cash','current_assets','current_liabilities','inventory','receivables','short_investments','debt_current','debt_long','debt_short','goodwill','capex','buybacks','dividends_paid','da'))


def finite(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):return None


def parse_statements(payload,cik,as_of=None,currency=None):
    if isinstance(cik,bool) or int(payload.get('cik',0))!=int(cik):raise ValueError('Company facts CIK mismatch')
    today=date.fromisoformat(str(as_of or date.today())[:10])
    gaap=payload.get('facts',{}).get('us-gaap',{})
    observations=defaultdict(dict);durations={};ambiguities=0
    for field,aliases in TAGS.items():
        candidates=defaultdict(list)
        for rank,tag in enumerate(aliases):
            for unit,items in gaap.get(tag,{}).get('units',{}).items():
                if not re.fullmatch(r'[A-Z]{3}',unit) or (currency and unit!=currency):continue
                for item in items:
                    try:
                        end=date.fromisoformat(item['end']);filed=date.fromisoformat(item['filed'])
                        start=date.fromisoformat(item['start']) if item.get('start') else None
                    except (KeyError,ValueError,TypeError):continue
                    accn=item.get('accn','');number=finite(item.get('val'))
                    if (number is None or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accn)
                        or item.get('form') not in ('10-K','10-K/A','20-F','20-F/A','40-F','40-F/A')
                        or end>today or filed>today or filed<end):continue
                    if field in INSTANT:
                        if start is not None:continue
                    elif start is None or not 330<=(end-start).days<=380:continue
                    if field in NONNEGATIVE and number<0:continue
                    key=(str(start) if start else None,str(end),accn,unit)
                    candidates[key].append((rank,number,tag,str(filed)))
        for key,items in candidates.items():
            best=min(v[0] for v in items);chosen=[v for v in items if v[0]==best]
            if len({v[1] for v in chosen})!=1:
                ambiguities+=1;continue
            _,n,tag,filed=max(chosen,key=lambda v:v[3])
            observations[key][field]={'value':n,'tag':tag,'filed':filed}
            if key[0]:durations[key]=max(durations.get(key,''),filed)
    groups=[]
    for key,filed in durations.items():
        start,end,accn,unit=key
        vals={k:v['value'] for k,v in observations[key].items()}
        if not any(k in vals for k in ('revenue','net_income','operating_income','ocf')):continue
        end_items=observations.get((None,end,accn,unit),{})
        begin=(date.fromisoformat(start)-timedelta(days=1)).isoformat()
        begin_items=observations.get((None,begin,accn,unit),{})
        vals.update({k:v['value'] for k,v in end_items.items()})
        opening={k:v['value'] for k,v in begin_items.items()}
        provenance={k:v['tag'] for k,v in observations[key].items()}
        provenance.update({k:v['tag'] for k,v in end_items.items()})
        groups.append({'start':start,'end':end,'accession':accn,'currency':unit,'filed':filed,
                       'values':vals,'opening':opening,'tags':provenance,
                       'url':f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace("-","")}/'})
    result=[]
    for end in sorted({p['end'] for p in groups},reverse=True)[:4]:
        options=[p for p in groups if p['end']==end]
        latest=max(p['filed'] for p in options);options=[p for p in options if p['filed']==latest]
        # Do not guess between currencies or contradictory annual contexts.
        if len({(p['currency'],p['start']) for p in options})!=1:continue
        result.append(max(options,key=lambda p:(len(p['values']),p['accession'])))
    return {'method':METHOD,'cik':int(cik),'as_of':str(today),'annual':result,
            'ambiguous_contexts_excluded':ambiguities,'taxonomy':'us-gaap',
            'limitation':'Standard consolidated GAAP tags only; custom/IFRS tags can be unavailable. Annual periods are not TTM.'}


def derived_metrics(period,previous=None):
    v={k:finite(n) for k,n in period.get('values',{}).items()}
    b={k:finite(n) for k,n in period.get('opening',{}).items()}
    out={k:{'value':n,'formula':'Reported '+period.get('tags',{}).get(k,k),'inputs':{k:n}}
         for k,n in v.items() if n is not None}
    def calc(key,n,formula,inputs):
        n=finite(n)
        if n is not None:out[key]={'value':n,'formula':formula,'inputs':dict(inputs)}
    def ratio(key,n,d,formula,mult=1):
        if n is not None and d is not None and d>0:calc(key,n/d*mult,formula,{'numerator':n,'denominator':d})
    def avg(key):
        x,y=b.get(key),v.get(key)
        return (x+y)/2 if x is not None and y is not None and x>0 and y>0 else None
    if 'gross_profit' not in out and all(v.get(k) is not None for k in ('revenue','cost_of_revenue')):
        v['gross_profit']=v['revenue']-v['cost_of_revenue'];calc('gross_profit',v['gross_profit'],'Revenue - Cost of Revenue',{k:v[k] for k in ('revenue','cost_of_revenue')})
    if all(v.get(k) is not None for k in ('pretax_income','interest_expense')) and v['interest_expense']>=0:
        v['ebit']=v['pretax_income']+v['interest_expense'];calc('ebit',v['ebit'],'Pretax Income + Interest Expense',{k:v[k] for k in ('pretax_income','interest_expense')})
    if v.get('ebit') is not None and v.get('da') is not None:
        v['ebitda']=v['ebit']+v['da'];calc('ebitda',v['ebitda'],'EBIT + reported D&A (proxy; may differ from adjusted EBITDA)',{'ebit':v['ebit'],'da':v['da']})
    if v.get('ocf') is not None and v.get('capex') is not None:
        v['fcf']=v['ocf']-v['capex'];calc('fcf',v['fcf'],'Operating Cash Flow - PP&E Capital Expenditure',{'ocf':v['ocf'],'capex':v['capex']})
    for prefix,values in (('',v),('opening_',b)):
        fields=('debt_current','debt_long','debt_short')
        if all(values.get(k) is not None for k in fields):
            values['debt']=sum(values[k] for k in fields)
            if not prefix:calc('debt',values['debt'],'Current maturities + noncurrent debt + short-term borrowings (reported components)',{k:values[k] for k in fields})
    for key,numerator in (('gross_margin','gross_profit'),('operating_margin','operating_income'),('net_margin','net_income'),('fcf_margin','fcf')):
        ratio(key,v.get(numerator),v.get('revenue'),numerator+' / Revenue × 100',100)
    ratio('roe',v.get('net_income'),avg('equity'),'Net Income / Average beginning-ending Equity × 100',100)
    ratio('roa',v.get('net_income'),avg('assets'),'Net Income / Average beginning-ending Assets × 100',100)
    ratio('asset_turnover',v.get('revenue'),avg('assets'),'Revenue / Average Assets')
    ratio('inventory_turnover',v.get('cost_of_revenue'),avg('inventory'),'Cost of Revenue / Average Inventory')
    ratio('de',v.get('debt'),v.get('equity'),'Interest-bearing Debt / Equity')
    ratio('liabilities_equity',v.get('liabilities'),v.get('equity'),'Total Liabilities / Equity (not interest-bearing D/E)')
    ratio('current_ratio',v.get('current_assets'),v.get('current_liabilities'),'Current Assets / Current Liabilities')
    if all(v.get(k) is not None for k in ('cash','short_investments','receivables')):
        ratio('quick_ratio',sum(v[k] for k in ('cash','short_investments','receivables')),v.get('current_liabilities'),'(Cash + Short-term Investments + Receivables) / Current Liabilities')
    ratio('cash_ratio',v.get('cash'),v.get('current_liabilities'),'Cash & Equivalents / Current Liabilities')
    ratio('interest_coverage',v.get('ebit'),v.get('interest_expense'),'EBIT / Interest Expense')
    ratio('ocf_ni',v.get('ocf'),v.get('net_income'),'Operating Cash Flow / positive Net Income')
    ratio('sbc_revenue',v.get('sbc'),v.get('revenue'),'Share-based Compensation / Revenue × 100',100)
    if v.get('debt') is not None and v.get('cash') is not None:
        net=v['debt']-v['cash'];calc('net_debt',net,'Debt - Cash',{'debt':v['debt'],'cash':v['cash']})
        ratio('net_debt_ebitda',net,v.get('ebitda'),'Net Debt / positive EBITDA')
    if v.get('current_assets') is not None and v.get('current_liabilities') is not None:
        calc('working_capital',v['current_assets']-v['current_liabilities'],'Current Assets - Current Liabilities',{'assets':v['current_assets'],'liabilities':v['current_liabilities']})
    if (v.get('pretax_income') is not None and v['pretax_income']>0 and v.get('tax_expense') is not None):
        tax=v['tax_expense']/v['pretax_income']
        if 0<=tax<=1 and v.get('operating_income') is not None:
            nopat=v['operating_income']*(1-tax);calc('nopat',nopat,'Operating Income × (1 - effective tax rate)',{'operating_income':v['operating_income'],'tax_rate':tax})
            invested=[]
            for point in (b,v):
                if all(point.get(k) is not None for k in ('equity','debt','cash')):
                    invested.append(point['equity']+point['debt']-point['cash'])
            if len(invested)==2 and min(invested)>0:
                ratio('roic',nopat,sum(invested)/2,'NOPAT / Average(Equity + interest-bearing Debt - Cash) × 100; unadjusted proxy',100)
    if previous and previous.get('currency')==period.get('currency'):
        # Comparison can be a different filing; exact fiscal-year adjacency required.
        gap=(date.fromisoformat(period['start'])-date.fromisoformat(previous['end'])).days
        if 0<gap<=7:
            old=previous.get('values',{})
            for key,field in (('revenue_growth_fy','revenue'),('net_income_growth_fy','net_income')):
                n,d=v.get(field),finite(old.get(field))
                if n is not None and d is not None and d>0:calc(key,(n/d-1)*100,'(Current FY / Previous FY - 1) × 100',{'current':n,'prior':d})
    return out
