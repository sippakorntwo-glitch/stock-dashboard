"""Owner-only LINE alerts from the published, strictly confirmed Top 10 board.

Credentials and recipient IDs are environment-only. The separate state branch
contains opaque deduplication keys and public market-message text, never IDs or
tokens. Persist a retry key before sending; uncertain sends never get a new key.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from ranking_policy import POLICY, is_entry

MODEL = 'existing-100-point-pullback-v1'
STATE_BRANCH = 'line-alert-state'
STATE_PATH = 'delivery-state.json'
DASHBOARD_URL = 'https://my-stock-terminal.streamlit.app/'
EXPECTED_BOT = '@618mpszx'
UTC = timezone.utc


class AlertError(RuntimeError):
    """A deliberately credential-free error safe to print in public CI logs."""


def stamp(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (float, int)):
            return datetime.fromtimestamp(value, UTC)
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def fresh(value, now, seconds):
    parsed = stamp(value)
    return parsed is not None and 0 <= (now - parsed).total_seconds() <= seconds


def number(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value))


def eligible(payload, now):
    if (not isinstance(payload, dict) or payload.get('schema') != 1
            or payload.get('model') != MODEL or payload.get('entry_policy') != POLICY
            or not isinstance(payload.get('items'), list) or len(payload['items']) > 10):
        raise AlertError('Unsupported or invalid ranking payload')
    if not fresh(payload.get('computed_at'), now, 35 * 60):
        return []
    result, seen = [], set()
    for row in payload['items']:
        if not isinstance(row, dict):
            raise AlertError('Invalid ranking row')
        ticker = row.get('ticker', '')
        if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}', ticker) or ticker in seen:
            raise AlertError('Invalid or repeated ranking symbol')
        seen.add(ticker)
        if not all(number(row.get(k)) for k in ('score', 'coverage')):
            raise AlertError('Invalid ranking score')
        if not 0 <= row['score'] <= row['coverage'] <= 100:
            raise AlertError('Invalid ranking score range')
        if type(row.get('ready_at_calculation')) is not bool or type(row.get('qualified')) is not bool:
            raise AlertError('Invalid ranking readiness')
        if (row.get('asset_type') not in ('Stock', 'ETF', 'Common Stock')
                or not fresh(row.get('quote_time'), now, 15 * 60)
                or not fresh(row.get('info_fetched_at'), now, 7 * 86400)):
            continue
        if is_entry(row, payload, now=now):
            result.append(row)
    return result


def opaque_key(recipient, label):
    return hmac.new(recipient.encode(), label.encode(), hashlib.sha256).hexdigest()


def format_alert(rows, now):
    clock = now.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%d/%m/%Y %H:%M')
    lines = [f'🔔 หุ้นผ่านเกณฑ์แดชบอร์ด {clock} น. (ไทย)',
             'คะแนน ≥80/100 · ข้อมูลคะแนนครบ · ผ่านรายการตรวจเข้าซื้อเดิม']
    for row in rows:
        q, stop, target = (float(row[k]) for k in ('quote', 'stop', 'target'))
        quote_clock = stamp(row['quote_time']).astimezone(ZoneInfo('Asia/Bangkok')).strftime('%H:%M:%S')
        lines.extend(['', f"{row['ticker']} · {row['score']:g}/100",
                      f'ราคา ${q:.4f} · เวลาราคา {quote_clock} น.',
                      f"โซนเข้า ${row['zone_low']:.4f}–${row['zone_high']:.4f}",
                      f'Stop ${stop:.4f} · เป้าหมาย ${target:.4f}',
                      f'R:R ที่ราคานี้ {(target-q)/(q-stop):.2f}'])
    lines.extend(['', DASHBOARD_URL])
    message = '\n'.join(lines)
    if len(message.encode('utf-16-le')) // 2 > 4900:
        raise AlertError('Alert message exceeds safe length')
    return message


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class JsonHTTP:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, method, url, token, body=None, extra=None):
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
                   'Content-Type': 'application/json', 'User-Agent': 'StockDashboard-LineAlerts/1'}
        headers.update(extra or {})
        request = urllib.request.Request(url, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode())
        try:
            response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, OSError, TimeoutError):
            raise AlertError('Network request failed; no credential details logged') from None
        with response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise AlertError('Response exceeds size limit')
            try:
                data = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                raise AlertError('Invalid JSON response') from None
            return response.code, dict(response.headers.items()), data


class GitHubState:
    def __init__(self, repo, token, http):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise AlertError('Invalid repository')
        self.base = 'https://api.github.com/repos/' + repo
        self.token, self.http, self.sha = token, http, None

    def call(self, method, path, body=None, missing=False):
        code, _, data = self.http.call(method, self.base + path, self.token, body)
        if missing and code == 404:
            return None
        if not 200 <= code < 300:
            raise AlertError(f'GitHub state request failed (HTTP {code})')
        return data

    def read(self):
        branch = self.call('GET', '/git/ref/heads/' + STATE_BRANCH, missing=True)
        if branch is None:
            tree = self.call('POST', '/git/trees', {'tree': [{'path': STATE_PATH, 'mode': '100644',
                                                          'type': 'blob', 'content': '{"schema":1,"recipients":{}}'}]})
            commit = self.call('POST', '/git/commits', {'message': 'Initialize LINE delivery state',
                                                       'tree': tree['sha'], 'parents': []})
            self.call('POST', '/git/refs', {'ref': 'refs/heads/' + STATE_BRANCH, 'sha': commit['sha']})
        data = self.call('GET', '/contents/' + STATE_PATH + '?ref=' + STATE_BRANCH)
        self.sha = data['sha']
        try:
            state = json.loads(base64.b64decode(data['content'], validate=False))
        except (ValueError, KeyError, TypeError):
            raise AlertError('Invalid persisted delivery state') from None
        if not isinstance(state, dict) or state.get('schema') != 1 or not isinstance(state.get('recipients'), dict):
            raise AlertError('Unsupported delivery state')
        return state

    def write(self, state):
        raw = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 900_000:
            raise AlertError('Delivery state exceeds size limit')
        result = self.call('PUT', '/contents/' + STATE_PATH,
                           {'message': 'Update LINE delivery state [skip ci]', 'branch': STATE_BRANCH,
                            'sha': self.sha, 'content': base64.b64encode(raw).decode()})
        self.sha = result['content']['sha']


class LineClient:
    def __init__(self, token, recipient, http):
        if not token or not re.fullmatch(r'U[0-9a-f]{32}', recipient):
            raise AlertError('Missing LINE secrets or invalid recipient')
        self.token, self.recipient, self.http = token, recipient, http

    def call(self, method, suffix, body=None, extra=None):
        return self.http.call(method, 'https://api.line.me/v2/bot/' + suffix, self.token, body, extra)

    def verify(self):
        code, _, bot = self.call('GET', 'info')
        if code != 200 or bot.get('basicId') != EXPECTED_BOT:
            raise AlertError('LINE token does not match the expected bot')
        code, _, _ = self.call('GET', 'profile/' + self.recipient)
        if code != 200:
            raise AlertError('Recipient unavailable: add this LINE bot as a friend first')

    def available(self):
        code, _, quota = self.call('GET', 'message/quota')
        if code != 200:
            raise AlertError('Cannot verify LINE message quota')
        if quota.get('type') == 'none':
            return True
        code, _, usage = self.call('GET', 'message/quota/consumption')
        if code != 200 or not number(usage.get('totalUsage')) or not number(quota.get('value')):
            raise AlertError('Cannot verify LINE quota usage')
        return quota.get('type') == 'limited' and usage['totalUsage'] < quota['value']

    def quota_snapshot(self):
        code, _, quota = self.call('GET', 'message/quota')
        code2, _, usage = self.call('GET', 'message/quota/consumption')
        limit, used = quota.get('value'), usage.get('totalUsage')
        if (code != 200 or code2 != 200 or quota.get('type') != 'limited'
                or not number(limit) or not number(used) or limit < 0 or used < 0
                or int(limit) != limit or int(used) != used):
            raise AlertError('Cannot verify a finite LINE monthly quota')
        return {'type': 'limited', 'limit': int(limit), 'used': int(used),
                'remaining': max(0, int(limit) - int(used))}

    def push(self, pending):
        messages = pending.get('messages') or [{'type': 'text', 'text': pending['text']}]
        validate_messages(messages)
        body = {'to': self.recipient, 'messages': messages}
        # Stored retry key and body are reused verbatim after uncertain responses.
        for attempt in range(2):
            expiry = stamp(pending.get('expires_at'))
            if expiry is None or datetime.now(UTC) >= expiry:
                raise AlertError('Reserved message expired before send; no stale signal sent')
            try:
                code, headers, _ = self.call('POST', 'message/push', body,
                                             {'X-Line-Retry-Key': pending['retry_key']})
            except AlertError:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise
            lower = {k.lower(): v for k, v in headers.items()}
            if code == 200 or (code == 409 and lower.get('x-line-accepted-request-id')):
                return
            if code >= 500 and attempt == 0:
                time.sleep(1)
                continue
            raise AlertError(f'LINE push not accepted (HTTP {code}); stored retry retained')


def validate_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 5:
        raise AlertError('Invalid LINE report message count')
    for message in messages:
        if not isinstance(message, dict):
            raise AlertError('Invalid LINE report message')
        if message.get('type') == 'text':
            value = message.get('text')
            if not isinstance(value, str) or not 1 <= len(value.encode('utf-16-le')) // 2 <= 4900:
                raise AlertError('Invalid LINE report text length')
        elif message.get('type') == 'image':
            for field in ('originalContentUrl', 'previewImageUrl'):
                url = message.get(field)
                if not isinstance(url, str) or not re.fullmatch(
                        r'https://raw\.githubusercontent\.com/sippakorntwo-glitch/stock-dashboard/'
                        r'[0-9a-f]{40}/briefing(?:-preview)?\.png', url):
                    raise AlertError('Image URL must use the immutable report asset')
        else:
            raise AlertError('Unsupported LINE report message type')


def deliver(payload, store, client, recipient, now, mode='scan', message_builder=None, clock=None):
    clock = clock or (lambda: now)
    if mode == 'scheduled':
        from line_alert_schedule import deliver_scheduled
        return deliver_scheduled(payload, store, client, recipient, now, message_builder, clock)
    state = store.read()
    scope = opaque_key(recipient, 'recipient-scope-v1')
    bucket = state['recipients'].setdefault(scope, {'seen': {}, 'pending': None})
    if not isinstance(bucket.get('seen'), dict):
        raise AlertError('Invalid recipient delivery state')
    # Retain a bounded month of hashes; the one-off setup-test key never expires.
    bucket['seen'] = {k: v for k, v in bucket['seen'].items()
                      if v == 'setup-test' or (stamp(v) is not None and stamp(v) >= now - timedelta(days=35))}
    pending = bucket.get('pending')
    expired = 0
    resumed = 0
    if pending:
        if not stamp(pending.get('expires_at')) or stamp(pending['expires_at']) <= now:
            # Delivery might have succeeded before a crash. Suppress these keys
            # for the day, rather than resend with a new key or send stale prices.
            for key in pending['keys']:
                bucket['seen'][key] = 'setup-test' if pending.get('test') else now.isoformat()
            bucket['pending'] = None
            store.write(state)
            expired = 1
        else:
            client.verify()
            # Retry an already-reserved request even if quota was exhausted by it.
            client.push(pending)
            for key in pending['keys']:
                bucket['seen'][key] = 'setup-test' if pending.get('test') else now.isoformat()
            bucket['pending'] = None
            store.write(state)
            resumed = 1
    permanent = mode in ('test', 'preview')
    test_key = opaque_key(recipient, 'five-stock-report-preview-v2' if mode == 'preview' else 'setup-test-v1')
    if permanent:
        if test_key in bucket['seen']:
            return {'status': 'accepted_by_line' if resumed else 'test_already_processed',
                    'messages': resumed, 'expired_pending': expired}
        keys, rows = [test_key], []
        text = ('✅ ทดสอบเชื่อมต่อ Sippakorn Stock Alerts สำเร็จ\n'
                'ระบบจะตรวจผลจัดอันดับทุก 30 นาที และแจ้งเฉพาะหุ้นที่ผ่านเกณฑ์เข้าซื้อเดิมครบ\n'
                'คะแนน ≥80/100 · ราคาในโซน · R:R ≥2 · ข้อมูลยังไม่หมดอายุ\n'
                'ไม่ส่งหุ้นซ้ำในวันตลาดสหรัฐเดียวกัน; หากไม่มีหุ้นผ่านจะไม่ส่งแจ้งเตือน\n'
                'นี่คือข้อความทดสอบ ไม่ใช่สัญญาณซื้อ\n' + DASHBOARD_URL)
        expires = now + timedelta(hours=1)
        if mode == 'preview':
            if message_builder is None:
                raise AlertError('Five-stock preview requires the report builder')
            text = 'รายงานตัวอย่างรูปแบบใหม่ พร้อมข้อมูลหุ้นจริงตามเวลาที่แสดง'
    else:
        day = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        rows = [row for row in eligible(payload, now)
                if opaque_key(recipient, day + ':' + row['ticker']) not in bucket['seen']][:5]
        if not rows:
            return {'status': 'accepted_by_line' if resumed else 'no_new_qualified_stocks',
                    'messages': resumed, 'expired_pending': expired}
        keys = [opaque_key(recipient, day + ':' + row['ticker']) for row in rows]
        text = format_alert(rows, now)
        expires = min([stamp(row['quote_time']) + timedelta(minutes=15) for row in rows]
                      + [stamp(payload['computed_at']) + timedelta(minutes=35)])
    client.verify()
    if not client.available():
        return {'status': 'quota_exhausted', 'messages': resumed, 'expired_pending': expired}
    rich = None
    if message_builder is not None and mode != 'test':
        rich = message_builder(payload, [row['ticker'] for row in rows], now, mode)
        if not isinstance(rich, dict):
            raise AlertError('Invalid report builder result')
        validate_messages(rich.get('messages'))
        if not isinstance(rich.get('stocks'), int) or not 1 <= rich['stocks'] <= 5:
            raise AlertError('Invalid report stock count')
        if mode == 'scan':
            current = {row['ticker'] for row in eligible(payload, clock())}
            if any(row['ticker'] not in current for row in rows):
                raise AlertError('A signal expired while preparing the report; nothing sent')
        if clock() >= expires:
            raise AlertError('Report reservation expired before delivery; nothing sent')
    pending = {'keys': keys, 'retry_key': str(uuid.uuid4()), 'text': text,
               'created_at': now.isoformat(), 'expires_at': expires.isoformat(), 'test': permanent}
    if rich is not None:
        pending['messages'] = rich['messages']
    bucket['pending'] = pending
    store.write(state)  # No outbound message until durable reservation succeeds.
    client.push(pending)
    for key in keys:
        bucket['seen'][key] = 'setup-test' if permanent else now.isoformat()
    bucket['pending'] = None
    store.write(state)
    return {'status': 'accepted_by_line', 'messages': 1 + resumed,
            'stocks': rich['stocks'] if rich else len(rows), 'expired_pending': expired}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('scan', 'test', 'dry-run', 'preview', 'scheduled', 'schedule-check'), default='scheduled')
    args = parser.parse_args()
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise AlertError('Delivery is restricted to the owner workflow on main')
    token, recipient = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', ''), os.environ.get('LINE_USER_ID', '')
    github_token = os.environ.get('GITHUB_TOKEN', '')
    if not github_token:
        raise AlertError('Missing workflow state permission')
    http = JsonHTTP()
    store = GitHubState(repo, github_token, http)
    payload = None
    if args.mode not in ('test', 'schedule-check'):
        raw = store.call('GET', '/contents/top10.json?ref=dashboard-rankings')
        try:
            payload = json.loads(base64.b64decode(raw['content']))
        except (ValueError, KeyError, TypeError):
            raise AlertError('Cannot read published ranking') from None
    now = datetime.now(UTC)
    if args.mode == 'schedule-check':
        from line_alert_schedule import schedule_summary
        report = schedule_summary(LineClient(token, recipient, http).quota_snapshot(), now)
    elif args.mode == 'dry-run':
        report = {'status': 'dry_run', 'eligible': len(eligible(payload, now)), 'messages': 0}
    else:
        from stock_alert_report import build_message_bundle
        builder = lambda data, tickers, at, mode: build_message_bundle(data, tickers, at, mode, store)
        report = deliver(payload, store, LineClient(token, recipient, http), recipient, now, args.mode,
                         message_builder=builder, clock=lambda: datetime.now(UTC))
    report['checked_at'] = now.isoformat()
    print('LINE_ALERT_REPORT:', json.dumps(report))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as out:
            out.write('### LINE alert delivery\n\n```json\n' + json.dumps(report, indent=2) + '\n```\n')


if __name__ == '__main__':
    try:
        main()
    except AlertError as error:
        print('LINE_ALERT_ERROR:', str(error), file=sys.stderr)
        sys.exit(1)
