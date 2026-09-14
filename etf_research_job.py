"""Bounded ETF holdings/profile collector; rendering never queries the provider."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import time

from etf_research import PRIORITY, SCHEMA, SOURCE, from_funds_data, retain_last_valid


def due_symbols(universe, profiles, bundles, attempts, etfs, *, now=None):
    from data_quality import timestamp
    clock = time.time() if now is None else now
    priority = {symbol:index for index,symbol in enumerate(PRIORITY)}
    result = []
    for ticker in universe:
        info = profiles.get('info:'+ticker, ({}, {}))[0] or {}
        if ticker not in etfs and info.get('quoteType') != 'ETF':
            continue
        prior, meta = bundles.get('etf_research:'+ticker, (None, {}))
        attempt = attempts.get('attempt:etf_research:'+ticker, ({}, {}))[1]
        if timestamp(attempt.get('retry_after')) > clock:
            continue
        valid = isinstance(prior, dict) and prior.get('schema') == SCHEMA and prior.get('available')
        stamp = timestamp(meta.get('fetched_at'))
        if valid and clock-stamp < 7*86400:
            continue
        # First visits precede failures/revisits, so unavailable funds cannot
        # consume the queue forever. Every eligible catalog member is reachable.
        attempted = timestamp(attempt.get('fetched_at'))
        result.append((bool(attempted), priority.get(ticker, 999), attempted or stamp, ticker))
    return [item[-1] for item in sorted(result)]


def collect_batch(cache, universe, etfs, *, limit=60, minutes=8, collector=None, pause=.6):
    from data_quality import read_objects, timestamp
    from data_sync import utc_now
    profiles = read_objects(cache, ('info:',))
    bundles = read_objects(cache, ('etf_research:',))
    attempts = read_objects(cache, ('attempt:etf_research:',))
    queue = due_symbols(universe, profiles, bundles, attempts, etfs)
    report = {'due_before':len(queue), 'attempted':0, 'updated':0, 'retained':0,
              'not_reported':0, 'failed':0, 'symbols_updated':[], 'errors':[]}
    circuit, _ = cache.get('external:etf-research-circuit', request_remote=False)
    if isinstance(circuit, dict) and timestamp(circuit.get('retry_after')) > time.time():
        report.update(cooldown_until=circuit['retry_after'], remaining_due=len(queue))
        return report
    if collector is None:
        import yfinance as yf
        yf.config.debug.hide_exceptions = False
        collector = lambda ticker: from_funds_data(ticker, yf.Ticker(ticker).funds_data)
    deadline = time.monotonic() + max(0, minutes)*60
    consecutive_failures = 0
    for ticker in queue[:max(0, limit)]:
        if time.monotonic() >= deadline:
            break
        stamp = utc_now()
        report['attempted'] += 1
        try:
            candidate = collector(ticker)
            if not isinstance(candidate, dict) or candidate.get('schema') != SCHEMA or candidate.get('ticker') != ticker:
                raise ValueError('Unexpected ETF collector schema or identity')
            previous = bundles.get('etf_research:'+ticker, (None, {}))[0]
            chosen = retain_last_valid(previous, candidate)
            updated = chosen is candidate
            if updated:
                cache.put('etf_research:'+ticker, chosen,
                          {'fetched_at':chosen['fetched_at'], 'schema':SCHEMA,
                           'available':bool(chosen.get('available')), 'source':SOURCE})
                report['updated'] += 1
                report['symbols_updated'].append(ticker)
            else:
                report['retained'] += 1
            usable = bool(candidate.get('available') and not candidate.get('errors'))
            if not candidate.get('available'):
                report['not_reported'] += 1
            retry = (datetime.now(timezone.utc) + timedelta(days=7 if usable else 1)).isoformat()
            cache.put('attempt:etf_research:'+ticker, {},
                      {'fetched_at':stamp, 'success':usable, 'retry_after':retry,
                       'retained_last_valid':not updated, 'errors':candidate.get('errors', [])})
            consecutive_failures = 0
        except Exception as exc:
            report['failed'] += 1
            consecutive_failures += 1
            limited = any(token in str(exc).lower() for token in ('429', 'rate limit', 'too many'))
            retry = (datetime.now(timezone.utc) + timedelta(hours=24 if limited else 6)).isoformat()
            cache.put('attempt:etf_research:'+ticker, {}, {'fetched_at':stamp,
                      'success':False, 'retry_after':retry, 'error':type(exc).__name__})
            report['errors'].append({'ticker':ticker, 'error':type(exc).__name__, 'rate_limited':limited})
            if limited or consecutive_failures >= 3:
                cache.put('external:etf-research-circuit', {'retry_after':retry}, {'fetched_at':stamp})
                report['cooldown_until'] = retry
                break
        if pause:
            time.sleep(pause)
    report['remaining_due'] = max(0, len(queue)-report['attempted'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--limit', type=int, default=60)
    parser.add_argument('--minutes', type=float, default=8)
    args = parser.parse_args()
    import dashboard_runtime as a
    from data_sync import ObjectStore, config_from, read_manifest, read_checked, restore_checkpoint, utc_now
    from data_quality import checked_universe
    from update_data import publish_snapshot
    config = config_from() or {'backend':'github', 'DASHBOARD_DATA_REPO':a.DEFAULT_REPO,
              'DASHBOARD_DATA_VISIBILITY':'public', 'DASHBOARD_DATA_BRANCH':'dashboard-data'}
    if args.publish and (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or config.get('DASHBOARD_DATA_REPO') != os.environ.get('GITHUB_REPOSITORY')
            or config.get('DASHBOARD_DATA_VISIBILITY') != 'public'):
        raise RuntimeError('Only this repository main-branch collector may publish ETF research')
    store = ObjectStore(config, writable=args.publish)
    previous = read_manifest(store)
    if not previous:
        raise RuntimeError('No verified prepared snapshot; preserve current data')
    summary = json.loads(gzip.decompress(read_checked(store, previous['summary'])))
    universe = checked_universe(summary)
    path = Path('work/etf-research.sqlite3')
    path.parent.mkdir(exist_ok=True)
    restore_checkpoint(store, previous, path)
    cache = a.DashboardCache(path)
    if cache.error:
        raise RuntimeError('Cannot persist ETF observations')
    report = {'started_at':utc_now(), 'source_generation':previous['generation'],
              'collection':collect_batch(cache, universe, set(a.ETF_NAMES),
                          limit=max(0, args.limit), minutes=max(0, args.minutes))}
    if args.publish and report['collection']['attempted']:
        if read_manifest(store)['generation'] != previous['generation']:
            raise RuntimeError('Prepared snapshot advanced; refusing to replace another collector')
        manifest = publish_snapshot(store, cache, universe,
                   {'task':'ETF research', **report['collection']}, previous,
                   watchlist_csv=summary.get('watchlist_csv'))
        report['generation'] = manifest['generation']
    else:
        report.update(generation=previous['generation'], snapshot_unchanged=True)
    report['finished_at'] = utc_now()
    Path('work/etf-research-report.json').write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
