"""Compose one five-stock LINE briefing with immutable, verified PNG assets."""
from __future__ import annotations

import json
import os
from pathlib import Path


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
    from stock_alert_briefing import build_briefing, format_briefing_text
    from stock_alert_image import render_briefing
    from stock_alert_media import publish_briefing, MediaError

    output = Path(os.environ.get('LINE_REPORT_OUTPUT', 'work/line-report'))
    output.mkdir(parents=True, exist_ok=True)
    verified_path = Path(__file__).with_name('stock_alert_news.json')
    verified = json.loads(verified_path.read_text(encoding='utf-8')) if verified_path.exists() else {}
    briefing = build_briefing(payload, now, preferred_tickers=preferred_tickers,
                             verified_news=verified, limit=5)
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
