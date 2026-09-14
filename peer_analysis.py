"""Bounded, same-industry research using dated canonical company observations.

The catalog only nominates peers. No screener ratio is substituted for a dated
financial observation, and a missing observation is never a zero or a rank.
"""
from __future__ import annotations

import math
import re
from statistics import median

from company_metrics import metric_observations
from financial_statements import day, number

MAX_PEERS = 5
DEFAULT_PEERS = 4
MIN_BENCHMARK_PEERS = 3
PERIOD_TOLERANCE_DAYS = 31
PEER_METRICS = (
    'revenueGrowthFY', 'netIncomeGrowthFY', 'epsGrowthFY',
    'grossMargins', 'operatingMargins', 'profitMargins',
    'returnOnEquity', 'returnOnAssets', 'roic', 'fcfMargin', 'cashConversion',
    'debtToEquity', 'interestCoverage', 'currentRatio',
    'trailingPE', 'forwardPE', 'priceToBook', 'evRevenue', 'evEbitda',
)
DATED_BASES = frozenset(('FY', 'FY vs prior FY', 'Balance sheet', 'TTM (4 reported quarters)'))


def _text(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    return '' if value.casefold() in ('', 'n/a', 'none', 'nan', 'unknown', 'not reported', 'currency not reported', 'ไม่ทราบ', 'ไม่มีข้อมูล') else value


def _catalog_rows(frame):
    if frame is None or getattr(frame, 'empty', True) or 'Ticker' not in frame:
        return {}
    # Duplicate symbols are ambiguous; don't silently pick a classification.
    unique = frame.loc[~frame['Ticker'].duplicated(keep=False)]
    return {row['Ticker']: row for row in unique.to_dict('records')
            if _text(row.get('Ticker')) and re.fullmatch(r'[A-Z0-9.^=/_-]{1,30}', row['Ticker'])}


def peer_candidates(ticker, frame, info=None):
    """Rank exact-industry common stocks; never compare nominal caps across FX."""
    rows = _catalog_rows(frame)
    current = rows.get(ticker, {})
    info = info or {}
    if current.get('Asset_Type') not in (None, 'Common Stock') or info.get('quoteType') == 'ETF':
        return []
    industry = _text(info.get('industry')) or _text(current.get('Industry'))
    if not industry:
        return []
    quote_currency = _text(info.get('currency')) or _text(current.get('Currency'))
    reporting_currency = _text(info.get('financialCurrency')) or _text(current.get('Financial_Currency'))
    size = number(info.get('marketCap'))
    if size is None:
        size = number(current.get('Market_Cap'))
    result = []
    for symbol, row in rows.items():
        if symbol == ticker or row.get('Asset_Type') != 'Common Stock':
            continue
        if _text(row.get('Industry')).casefold() != industry.casefold():
            continue
        currency = _text(row.get('Currency'))
        financial_currency = _text(row.get('Financial_Currency'))
        cap = number(row.get('Market_Cap'))
        same_quote = bool(quote_currency and currency == quote_currency)
        same_reporting = bool(reporting_currency and financial_currency == reporting_currency)
        distance = (abs(math.log(cap) - math.log(size))
                    if same_quote and cap is not None and cap > 0 and size is not None and size > 0
                    else math.inf)
        result.append({**row, '_rank': (not same_reporting, not same_quote, distance, symbol),
                       '_same_quote_currency': same_quote, '_same_reporting_currency': same_reporting})
    return sorted(result, key=lambda row: row['_rank'])


def selected_peer_symbols(ticker, frame, selection=None, info=None):
    """None initializes defaults; an explicitly empty saved selection stays empty."""
    candidates = peer_candidates(ticker, frame, info)
    options = {row['Ticker'] for row in candidates}
    if selection is None:
        return [row['Ticker'] for row in candidates[:DEFAULT_PEERS]]
    if not isinstance(selection, (list, tuple)):
        return []
    return list(dict.fromkeys(symbol for symbol in selection
                             if isinstance(symbol, str) and symbol in options))[:MAX_PEERS]


def observation_problem(item):
    """A known collection timestamp is not an accounting-period timestamp."""
    if not isinstance(item, dict) or item.get('state') != 'available' or number(item.get('value')) is None:
        return 'unavailable'
    if item.get('basis') not in DATED_BASES or day(item.get('end')) is None:
        return 'unknown_period'
    if not _text(item.get('currency')):
        return 'unknown_currency'
    if not _text(item.get('source')):
        return 'unknown_source'
    if item['basis'] == 'TTM (4 reported quarters)':
        dates = [day(value) for value in item.get('period_ends', [])]
        if (len(dates) != 4 or not all(dates) or dates[0] != day(item['end'])
                or not all(65 <= (a-b).days <= 115 for a, b in zip(dates, dates[1:]))):
            return 'unknown_window'
    return None


def comparable_reason(reference, candidate):
    """None means comparable; other results are explicit exclusion reasons.

    Calendar endpoints may differ by up to 31 days (including 52/53-week years).
    TTM requires all four reported quarters within the same tolerance. This is a
    transparent approximation, not a claim of identical reporting calendars.
    """
    problem = observation_problem(reference)
    if problem:
        return 'reference_' + problem
    problem = observation_problem(candidate)
    if problem:
        return problem
    if reference['currency'] != candidate['currency']:
        return 'currency_mismatch'
    if reference['basis'] != candidate['basis']:
        return 'basis_mismatch'
    if abs((day(reference['end']) - day(candidate['end'])).days) > PERIOD_TOLERANCE_DAYS:
        return 'period_mismatch'
    if reference['source'] != candidate['source'] or reference.get('formula') != candidate.get('formula'):
        return 'method_mismatch'
    if reference['basis'] == 'TTM (4 reported quarters)':
        if any(abs((day(a)-day(b)).days) > PERIOD_TOLERANCE_DAYS
               for a, b in zip(reference['period_ends'], candidate['period_ends'])):
            return 'window_mismatch'
    return None


def benchmark_metric(reference, peers):
    """Median excludes the researched company; percentile is raw value position."""
    eligible, excluded = {}, {}
    for symbol, item in peers.items():
        reason = comparable_reason(reference, item)
        if reason:
            excluded[symbol] = reason
        else:
            eligible[symbol] = number(item['value'])
    result = {'median': None, 'percentile': None, 'count': len(eligible),
              'selected_count': len(peers), 'eligible': eligible, 'excluded': excluded,
              'state': 'available' if len(eligible) >= MIN_BENCHMARK_PEERS else 'insufficient_peers'}
    if result['state'] == 'available':
        values = list(eligible.values())
        current = number(reference['value'])
        result['median'] = median(values)
        result['percentile'] = 100 * (sum(v < current for v in values)
                                      + .5 * sum(v == current for v in values)) / len(values)
    return result


def build_peer_analysis(ticker, records, peers):
    """records maps symbol -> {info, bundle}; callers supply one pinned read view."""
    peers = list(dict.fromkeys(s for s in peers if s != ticker))[:MAX_PEERS]
    symbols = [ticker, *peers]
    observations = {}
    for symbol in symbols:
        record = records.get(symbol) or {}
        observations[symbol] = metric_observations(symbol, record.get('info') or {}, record.get('bundle'))
    rows = []
    for key in PEER_METRICS:
        values = {symbol: observations[symbol][key] for symbol in symbols}
        rows.append({'key': key, 'observations': values,
                     'benchmark': benchmark_metric(values[ticker], {s: values[s] for s in peers})})
    return {'ticker': ticker, 'peers': peers, 'rows': rows}
