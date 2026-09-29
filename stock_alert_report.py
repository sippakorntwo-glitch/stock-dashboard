"""Compose one five-stock LINE briefing with immutable, verified PNG assets."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def refresh_report_quotes(payload, tickers, fetcher=None, now=None):
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
    except Exception:
        return 0
    updated = 0
    for row in payload['items']:
        quote = observations.get(row['ticker'])
        if not quote or row['ticker'] not in tickers:
            continue
        source_time = _stamp(quote['quote_time'])
        previous_time = _stamp(row.get('quote_time'))
        currency = (row.get('info') or {}).get('currency', 'USD')
        if (source_time is None or not 0 <= (now - source_time).total_seconds() <= 900
                or (previous_time is not None and source_time < previous_time)
                or quote['currency'] != currency or quote['market_state'] != 'REGULAR'
                or quote['session'] != 'regular'
                or (quote.get('delay_minutes') is not None and quote['delay_minutes'] > 15)):
            continue
        row['quote'] = quote['price']
        row['quote_time'] = quote['quote_time']
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
    from line_alerts import AlertError
    from stock_alert_briefing import build_briefing, format_briefing_text, select_rows
    from stock_alert_image import render_briefing
    from stock_alert_media import publish_briefing, MediaError

    output = Path(os.environ.get('LINE_REPORT_OUTPUT', 'work/line-report'))
    output.mkdir(parents=True, exist_ok=True)
    verified_path = Path(__file__).with_name('stock_alert_news.json')
    verified = json.loads(verified_path.read_text(encoding='utf-8')) if verified_path.exists() else {}
    tickers = [row['ticker'] for row in select_rows(payload, preferred_tickers=preferred_tickers)]
    updated_quotes = refresh_report_quotes(payload, tickers)
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
    return {'messages': messages, 'stocks': briefing['actual_count']}
