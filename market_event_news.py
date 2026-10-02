"""Explicit industry links and attributed mechanisms, not headline sentiment scores."""
from __future__ import annotations
import re


def story_id(ticker, article):
    import hashlib
    impact = article.get('industry_impact') or {}
    identity = ('toshiba-hdd-capacity' if impact.get('impact_type') == 'competitor_supply' else article['url'])
    return hashlib.sha256((ticker + ':' + identity).encode()).hexdigest()[:24]


def industry_impact(title, ticker):
    # HDD competition is a precise relationship. Do not map Toshiba's nuclear,
    # semiconductor or NAND news to every storage-related stock.
    if (ticker in ('WDC', 'STX') and re.search(r'\bToshiba\b', title, re.I)
            and re.search(r'\bHDD\b|hard[ -]?(?:disk|drive)', title, re.I)
            and re.search(r'doubl\w*|expan\w*|boost\w*|ramp\w*|increas\w*|supply|capacity|production', title, re.I)):
        return {'relationship': 'คู่แข่งในอุตสาหกรรม HDD', 'impact_type': 'competitor_supply',
                'impact_th': 'แผนเพิ่มกำลังผลิตของ Toshiba อาจเพิ่มการแข่งขันด้านราคาและส่วนแบ่งตลาดของผู้ผลิต HDD',
                'counterpoint_th': 'เป็นแผนกำลังผลิตในอนาคต ต้องติดตามการลงทุน ซัพพลายเออร์ และวันที่ผลิตได้จริง',
                'interpretation': 'กลไกผลกระทบที่อนุมานจากข่าว ไม่ใช่ผลประกอบการที่เกิดขึ้นแล้ว'}
    if re.search(r'\b(?:capacity|production|supply)\b', title, re.I) and re.search(r'expan\w*|doubl\w*|boost\w*|ramp\w*|cut\w*', title, re.I):
        return {'relationship': 'กำลังผลิต/อุปทานในข่าว', 'impact_type': 'supply_change',
                'impact_th': 'การเปลี่ยนกำลังผลิตอาจเปลี่ยนยอดขาย ต้นทุน และอำนาจกำหนดราคา ต้องแยกบริษัทเจ้าของแผนกับคู่แข่ง',
                'counterpoint_th': 'ต้องตรวจช่วงเวลาที่มีผลและขนาดกำลังผลิตเทียบกับความต้องการ',
                'interpretation': 'ประเด็นวิเคราะห์จากหัวข้อข่าว'}
    return None


def material_event(title):
    # Upcoming operating investments matter today; merely scheduling an
    # earnings call does not provide earnings results.
    excluded = re.compile(r'\b(?:will (?:report|release|announce)|to (?:report|release|announce)|'
                          r'schedules?|conference call|earnings date|preview|what to expect|'
                          r'should you|is .+ a buy|worth buying|price target|valuation|'
                          r'52.week|all.time high|retire\w*|succession|appoint\w*)\b', re.I)
    event = re.compile(r'\b(?:reports? .{0,55}(?:results|earnings)|results|'
                       r'earnings (?:beat|miss)|guidance|outlook|forecast|'
                       r'wins? .{0,45}contract|(?:signs?|awarded) .{0,40}(?:deal|contract)|'
                       r'acquires?|acquisition|merger|FDA .{0,40}(?:approv\w*|reject\w*)|'
                       r'approv\w* .{0,30}(?:drug|treatment)|recall|lawsuit|'
                       r'bankruptcy|deliveries|production|capacity|supply|expansion|tariff\w*|'
                       r'export ban|sanction\w*|price cuts?|data breach|cyberattack)\b', re.I)
    return bool(not excluded.search(title) and event.search(title))
