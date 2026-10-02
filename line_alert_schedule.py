"""Monthly LINE allocation across actual NYSE sessions, including pre-market.

The event monitor checks these half-hour slots. A delayed run can send
only its current slot, never a backlog. One push to the configured owner is one
quota unit, including its image and all text objects.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
THAI = ZoneInfo('Asia/Bangkok')
SLOT_MINUTES = 30
PRE_START_HOUR = 7
PRE_SHARE = 0.30


def period_bounds(now):
    local = now.astimezone(THAI)
    begin = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
    return begin.strftime('%Y-%m'), begin.astimezone(UTC), end.astimezone(UTC)


@lru_cache(maxsize=12)
def month_slots(period):
    import pandas_market_calendars as mcal
    begin = datetime.fromisoformat(period + '-01').replace(tzinfo=THAI)
    _, begin, end = period_bounds(begin)
    schedule = mcal.get_calendar('NYSE').schedule(
        start_date=(begin.astimezone(NY) - timedelta(days=1)).date(),
        end_date=end.astimezone(NY).date())
    slots = []
    for day, session in schedule.iterrows():
        opening = session['market_open'].to_pydatetime().astimezone(UTC)
        closing = session['market_close'].to_pydatetime().astimezone(UTC)
        start = opening.astimezone(NY).replace(hour=PRE_START_HOUR, minute=15)
        current = start.astimezone(UTC)
        while current < closing:
            session_name = 'pre' if current < opening else 'regular'
            expiry = min(current + timedelta(minutes=15), opening if session_name == 'pre' else closing)
            if begin <= current < end and expiry <= end:
                slots.append({'id': current.isoformat(), 'start': current.isoformat(),
                              'expires_at': expiry.isoformat(), 'session': session_name,
                              'trading_date': day.date().isoformat()})
            current += timedelta(minutes=SLOT_MINUTES)
    return tuple(slots)


def _time(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def current_slot(now):
    period, _, _ = period_bounds(now)
    return next((dict(slot) for slot in month_slots(period)
                 if _time(slot['start']) <= now < _time(slot['expires_at'])), None)


def _spread(items, count):
    if not count:
        return []
    if count == 1:
        return [items[-1]]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def select_day_slots(slots, count):
    count = min(count, len(slots))
    pre = [slot for slot in slots if slot['session'] == 'pre']
    regular = [slot for slot in slots if slot['session'] == 'regular']
    n_pre = min(len(pre), max(1, round(count * PRE_SHARE))) if count and pre else 0
    n_pre = max(n_pre, count - len(regular))
    selected = _spread(pre, n_pre) + _spread(regular, count - n_pre)
    return sorted(selected, key=lambda slot: slot['start'])


def allocation(period, remaining, first_day=None):
    groups = defaultdict(list)
    for slot in month_slots(period):
        if first_day is None or slot['trading_date'] >= first_day:
            groups[slot['trading_date']].append(dict(slot))
    days, result = sorted(groups), {}
    for index, day in enumerate(days):
        future_capacity = sum(len(groups[value]) for value in days[index + 1:])
        desired = max(math.ceil(remaining / (len(days) - index)), remaining - future_capacity)
        count = min(remaining, len(groups[day]), desired)
        result[day] = select_day_slots(groups[day], count)
        remaining -= count
    return result, remaining


def quota_remaining(bucket, quota, now):
    """Account for API lag by charging each reservation durably before a push."""
    from line_alerts import AlertError
    if quota.get('type') != 'limited':
        raise AlertError('A finite LINE quota is required for monthly allocation')
    period, _, _ = period_bounds(now)
    ledger = bucket.get('quota_ledger')
    if not isinstance(ledger, dict) or ledger.get('period') != period:
        ledger = {'period': period, 'conservative_used': quota['used'], 'last_api_used': quota['used']}
        bucket['quota_ledger'] = ledger
    # Counter resets near the month boundary can precede Thai midnight. The
    # live API remains authoritative; no reservation is refunded mid-month.
    local = now.astimezone(THAI)
    last_day = (local + timedelta(days=1)).month != local.month
    reset_window = (local.day == 1 and local.hour < 6) or (last_day and local.hour >= 21)
    if reset_window and quota['used'] == 0 and ledger.get('last_api_used', 0) > 0:
        ledger['conservative_used'] = quota['used']
    ledger['conservative_used'] = max(ledger['conservative_used'], quota['used'])
    ledger['last_api_used'] = quota['used']
    return max(0, quota['limit'] - ledger['conservative_used'])


def planned_slot(bucket, quota, now):
    period, _, _ = period_bounds(now)
    remaining = quota_remaining(bucket, quota, now)
    slot = current_slot(now)
    if slot is None or not remaining:
        return None
    plans = bucket.setdefault('schedule_plans', {})
    # Keep bounded public timestamps only, no recipient identity or credentials.
    for old in sorted(plans)[:-2]:
        del plans[old]
    days = plans.setdefault(period, {})
    day = slot['trading_date']
    if day not in days:
        plan, _ = allocation(period, remaining, first_day=day)
        days[day] = plan.get(day, [])
    return slot if any(item['id'] == slot['id'] for item in days[day]) else None


def schedule_summary(quota, now):
    period, _, _ = period_bounds(now)
    remaining = max(0, quota['limit'] - quota['used'])
    full, unused = allocation(period, quota['limit'])
    current, current_unused = allocation(period, remaining, now.astimezone(NY).date().isoformat())
    future = [slot for slots in current.values() for slot in slots if _time(slot['expires_at']) > now]
    next_period = period_bounds(period_bounds(now)[2] + timedelta(seconds=1))[0]
    next_full, next_unused = allocation(next_period, quota['limit'])
    example = next((slots for slots in next_full.values() if any(slot['session'] == 'pre' for slot in slots)), [])
    return {'period': period, 'quota': quota, 'monthly_planned': sum(map(len, full.values())),
            'unallocatable': unused, 'remaining_future_rounds': len(future),
            'remaining_above_capacity': current_unused,
            'next_period': next_period, 'next_month_planned': sum(map(len, next_full.values())),
            'next_month_above_capacity': next_unused,
            'example_day': example[0]['trading_date'] if example else None,
            'example_pre_thai': [_time(s['start']).astimezone(THAI).strftime('%H:%M') for s in example if s['session'] == 'pre'],
            'example_regular_thai': [_time(s['start']).astimezone(THAI).strftime('%H:%M') for s in example if s['session'] == 'regular'],
            'messages_sent': 0}


def deliver_scheduled(payload, store, client, recipient, now, message_builder, clock):
    from line_alerts import AlertError, fresh, opaque_key, stamp, validate_messages
    from short_term_engine import MODEL
    import uuid
    state = store.read()
    scope = opaque_key(recipient, 'recipient-scope-v1')
    bucket = state['recipients'].setdefault(scope, {'seen': {}, 'pending': None})
    if not isinstance(bucket.get('seen'), dict):
        raise AlertError('Invalid recipient delivery state')
    bucket['seen'] = {key: value for key, value in bucket['seen'].items()
                      if value == 'setup-test' or (stamp(value) is not None and stamp(value) >= now - timedelta(days=35))}
    pending = bucket.get('pending')
    if pending:
        expiry = stamp(pending.get('expires_at'))
        if expiry is not None and now < expiry:
            client.verify()
            client.push(pending)
            status, messages = 'accepted_by_line', 1
        else:
            status, messages = 'expired_pending', 0
        for key in pending['keys']:
            bucket['seen'][key] = 'setup-test' if pending.get('test') else now.isoformat()
        bucket['pending'] = None
        store.write(state)
        # Do not send another report in the same invocation after a retry.
        return {'status': status, 'messages': messages, 'resumed': messages}
    if current_slot(now) is None:
        return {'status': 'outside_scheduled_window', 'messages': 0}
    quota = client.quota_snapshot()
    before = repr(bucket)
    slot = planned_slot(bucket, quota, now)
    if repr(bucket) != before:
        store.write(state)
    remaining = quota_remaining(bucket, quota, now)
    if slot is None:
        return {'status': 'quota_exhausted' if not remaining else 'not_a_planned_round',
                'messages': 0, 'quota_remaining': remaining}
    key = opaque_key(recipient, 'scheduled-v1:' + slot['id'])
    if key in bucket['seen']:
        return {'status': 'scheduled_round_already_processed', 'messages': 0}
    if not fresh(payload.get('computed_at'), now, 35 * 60):
        return {'status': 'ranking_not_current', 'messages': 0}
    if message_builder is None:
        raise AlertError('Scheduled delivery requires a report builder')
    client.verify()
    payload['report_session'] = slot['session']
    payload['schedule_slot'] = slot
    bundle = message_builder(payload, [], now, 'scheduled')
    if (not isinstance(bundle, dict) or bundle.get('model') != MODEL
            or type(bundle.get('stocks')) is not int or not 0 <= bundle['stocks'] <= 5):
        raise AlertError('Scheduled report requires zero to five short-term plans')
    validate_messages(bundle.get('messages'))
    sent_at = clock()
    if current_slot(sent_at) != slot or not fresh(payload['computed_at'], sent_at, 35 * 60):
        raise AlertError('Scheduled round expired while preparing the report; nothing sent')
    expiry = min(_time(slot['expires_at']), stamp(payload['computed_at']) + timedelta(minutes=35),
                 stamp(bundle.get('expires_at')) or sent_at + timedelta(minutes=2))
    if sent_at >= expiry:
        raise AlertError('Scheduled report prices expired before delivery; nothing sent')
    keys = [key]
    from market_event_monitor import report_notice_key
    notice_keys = [report_notice_key(recipient, value) for value in bundle.get('notice_ids', [])]
    if not bundle['stocks'] and bundle.get('events', 0) and notice_keys and all(k in bucket['seen'] for k in notice_keys):
        bucket['seen'][key] = sent_at.isoformat()
        store.write(state)
        return {'status': 'event_summary_already_sent', 'messages': 0, 'stocks': 0,
                'quota_remaining': remaining}
    keys.extend(notice_keys)
    if not bundle['stocks'] and not bundle.get('events', 0):
        # Monthly quota is a ceiling, never an incentive to manufacture picks.
        # One empty/data-failure summary per session; keep scanning later slots.
        empty_key = opaque_key(recipient, 'short-term-empty-v1:' + slot['trading_date'] + ':' + slot['session'])
        if empty_key in bucket['seen']:
            bucket['seen'][key] = sent_at.isoformat()
            store.write(state)
            return {'status': 'no_setup_summary_already_sent', 'messages': 0, 'stocks': 0,
                    'quota_remaining': remaining}
        keys.append(empty_key)
    # Check again after report preparation; the API can also include other OA use.
    quota = client.quota_snapshot()
    remaining = quota_remaining(bucket, quota, sent_at)
    if not remaining:
        store.write(state)
        return {'status': 'quota_exhausted', 'messages': 0}
    bucket['quota_ledger']['conservative_used'] += 1
    pending = {'keys': keys, 'retry_key': str(uuid.uuid4()), 'text': '',
               'created_at': sent_at.isoformat(), 'expires_at': expiry.isoformat(),
               'test': False, 'scheduled_slot': slot, 'messages': bundle['messages']}
    bucket['pending'] = pending
    store.write(state)
    client.push(pending)
    for delivered_key in keys:
        bucket['seen'][delivered_key] = sent_at.isoformat()
    bucket['pending'] = None
    store.write(state)
    return {'status': 'accepted_by_line', 'messages': 1, 'stocks': bundle['stocks'],
            'session': slot['session'], 'slot': slot['start'], 'quota_remaining': remaining - 1}
