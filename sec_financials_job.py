"""Bounded SEC reconciliation of existing dated company statements.

Runs only in the prepared-data collector. No network request is made by the UI.
Uses the same persistent SEC denial/rate-limit circuit as reference collection.
"""
from datetime import datetime, timedelta, timezone
import time

from financial_completeness import statement_gaps
from financial_statements import SCHEMA, observations
from sec_reference import SecClient, INDEX_URL, INDEX_TTL, ticker_index, normalized

SEC_REFRESH_DAYS = 2


def collect_batch(cache, universe, etfs, *, limit=300, minutes=15, client=None):
    from data_quality import read_objects, timestamp
    from data_sync import utc_now
    from sec_financials import merge_missing

    report = {'provider': 'SEC EDGAR', 'attempted': 0, 'checked': 0, 'updated': 0,
              'filled_cells': 0, 'conflicting_cells': 0, 'failed': 0,
              'revised_cells': 0,
              'errors': [], 'symbols_updated': [], 'only_missing': True}
    now = datetime.now(timezone.utc)
    deadline = time.monotonic() + max(0, minutes) * 60
    circuit, _ = cache.get('external:sec-circuit', request_remote=False)
    if isinstance(circuit, dict) and timestamp(circuit.get('next_attempt_after')) > now.timestamp():
        return {**report, 'cooldown_until': circuit['next_attempt_after'], 'provider_requests': 0}
    client = client or SecClient(max_requests=2*max(0, limit)+1)
    try:
        raw, meta = cache.get('external:sec-ticker-map', request_remote=False)
        if not raw or now.timestamp()-timestamp(meta.get('fetched_at')) > INDEX_TTL:
            raw = client.get(INDEX_URL)
            index = ticker_index(raw)
            cache.put('external:sec-ticker-map', raw, {'fetched_at': utc_now(), 'source_url': INDEX_URL})
        else:
            index = ticker_index(raw)
        bundles = read_objects(cache, ('financials:',))
        profiles = read_objects(cache, ('info:',))
        attempts = read_objects(cache, ('attempt:sec-financials:',))
        queue = []
        for ticker in universe:
            info = profiles.get('info:'+ticker, ({}, {}))[0] or {}
            value = bundles.get('financials:'+ticker, ({}, {}))[0] or {}
            has_sec_cells = any(origin.get('source') == 'SEC EDGAR'
                for period in ('annual', 'quarterly') for kind in ('income', 'balance', 'cashflow')
                for row in value.get(period, {}).get(kind, [])
                for origin in row.get('field_provenance', {}).values() if isinstance(origin, dict))
            if ticker in etfs or info.get('quoteType') in ('ETF', 'MUTUALFUND'):
                continue
            if (value.get('schema') != SCHEMA or value.get('ticker') != ticker
                    or not value.get('currency') or value['currency'] != info.get('financialCurrency')
                    or not (statement_gaps(value) or has_sec_cells or value.get('sec_reconciliation'))):
                continue
            mapped = index.get(normalized(ticker))
            if not mapped:
                report['unmapped_companies'] = report.get('unmapped_companies', 0)+1
                continue
            attempt = attempts.get('attempt:sec-financials:'+ticker, ({}, {}))[1]
            if timestamp(attempt.get('retry_after')) > now.timestamp():
                continue
            queue.append((timestamp(attempt.get('fetched_at')), ticker != 'AARD', ticker, mapped['cik']))
        queue.sort()
        report['due_before'] = len(queue)
        for _, _, ticker, cik in queue[:max(0, limit)]:
            if time.monotonic() >= deadline or client.blocked or client.calls+2 > client.max_requests:
                break
            stamp = utc_now()
            report['attempted'] += 1
            success = False
            try:
                submission = client.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
                # Reject identity before spending the larger companyfacts request.
                from sec_reference import identity
                identity(submission, ticker, cik)
                facts = client.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
                previous, meta = bundles['financials:'+ticker]
                value, checked = merge_missing(previous, facts, submission, cik=cik, fetched_at=stamp)
                value['sec_reconciliation'] = {**checked, 'checked_at': stamp, 'cik': cik}
                value['observations'] = observations(value)
                cache.put('financials:'+ticker, value, {**meta, 'fetched_at': stamp,
                          'source': value.get('source', previous.get('source'))})
                report['checked'] += 1
                # Count actual newly filled cells, separately from companies checked.
                filled = checked['filled_count']
                conflicts = checked.get('conflicts', [])
                revised = checked.get('revised_count', 0)
                report['filled_cells'] += filled
                report['revised_cells'] += revised
                report['conflicting_cells'] += len(conflicts)
                if filled or revised:
                    report['updated'] += 1
                    report['symbols_updated'].append(ticker)
                success = True
            except Exception as exc:
                report['failed'] += 1
                report['errors'].append({'ticker': ticker, 'error': type(exc).__name__})
            retry = (datetime.now(timezone.utc)+timedelta(days=SEC_REFRESH_DAYS if success else 1)).isoformat()
            cache.put('attempt:sec-financials:'+ticker, {},
                      {'fetched_at': stamp, 'success': success, 'retry_after': retry})
            if client.blocked:
                break
            if report['attempted'] % 25 == 0:
                print({'sec_checked': report['checked'], 'filled_cells': report['filled_cells'],
                       'due_before': len(queue)}, flush=True)
        report['remaining_due'] = max(0, len(queue)-report['attempted'])
    except Exception as exc:
        report['errors'].append({'source': 'SEC ticker index', 'error': type(exc).__name__})
    if client.blocked and client.calls:
        until = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        cache.put('external:sec-circuit', {'next_attempt_after': until,
                  'reason': 'access denied or rate limit'}, {'fetched_at': utc_now()})
        report['cooldown_until'] = until
    report['provider_requests'] = client.calls
    # Per-cell filing provenance lives in the checkpoint. Keep this compact
    # public summary bounded even when a batch makes hundreds of requests.
    report['http_evidence'] = client.evidence[-8:]
    return report
