"""Asset-aware availability. Never invent earnings for a gold/bond/crypto fund.

Classification uses reported category or a reviewed issuer filing, not ticker-name
keywords. Raw provider objects and trading scores are not changed by presentation.
"""
from __future__ import annotations
import math
import re

AAAU_FILING='https://www.sec.gov/Archives/edgar/data/1708646/000119312526067559/d56933d10k.htm'
AAAU_HOME='https://www.gsam.com/content/gsam/us/en/advisors/fund-center/etf-fund-finder/goldman-sachs-physical-gold-etf.html'
REVIEWED_INSTRUMENTS={
    'AAAU':{'name':'Goldman Sachs Physical Gold ETF','kind':'physical_gold','cik':1708646,
            'issuer':'Goldman Sachs Asset Management, L.P.','currency':'USD',
            'sponsor_fee_pct':0.18,'source_as_of':'2025-12-31','reviewed_at':'2026-09-12',
            'filing_url':AAAU_FILING,'issuer_url':AAAU_HOME,
            'description':'Physically backed gold trust. Tracks gold less expenses; corporate earnings P/E and analyst corporate target prices do not apply.'},
}
# Do not classify equity gold-miner/energy funds as bullion from their names.
NON_EQUITY_CATEGORY=re.compile(r'commodit|\bbonds?\b|fixed income|treasur|money market|\bcurrenc|digital assets?',re.I)
CORPORATE_FIELDS=frozenset(('industry','sector','marketCap','enterpriseToEbitda','revenueGrowth','earningsGrowth',
    'profitMargins','operatingMargins','returnOnEquity','returnOnAssets','operatingCashflow','freeCashflow',
    'totalCash','totalDebt','targetMeanPrice','numberOfAnalystOpinions','earningsTimestampStart','forwardEps','trailingEps'))
FUND_FIELDS=frozenset(('category','fundFamily','totalAssets','navPrice','beta3Year','annualReportExpenseRatio'))
RATIO_FIELDS=frozenset(('forwardPE','trailingPE','priceToBook'))
TEXT_FIELDS=frozenset(('industry','industryDisp','sector','category','fundFamily','country','currency','financialCurrency','shortName','longName','quoteType'))
POSITIVE_FIELDS=frozenset(('marketCap','totalAssets','navPrice','regularMarketPrice','currentPrice','targetMeanPrice','regularMarketTime','earningsTimestampStart'))
NONNEGATIVE_FIELDS=frozenset(('totalCash','totalDebt','numberOfAnalystOpinions','bid','ask','annualReportExpenseRatio'))
ABSENT={'','none','null','nan','n/a','—','ไม่ระบุ'}


def number(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):return None


def kind_for(ticker,info,is_etf=False):
    reviewed=REVIEWED_INSTRUMENTS.get(ticker)
    if reviewed:return reviewed['kind']
    if not is_etf and info.get('quoteType')!='ETF':return 'company'
    category=str(info.get('category') or '')
    return 'non_equity_fund' if NON_EQUITY_CATEGORY.search(category) else 'portfolio_fund'


def field_state(ticker,info,field,*,is_etf=False):
    kind=kind_for(ticker,info,is_etf)
    fund=kind!='company'
    if (fund and field in CORPORATE_FIELDS) or (not fund and field in FUND_FIELDS):return 'not_applicable'
    if kind in ('physical_gold','non_equity_fund') and field in RATIO_FIELDS:return 'not_applicable'
    if not fund and field in ('forwardPE','trailingPE'):
        eps=number(info.get('forwardEps' if field=='forwardPE' else 'trailingEps'))
        if eps is not None and eps<=0:return 'not_meaningful'
    raw=info.get(field)
    if raw is None or (isinstance(raw,str) and raw.strip().casefold() in ABSENT):return 'not_reported' if info else 'pending'
    if field in TEXT_FIELDS:return 'available' if isinstance(raw,str) and raw.strip() else 'invalid'
    n=number(raw)
    if n is None:return 'invalid'
    if field in POSITIVE_FIELDS and n<=0:return 'invalid'
    if field in NONNEGATIVE_FIELDS and n<0:return 'invalid'
    if field in ('forwardPE','trailingPE'):
        eps=number(info.get('forwardEps' if field=='forwardPE' else 'trailingEps'))
        if n<=0 or (not fund and eps is not None and eps<=0):return 'not_meaningful'
    return 'available'


def display_value(ticker,info,field,*,is_etf=False,percent=False,suffix=''):
    state=field_state(ticker,info,field,is_etf=is_etf)
    if state=='not_applicable':return 'N/A — Not applicable'
    if state=='not_meaningful':return 'N/M — Non-positive earnings'
    if state=='invalid':return '— (invalid source value)'
    if state!='available':return 'Not reported' if info else 'Awaiting data'
    raw=info[field]
    if field in TEXT_FIELDS:return str(raw)
    n=number(raw)
    return f'{n*100 if percent else n:,.2f}'+('%' if percent else suffix)


def adapt_analysis(frame,ticker,info,is_etf):
    """Project the explanatory 360 table without changing its numerical inputs."""
    result=frame.copy(deep=True)
    if 'ปัจจัย' not in result:return result
    kind=kind_for(ticker,info,is_etf)
    for label,field in [('Forward P/E','forwardPE'),('Trailing P/E','trailingPE'),('Target Price','targetMeanPrice')]:
        mask=result['ปัจจัย'].eq(label)
        if not mask.any():continue
        state=field_state(ticker,info,field,is_etf=is_etf)
        if state in ('not_applicable','not_meaningful','invalid'):
            result.loc[mask,'ค่าล่าสุด']=display_value(ticker,info,field,is_etf=is_etf)
            if state=='not_applicable':
                result.loc[mask,'การแปลผล']=('Gold/bond/currency exposure has no underlying corporate earnings P/E.' if field in RATIO_FIELDS else 'Corporate analyst target price does not apply to this fund; compare NAV, strategy, costs and risk.')
            elif state=='not_meaningful':result.loc[mask,'การแปลผล']='P/E is not meaningful with non-positive earnings; this is not a missing-data failure.'
            else:result.loc[mask,'การแปลผล']='Source value failed validation; excluded from this displayed metric.'
        elif is_etf and field in ('forwardPE','trailingPE'):
            result.loc[mask,'ปัจจัย']='Portfolio '+label
            result.loc[mask,'การแปลผล']='Holdings-level ratio reported by the provider, not earnings per ETF unit; methodology may differ between providers.'
    if is_etf:
        mask=result['ปัจจัย'].eq('Beta')
        if field_state(ticker,info,'beta3Year',is_etf=True)=='available':
            result.loc[mask,'ปัจจัย']='Beta (3Y, provider)'
            result.loc[mask,'ค่าล่าสุด']=display_value(ticker,info,'beta3Year',is_etf=True)
            result.loc[mask,'การแปลผล']='Provider three-year beta; not a missing company beta or a prediction.'
    return result


def safe_numeric_profile(info,ticker='',is_etf=False):
    """A calculation copy; preserve raw provider values in persistent storage."""
    result=dict(info)
    for field in POSITIVE_FIELDS | NONNEGATIVE_FIELDS | RATIO_FIELDS:
        if field in result and field_state(ticker,info,field,is_etf=is_etf) in ('invalid','not_applicable','not_meaningful'):
            result[field]=None
    return result
