"""Ten-minute public event board and quota-bounded, deduplicated LINE events."""
from __future__ import annotations
import base64
from copy import deepcopy
from datetime import timedelta
import json
import math
import uuid

from short_term_engine import MODEL, instant

BOARD_BRANCH = 'line-alert-media'
BOARD_PATH = 'event-board.json'


def publish_board(store, report):
    """Public market data only; compare actual source generation, not run start."""
    from line_alerts import AlertError
    raw = json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 400_000 or report.get('model') != MODEL:
        raise AlertError('Invalid event board publication')
    old = store.call('GET', '/contents/' + BOARD_PATH + '?ref=' + BOARD_BRANCH, missing=True)
    if old:
        previous = json.loads(base64.b64decode(old['content']))
        if instant(previous.get('generated_at')) > instant(report['generated_at']):
            raise AlertError('Refusing to replace a newer market event board')
    body = {'branch': BOARD_BRANCH, 'message': 'Refresh public market events [skip ci]',
            'content': base64.b64encode(raw).decode()}
    if old:
        body['sha'] = old['sha']
    store.call('PUT', '/contents/' + BOARD_PATH, body)


def report_notice_key(recipient, value):
    from line_alerts import opaque_key
    return opaque_key(recipient, 'market-notice-v2:' + value)


def deliver_urgent(report, payload, store, client, recipient, now, builder, clock):
    from line_alerts import AlertError, opaque_key, validate_messages, stamp
    from line_alert_schedule import quota_remaining, period_bounds
    from short_term_report import notice_ids
    if report.get('model') != MODEL or report.get('session') not in ('pre', 'regular'):
        return {'status': 'no_urgent_events', 'messages': 0}
    generated = instant(report.get('generated_at'))
    if generated is None or not 0 <= (now - generated).total_seconds() <= 180:
        return {'status': 'event_report_expired', 'messages': 0}
    state = store.read()
    bucket = state['recipients'].setdefault(opaque_key(recipient, 'recipient-scope-v1'), {'seen': {}, 'pending': None})
    if bucket.get('pending'):
        return {'status': 'pending_delivery_waits_for_retry', 'messages': 0}
    report = deepcopy(report)
    # Only genuine new events/plan transitions, not another push for the same
    # negative headline every ten minutes. A changed price alone isn't a story.
    selected = []
    for event in report.get('events', []):
        if event.get('urgent'):
            label = report['trading_date'] + ':' + event['event_id'] + ':event'
            if report_notice_key(recipient, label) not in bucket['seen']:
                selected.append(event)
    plans = []
    for card in report['cards']:
        one = dict(report, cards=[card], events=[])
        if all(report_notice_key(recipient, key) not in bucket['seen'] for key in notice_ids(one)):
            plans.append(card)
    report['cards'], report['events'] = plans[:5], selected[:5]
    report['actual_count'] = len(report['cards'])
    notices = notice_ids(report)
    if not notices:
        return {'status': 'no_new_urgent_events', 'messages': 0}
    quota = client.quota_snapshot()
    remaining = quota_remaining(bucket, quota, now)
    period, _, _ = period_bounds(now)
    budget = bucket.get('event_budget')
    if not isinstance(budget, dict) or budget.get('period') != period:
        budget = {'period': period, 'used': 0, 'days': {}}
        bucket['event_budget'] = budget
    # At most 20% of a finite monthly LINE plan and two extra pushes a day.
    # Normal scheduled summaries share the same conservative overall ledger.
    day = report['trading_date']
    limit = math.floor(quota['limit'] * .20)
    if not remaining or budget['used'] >= limit or budget['days'].get(day, 0) >= 2:
        return {'status': 'event_budget_reached', 'messages': 0, 'quota_remaining': remaining}
    client.verify()
    bundle = builder(payload, now, report)
    if bundle.get('model') != MODEL:
        raise AlertError('Wrong event report model')
    validate_messages(bundle.get('messages'))
    sent_at = clock()
    expiry = stamp(bundle.get('expires_at'))
    from short_term_engine import session_context
    if expiry is None or sent_at >= expiry or session_context(sent_at)['session'] != report['session']:
        raise AlertError('Event prices expired while preparing the report; nothing sent')
    remaining = quota_remaining(bucket, client.quota_snapshot(), sent_at)
    if not remaining:
        store.write(state)
        return {'status': 'quota_exhausted', 'messages': 0}
    keys = [report_notice_key(recipient, key) for key in notices]
    pending = {'keys': keys, 'retry_key': str(uuid.uuid4()), 'text': '', 'test': False,
               'created_at': sent_at.isoformat(), 'expires_at': expiry.isoformat(),
               'messages': bundle['messages'], 'market_event': True}
    bucket['quota_ledger']['conservative_used'] += 1
    budget['used'] += 1
    budget['days'][day] = budget['days'].get(day, 0) + 1
    bucket['pending'] = pending
    store.write(state)
    client.push(pending)
    for key in keys:
        bucket['seen'][key] = sent_at.isoformat()
    bucket['pending'] = None
    store.write(state)
    return {'status': 'accepted_by_line', 'messages': 1, 'stocks': len(plans[:5]),
            'event_alert': True, 'quota_remaining': remaining - 1}


def monitor(payload, store, client, recipient, now, *, clock, scanner=None, builder=None):
    from short_term_service import scan
    from short_term_report import build_bundle
    from line_alert_schedule import deliver_scheduled
    from short_term_engine import session_context
    if session_context(now)['session'] == 'closed':
        return {'status': 'outside_market_sessions', 'messages': 0}
    report = (scanner or scan)(payload, clock=clock)
    publish_board(store, report)
    builder = builder or (lambda p, at, value: build_bundle(p, at, store, report=value))
    result = deliver_scheduled(payload, store, client, recipient, clock(),
                               lambda p, tickers, at, mode: builder(p, at, report), clock)
    if result.get('messages') or result.get('status') == 'expired_pending':
        return {**result, 'board_status': report['status']}
    urgent = deliver_urgent(report, payload, store, client, recipient, clock(), builder, clock)
    return {**urgent, 'scheduled_status': result['status'], 'board_status': report['status'],
            'quotes_scanned': report['counts'].get('fresh_quotes', 0)}
