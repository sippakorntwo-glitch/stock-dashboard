"""Bounded current-data scan for the independent short-term alert model."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from short_term_engine import (MODEL, COST_RATE, instant, number, validate_pool,
                               quote_observation, intraday_metrics, make_plan, session_context)

MAX_NEWS = 16
MAX_CHARTS = 8
DEADLINE_SECONDS = 150


def unpack_quotes(raw):
    if isinstance(raw, dict):
        raw = raw.get('quoteResponse', {}).get('result')
    if not isinstance(raw, list):
        raise ValueError('Invalid quote envelope')
    result = {}
    for value in raw:
        if isinstance(value, dict) and isinstance(value.get('symbol'), str):
            if value['symbol'] in result:
                raise ValueError('Duplicate quote identity')
            result[value['symbol']] = value
    return result


def fresh_catalysts(row, fetched, now):
    """Attributed event headlines, never an invented article summary/sentiment."""
    from market_pulse import normalize_news
    from stock_alert_briefing import _company_relevance, _topic_guide
    if not isinstance(fetched, dict) or not isinstance(fetched.get('items'), list):
        return [], 'news_feed_unavailable'
    items, seen = [], set()
    excluded = re.compile(r'\b(?:will (?:report|release|announce)|to (?:report|release|announce)|'
                          r'schedules?|conference call|earnings (?:date|preview)|'
                          r'should you|is .+ a buy|worth buying|price target|valuation|'
                          r'52.week|all.time high|retire\w*|succession|appoint\w*)\b', re.I)
    event = re.compile(r'\b(?:reports? .{0,55}(?:results|earnings)|results|'
                       r'earnings (?:beat|miss)|guidance|raises? .{0,30}(?:outlook|forecast)|'
                       r'cuts? .{0,30}(?:outlook|forecast)|wins? .{0,45}contract|'
                       r'(?:signs?|awarded) .{0,40}(?:deal|contract)|'
                       r'(?:acquires?|acquisition|merger)|FDA .{0,40}(?:approv|reject)|'
                       r'approv\w* .{0,30}(?:drug|treatment)|recall|lawsuit|'
                       r'files? .{0,20}bankruptcy|deliveries|production results)\b', re.I)
    for raw in fetched['items'][:20]:
        normalized = normalize_news([raw], row['ticker'], now)
        for article in normalized['items']:
            at = instant(article.get('published_at'))
            title = article.get('title', '')
            if (at is None or not 0 <= (now - at).total_seconds() <= 36 * 3600
                    or not _company_relevance(article, raw, row) or excluded.search(title)
                    or not event.search(title) or article['url'] in seen):
                continue
            topic, context = _topic_guide(title)
            items.append({**article, 'topic': topic, 'context': context,
                          'evidence_type': 'provider_headline', 'direction': 'unassessed'})
            seen.add(article['url'])
    items.sort(key=lambda x: x['published_at'], reverse=True)
    return items[:2], '' if items else 'no_fresh_company_catalyst'


def fetch_chart(ticker):
    import dashboard_runtime as a
    with a.core._PROVIDER_LOCK:
        source = a.yf.Ticker(ticker)
        frame = source.history(period='1mo', interval='5m', auto_adjust=False,
                               actions=False, prepost=True, timeout=10, raise_errors=True)
        metadata = source.get_history_metadata() or {}
    if metadata.get('currency') != 'USD' or metadata.get('symbol') != ticker:
        raise ValueError('Intraday source identity/currency mismatch')
    return frame


def scan(payload, *, clock=None, quote_fetcher=None, news_fetcher=None, chart_fetcher=None, monotonic=time.monotonic):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    context = session_context(now)
    report = {'schema': 1, 'model': MODEL, 'generated_at': now.isoformat(),
              'session': context['session'], 'trading_date': context['trading_date'],
              'next_trading_day': context['next_day'], 'cards': [], 'actual_count': 0,
              'counts': {}, 'excluded': {}, 'diagnostics': [], 'cost_pct': COST_RATE * 100,
              'status': 'no_setup', 'source': 'Yahoo Finance: timestamped quotes, 5-minute bars and linked news',
              'performance': 'ยังไม่มีสถิติผลลัพธ์ล่วงหน้าของเกณฑ์รุ่นนี้'}
    if context['session'] == 'closed':
        report['status'] = 'market_closed'
        return report
    try:
        rows = validate_pool(payload.get('short_term_pool'), now)
    except (ValueError, TypeError, KeyError):
        report['status'] = 'data_unavailable'
        report['diagnostics'] = ['short_term_universe_missing_or_stale']
        return report
    from stock_alert_briefing import fetch_alert_news, _blocked_news_access
    if quote_fetcher is None:
        from market_pulse_service import fetch_quotes
        quote_fetcher = fetch_quotes
    news_fetcher = news_fetcher or fetch_alert_news
    chart_fetcher = chart_fetcher or fetch_chart
    deadline = monotonic() + DEADLINE_SECONDS
    counts = Counter(universe=len(rows), fresh_quotes=0, news_checked=0, charts_checked=0,
                     news_passed=0, technical_checked=0)
    rejected = Counter()
    diagnostics = []
    raw_quotes = {}
    symbols = [row['ticker'] for row in rows] + ['SPY']
    try:
        for index in range(0, len(symbols), 50):
            raw_quotes.update(unpack_quotes(quote_fetcher(symbols[index:index + 50])))
    except Exception:
        report.update(status='data_unavailable', diagnostics=['quote_feed_unavailable'])
        return report
    now = clock()
    benchmark = quote_observation(raw_quotes.get('SPY'), 'SPY', now, context['session'])
    candidates = []
    for row in rows:
        q = quote_observation(raw_quotes.get(row['ticker']), row['ticker'], now, context['session'])
        if q is None:
            rejected['missing_stale_or_delayed_quote'] += 1
            continue
        counts['fresh_quotes'] += 1
        if q['quote_type'] != 'EQUITY' or q['price'] < 10 or q['change_pct'] < .75:
            rejected['no_long_momentum'] += 1
            continue
        # Prescreen only: final RVOL uses 5-minute bars at the same clock time.
        activity = ((q['day_volume'] or 0) / row['average_shares_20d']) if context['session'] == 'regular' else 1
        candidates.append((q['change_pct'] * activity, row, q))
    candidates.sort(key=lambda x: (-x[0], x[1]['ticker']))
    counts['momentum_candidates'] = len(candidates)
    prepared = []
    for _, row, q in candidates[:MAX_NEWS]:
        if monotonic() >= deadline or counts['charts_checked'] >= MAX_CHARTS:
            diagnostics.append('bounded_scan_limit_reached')
            break
        counts['news_checked'] += 1
        fetched = {}
        try:
            fetched = news_fetcher(row['ticker'], clock())
            articles, why = fresh_catalysts(row, fetched, clock())
        except Exception as exc:
            articles, why = [], 'news_feed_unavailable'
            if _blocked_news_access(exc):
                diagnostics.append('provider_access_or_rate_blocked')
                break
        if why:
            rejected[why] += 1
            if isinstance(fetched, dict) and fetched.get('fallback_error') == 'not_attempted_access_or_rate_blocked':
                diagnostics.append('provider_access_or_rate_blocked')
                break
            continue
        counts['news_passed'] += 1
        counts['charts_checked'] += 1
        try:
            frame = chart_fetcher(row['ticker'])
            metrics, why = intraday_metrics(frame, clock(), context['session'])
        except Exception as exc:
            metrics, why = None, 'intraday_feed_unavailable'
            if _blocked_news_access(exc):
                diagnostics.append('provider_access_or_rate_blocked')
                break
        if why:
            rejected[why] += 1
            continue
        prepared.append((row, frame, articles))
    # Re-read prices AFTER news/charts; a timestamp at job start is not live
    # execution evidence after a slow scan. Recompute bar age at this clock.
    if prepared:
        try:
            refreshed = unpack_quotes(quote_fetcher([r['ticker'] for r, _, _ in prepared] + ['SPY']))
        except Exception:
            refreshed = {}
            diagnostics.append('final_quote_refresh_failed')
        now = clock()
        benchmark = quote_observation(refreshed.get('SPY'), 'SPY', now, context['session'])
        for row, frame, news in prepared:
            quote = quote_observation(refreshed.get(row['ticker']), row['ticker'], now, context['session'])
            metrics, why = intraday_metrics(frame, now, context['session'])
            if quote is None or why:
                rejected[why or 'final_quote_not_fresh'] += 1
                continue
            counts['technical_checked'] += 1
            plan, why = make_plan(row, quote, metrics, news, benchmark, now, context['session'])
            if plan:
                report['cards'].append(plan)
            else:
                rejected.update(why)
    if len(candidates) > counts['news_checked']:
        diagnostics.append('not_all_momentum_candidates_deep_scanned')
    report['cards'].sort(key=lambda x: (-x['rvol'], -x['net_upside_pct'], x['ticker']))
    report['cards'] = report['cards'][:5]
    report.update(generated_at=clock().isoformat(), actual_count=len(report['cards']),
                  counts=dict(counts), excluded=dict(rejected), diagnostics=list(dict.fromkeys(diagnostics)))
    report['status'] = 'conditional_plans' if report['cards'] else 'data_unavailable' if (
        not counts['fresh_quotes'] or 'provider_access_or_rate_blocked' in diagnostics or
        (counts['news_checked'] and rejected['news_feed_unavailable'] == counts['news_checked'])) else 'no_setup'
    return report


def main():
    import argparse
    from short_term_report import save_report
    parser = argparse.ArgumentParser(description='Current-data short-term review; never sends LINE or orders')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default='work/short-term-review')
    args = parser.parse_args()
    report = scan(json.loads(Path(args.input).read_text(encoding='utf-8')))
    save_report(report, Path(args.output))
    print('SHORT_TERM_REVIEW:', json.dumps({key: report[key] for key in (
        'model', 'generated_at', 'status', 'actual_count', 'counts', 'excluded', 'diagnostics')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
