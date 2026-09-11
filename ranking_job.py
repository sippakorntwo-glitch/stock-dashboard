"""Scheduled ranking, independently published without rewriting the market snapshot.

Read every catalog member from a checksum-verified checkpoint. During the US
regular-session clock window refresh provider info for at most 20 candidates.
Re-score the whole catalog afterwards; never imply 4,900 realtime quote refreshes.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import tempfile
import time
from data_sync import ObjectStore, config_from, read_manifest, restore_checkpoint
from github_store import GitHubReleaseStore
import dashboard_runtime as a
from ranking_engine import (MODEL, utc, seconds, rank_all, make_payload,
                            regular_session_clock, public_info)

RANK_BRANCH = 'dashboard-rankings'
RANK_PATH = 'top10.json'


def refresh_shortlist(cache, candidates, now=None, maximum=20):
    report = dict(attempted=0, success=0, failed=0, limit=maximum,
                  mode='regular-session-shortlist' if regular_session_clock(now) else 'closed-clock-no-quote-fetch')
    if not regular_session_clock(now):
        return report
    deadline = time.monotonic() + 150
    consecutive = 0
    for item in candidates[:maximum]:
        if time.monotonic() >= deadline:
            break
        report['attempted'] += 1
        try:
            with a.core._PROVIDER_LOCK:
                info = a.yf.Ticker(item['ticker']).get_info()
            if not isinstance(info, dict) or not a.number(info.get('regularMarketPrice')):
                raise ValueError('No usable regular-market quote')
            # Fetch time is NOT the exchange quote timestamp.
            stamp = utc().isoformat()
            info['_Fetched_At_UTC'] = stamp
            cache.put('info:' + item['ticker'], public_info(info), {'fetched_at':stamp, 'source':'Yahoo Finance'})
            report['success'] += 1
            consecutive = 0
        except Exception as exc:
            report['failed'] += 1
            consecutive += 1
            if consecutive >= 3 or any(s in str(exc).lower() for s in ('429', 'rate limit', 'too many')):
                report['stopped_on_errors'] = True
                break
        time.sleep(1)
    return report


def publish(config, payload):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Publication is restricted to the owner GitHub workflow')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if (event.get('repository', {}).get('private') is not False
            or config['DASHBOARD_DATA_REPO'].casefold() != os.environ.get('GITHUB_REPOSITORY', '').casefold()
            or config.get('DASHBOARD_DATA_VISIBILITY') != 'public'):
        raise RuntimeError('Publish only to the same public repository')
    writer = GitHubReleaseStore({**config, 'DASHBOARD_DATA_BRANCH': RANK_BRANCH})
    writer._ensure_data_branch()
    old = writer._json('GET', '/contents/' + RANK_PATH, missing=True, params={'ref':RANK_BRANCH})
    if old:
        previous = json.loads(base64.b64decode(old['content']))
        if (seconds(previous.get('computed_at')) or 0) > (seconds(payload['computed_at']) or 0):
            raise RuntimeError('Refusing to replace a newer ranking')
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 1_000_000:
        raise ValueError('Ranking publication exceeds size budget')
    body = dict(message='Refresh Top 10 buy-watch ranking ' + payload['computed_at'],
                branch=RANK_BRANCH, content=base64.b64encode(raw).decode())
    if old:
        body['sha'] = old['sha']
    writer._json('PUT', '/contents/' + RANK_PATH, json=body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='work/top10.json')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--no-quote-refresh', action='store_true')
    args = parser.parse_args()
    config = config_from() or dict(backend='github', DASHBOARD_DATA_REPO=a.DEFAULT_REPO,
                                  DASHBOARD_DATA_VISIBILITY='public', DASHBOARD_DATA_BRANCH='dashboard-data')
    store = ObjectStore(config)
    manifest = read_manifest(store)
    if not manifest:
        raise RuntimeError('No verified market snapshot; keep the previous board unchanged')
    with tempfile.TemporaryDirectory(prefix='rank-catalog-') as folder:
        cache_path = Path(folder) / 'source.sqlite3'
        restore_checkpoint(store, manifest, cache_path)
        cache = a.DashboardCache(cache_path)
        if cache.error:
            raise RuntimeError('Cannot read the verified checkpoint')
        # Same canonical catalog as the dashboard; independent of uploaded session CSVs.
        import pandas as pd
        universe = a.select_universe(pd.DataFrame(columns=['Ticker']))
        before, counts, excluded = rank_all(cache, universe)
        report = {'attempted':0, 'success':0, 'failed':0, 'mode':'disabled-for-verification'}
        if not args.no_quote_refresh:
            report = refresh_shortlist(cache, before)
        if report['success']:
            candidates, counts, excluded = rank_all(cache, universe)
        else:
            candidates = before
        if counts['scanned'] != len(universe) or counts['calculation_errors'] > max(10, counts['evaluated'] // 10):
            raise RuntimeError('Incomplete/error-prone ranking; do not replace the existing board')
        payload = make_payload(candidates, counts, excluded, manifest, refresh_report=report)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        if args.publish:
            publish(config, payload)
        concise = {k:payload[k] for k in ('computed_at','next_scheduled_at','source_generation','counts','excluded','quote_refresh')}
        concise['top10'] = [{k:r[k] for k in ('ticker','score','coverage','qualified','ready_at_calculation','price_asof','quote_time','rr')} for r in payload['items']]
        print('TOP10_RANKING_REPORT:', json.dumps(concise, ensure_ascii=False), flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
                f.write('### Top 10 ranking — '+MODEL+'\n\n```json\n'+json.dumps(concise,ensure_ascii=False,indent=2)+'\n```\n')


if __name__ == '__main__':
    main()
