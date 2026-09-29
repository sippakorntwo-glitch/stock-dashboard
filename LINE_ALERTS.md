# LINE stock alerts

The `LINE stock alerts` workflow runs after each successful `Refresh Top 10 board (30 minutes)` run on `main`. GitHub scheduling can be delayed; this is not a real-time trade execution service. It reads the published Top 10 board and calls the existing `ranking_policy.is_entry` checklist again at delivery time. It never places orders or changes ranking scores.

Only current, confirmed entries can notify: score at least 80 with full scoring coverage, quote in the entry zone, current reward/risk at least 2, the existing spread/fundamental checks, ranking no older than 35 minutes, quote no older than 15 minutes, and no future source timestamps. Missing checks do not count as passed. An empty result produces no LINE message. Alerts cover the board's Top 10, drawn from the whole-catalog ranking; they do not claim a fresh quote scan of every listed security.

New qualified symbols are combined into one Thai message per run. Each symbol notifies at most once per New York market date. The message includes source quote time, score, entry zone, stop, target, current reward/risk and the dashboard link. Monthly LINE quota is checked before a new send. Exhausted quota stops delivery without purchasing or upgrading a plan.

## Configuration

Repository Actions Secrets: `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_USER_ID`. The built-in `GITHUB_TOKEN` writes only delivery state. The sender verifies the token's bot basic ID against `@618mpszx` and checks that the configured recipient is accessible. Add the OA as a friend before the setup test. No webhook, friend-list read, personal chat access, broker login, or channel secret is needed.

Run manually from Actions with `mode=test` for the one-time setup message, `mode=dry-run` to count current qualified signals without sending, or `mode=scan` for normal delivery. A successful LINE API response means LINE accepted the request, not a read receipt or proof that the phone displayed a notification.

## Delivery state and failures

The isolated `line-alert-state` branch stores HMAC identifiers and the pending public-market alert text. It never stores LINE IDs, tokens or account profiles. A durable reservation, exact message body and LINE retry UUID are saved before sending. Uncertain sends reuse that exact request within its expiry. Expired uncertain sends are suppressed for the same market date to avoid duplicate or stale notifications; the report exposes `expired_pending`. This intentionally favors avoiding stale/duplicate delivery over claiming guaranteed delivery.

Quota, permission, malformed-data and delivery failures are visible in Actions. Logs and summaries contain counts/status only, not credentials or recipient IDs. Tests use fake delivery and storage; they never call LINE. To pause alerts, disable `LINE stock alerts` in GitHub Actions; the dashboard/ranking jobs continue independently.

Official references: [LINE retry handling](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/), [LINE Messaging API](https://developers.line.biz/en/reference/messaging-api/), [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
