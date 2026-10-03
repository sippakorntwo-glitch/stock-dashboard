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

MAX_NEWS = 20
MAX_CHARTS = 10
DEADLINE_SECONDS = 240
QUOTE_SCAN_SECONDS = 120
FINAL_REFRESH_RESERVE = 15


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
    from market_event_news import industry_impact, material_event
    if not isinstance(fetched, dict) or not isinstance(fetched.get('items'), list):
        return [], 'news_feed_unavailable'
    items, seen = [], set()
    for raw in fetched['items'][:20]:
        content = raw.get('content', raw) if isinstance(raw, dict) else {}
        impact = industry_impact(content.get('title', ''), row['ticker']) if isinstance(content, dict) else None
        competitor = bool(impact and impact['impact_type'] == 'competitor_supply')
        # This explicit industry mapping is our inference, not a provider ticker
        # association. Still validate URL, publisher and publication time.
        normalized = normalize_news([raw], row['ticker'], now, allow_unlinked=competitor)
        for article in normalized['items']:
            at = instant(article.get('published_at'))
            title = article.get('title', '')
            impact = industry_impact(title, row['ticker'])
            relation = _company_relevance(article, raw, row)
            if impact and impact['impact_type'] == 'competitor_supply':
                relation = relation or impact['relationship']
            if (at is None or not 0 <= (now - at).total_seconds() <= 36 * 3600
                    or not relation or not material_event(title) or article['url'] in seen):
                continue
            topic, context = _topic_guide(title)
            items.append({**article, 'topic': topic, 'context': context,
                          'company_relevance': relation, 'industry_impact': impact,
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


def movement_priority(candidates, limit=MAX_NEWS):
    """Reserve coverage for BOTH losers and gainers, then fill unused slots."""
    sides = [sorted([c for c in candidates if c[2]['change_pct'] < 0], key=lambda x: (-x[0], x[1]['ticker'])),
             sorted([c for c in candidates if c[2]['change_pct'] >= 0], key=lambda x: (-x[0], x[1]['ticker']))]
    output = []
    for index in range(limit):
        for side in sides:
            if index < len(side) and len(output) < limit:
                output.append(side[index])
    return output


def news_priority(candidates, slot, limit=MAX_NEWS):
    """Keep the strongest movers and rotate the remainder for broader discovery."""
    ordered = movement_priority(candidates, limit=len(candidates))
    fixed = min(12, limit)
    first, rest = ordered[:fixed], ordered[fixed:]
    if not rest or len(first) >= limit:
        return first
    remaining = limit - len(first)
    offset = (slot * remaining) % len(rest)
    return first + (rest[offset:] + rest[:offset])[:remaining]


def chart_order(size, slot):
    """Six priority charts plus four rotating places across the remaining news."""
    first = list(range(min(6, size)))
    rest = list(range(len(first), size))
    if not rest:
        return first
    offset = (slot * max(1, MAX_CHARTS - len(first))) % len(rest)
    return first + rest[offset:] + rest[:offset]


def event_card(row, quote, articles, metrics, reasons):
    from market_event_news import story_id
    # One ticker/story/day event key. Delivery uses HMAC-scoped deduplication.
    story = story_id(row['ticker'], articles[0])
    falling = quote['change_pct'] <= -3 or (quote.get('gap_pct') or 0) <= -3
    if quote['price'] < 1:
        state, action = 'below_entry_price', 'ราคาไม่ถึง $1: แสดงข่าวและการเคลื่อนไหว ยังไม่สร้างแผนซื้อ'
    elif falling:
        state, action = 'recovery_watch', 'รอหยุดทำจุดต่ำใหม่ ยืนเหนือ VWAP 2 แท่ง และยกจุดต่ำขึ้น ก่อนพิจารณาแผนฟื้นตัว'
    else:
        state, action = 'event_watch', 'ติดตามจุดเบรกและวอลุ่ม; เข้าเมื่อมีแผนผ่านเกณฑ์และราคาอยู่ใต้เพดานซื้อ'
    return {**row, **quote, 'news': articles[:2], 'status': state, 'event_id': story,
            'action': action, 'reasons': reasons, 'metrics_available': metrics is not None,
            'rvol': metrics['rvol'] if metrics else None,
            'session_dollars': metrics['session_dollars'] if metrics else None,
            'session_volume': metrics['session_volume'] if metrics else None,
            'vwap': metrics['vwap'] if metrics else None,
            'bar_end': metrics['bar_end'] if metrics else None,
            'urgent': bool(metrics and abs(quote['change_pct']) >= 7 and metrics['rvol'] >= 2
                           and metrics['session_dollars'] >= 5_000_000)}


def scan(payload, *, clock=None, quote_fetcher=None, news_fetcher=None, chart_fetcher=None, monotonic=time.monotonic):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    context = session_context(now)
    report = {'schema': 1, 'model': MODEL, 'generated_at': now.isoformat(),
              'session': context['session'], 'trading_date': context['trading_date'],
              'next_trading_day': context['next_day'], 'cards': [], 'events': [], 'actual_count': 0,
              'counts': {}, 'excluded': {}, 'diagnostics': [], 'audit': [], 'cost_pct': COST_RATE * 100,
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
    pool = payload['short_term_pool']
    counts = Counter(universe=len(rows), fresh_quotes=0, quote_attempted=0, quote_failed_batches=0,
                     quote_unattempted=0, news_checked=0, charts_checked=0, news_passed=0,
                     technical_checked=0, momentum_candidates=0,
                     news_limit=MAX_NEWS, chart_limit=MAX_CHARTS,
                     catalog=payload.get('counts', {}).get('total', 0))
    for key in ('catalog_common_stocks', 'catalog_funds', 'catalog_other'):
        if key in pool:
            counts[key] = pool[key]
    report['pool_computed_at'] = pool.get('computed_at')
    rejected = Counter()
    diagnostics = []
    raw_quotes = {}
    symbols = [row['ticker'] for row in rows]
    slot = int(now.timestamp() // 600)
    # If a provider deadline interrupts a round, its tail must not stay unseen
    # indefinitely. This changes read order, never the liquidity/entry criteria.
    offset = (slot * 100) % len(symbols) if symbols else 0
    symbols = symbols[offset:] + symbols[:offset] + ['SPY']
    quote_deadline = min(deadline - FINAL_REFRESH_RESERVE, monotonic() + QUOTE_SCAN_SECONDS)
    for index in range(0, len(symbols), 100):
        if monotonic() >= quote_deadline:
            diagnostics.append('quote_scan_limit_reached')
            break
        batch = symbols[index:index + 100]
        counts['quote_attempted'] += sum(t != 'SPY' for t in batch)
        try:
            raw_quotes.update(unpack_quotes(quote_fetcher(batch)))
        except Exception as exc:
            counts['quote_failed_batches'] += 1
            diagnostics.append('quote_batch_unavailable')
            if _blocked_news_access(exc):
                diagnostics.append('provider_access_or_rate_blocked')
                break
    counts['quote_unattempted'] = len(rows) - counts['quote_attempted']
    now = clock()
    benchmark = quote_observation(raw_quotes.get('SPY'), 'SPY', now, context['session'])
    candidates = []
    for row in rows:
        q = quote_observation(raw_quotes.get(row['ticker']), row['ticker'], now, context['session'])
        if q is None:
            rejected['missing_stale_or_delayed_quote'] += 1
            continue
        counts['fresh_quotes'] += 1
        if q['quote_type'] != 'EQUITY':
            rejected['not_eligible_common_stock'] += 1
            continue
        # Prescreen only: final RVOL uses 5-minute bars at the same clock time.
        activity = ((q['day_volume'] or 0) / row['average_shares_20d']) if context['session'] == 'regular' else 1
        movement = max(abs(q['change_pct']), abs(q.get('gap_pct') or 0), abs(q.get('from_open_pct') or 0))
        if movement < .75 and activity < 1.5:
            rejected['no_material_movement'] += 1
            continue
        candidates.append((max(movement, 1.) * max(activity, .05), row, q))
    counts['momentum_candidates'] = len(candidates)
    prepared = []
    for _, row, q in news_priority(candidates, slot):
        if 'provider_access_or_rate_blocked' in diagnostics:
            break
        if monotonic() >= deadline - FINAL_REFRESH_RESERVE:
            diagnostics.append('bounded_scan_limit_reached')
            break
        counts['news_checked'] += 1
        fetched = {}
        audit = {'ticker': row['ticker'], 'stage': 'news', 'reasons': []}
        report['audit'].append(audit)
        try:
            fetched = news_fetcher(row['ticker'], clock())
            articles, why = fresh_catalysts(row, fetched, clock())
        except Exception as exc:
            articles, why = [], 'news_feed_unavailable'
            if _blocked_news_access(exc):
                audit['reasons'] = ['provider_access_or_rate_blocked']
                diagnostics.append('provider_access_or_rate_blocked')
                break
        audit['news_source'] = fetched.get('source') if isinstance(fetched, dict) else None
        audit['news_errors'] = [fetched[k] for k in ('primary_error', 'fallback_error') if fetched.get(k)] if isinstance(fetched, dict) else []
        if why:
            audit['reasons'] = [why]
            rejected[why] += 1
            if isinstance(fetched, dict) and fetched.get('fallback_error') in {
                    'not_attempted_access_or_rate_blocked', 'access_or_rate_blocked',
                    'HTTP_401', 'HTTP_403', 'HTTP_407', 'HTTP_429'}:
                diagnostics.append('provider_access_or_rate_blocked')
                break
            continue
        counts['news_passed'] += 1
        audit['headlines'] = [{'title': a['title'], 'url': a['url'], 'published_at': a['published_at']} for a in articles]
        audit['stage'] = 'intraday'
        prepared.append((row, None, articles, audit))
    # Translate before obtaining time-sensitive bars and final quotes. Keep the
    # original provider-work budget, excluding bounded offline CPU translation.
    if prepared and 'provider_access_or_rate_blocked' not in diagnostics:
        from thai_news_translation import enrich_prepared
        translation_start = monotonic()
        enrich_prepared(prepared)
        deadline += monotonic() - translation_start
    for index in chart_order(len(prepared), slot):
        row, _, articles, audit = prepared[index]
        if 'provider_access_or_rate_blocked' in diagnostics:
            break
        if counts['charts_checked'] >= MAX_CHARTS or monotonic() >= deadline - FINAL_REFRESH_RESERVE:
            audit['reasons'] = ['intraday_scan_limit']
            continue
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
            audit['reasons'] = [why]
            rejected[why] += 1
            continue
        prepared[index] = (row, frame, articles, audit)
    # Re-read prices AFTER news/charts; a timestamp at job start is not live
    # execution evidence after a slow scan. Recompute bar age at this clock.
    if prepared and 'provider_access_or_rate_blocked' not in diagnostics:
        try:
            refreshed = unpack_quotes(quote_fetcher([r['ticker'] for r, _, _, _ in prepared] + ['SPY']))
        except Exception:
            refreshed = {}
            diagnostics.append('final_quote_refresh_failed')
        now = clock()
        benchmark = quote_observation(refreshed.get('SPY'), 'SPY', now, context['session'])
        for row, frame, news, audit in prepared:
            quote = quote_observation(refreshed.get(row['ticker']), row['ticker'], now, context['session'])
            metrics, why = intraday_metrics(frame, now, context['session'])
            if quote is None:
                audit['reasons'] = [why or 'final_quote_not_fresh']
                rejected[why or 'final_quote_not_fresh'] += 1
                continue
            if why:
                report['events'].append(event_card(row, quote, news, None, audit['reasons'] or [why]))
                continue
            counts['technical_checked'] += 1
            audit.update(stage='plan', rvol=metrics['rvol'], session_dollars=metrics['session_dollars'],
                         quote_time=quote['quote_time'], bar_end=metrics['bar_end'])
            plan, why = make_plan(row, quote, metrics, news, benchmark, now, context['session'])
            if plan:
                audit['stage'] = 'conditional_plan'
                report['cards'].append(plan)
            else:
                audit['reasons'] = why
                rejected.update(why)
            event = event_card(row, quote, news, metrics, why)
            if plan:
                event.update(status='conditional_plan', action=plan['entry_rule'])
            report['events'].append(event)
    if len(candidates) > counts['news_checked']:
        diagnostics.append('not_all_momentum_candidates_deep_scanned')
    report['cards'].sort(key=lambda x: (-x['rvol'], -x['net_upside_pct'], x['ticker']))
    report['cards'] = report['cards'][:5]
    report['events'].sort(key=lambda e: (-int(e['urgent']), -abs(e['change_pct']), e['ticker']))
    report['events'] = report['events'][:MAX_NEWS]
    report.update(generated_at=clock().isoformat(), actual_count=len(report['cards']),
                  counts=dict(counts), excluded=dict(rejected), diagnostics=list(dict.fromkeys(diagnostics)))
    report['status'] = 'conditional_plans' if report['cards'] else 'events_watch' if report['events'] else 'data_unavailable' if (
        not counts['fresh_quotes'] or 'provider_access_or_rate_blocked' in diagnostics or
        (counts['news_checked'] and rejected['news_feed_unavailable'] == counts['news_checked']) or
        (counts['charts_checked'] and not counts['technical_checked'] and any(rejected[k] for k in (
            'intraday_feed_unavailable', 'missing_intraday_bars', 'invalid_intraday_bars',
            'stale_intraday_bars', 'insufficient_same_time_volume_history', 'final_quote_not_fresh', 'recent_bar_gap')))) else 'no_setup'
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
