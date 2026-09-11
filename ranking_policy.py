"""Conservative entry checklist. Unknown checks block entries, not watch candidates.
Heuristics only: no claim of complete due diligence or a profit guarantee.
"""
from __future__ import annotations
import math
import pandas as pd

POLICY='entry-checklist-v1'
UNASSESSED=['ข่าวด่วน/ข่าวเชิงลึกและประกาศบริษัททุกฉบับ',
            'งบฉบับเต็มและมูลค่ายุติธรรมเฉพาะอุตสาหกรรม',
            'ความเหมาะสมกับพอร์ต ภาษี และความเสี่ยงเฉพาะบุคคล']


def finite(x):
    if isinstance(x,bool):return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None


def instant(x):
    try:
        if x is None or x=='':return None
        t=pd.Timestamp(x,unit='s',tz='UTC') if isinstance(x,(int,float)) else pd.Timestamp(x)
        if pd.isna(t):return None
        return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
    except (ValueError,TypeError,OverflowError):return None


def recent(x,now,limit):
    t=instant(x)
    return t is not None and -60<=(now-t).total_seconds()<=limit


def prices_valid(row):
    q,lo,hi,stop,target=(finite(row.get(k)) for k in ('quote','zone_low','zone_high','stop','target'))
    return (all(v is not None for v in (q,lo,hi,stop,target)) and 0<stop<q<target
            and 0<lo<=q<=hi and (target-q)/(q-stop)>=2)


def entry_checks(row,now=None):
    now=instant(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if now is None:raise ValueError('Invalid audit clock')
    info=row.get('info') if isinstance(row.get('info'),dict) else {}
    checks=[]
    def add(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    def positive(field,name):
        v=finite(info.get(field))
        add(name,v is not None and v>0,'ต้องเป็นบวก; ไม่มีข้อมูลไม่ถือว่าผ่าน')
    local=now.tz_convert('America/New_York')
    opened=local.weekday()<5 and 570<=local.hour*60+local.minute<960
    add('เวลาตลาดและ quote',opened and recent(row.get('quote_time'),now,900),
        'เฉพาะนาฬิกาช่วงตลาดสหรัฐ และ quote อายุไม่เกิน 15 นาที; ไม่ใช้เวลาดาวน์โหลดแทนเวลาราคา')
    add('คะแนนและข้อมูล',(finite(row.get('score')) or 0)>=80 and row.get('coverage')==100,
        'คะแนนเดิม ≥80/100 และช่องให้คะแนนครบ 100/100 ไม่ใช่ความครบทุกด้านของบริษัท')
    add('ราคาตรงโซนและ R:R ปัจจุบัน',prices_valid(row),
        'ราคา quote อยู่ในโซนเข้า Stop < ราคา < เป้าหมาย และ (เป้าหมาย-ราคา)/(ราคา-Stop) ≥2')
    add('พื้นฐานอัปเดต',recent(row.get('info_fetched_at'),now,7*86400),
        'ดึงข้อมูลบริษัทสำเร็จไม่เกิน 7 วัน ไม่ใช่วันที่งบทุกช่อง')
    bid,ask=finite(info.get('bid')),finite(info.get('ask'))
    spread=(ask-bid)/((ask+bid)/2)*100 if bid and ask and ask>=bid>0 else None
    add('ส่วนต่าง Bid/Ask',spread is not None and spread<=0.5,
        'ส่วนต่างไม่เกิน 0.5%; เป็นค่าจากผู้ให้ข้อมูล ไม่ใช่ราคาที่รับประกันการส่งคำสั่ง')
    if row.get('asset_type')=='ETF':
        assets=finite(info.get('totalAssets'))
        add('ข้อมูลกองทุน',bool(info.get('category')) and assets is not None and assets>0,
            'ต้องมีหมวดกองทุนและสินทรัพย์รวม; ไม่ใช้กระแสเงินสดบริษัทมาตัดสิน ETF')
    else:
        positive('trailingEps','กำไรต่อหุ้นย้อนหลัง')
        positive('profitMargins','อัตรากำไรสุทธิ')
        positive('operatingCashflow','กระแสเงินสดจากการดำเนินงาน')
        positive('freeCashflow','กระแสเงินสดอิสระ')
        growth=finite(info.get('revenueGrowth'))
        add('รายได้ไม่หดตัว',growth is not None and growth>=0,'revenueGrowth ≥0 ตามช่วงที่ผู้ให้ข้อมูลรายงาน')
        debt,cash,ocf=(finite(info.get(k)) for k in ('totalDebt','totalCash','operatingCashflow'))
        valid=debt is not None and cash is not None and ocf is not None and debt>=0 and cash>=0 and ocf>0
        ratio=max(0,debt-cash)/ocf if valid else None
        add('ภาระหนี้สุทธิ',ratio is not None and ratio<=5,
            'หนี้สุทธิที่เป็นบวก/กระแสเงินสดดำเนินงาน ≤5 เท่า เป็นเกณฑ์อนุรักษนิยม ไม่ใช่มาตรฐานทุกอุตสาหกรรม')
        sector=str(info.get('sector') or '').casefold()
        add('ธุรกิจในขอบเขตเกณฑ์กระแสเงินสด',bool(sector) and sector not in ('financial services','real estate'),
            'โมเดลหนี้/กระแสเงินสดนี้ไม่รับรองธนาคาร การเงิน และอสังหาริมทรัพย์; กลุ่มเหล่านี้ยังอยู่ในรายการเฝ้าดู')
        dates=[instant(info.get(k)) for k in ('earningsTimestamp','earningsTimestampStart','earningsTimestampEnd')]
        known=[x for x in dates if x is not None and x>=now-pd.Timedelta(days=1)]
        next_event=min(known) if known else None
        add('ช่วงประกาศกำไร',next_event is not None and next_event>now+pd.Timedelta(days=3),
            'พักอย่างน้อย 3 วันก่อน/1 วันหลังวันประกาศที่มีข้อมูล; ไม่ทราบวันถัดไปถือว่ายังรอตรวจ')
    return {'policy':POLICY,'checked_at':now.isoformat(),'passed':all(x['passed'] for x in checks),
            'checks':checks,'unassessed':list(UNASSESSED)}


def apply_entry_policy(rows,now=None):
    result=[]
    for original in rows:
        row=dict(original)
        audit=entry_checks(row,now)
        row['entry_audit']=audit
        row['ready_at_calculation']=bool(row.get('ready_at_calculation') and audit['passed'])
        additional=['ตรวจเพิ่ม: '+x['check'] for x in audit['checks'] if not x['passed']]
        row['blockers']=list(dict.fromkeys(list(row.get('blockers',[]))+additional))
        result.append(row)
    return sorted(result,key=lambda r:(-int(r['ready_at_calculation']),-int(r.get('qualified',False)),
        -r['score'],-r['coverage'],-min(r['rr'],10),r.get('distance_pct') or 0,r['ticker']))


def is_entry(row,payload,now=None):
    now=instant(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if now is None or not recent(payload.get('computed_at'),now,35*60):return False
    audit=row.get('entry_audit') or {}
    return bool(row.get('ready_at_calculation') and row.get('qualified')
                and audit.get('policy')==POLICY and audit.get('passed')
                and entry_checks(row,now)['passed'])
