"""Beginner-readable Thai short-term plans and an exact one-page PNG."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from short_term_engine import MODEL, instant

LABELS = {
    'not_common_stock': 'ไม่ใช่หุ้นสามัญ',
    'missing_stale_or_delayed_quote': 'ราคาไม่มี/เก่า/ล่าช้า',
    'no_long_momentum': 'ราคาไม่ผ่านเกณฑ์ขาขึ้นระยะสั้น',
    'no_fresh_company_catalyst': 'ไม่มีข่าวเหตุการณ์ตรงบริษัทใน 36 ชั่วโมง',
    'news_feed_unavailable': 'อ่านฟีดข่าวไม่ได้',
    'same_time_rvol_too_low': 'วอลุ่มเทียบเวลาเดียวกันยังต่ำ',
    'session_liquidity_too_low': 'มูลค่าซื้อขายรอบนี้ยังน้อย',
    'premarket_volume_too_low': 'วอลุ่มก่อนเปิดยังน้อย',
    'price_trend_not_confirmed': 'ราคา/VWAP/แนวโน้มยังไม่สอดคล้อง',
    'market_or_relative_strength': 'ตลาดหรือความแข็งแรงเทียบตลาดไม่ผ่าน',
    'outside_entry_zone_or_chasing': 'ห่างจุดเข้าหรือเสี่ยงไล่ราคา',
    'stop_distance_unsuitable': 'ระยะตัดขาดทุนไม่เหมาะ',
    'insufficient_room_after_costs': 'พื้นที่ถึงเป้าไม่พอหลังหักต้นทุน',
    'wait_for_six_closed_bars': 'รอแท่ง 5 นาทีปิดครบ 6 แท่ง',
    'insufficient_same_time_volume_history': 'ประวัติวอลุ่มเวลาเดียวกันไม่ครบ 10 วัน',
    'stale_intraday_bars': 'กราฟระหว่างวันไม่สด',
    'intraday_feed_unavailable': 'อ่านกราฟระหว่างวันไม่ได้',
    'missing_intraday_bars': 'ไม่มีกราฟระหว่างวัน',
    'invalid_intraday_bars': 'ข้อมูลแท่งราคาไม่ผ่านการตรวจ',
    'recent_bar_gap': 'ข้อมูลแท่งราคาล่าสุดขาดช่วง',
    'outside_entry_window': 'นอกช่วงเข้าแผน/ใกล้ปิดตลาด',
    'final_quote_not_fresh': 'ราคาหลังคัดกรองไม่สดพอ',
    'daily_price_scale_mismatch': 'ราคาฐานรายวันกับฟีดสดไม่สอดคล้อง',
    'not_eligible_common_stock': 'ไม่ผ่านชนิดหุ้นหรือราคาขั้นต่ำ',
    'no_material_movement': 'การเคลื่อนไหวหรือวอลุ่มยังไม่เด่น',
    'recovery_not_confirmed': 'ยังไม่ยืนยันการฟื้นตัวหลังลงแรง',
    'low_price_volume_too_low': 'วอลุ่มหุ้นราคาต่ำยังไม่ถึงเกณฑ์',
    'intraday_scan_limit': 'รอคิวตรวจกราฟระหว่างวัน',
}


def thai_time(value):
    t = instant(value)
    return t.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%d/%m %H:%M') if t else 'ไม่ทราบเวลา'


def visible_events(report):
    plans = {c['ticker'] for c in report['cards']}
    return [e for e in report.get('events', []) if e['ticker'] not in plans][:max(0, 5 - len(plans))]


def notice_ids(report):
    ids = []
    for c in report['cards']:
        from market_event_news import story_id
        story = story_id(c['ticker'], c['news'][0])
        ids.append(report['trading_date'] + ':' + story + ':plan')
    ids.extend(report['trading_date'] + ':' + e['event_id'] + ':event' for e in visible_events(report))
    return ids


def report_rows(report):
    return report['cards'] + visible_events(report)


def report_sections(row, *, plan=None):
    from short_term_context import company_view, trend_view, sma_line, rvol_line, price_text
    company, trend = company_view(row), trend_view(row)
    sections = [('บริษัท', company['business'])]
    if company['profile'] and company['profile'] != company['business']:
        sections.append(('หมวดอุตสาหกรรม', company['profile']))
    if company['financials']:
        evidence = company['financials']
        if company['financial_sources']:
            evidence += '\nที่มางบ: ' + company['financial_sources']
        sections.append(('งบสำคัญ', evidence))
    headlines = []
    for article in row['news'][:2]:
        translated = article.get('title_th')
        headlines.append('• ' + (translated or 'ต้นฉบับ (ยังไม่มีคำแปล): ' + article['title']))
    sections.append(('ข่าวสำคัญ · แปลพาดหัว' if all(n.get('title_th') for n in row['news'][:2]) else 'ข่าวสำคัญ', '\n'.join(headlines)))
    outlook = company['outlook']
    if company['counterpoint']:
        outlook += '\nอีกมุม: ' + company['counterpoint']
    sections.append(('ทิศทางธุรกิจ', outlook))
    sections.append(('แนวโน้มราคา', trend['intraday'] + '\n' + trend['daily']))
    volume = row.get('session_dollars')
    market = rvol_line(row) + ' · VWAP ' + price_text(row.get('vwap'))
    if volume is not None:
        market += f' · ซื้อขาย ${volume/1e6:,.1f} ล้าน'
    sections.append(('ตัวเลขที่ใช้ตัดสินใจ', market + '\n' + sma_line(row)))
    if plan:
        action = (f"รอเข้า ${plan['entry']:.2f}–{plan['max_entry']:.2f} | ตัดขาดทุน ${plan['stop']:.2f}\n"
                  f"เป้า 1 ${plan['target1']:.2f} | เป้า 2 ${plan['target2']:.2f}\n"
                  f"ต้นทุนเผื่อ {plan['cost_pct']:.2f}% · R:R สุทธิ {plan['net_rr']:.2f}:1 ที่เป้า 2\n"
                  f"{plan['entry_rule']}\n"
                  f"ใช้แผนถึง {thai_time(plan['valid_until'])} · {plan['cancel_rule']}\n"
                  f"ปิดแผนภายใน {thai_time(plan['exit_by'])} ไทย")
    else:
        action = row.get('action') or 'รอข้อมูลเพิ่ม'
        reasons = '; '.join(LABELS.get(k, k) for k in row.get('reasons', [])[:2])
        if reasons:
            action += '\nยังติดเงื่อนไข: ' + reasons
    sections.append(('แผนวันนี้' if plan else 'ควรทำอย่างไร', action))
    return sections


def format_report(report):
    rows = report_rows(report)
    plans = {c['ticker']: c for c in report['cards']}
    session = {'pre': 'ก่อนเปิดตลาด', 'regular': 'ระหว่างตลาด'}.get(report['session'], 'ตลาดปิด')
    text = [f"หุ้นจับตา · {session} · {thai_time(report['generated_at'])} ไทย",
            f"แผนมีเงื่อนไข {len(plans)} ตัว · ข่าว/รอติดตาม {len(visible_events(report))} ตัว"]
    if not rows:
        text.append('ข้อมูลรอบนี้ยังไม่พอจัดแผนเข้า' if report['status'] == 'data_unavailable' else 'รอบนี้ยังไม่มีหุ้นผ่านเงื่อนไข รอรอบใหม่')
        text.append('\n'.join('• ' + LABELS.get(k, k) for k, v in sorted(report['excluded'].items(), key=lambda x: -x[1])[:3]))
    for index, row in enumerate(rows, 1):
        state = 'แผนมีเงื่อนไข' if row['ticker'] in plans else 'รอฟื้นตัว' if row.get('status') == 'recovery_watch' else 'ข่าวกระทบราคา / รอติดตาม'
        text.append(f"{'─' * 20}\n{index}) {row['ticker']} — {row['name']}\n"
                    f"${row['price']:.2f} ({row['change_pct']:+.2f}%) · ราคา ณ {thai_time(row['quote_time'])} ไทย\n"
                    f"สถานะ: {state}")
        for heading, body in report_sections(row, plan=plans.get(row['ticker'])):
            text.append(heading + '\n' + body)
        sources = [f"{n['publisher']} · {thai_time(n['published_at'])} ไทย\n{n['url']}" for n in row['news'][:2]]
        text.append('ที่มาข่าว\n' + '\n'.join(sources))
    from short_term_context import GLOSSARY
    text.append('อ่านตัวเลขง่าย ๆ\n' + GLOSSARY)
    return '\n\n'.join(t for t in text if t)


def render_report(report, output):
    from PIL import Image, ImageDraw
    from stock_alert_image import ThaiText, NAVY, INK, MUTED, TEAL, BG
    from short_term_context import company_view, trend_view, sma_line, rvol_line, price_text
    from company_analysis_th import INDUSTRY_LABELS
    rows = report_rows(report)
    plans = {c['ticker']: c for c in report['cards']}
    card_height = 635
    canvas = Image.new('RGB', (1600, 440 + max(1, len(rows)) * card_height), BG)
    draw = ImageDraw.Draw(canvas)
    font = ThaiText(draw)
    draw.rectangle((0, 0, 1600, 190), fill=NAVY)
    font.line((60, 35), 'หุ้นจับตา | บริษัท • ข่าว • จังหวะซื้อขาย', 44, 'white', True)
    font.line((60, 104), f"{thai_time(report['generated_at'])} ไทย · แผน {len(plans)} · ข่าว/รอติดตาม {len(visible_events(report))}", 29, '#C3D6E8')
    y = 220
    for index, row in enumerate(rows, 1):
        company, trend = company_view(row), trend_view(row)
        plan = plans.get(row['ticker'])
        draw.rounded_rectangle((45, y, 1555, y + card_height - 20), radius=24, fill='white')
        font.line((75, y + 20), f"{index}) {row['ticker']}", 42, TEAL, True)
        font.paragraph((360, y + 31), row['name'], 1140, size=27, lines=1, color=INK)
        font.paragraph((75, y + 84), company['business'], 1430, size=25, lines=1, color=MUTED)
        state = 'แผนมีเงื่อนไข' if plan else 'รอฟื้นตัว' if row.get('status') == 'recovery_watch' else 'รอติดตาม'
        font.line((75, y + 132), f"${row['price']:.2f} ({row['change_pct']:+.2f}%) · {state}", 32, INK, True)
        industry = INDUSTRY_LABELS.get(row.get('industry'), row.get('industry', ''))
        font.paragraph((75, y + 181), rvol_line(row) + ' · VWAP ' + price_text(row.get('vwap'))
                       + ' · ' + industry, 1420, size=27, lines=1, color=TEAL, bold=True)
        font.paragraph((75, y + 224), sma_line(row), 1420, size=25, lines=1, color=MUTED)
        headline = row['news'][0].get('title_th') or row['news'][0]['title']
        font.paragraph((75, y + 274), 'ข่าว: ' + headline, 1420, size=28, lines=2, leading=37)
        direction = (company['financials'] + ' · ' if company['financials'] else '') + trend['intraday']
        font.paragraph((75, y + 364), 'ภาพรวม: ' + direction, 1420, size=26, lines=2, leading=36)
        if plan:
            action = (f"เข้า ${plan['entry']:.2f}–{plan['max_entry']:.2f} · หยุด ${plan['stop']:.2f} · เป้า ${plan['target1']:.2f} / ${plan['target2']:.2f}")
            extra = f"R:R สุทธิ {plan['net_rr']:.2f}:1 · ต้นทุนเผื่อ {plan['cost_pct']:.2f}% · ใช้ถึง {thai_time(plan['valid_until'])}"
        else:
            action = row.get('action', 'รอข้อมูลรอบใหม่')
            extra = 'รอ: ' + '; '.join(LABELS.get(k, k) for k in row.get('reasons', [])[:2])
        font.paragraph((75, y + 454), action, 1420, size=27, lines=2, leading=36, color=TEAL, bold=True)
        font.paragraph((75, y + 548), extra, 1420, size=24, lines=1, color=MUTED)
        y += card_height
    if not rows:
        draw.rounded_rectangle((45, y, 1555, y + card_height - 20), radius=24, fill='white')
        font.line((80, y + 65), 'รอบนี้ยังไม่มีหุ้นผ่านเงื่อนไข', 40, INK, True)
        for i, (key, value) in enumerate(sorted(report['excluded'].items(), key=lambda x: -x[1])[:4]):
            font.paragraph((80, y + 150 + i * 70), LABELS.get(key, key), 1420, size=28, lines=1)
        y += card_height
    font.paragraph((60, y + 5), 'RVOL: วอลุ่มเทียบเวลาเดียวกัน · 2× = ซื้อขาย 2 เท่าของปกติ', 1470, size=27, lines=1, bold=True)
    font.paragraph((60, y + 55), 'VWAP: ราคาเฉลี่ยถ่วงน้ำหนักวอลุ่ม · SMA: ราคาปิดเฉลี่ยตามจำนวนวัน', 1470, size=27, lines=1)
    font.paragraph((60, y + 113), 'อ่านข่าวทั้งสองมุม งบบริษัท และเงื่อนไขเข้า–ออกในข้อความประกอบ', 1470, size=25, lines=1, color=MUTED)
    original, preview = output / 'briefing.png', output / 'briefing-preview.png'
    canvas.save(original, optimize=True)
    small = canvas.copy(); small.thumbnail((800, 2400)); small.save(preview, optimize=True)
    return original, preview


def save_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'briefing.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'briefing.txt').write_text(format_report(report), encoding='utf-8')
    return render_report(report, output)


def build_bundle(payload, now, store, report=None):
    from short_term_service import scan
    from stock_alert_report import text_chunks
    from stock_alert_media import publish_briefing
    report = report if report is not None else scan(payload)
    output = Path(os.environ.get('LINE_REPORT_OUTPUT', 'work/line-report'))
    original, preview = save_report(report, output)
    media = publish_briefing(store, original.read_bytes(), preview.read_bytes(), report)
    messages = [{'type': 'image', 'originalContentUrl': media['original_url'], 'previewImageUrl': media['preview_url']}]
    messages.extend({'type': 'text', 'text': t} for t in text_chunks(format_report(report)))
    at = datetime.now(timezone.utc)
    expiry = min([instant(c['expires_at']) for c in report['cards']] +
                 [instant(e['quote_time']) + timedelta(minutes=3) for e in visible_events(report)] + [at + timedelta(minutes=2)])
    return {'model': MODEL, 'messages': messages, 'stocks': len(report['cards']),
            'expires_at': expiry.isoformat(), 'empty_status': report['status'],
            'events': len(visible_events(report)), 'notice_ids': notice_ids(report),
            'study_plans': report['cards'], 'generated_at': report['generated_at']}
