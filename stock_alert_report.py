"""Compose one five-stock LINE briefing with immutable, verified PNG assets."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def refresh_report_quotes(payload, tickers, fetcher=None, now=None, *, allow_closed=False, pre_market=False):
    """Refresh source prices for the five cards, without upgrading saved signals.

    Missing quotes preserve their original source timestamp. The existing
    readiness flags and entry audit are never changed by this operation.
    """
    from market_pulse import normalize_quotes, _stamp
    try:
        if fetcher is None:
            from market_pulse_service import fetch_quotes
            fetcher = fetch_quotes
        raw = fetcher(tickers)
        now = now or datetime.now(timezone.utc)
        observations = normalize_quotes(raw, tickers, now.isoformat())
        if allow_closed or pre_market:
            from stock_brief_service import normalize_brief_quotes
            observations = {ticker: normalize_brief_quotes(raw, ticker, now.isoformat())
                            for ticker in tickers}
    except Exception:
        return 0
    updated = 0
    for row in payload['items']:
        quote = observations.get(row['ticker'])
        extended = None
        if quote and (allow_closed or pre_market):
            extended, quote = quote['extended'], quote['regular']
        if pre_market and row['ticker'] in tickers:
            row['quote_session'] = 'regular'
            row.pop('extended_quote', None)
            # A current PRE observation has its own source timestamp and
            # currency. A recent POST/regular observation cannot substitute.
            pre_time = _stamp(extended.get('quote_time')) if extended else None
            currency = (row.get('info') or {}).get('currency', 'USD')
            delay = extended.get('delay_minutes') if extended else None
            if (extended and extended.get('session') == 'pre' and extended.get('market_state') == 'PRE'
                    and pre_time is not None and 0 <= (now - pre_time).total_seconds() <= 900
                    and extended['currency'] == currency and (delay is None or 0 <= delay <= 15)):
                row['regular_quote'] = quote
                row['quote'], row['quote_time'] = extended['price'], extended['quote_time']
                row['quote_session'] = 'pre'
                row['pre_change_pct'] = extended.get('change_pct')
                updated += 1
                continue
        if not quote or row['ticker'] not in tickers:
            continue
        source_time = _stamp(quote['quote_time'])
        previous_time = _stamp(row.get('quote_time'))
        currency = (row.get('info') or {}).get('currency', 'USD')
        maximum_age = 4 * 86400 if allow_closed or pre_market else 900
        if (source_time is None or not 0 <= (now - source_time).total_seconds() <= maximum_age
                or (previous_time is not None and source_time < previous_time)
                or quote['currency'] != currency or (not (allow_closed or pre_market) and quote['market_state'] != 'REGULAR')
                or quote['session'] != 'regular'
                or (quote.get('delay_minutes') is not None and quote['delay_minutes'] > 15)):
            continue
        row['quote'] = quote['price']
        row['quote_time'] = quote['quote_time']
        if extended and extended['currency'] == currency and not pre_market:
            row['extended_quote'] = extended
        updated += 1
    return updated


def text_chunks(text, limit=4400):
    """Keep every source link and word; split paragraphs, then Unicode text."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Empty report text')
    chunks, current = [], ''
    for paragraph in text.split('\n\n'):
        pieces, piece, units = [], '', 0
        for char in paragraph:
            size = len(char.encode('utf-16-le')) // 2
            if units + size > limit:
                pieces.append(piece)
                piece, units = '', 0
            piece += char
            units += size
        pieces.append(piece)
        for piece in pieces:
            candidate = current + ('\n\n' if current else '') + piece
            if len(candidate.encode('utf-16-le')) // 2 > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    if len(chunks) > 4:
        raise ValueError('Report exceeds four text messages')
    return chunks


def build_message_bundle(payload, preferred_tickers, now, mode, store):
    if mode == 'scheduled':
        from short_term_report import build_bundle
        return build_bundle(payload, now, store)
    from line_alerts import AlertError
    from stock_alert_briefing import build_briefing, format_briefing_text, select_rows
    from stock_alert_image import render_briefing
    from stock_alert_media import publish_briefing, MediaError

    output = Path(os.environ.get('LINE_REPORT_OUTPUT', 'work/line-report'))
    output.mkdir(parents=True, exist_ok=True)
    verified_path = Path(__file__).with_name('stock_alert_news.json')
    verified = json.loads(verified_path.read_text(encoding='utf-8')) if verified_path.exists() else {}
    tickers = [row['ticker'] for row in select_rows(payload, preferred_tickers=preferred_tickers)]
    pre_market = mode == 'scheduled' and payload.get('report_session') == 'pre'
    updated_quotes = refresh_report_quotes(payload, tickers, allow_closed=mode == 'preview', pre_market=pre_market)
    now = datetime.now(timezone.utc)
    briefing = build_briefing(payload, now, preferred_tickers=preferred_tickers,
                             verified_news=verified, limit=5)
    briefing['quotes_refreshed'] = updated_quotes
    if mode == 'scan' and any(card['status'] != 'entry' for card in briefing['cards']
                              if card['ticker'] in preferred_tickers):
        raise AlertError('A current quote no longer passes the entry checks; nothing sent')
    briefing['report_mode'] = mode
    briefing['new_signal_tickers'] = preferred_tickers
    text = format_briefing_text(briefing)
    if mode == 'preview':
        text = 'รายงานตัวอย่างรูปแบบใหม่ · ข้อมูลหุ้นจริงตามเวลาที่แสดง\n\n' + text
    chunks = text_chunks(text)
    (output / 'briefing.json').write_text(json.dumps(briefing, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'briefing.txt').write_text(text, encoding='utf-8')
    # Renderer contract is deliberately file-based so the same exact images
    # can be reviewed as workflow artifacts and delivered to LINE.
    result = render_briefing(briefing, output)
    original = Path(result['original_path'])
    preview = Path(result['preview_path'])
    try:
        media = publish_briefing(store, original.read_bytes(), preview.read_bytes(), briefing)
    except MediaError:
        raise AlertError('Report image publication failed; no LINE message sent') from None
    messages = [{'type': 'image', 'originalContentUrl': media['original_url'],
                 'previewImageUrl': media['preview_url']}]
    messages.extend({'type': 'text', 'text': chunk} for chunk in chunks)
    from datetime import timedelta
    current_quotes = [datetime.fromisoformat(card['quote_time']) + timedelta(minutes=15)
                      for card in briefing['cards'] if card['quote_fresh']]
    expires = min(current_quotes + [now + timedelta(minutes=5)])
    return {'messages': messages, 'stocks': briefing['actual_count'], 'expires_at': expires.isoformat()}


def render_review(input_path, output_dir):
    """Prepare a real-data report for review; no LINE client or media publication."""
    from stock_alert_briefing import build_briefing, format_briefing_text, select_rows
    from stock_alert_image import render_briefing
    payload = json.loads(Path(input_path).read_text(encoding='utf-8'))
    tickers = [row['ticker'] for row in select_rows(payload)]
    updated = refresh_report_quotes(payload, tickers, allow_closed=True)
    now = datetime.now(timezone.utc)
    verified = json.loads(Path(__file__).with_name('stock_alert_news.json').read_text(encoding='utf-8'))
    briefing = build_briefing(payload, now, verified_news=verified)
    briefing.update(report_mode='review', quotes_refreshed=updated)
    text = format_briefing_text(briefing)
    text_chunks(text)  # Verify the same delivery-size limit before saving the preview.
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'briefing.json').write_text(json.dumps(briefing, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'briefing.txt').write_text(text, encoding='utf-8')
    render_briefing(briefing, output)
    print('STOCK_REPORT_REVIEW: ' + json.dumps({
        'stocks': len(briefing['cards']), 'generated_at': briefing['generated_at'],
        'technical_available': sum(bool(card['technical']['ema200']) for card in briefing['cards']),
        'news_available': sum(card['news']['feed_status'] == 'available' for card in briefing['cards']),
        'messages_sent': 0,
    }))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Render a stock report without sending LINE messages')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default='work/stock-report-review')
    args = parser.parse_args()
    render_review(args.input, args.output)
