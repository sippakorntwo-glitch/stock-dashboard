"""Pure screening of reported values. AND across filters, OR within a category.

Compact profile fields are prepared server-side with their own source timestamp.
Never infer industry from a name, convert currencies implicitly, or fill NaN with 0.
"""
from __future__ import annotations
import math
import pandas as pd
import numpy as np

SCREENER_SCHEMA=2
TEXT_FIELDS={'Sector':'sector','Country':'country','Currency':'currency','Financial_Currency':'financialCurrency',
             'Exchange':'fullExchangeName','Fund_Family':'fundFamily'}
NUMERIC_FIELDS={'Market_Cap':'marketCap','Fund_Assets':'totalAssets','Forward_PE':'forwardPE',
                'Price_To_Book':'priceToBook','Revenue_Growth':'revenueGrowth','Profit_Margin':'profitMargins',
                'ROE':'returnOnEquity','Free_Cash_Flow':'freeCashflow','Beta':'beta',
                'Trailing_PE':'trailingPE','Operating_Margin':'operatingMargins','ROA':'returnOnAssets',
                'Debt_To_Equity':'debtToEquity','Current_Ratio':'currentRatio',
                'Dividend_Yield':'trailingAnnualDividendYield'}
COMPANY_ONLY_FIELDS=frozenset(('Market_Cap','Market_Cap_Millions','Forward_PE','Trailing_PE','Price_To_Book',
    'Revenue_Growth','Profit_Margin','Operating_Margin','ROE','ROA','Free_Cash_Flow','Debt_To_Equity','Current_Ratio'))
FUND_ONLY_FIELDS=frozenset(('Fund_Assets','Fund_Assets_Millions'))
COMPANY_ONLY_CATEGORIES=frozenset(('Sector','Financial_Currency'))
FUND_ONLY_CATEGORIES=frozenset(('Fund_Family',))
PROFILE_FIELDS=tuple([*TEXT_FIELDS,*NUMERIC_FIELDS,'Profile_AsOf','Size_Millions','Market_Cap_Millions','Fund_Assets_Millions'])
UNKNOWN='(Not reported)'


def number(value):
    if isinstance(value,bool):return None
    try:
        n=float(value);return n if math.isfinite(n) else None
    except (ValueError,TypeError,OverflowError):return None


def profile_rows(cache,universe):
    from data_quality import read_objects, present
    from dashboard_runtime import ETF_NAMES
    objects=read_objects(cache,('info:',));result={}
    for ticker in universe:
        info,meta=objects.get('info:'+ticker,({},{}))
        if not isinstance(info,dict) or not info:continue
        from asset_semantics import safe_numeric_profile
        info=safe_numeric_profile(info,ticker,ticker in ETF_NAMES or info.get('quoteType')=='ETF')
        row={field:str(info[key]).strip() if present(info.get(key)) else None for field,key in TEXT_FIELDS.items()}
        row.update({field:number(info.get(key)) for field,key in NUMERIC_FIELDS.items()})
        for field in ('Revenue_Growth','Profit_Margin','Operating_Margin','ROE','ROA','Dividend_Yield'):
            if row[field] is not None:row[field]*=100
        if row['Debt_To_Equity'] is not None:row['Debt_To_Equity']/=100
        for field in ('Debt_To_Equity','Current_Ratio','Dividend_Yield'):
            if row[field] is not None and row[field]<0:row[field]=None
        row['Profile_AsOf']=meta.get('fetched_at') or info.get('_Fetched_At_UTC')
        result[ticker]=row
    return result


def enrich_frame(frame,profiles):
    result=frame.copy()
    for field in PROFILE_FIELDS:
        if field in ('Size_Millions','Market_Cap_Millions','Fund_Assets_Millions'):continue
        values=result.Ticker.map(lambda t:(profiles.get(t) or {}).get(field))
        result[field]=pd.to_numeric(values,errors='coerce') if field in NUMERIC_FIELDS else values
    # Provider fund profiles sometimes contain corporate placeholders such as
    # profitMargins=0. These are N/A, not a reported zero-profit business. Mask
    # only the view used by filters/exports, preserving the raw stored objects.
    funds=result.Asset_Type.eq('ETF')
    for field in COMPANY_ONLY_FIELDS:
        if field not in result:continue
        result.loc[funds,field]=np.nan
    result.loc[~funds,'Fund_Assets']=np.nan
    size=result['Fund_Assets'].where(funds,result['Market_Cap'])
    result['Size_Millions']=size/1_000_000
    result['Market_Cap_Millions']=result['Market_Cap']/1_000_000
    result['Fund_Assets_Millions']=result['Fund_Assets']/1_000_000
    return result


def categorical_values(frame,field):
    values=frame.get(field,pd.Series(index=frame.index,dtype=object))
    found=sorted({str(v).strip() for v in values if pd.notna(v) and str(v).strip() not in ('','None','nan','null')},key=str.casefold)
    if values.isna().any() or values.astype(str).isin(['','None','nan','null']).any():found.append(UNKNOWN)
    return found


def filter_frame(frame,*,categories=None,bounds=None,max_price_age=None,max_profile_age=None,
                 include_missing=False,require_returns=(),above_sma=False,bullish_ema=False,
                 favourites=None,now=None):
    result=frame.copy();mask=pd.Series(True,index=result.index)
    for field,selected in (categories or {}).items():
        if not selected:continue
        values=result.get(field,pd.Series(index=result.index,dtype=object))
        missing=values.isna() | values.astype(str).isin(['','None','nan','null'])
        mask &= values.isin([s for s in selected if s!=UNKNOWN]) | (missing if UNKNOWN in selected else False)
        assets=result.get('Asset_Type',pd.Series(index=result.index,dtype=object))
        if field in COMPANY_ONLY_CATEGORIES:mask &= assets.eq('Common Stock')
        if field in FUND_ONLY_CATEGORIES:mask &= assets.eq('ETF')
    for field,pair in (bounds or {}).items():
        low,high=pair
        if low is None and high is None:continue
        if any(value is not None and number(value) is None for value in (low,high)):
            raise ValueError(field+': limits must be finite numbers')
        low=number(low) if low is not None else None
        high=number(high) if high is not None else None
        if low is not None and high is not None and high<low:raise ValueError(field+': maximum is below minimum')
        raw=result.get(field,pd.Series(index=result.index,dtype=float))
        values=pd.to_numeric(raw,errors='coerce')
        known=pd.Series(np.isfinite(values.to_numpy(dtype=float,na_value=np.nan)),index=result.index)
        keep=known.copy()
        if low is not None:keep &= values.ge(low)
        if high is not None:keep &= values.le(high)
        missing=raw.isna() | raw.astype(str).str.strip().str.casefold().isin(('','none','nan','null','n/a','—'))
        mask &= keep | (missing if include_missing else False)
        assets=result.get('Asset_Type',pd.Series(index=result.index,dtype=object))
        if field in COMPANY_ONLY_FIELDS:mask &= assets.eq('Common Stock')
        if field in FUND_ONLY_FIELDS:mask &= assets.eq('ETF')
    stamp=pd.Timestamp(now if now is not None else pd.Timestamp.now(tz='America/New_York'))
    if stamp.tzinfo is None:stamp=stamp.tz_localize('America/New_York')
    for field,maximum in [('Price_AsOf',max_price_age),('Profile_AsOf',max_profile_age)]:
        if maximum is None:continue
        dates=pd.to_datetime(result.get(field,pd.Series(index=result.index,dtype=object)),errors='coerce',utc=True)
        # Price_AsOf is a date, not a UTC instant that should be shifted to yesterday.
        if field=='Price_AsOf':ages=(stamp.tz_convert('America/New_York').tz_localize(None).normalize()-dates.dt.tz_localize(None).dt.normalize()).dt.days
        else:ages=(stamp.tz_convert('UTC')-dates).dt.total_seconds()/86400
        mask &= ages.between(0,maximum)
    for field in require_returns:
        values=pd.to_numeric(result.get(field,pd.Series(index=result.index,dtype=float)),errors='coerce')
        mask &= np.isfinite(values)
    def numeric(field):return pd.to_numeric(result.get(field,pd.Series(index=result.index,dtype=float)),errors='coerce')
    if above_sma:
        close,sma=numeric('Close'),numeric('SMA200')
        mask &= np.isfinite(close) & np.isfinite(sma) & close.gt(sma)
    if bullish_ema:
        close,ema20,ema50=numeric('Close'),numeric('EMA20'),numeric('EMA50')
        mask &= np.isfinite(close) & np.isfinite(ema20) & np.isfinite(ema50) & close.gt(ema20) & ema20.gt(ema50)
    if favourites is not None:mask &= result.Ticker.isin(favourites)
    return result.loc[mask].copy()


def search_frame(frame, query):
    """Prefer an exact symbol; otherwise literal company/industry search.

    A query such as MSFT must select the company, not the many funds whose
    names contain MSFT. Prefix name: to deliberately search all name matches.
    """
    query = str(query or '').strip()
    if not query:
        return frame.copy()
    names_only = query.casefold().startswith('name:')
    text = query[5:].strip() if names_only else query
    if not text:
        return frame.copy()
    if not names_only:
        symbols = frame['Ticker'].fillna('').astype(str).str.upper()
        exact = symbols.eq(text.upper())
        if not exact.any():
            exact = symbols.eq(text.upper().replace('.', '-'))
        if exact.any():
            return frame.loc[exact].copy()
    mask = pd.Series(False, index=frame.index)
    fields = ('Security_Name',) if names_only else ('Ticker','Security_Name','Industry')
    for field in fields:
        values = frame.get(field, pd.Series(index=frame.index, dtype=object))
        mask |= values.fillna('').astype(str).str.contains(text, case=False, regex=False)
    return frame.loc[mask].copy()
