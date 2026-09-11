"""Deterministic whole-catalog buy-watch ranking using the existing 100-point model.

No provider calls here. A ranked candidate is not automatically an entry signal.
Daily observations and quote timestamps are deliberately different clocks.
"""
from __future__ import annotations
from collections import Counter
import math
import re
import pandas as pd
import dashboard_runtime as a

SCHEMA = 1
MODEL = 'existing-100-point-pullback-v1'
REFRESH_SECONDS = 1800
MAX_DAILY_AGE = 4  # Calendar-day convention; not an exchange holiday calendar.
MAX_INFO_AGE = 7 * 86400
STALE_SECONDS = 35 * 60


def utc(value=None):
    t = pd.Timestamp.now(tz='UTC') if value is None else pd.Timestamp(value)
    return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')


def seconds(value):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value) if math.isfinite(value) else None
        t = utc(value)
        return None if pd.isna(t) else t.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def fresh(value, now, maximum):
    stamp = seconds(value)
    return stamp is not None and -60 <= utc(now).timestamp() - stamp <= maximum


def regular_session_clock(now):
    """Clock filter only. A fresh regular-market quote is required as well."""
    local = utc(now).tz_convert('America/New_York')
    return local.weekday() < 5 and 570 <= local.hour * 60 + local.minute < 960


def daily_recent(value, now):
    try:
        day = pd.Timestamp(value).date()
        age = (utc(now).tz_convert('America/New_York').date() - day).days
        return 0 <= age <= MAX_DAILY_AGE
    except (ValueError, TypeError):
        return False


def candidate_exclusion(row, info, now):
    if row.get('Asset_Type') not in ('Common Stock', 'ETF'):
        return 'unsupported_asset'
    if not daily_recent(row.get('Price_AsOf'), now):
        return 'old_or_unknown_daily_price'
    price = a.number(row.get('Close'))
    if price is None or price < 1:
        return 'price_below_1_or_missing'
    # Do not compare liquidity proxies across unverified currencies.
    if info.get('currency') != 'USD':
        return 'currency_unknown_or_not_usd'
    liquidity = a.number(row.get('Dollar_Volume_20D'))
    if liquidity is None or liquidity < 1_000_000:
        return 'liquidity_below_1m_or_missing'
    words = ' '.join(str(x or '') for x in (row.get('Security_Name'), row.get('Industry'),
                        info.get('shortName'), info.get('longName'), info.get('industry'))).lower()
    if 'shell compan' in words or 'blank check' in words:
        return 'shell_company'
    if row.get('Asset_Type') == 'ETF' and re.search(r'\b(2x|3x|4x|5x|inverse|leveraged|ultrapro|ultrashort)\b', words):
        return 'leveraged_or_inverse_etf'
    return ''


def public_info(info):
    """JSON-compatible public company data; never credentials or local settings."""
    def clean(x):
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items() if str(k).lower() not in ('token', 'password', 'authorization', 'cookie')}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return x if x is None or isinstance(x, (str, int, float, bool)) else str(x)
    return clean(info)


def evaluate(ticker, row, history, info, info_meta, benchmark, now):
    stamp = info_meta.get('fetched_at') or info.get('_Fetched_At_UTC')
    usable_info = dict(info)
    info_fresh = fresh(stamp, now, MAX_INFO_AGE)
    if not info_fresh:
        # Never award fundamental points to stale estimates.
        usable_info.pop('forwardPE', None)
        usable_info.pop('targetMeanPrice', None)
    is_etf = row.get('Asset_Type') == 'ETF'
    ctx = a.decision_context(history, usable_info, benchmark if is_etf else None, now=now)
    f, m = ctx.get('history'), ctx.get('metrics', {})
    if f is None or len(f) < 200 or not daily_recent(f.index[-1], now):
        return None
    # Missing/future quote timestamps must not be treated as live reference prices.
    if not fresh(ctx.get('quote_time'), now, MAX_DAILY_AGE * 86400):
        ctx['quote'] = None
        ctx['quote_time'] = None
    score = a.criteria_score(ctx, usable_info, is_etf)
    plan = a.build_entry_plan(ctx, usable_info, score, is_etf, min_rr=2.0, now=now)
    rr = a.number(plan.get('rr'))
    # Do not fill ten places with downtrends, nonsensical plans or very weak scores.
    if score['trend'] is not True or score['score'] < 60 or rr is None or rr <= 0:
        return None
    qualified = bool(score['score'] >= 80 and score['coverage'] == 100 and rr >= 2
                     and (is_etf or info_fresh))
    ready = bool(plan['ready'] and qualified and regular_session_clock(now)
                 and fresh(ctx.get('quote_time'), now, 900))
    daily_close = a.number(m.get('Close'))
    reference = ctx.get('quote') or daily_close
    distance = abs(reference / plan['entry'] - 1) * 100 if reference and plan.get('entry') else None
    reasons = []
    for criterion in score['rows'].to_dict('records'):
        if criterion.get('ได้') == criterion.get('เต็ม'):
            reasons.append(criterion['เกณฑ์'])
    blockers = list(plan['blockers'])
    if not regular_session_clock(now):
        blockers.append('นอกช่วงเวลาตลาดปกติสหรัฐ รอราคาในวันซื้อขายถัดไป')
    if not info_fresh and not is_etf:
        blockers.append('ข้อมูลพื้นฐานไม่ครบหรือเกิน 7 วัน ไม่ให้คะแนนส่วนที่เก่า')
    return dict(ticker=ticker, name=str(info.get('shortName') or row.get('Security_Name') or ticker),
                asset_type=row.get('Asset_Type'), industry=str(row.get('Industry') or info.get('industry') or 'ไม่ระบุ'),
                score=int(score['score']), coverage=int(score['coverage']), upper=int(score['upper']),
                qualified=qualified, ready_at_calculation=ready, rr=rr,
                daily_close=daily_close, price_asof=f.index[-1].date().isoformat(),
                quote=a.number(ctx.get('quote')), quote_time=seconds(ctx.get('quote_time')),
                zone_low=plan.get('zone_low'), zone_high=plan.get('zone_high'), stop=plan.get('stop'), target=plan.get('target'),
                distance_pct=distance, rsi=a.number(m.get('RSI_14')),
                liquidity=a.number(row.get('Dollar_Volume_20D')), reasons=reasons[:4], blockers=blockers,
                info_fetched_at=stamp, info=public_info(info), info_meta=public_info(info_meta))


def sort_candidates(rows):
    return sorted(rows, key=lambda r: (-int(r['ready_at_calculation']), -int(r['qualified']),
        -r['score'], -r['coverage'], -min(r['rr'], 10), r.get('distance_pct') or 0,
        -(r.get('liquidity') or 0), r['ticker']))


def rank_all(cache, universe, now=None):
    now = utc(now)
    quotes, classifications = cache.quotes(), cache.classifications()
    benchmark, _ = cache.history('SPY')
    counts = Counter(total=len(universe), scanned=0, evaluated=0, candidates=0, calculation_errors=0)
    rejected = Counter()
    result = []
    for ticker in universe:
        counts['scanned'] += 1
        row = dict(quotes.get(ticker, {}))
        if not row:
            rejected['missing_summary'] += 1
            continue
        row.update({k:v for k,v in classifications.get(ticker, {}).items() if k == 'Industry' and v})
        info, meta = cache.get('info:' + ticker, request_remote=False)
        info = info if isinstance(info, dict) else {}
        why = candidate_exclusion(row, info, now)
        if why:
            rejected[why] += 1
            continue
        try:
            history, _ = cache.history(ticker)
            candidate = evaluate(ticker, row, history, info, meta, benchmark, now)
            counts['evaluated'] += 1
            if candidate is not None:
                result.append(candidate)
            else:
                rejected['insufficient_history_or_model_conditions'] += 1
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            counts['calculation_errors'] += 1
    counts['candidates'] = len(result)
    return sort_candidates(result), dict(counts), dict(rejected)


def next_scheduled(now):
    t = utc(now).floor('min')
    for delta in range(1, 61):
        candidate = t + pd.Timedelta(minutes=delta)
        if candidate.minute in (7, 37):
            return candidate.isoformat()
    raise AssertionError('Unreachable schedule')


def make_payload(candidates, counts, rejected, manifest, now=None, refresh_report=None):
    now = utc(now)
    return dict(schema=SCHEMA, model=MODEL, app_version=a.APP_VERSION,
                computed_at=now.isoformat(), next_scheduled_at=next_scheduled(now), refresh_seconds=REFRESH_SECONDS,
                source_generation=manifest.get('generation'), source_published_at=manifest.get('published_at'),
                scope='หุ้นและ ETF ทั้งทะเบียน ไม่ตามตัวกรองส่วนบุคคล',
                counts=counts, excluded=rejected, quote_refresh=refresh_report or {},
                items=candidates[:10])


def display_status(item, payload, now=None):
    now = utc(now)
    if not fresh(payload.get('computed_at'), now, STALE_SECONDS):
        return 'ข้อมูลอันดับเก่า', False
    if not regular_session_clock(now):
        return 'รอตลาดเปิด', False
    if item.get('ready_at_calculation') and fresh(item.get('quote_time'), now, 900):
        return 'ผ่านเงื่อนไข ณ เวลาราคา', True
    if item.get('qualified'):
        return 'รอราคา / รอยืนยัน', False
    return 'เฝ้าดู ยังไม่ผ่านแผน', False
