"""A pre-market price candidate is distinct from the regular entry checklist."""
from ranking_policy import entry_checks


def apply_pre_market_assessment(card, row, now):
    checks = entry_checks(row, now)['checks']
    # Bid/Ask in saved company metadata has no independent pre-market timestamp.
    # Its apparent narrow spread therefore cannot clear the liquidity check.
    independent = [check for check in checks
                   if check['check'] not in ('เวลาตลาดและ quote', 'ส่วนต่าง Bid/Ask')]
    blockers = [check['check'] for check in independent if not check['passed']]
    if row.get('qualified') is not True:
        blockers.append('เงื่อนไขโมเดลคัดหุ้น')
    current = card['quote_fresh'] and card.get('quote_session') == 'pre'
    candidate = current and not blockers
    card['status'] = 'pre_candidate' if candidate else 'watch'
    card['status_label'] = 'เข้าโซนก่อนเปิด · ตรวจสภาพคล่อง' if candidate else 'ก่อนเปิด · เฝ้าดู'
    details = [value for value in card['blocker_details']
               if value not in ('รอช่วงซื้อขายปกติสหรัฐ', 'รอราคาที่อัปเดตไม่เกิน 15 นาที',
                                'รอข้อมูลราคาฝั่งซื้อและขาย', 'รอส่วนต่างราคาฝั่งซื้อ/ขายไม่เกิน 0.5%')]
    if row.get('qualified') is not True:
        details.insert(0, 'รอให้หุ้นผ่านเงื่อนไขโมเดลคัดหุ้น')
    liquidity = 'ตรวจ Bid/Ask ปัจจุบันใน Dime ให้ส่วนต่างไม่เกิน 0.5% และใช้ Limit Order ระบุราคาซื้อ'
    if not current:
        card['situation'] = 'ยังไม่มีราคา Pre-market อายุไม่เกิน 15 นาที; แสดงราคาปกติล่าสุดเป็นข้อมูลประกอบ'
        details.insert(0, 'รอราคา Pre-market ปัจจุบัน')
    elif candidate:
        card['situation'] = 'ราคา Pre-market อยู่ในโซนและ R:R ≥2; รอยืนยัน Bid/Ask ก่อนส่งคำสั่ง'
    elif card['situation'].startswith('ราคาอยู่ในโซนเข้า'):
        card['situation'] = 'ราคา Pre-market อยู่ในโซน แต่ยังมีเงื่อนไขค้าง'
    card['blockers'] = ([] if current else ['ราคา Pre-market ปัจจุบัน']) + blockers + ['Bid/Ask ก่อนตลาดเปิด']
    card['blocker_details'] = details + [liquidity]
    card['pre_market_audit'] = {'candidate': candidate, 'quote_current': current,
                                'liquidity_confirmed': False, 'checks': independent}
    card['next_step'] = (liquidity + '; ถ้าราคาออกนอกโซนให้รอ' if candidate else
                         'ขั้นถัดไป: ' + '; '.join((details + [liquidity])[:3]))
