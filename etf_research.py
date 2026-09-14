"""ETF observations, explicit coverage and conservative comparisons.

Yahoo FundsData top_holdings is a subset, and its public wrapper supplies no
holdings report date. fetched_at is never promoted to source_asof. Ratios in the
verified yfinance FundsData schema are fractions, not percentage points.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from io import StringIO
import math
import re
from urllib.parse import urlparse

SCHEMA = 1
SOURCE = 'Yahoo Finance fund profile / top holdings'
PRIORITY = ('SPY', 'QQQ', 'VTI', 'VOO', 'IVV', 'SCHD', 'IWM', 'DIA', 'TLT', 'GLD', 'QQQI', 'JEPI')
SYMBOL = re.compile(r'[A-Z0-9.^=/_-]{1,30}')
SECTORS_TH = {'technology':'เทคโนโลยี', 'financial_services':'บริการการเงิน',
    'consumer_cyclical':'สินค้าฟุ่มเฟือย', 'communication_services':'การสื่อสาร',
    'healthcare':'สุขภาพ', 'industrials':'อุตสาหกรรม', 'consumer_defensive':'สินค้าอุปโภคบริโภค',
    'energy':'พลังงาน', 'utilities':'สาธารณูปโภค', 'realestate':'อสังหาริมทรัพย์',
    'real_estate':'อสังหาริมทรัพย์', 'basic_materials':'วัสดุพื้นฐาน'}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def valid_date(value, *, today=None):
    try:
        result = date.fromisoformat(str(value))
        return result.isoformat() if result <= (today or datetime.now(timezone.utc).date()) else None
    except (ValueError, TypeError):
        return None


def valid_source(value):
    try:
        parsed = urlparse(str(value))
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def holdings_observation(rows, *, source=SOURCE, source_url='', source_asof=None,
                         fetched_at=None, full_portfolio=False, source_kind='provider'):
    """Reject ambiguous positions rather than renormalize a subset to 100%."""
    normalized = []
    seen = set()
    for item in rows:
        symbol = str(item.get('symbol') or '').strip().upper()
        weight = number(item.get('weight'))
        if not SYMBOL.fullmatch(symbol):
            raise ValueError('รหัสหลักทรัพย์ต้องระบุตลาด/รุ่นให้ชัดเจนและไม่เกิน 30 ตัวอักษร')
        if symbol in seen:
            raise ValueError('พบรหัสหลักทรัพย์ซ้ำ กรุณารวมรายการที่ซ้ำในไฟล์ต้นทางก่อน')
        if weight is None or not 0 <= weight <= 1:
            raise ValueError('น้ำหนักแต่ละรายการต้องอยู่ระหว่าง 0–100% และเป็นตัวเลขที่ระบุจริง')
        seen.add(symbol)
        normalized.append({'symbol':symbol, 'name':str(item.get('name') or symbol)[:200], 'weight':weight})
    coverage = sum(item['weight'] for item in normalized)
    if coverage > 1.000001:
        raise ValueError('ผลรวมน้ำหนักเกิน 100%; ยังไม่รองรับพอร์ต leverage/short หรือการนับรายการซ้ำ')
    if full_portfolio and (not normalized or coverage < .995):
        raise ValueError('ไฟล์ที่ระบุว่าครบพอร์ตต้องมีผลรวมน้ำหนักอย่างน้อย 99.5% และไม่เกิน 100%')
    if full_portfolio and not valid_date(source_asof):
        raise ValueError('การยืนยันข้อมูลครบพอร์ตต้องระบุวันที่ถือครองที่ถูกต้อง')
    return {'rows':sorted(normalized, key=lambda item:item['weight'], reverse=True),
            'coverage':coverage if normalized else None, 'complete':bool(full_portfolio),
            'state':'available' if normalized else 'not_reported', 'source':source,
            'source_url':source_url, 'source_asof':valid_date(source_asof),
            'fetched_at':fetched_at, 'source_kind':source_kind}


def parse_holdings_csv(raw, *, source_url, source_asof, full_portfolio=False, fetched_at=None):
    """Explicit weight_pct avoids guessing whether 0.5 means 0.5% or 50%."""
    if not isinstance(raw, bytes) or len(raw) > 1_000_000:
        raise ValueError('ไฟล์ต้องเป็น CSV ขนาดไม่เกิน 1 MB')
    if not valid_source(source_url):
        raise ValueError('กรุณาระบุลิงก์แหล่งข้อมูล HTTPS โดยไม่มีชื่อผู้ใช้หรือรหัสผ่าน')
    if not valid_date(source_asof):
        raise ValueError('กรุณาระบุวันที่ถือครองจริงที่ไม่ใช่วันในอนาคต')
    try:
        reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')))
        if not reader.fieldnames or not {'symbol','weight_pct'}.issubset(reader.fieldnames):
            raise ValueError('CSV ต้องมีคอลัมน์ symbol, weight_pct และใส่ name เพิ่มได้')
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('CSV มีชื่อคอลัมน์ซ้ำ')
        rows = []
        for index, item in enumerate(reader):
            if index >= 5000:
                raise ValueError('รองรับไม่เกิน 5,000 รายการต่อไฟล์')
            if None in item:
                raise ValueError('จำนวนคอลัมน์ใน CSV ไม่สม่ำเสมอ')
            value = number(item.get('weight_pct'))
            rows.append({'symbol':item.get('symbol'), 'name':item.get('name'),
                         'weight':value / 100 if value is not None else None})
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError('อ่านไฟล์ CSV UTF-8 ไม่สำเร็จ') from exc
    if not rows:
        raise ValueError('CSV ไม่มีรายการถือครอง')
    return holdings_observation(rows, source='ไฟล์ที่ผู้ใช้นำเข้า (ยังไม่ได้ตรวจสอบกับผู้ออกกองทุน)',
            source_url=source_url, source_asof=source_asof, fetched_at=fetched_at,
            full_portfolio=full_portfolio, source_kind='user_import')


def _ratio(value):
    value = number(value)
    return value if value is not None and 0 <= value <= 1 else None


def _operation(frame, row, ticker):
    if frame is None or not hasattr(frame, 'loc') or row not in frame.index or ticker not in frame.columns:
        return None
    # Duplicate rows or columns are ambiguous; never select the first silently.
    if list(frame.index).count(row) != 1 or list(frame.columns).count(ticker) != 1:
        return None
    return number(frame.loc[row, ticker])


def from_funds_data(ticker, funds, *, fetched_at=None):
    """Map the public FundsData schema; no data-provider requests in page render."""
    stamp = fetched_at or datetime.now(timezone.utc).isoformat()
    result = {'schema':SCHEMA, 'ticker':ticker, 'fetched_at':stamp,
              'source':SOURCE, 'source_url':f'https://finance.yahoo.com/quote/{ticker}/holdings/',
              'source_asof':None, 'errors':[]}
    try:
        frame = funds.top_holdings
        rows = []
        if frame is not None and not frame.empty:
            if not {'Name','Holding Percent'}.issubset(frame.columns):
                raise ValueError('Unexpected provider holdings schema')
            rows = [{'symbol':symbol, 'name':item['Name'], 'weight':item['Holding Percent']}
                    for symbol, item in frame.iterrows()]
        result['holdings'] = holdings_observation(rows, source_url=result['source_url'], fetched_at=stamp)
    except (ValueError, TypeError, KeyError) as exc:
        result['holdings'] = holdings_observation([], source_url=result['source_url'], fetched_at=stamp)
        result['errors'].append('holdings:' + type(exc).__name__)
    operations = funds.fund_operations
    result['expense_ratio'] = _ratio(_operation(operations, 'Annual Report Expense Ratio', ticker))
    result['category_expense_ratio'] = _ratio(_operation(operations, 'Annual Report Expense Ratio', 'Category Average'))
    turnover = _operation(operations, 'Annual Holdings Turnover', ticker)
    result['turnover'] = turnover if turnover is not None and turnover >= 0 else None
    assets = _operation(operations, 'Total Net Assets', ticker)
    result['net_assets'] = assets if assets is not None and assets >= 0 else None
    overview = funds.fund_overview
    result['overview'] = {key:str(value)[:300] for key,value in (overview or {}).items()
                          if key in ('categoryName','family','legalType') and value is not None}
    for target, attr in (('sectors','sector_weightings'), ('asset_classes','asset_classes')):
        supplied = getattr(funds, attr) or {}
        accepted = {str(key):_ratio(value) for key,value in supplied.items() if value is not None}
        # Missing entries stay absent; an invalid vector is withheld as a whole.
        if any(value is None for value in accepted.values()) or sum(accepted.values()) > 1.000001:
            result[target] = {}
            result['errors'].append(target + ':invalid_weights')
        else:
            result[target] = accepted
    result['available'] = bool(result['holdings']['rows'] or result['expense_ratio'] is not None or result['sectors'])
    return result


def retain_last_valid(previous, candidate):
    """A partial/empty response never removes a valid section or changes its date."""
    if not isinstance(previous, dict) or previous.get('schema') != SCHEMA or not previous.get('available'):
        return candidate
    if not isinstance(candidate, dict) or candidate.get('schema') != SCHEMA or not candidate.get('available'):
        return previous
    # Keep whole coherent older response when the new source loses a valid part.
    prior_holdings = previous.get('holdings', {}).get('rows')
    new_holdings = candidate.get('holdings', {}).get('rows')
    if (candidate.get('errors') or (prior_holdings and not new_holdings)
            or any(previous.get(key) is not None and candidate.get(key) is None
                   for key in ('expense_ratio','net_assets','turnover'))
            or any(previous.get(key) and not candidate.get(key) for key in ('sectors','asset_classes'))):
        return previous
    old_date = previous.get('holdings', {}).get('source_asof')
    new_date = candidate.get('holdings', {}).get('source_asof')
    if old_date and new_date and new_date < old_date:
        return previous
    return candidate


def concentration(holdings):
    rows = (holdings or {}).get('rows') or []
    if not rows:
        return {'state':'not_reported', 'coverage':None, 'top1':None, 'top5':None}
    weights = sorted((item['weight'] for item in rows), reverse=True)
    return {'state':'available', 'coverage':sum(weights), 'top1':weights[0],
            'top5':sum(weights[:5]), 'known_positions':len(weights),
            'complete':bool(holdings.get('complete'))}


def overlap(left, right):
    """Sum min(weight A, weight B), retaining source dates and subset scope."""
    if not (left or {}).get('rows') or not (right or {}).get('rows'):
        return {'state':'not_reported', 'weight':None, 'rows':[], 'complete':False}
    by_symbol = {item['symbol']:item for item in right['rows']}
    shared = []
    for item in left['rows']:
        other = by_symbol.get(item['symbol'])
        if other and min(item['weight'], other['weight']) > 0:
            shared.append({'symbol':item['symbol'], 'left_weight':item['weight'],
                           'right_weight':other['weight'], 'overlap':min(item['weight'], other['weight'])})
    date_a, date_b = left.get('source_asof'), right.get('source_asof')
    aligned = bool(date_a and date_b and date_a == date_b)
    return {'state':'available', 'weight':sum(item['overlap'] for item in shared),
            'rows':sorted(shared, key=lambda item:item['overlap'], reverse=True),
            'complete':bool(aligned and left.get('complete') and right.get('complete')),
            'date_state':'aligned' if aligned else 'different_dates' if date_a and date_b else 'unknown_date',
            'left_asof':date_a, 'right_asof':date_b,
            'left_coverage':left.get('coverage'), 'right_coverage':right.get('coverage')}


def price_comparison(history, benchmark_history, *, currency=None, benchmark_currency=None, years=1):
    """Aligned adjusted closing-price comparison, explicitly not NAV tracking error."""
    import pandas as pd
    if not currency or not benchmark_currency or currency != benchmark_currency:
        return {'state':'currency_mismatch', 'data':pd.DataFrame()}
    if history is None or benchmark_history is None or history.empty or benchmark_history.empty:
        return {'state':'missing_history', 'data':pd.DataFrame()}
    try:
        frames = []
        for frame, name in ((history, 'กองทุน'), (benchmark_history, 'ตัวเปรียบเทียบ')):
            if 'Close' not in frame or frame.index.has_duplicates:
                raise ValueError('invalid history')
            series = pd.to_numeric(frame['Close'], errors='coerce').rename(name)
            series.index = pd.to_datetime(series.index, utc=True).tz_localize(None).normalize()
            if series.index.has_duplicates:
                raise ValueError('ambiguous daily date')
            frames.append(series)
        data = pd.concat(frames, axis=1, join='inner').sort_index()
        data = data.replace([float('inf'), float('-inf')], float('nan')).dropna()
        data = data[(data > 0).all(axis=1)]
        if len(data) < 20:
            return {'state':'insufficient_history', 'data':pd.DataFrame()}
        data = data.loc[data.index >= data.index[-1] - pd.DateOffset(years=years)]
        if len(data) < 20:
            return {'state':'insufficient_history', 'data':pd.DataFrame()}
        rebased = data.div(data.iloc[0]).mul(100)
        returns = data.iloc[-1].div(data.iloc[0]).sub(1)
        return {'state':'available', 'data':rebased, 'fund_return':float(returns.iloc[0]),
                'benchmark_return':float(returns.iloc[1]), 'gap_pp':float((returns.iloc[0]-returns.iloc[1])*100),
                'start':data.index[0].date().isoformat(), 'end':data.index[-1].date().isoformat(),
                'observations':len(data), 'currency':currency}
    except (ValueError, TypeError, KeyError):
        return {'state':'invalid_history', 'data':pd.DataFrame()}
