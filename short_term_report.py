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
}


def thai_time(value):
    t = instant(value)
    return t.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%d/%m %H:%M') if t else 'ไม่ทราบเวลา'


def format_report(report):
    cards = report['cards']
    session = 'ก่อนเปิดตลาด' if report['session'] == 'pre' else 'ระหว่างตลาด' if report['session'] == 'regular' else 'ตลาดปิด'
    counts = report['counts']
    text = [f"คัดหุ้นเทรดสั้น · {session} · {thai_time(report['generated_at'])} ไทย",
            f"ผ่าน {len(cards)} ตัว จากหุ้นสภาพคล่องสูง {counts.get('universe', 0)} ตัว · ข่าวตรวจ {counts.get('news_checked', 0)} · กราฟตรวจ {counts.get('charts_checked', 0)}\n"
            'เลือกสูงสุด 5 ตัวตามข้อมูลที่ตรวจได้; จำนวนเหตุผลตัดออกอาจซ้ำตัวกัน']
    if not cards:
        heading = ('ข้อมูลรอบนี้ไม่ครบ จึงยังจัดแผนเข้าไม่ได้' if report['status'] == 'data_unavailable' else
                   'ตลาดปิด รอคัดใหม่ในวันซื้อขาย' if report['status'] == 'market_closed' else
                   'รอบนี้ยังไม่มีแผนผ่านเกณฑ์ รอรอบถัดไป')
        text.append(heading)
        reasons = sorted(report['excluded'].items(), key=lambda x: -x[1])[:6]
        text.append('\n'.join(f"• {LABELS.get(k, k)}: {v}" for k, v in reasons) or
                    'ยังไม่มีข้อมูลใหม่พอให้ประเมินข่าว วอลุ่ม และจุดเข้า–ออก')
    for index, c in enumerate(cards, 1):
        text.append(f"{index}. {c['ticker']} — {c['name']}\nหมวด {c['sector']} / {c['industry']}\n"
                    f"แผนรอเงื่อนไข · ราคา ${c['price']:.2f} ({c['change_pct']:+.2f}%) ณ {thai_time(c['quote_time'])}\n"
                    f"วอลุ่ม {c['session_volume']:,.0f} หุ้น / ${c['session_dollars']/1e6:,.1f} ล้าน · RVOL {c['rvol']:.2f} เท่า\n"
                    f"RVOL เทียบเวลานี้ของ {c['rvol_sessions']} วันก่อนหน้า · VWAP ${c['vwap']:.2f}\n"
                    'ปัจจัยสนับสนุน: ราคาเหนือ VWAP และวอลุ่มผ่านเกณฑ์; วอลุ่มนี้เป็นยอดซื้อขายรวม ไม่ใช่ยอดซื้อสุทธิ')
        for n in c['news']:
            text.append(f"ข่าวเหตุการณ์: {n['title']}\n{n['publisher']} · {thai_time(n['published_at'])}\n"
                        f"ประเด็นวิเคราะห์: {n['context']}\nข้อมูลที่อ่านได้: พาดหัวข่าว; ผลบวก/ลบจากเนื้อหาฉบับเต็มยังไม่ยืนยัน\n{n['url']}")
        text.append(f"แผนจบในวัน: จุดเข้า ${c['entry']:.2f} / เพดานซื้อ ${c['max_entry']:.2f}\n"
                    f"หยุดขาดทุน ${c['stop']:.2f} · เป้า 1 ${c['target1']:.2f} · เป้า 2 ${c['target2']:.2f}\n"
                    f"ที่เป้า 2: ส่วนต่างสุทธิประมาณ {c['net_upside_pct']:.2f}% / ผลตอบแทนต่อความเสี่ยงสุทธิ {c['net_rr']:.2f}:1\n"
                    f"เผื่อต้นทุนรวม {c['cost_pct']:.2f}% ต่อรอบซื้อ–ขาย; เป้า 1 = 1R สุทธิ / เป้า 2 = 2R สุทธิ\n"
                    'R:R นี้คำนวณกรณีขายทั้งหมดที่เป้า 2; การแบ่งขายที่เป้า 1 ทำให้ผลตอบแทนรวมต่ำลง\n'
                    f"วิธีเข้า: {c['entry_rule']}\n"
                    f"ใช้แผนถึง {thai_time(c['valid_until'])} · {c['cancel_rule']}\n"
                    f"ปิดแผนภายใน {thai_time(c['exit_by'])} ไทย; Stop เป็นระดับวางแผน ต้องตรวจคำสั่งที่ Dime รองรับ\n"
                    f"วันถัดไป {c['next_trading_day']}: คัดข่าว วอลุ่ม และราคาใหม่ ไม่ยกเป้า/จุดเข้าวันนี้ไปใช้ต่อ")
    text.append('อ่านค่าแบบมือใหม่: RVOL 1.5 = ซื้อขายมากกว่าเวลาเดียวกันปกติ 50%; VWAP = ราคาเฉลี่ยถ่วงน้ำหนักด้วยวอลุ่มในช่วงนี้; '
                'Spread = ช่องว่างราคาซื้อ–ขาย; R = เงินที่เสี่ยงต่อหุ้นรวมต้นทุน\n'
                'ต้นทุนที่ใช้เป็นงบเผื่อ: คอมมิชชันปกติ 0.30% สองขา + Spread 0.20% + ราคาคลาดเคลื่อน 0.10% + ค่าธรรมเนียมย่อย; คิดเป็น USD ก่อนภาษีและผลของอัตราแลกเปลี่ยน\n'
                'ฟีดไม่มีเวลาของ Bid/Ask แยกจากราคาล่าสุด จึงต้องตรวจ Spread และราคาที่ซื้อได้จริงใน Dime ก่อนใช้แผน\n'
                + report['performance'])
    if report.get('diagnostics'):
        text.append('ขอบเขตข้อมูล: ตรวจข่าวสูงสุด 16 ตัว / กราฟสูงสุด 8 ตัวต่อรอบ; หากแหล่งข้อมูลขัดข้องจะตัดตัวที่ตรวจไม่ได้ออก')
    return '\n\n'.join(text)


def render_report(report, output):
    from PIL import Image, ImageDraw
    from stock_alert_image import ThaiText, NAVY, INK, MUTED, TEAL, BG
    count = len(report['cards'])
    card_height = 510
    height = 480 + max(count, 1) * card_height
    canvas = Image.new('RGB', (1600, height), BG)
    draw = ImageDraw.Draw(canvas)
    font = ThaiText(draw)
    draw.rectangle((0, 0, 1600, 210), fill=NAVY)
    font.line((60, 40), 'หุ้นเทรดสั้น | ข่าว + วอลุ่ม + จุดเข้า', 44, 'white', True)
    font.line((60, 110), f"{thai_time(report['generated_at'])} ไทย · ผ่าน {count} ตัว · สูงสุด 5 ตัว", 30, '#C3D6E8')
    font.line((60, 164), 'แผนมีเงื่อนไขสำหรับจบในวัน · ตรวจราคาจริงใน Dime ก่อนเข้า', 25, '#C3D6E8')
    y = 240
    for c in report['cards']:
        draw.rounded_rectangle((45, y, 1555, y + card_height - 20), radius=24, fill='white')
        font.line((75, y + 20), c['ticker'], 44, TEAL, True)
        font.paragraph((280, y + 34), f"{c['sector']} / {c['industry']}", 1210, size=25, lines=1, color=MUTED)
        font.line((75, y + 86), f"${c['price']:.2f} ({c['change_pct']:+.2f}%)   RVOL {c['rvol']:.2f}x   VWAP ${c['vwap']:.2f}", 31, INK, True)
        font.line((75, y + 132), f"ซื้อขาย {c['session_volume']:,.0f} หุ้น / ${c['session_dollars']/1e6:,.1f} ล้าน · เทียบเวลาเดียวกัน {c['rvol_sessions']} วัน", 26, MUTED)
        font.paragraph((75, y + 180), 'ข่าว: ' + c['news'][0]['title'], 1430, size=27, lines=2, leading=36)
        font.line((75, y + 262), f"เข้า ${c['entry']:.2f}–{c['max_entry']:.2f}   หยุด ${c['stop']:.2f}   เป้า ${c['target1']:.2f} / ${c['target2']:.2f}", 29, INK, True)
        font.line((75, y + 310), f"ถึงเป้า 2 สุทธิ ~{c['net_upside_pct']:.2f}% · R:R สุทธิ {c['net_rr']:.2f}:1 · ต้นทุนเผื่อ {c['cost_pct']:.2f}%", 27, TEAL, True)
        font.paragraph((75, y + 357), c['entry_rule'], 1420, size=26, lines=2, leading=37)
        font.line((75, y + 442), f"ใช้แผนถึง {thai_time(c['valid_until'])} · หลุด VWAP/Stop หรือเกินเพดาน: ยกเลิก", 25, MUTED)
        y += card_height
    if not count:
        draw.rounded_rectangle((45, y, 1555, y + card_height - 20), radius=24, fill='white')
        title = 'ข้อมูลรอบนี้ยังไม่ครบ' if report['status'] == 'data_unavailable' else 'รอบนี้ยังไม่มีแผนผ่านเกณฑ์'
        font.line((80, y + 35), title, 40, INK, True)
        font.line((80, y + 100), 'รอจังหวะที่มีข่าวใหม่ วอลุ่ม และพื้นที่ถึงเป้าหลังต้นทุน', 28, MUTED)
        reasons = sorted(report['excluded'].items(), key=lambda x: -x[1])[:5]
        for i, (key, value) in enumerate(reasons):
            font.paragraph((80, y + 164 + i * 51), f"{LABELS.get(key, key)}: {value}", 1420, size=27, lines=1)
        if not reasons:
            font.line((80, y + 180), 'ไม่ใช้รายชื่อจากรอบเก่ามาทดแทนข้อมูลที่ขาด', 29, TEAL)
        y += card_height
    font.line((60, y + 10), 'RVOL = วอลุ่มเทียบเวลาเดียวกัน | VWAP = ราคาเฉลี่ยถ่วงน้ำหนัก', 27, INK, True)
    font.paragraph((60, y + 58), 'ข่าวในภาพเป็นพาดหัว; อ่านที่มาและเงื่อนไขเต็มในข้อความ · ยังไม่มีสถิติผลลัพธ์ล่วงหน้าของเกณฑ์รุ่นนี้',
                   1470, size=25, lines=2, color=MUTED)
    font.line((60, y + 137), f"วันซื้อขายถัดไป {report['next_trading_day']}: ต้องคัดใหม่ | Yahoo Finance / Dime fee assumptions", 24, MUTED)
    original, preview = output / 'briefing.png', output / 'briefing-preview.png'
    canvas.save(original, optimize=True)
    small = canvas.copy()
    small.thumbnail((800, 2400))
    small.save(preview, optimize=True)
    return original, preview


def save_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'briefing.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'briefing.txt').write_text(format_report(report), encoding='utf-8')
    return render_report(report, output)


def build_bundle(payload, now, store):
    from short_term_service import scan
    from stock_alert_report import text_chunks
    from stock_alert_media import publish_briefing
    report = scan(payload)
    output = Path(os.environ.get('LINE_REPORT_OUTPUT', 'work/line-report'))
    original, preview = save_report(report, output)
    media = publish_briefing(store, original.read_bytes(), preview.read_bytes(), report)
    messages = [{'type': 'image', 'originalContentUrl': media['original_url'], 'previewImageUrl': media['preview_url']}]
    messages.extend({'type': 'text', 'text': t} for t in text_chunks(format_report(report)))
    at = datetime.now(timezone.utc)
    expiry = min([instant(c['expires_at']) for c in report['cards']] + [at + timedelta(minutes=2)])
    return {'model': MODEL, 'messages': messages, 'stocks': len(report['cards']),
            'expires_at': expiry.isoformat(), 'empty_status': report['status'],
            'study_plans': report['cards'], 'generated_at': report['generated_at']}
