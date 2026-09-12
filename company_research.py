"""Pure, display-only financial review. No provider calls or trading-score changes."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, date
import math
from company_metrics import METRICS, BY_KEY, GUIDE_NOTE
from financial_statements import METHOD as STATEMENT_METHOD, derived_metrics, finite
from asset_semantics import field_state

METHOD='company-review-v1'
SPECIAL_SECTORS={'financial services','real estate'}
PROVIDER_ONLY={'market_cap','forward_pe','trailing_pe','price_book','price_sales','ev_ebitda','ev_sales','payout','target','analysts','eps','revenue_growth','earnings_growth'}
RATIOS_POSITIVE={'forward_pe','trailing_pe','price_book','price_sales','ev_ebitda'}
NONNEGATIVE={'assets','liabilities','cash','debt','interest_expense','current_ratio','quick_ratio','cash_ratio','analysts','payout','buybacks','dividends_paid','capex','dividend_yield'}
STATUS_TEXT={'missing':'Not reported','not_applicable':'N/A — Not applicable','not_meaningful':'N/M — Not meaningful','invalid':'— (invalid source value)'}


def parse_time(value):
    try:
        if isinstance(value,bool):return None
        if isinstance(value,(int,float)):return datetime.fromtimestamp(value,timezone.utc)
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):return None


def assess(spec,value,status,*,special=False,wacc=None):
    if status!='available':return 'Not assessed',STATUS_TEXT.get(status,'Not reported')
    if spec.industrial and special:
        return 'Sector-specific review','เกณฑ์กิจการทั่วไปไม่เหมาะกับธุรกิจนี้: พิจารณา CET1/NIM/คุณภาพสินเชื่อสำหรับธนาคาร หรือ FFO/AFFO/NAV สำหรับ REIT; ไม่สร้างข้อมูลที่ไม่ได้รายงาน'
    p=spec.policy
    if p=='context':return 'Context needed','ไม่มีค่าดีหรือไม่ดีแบบตายตัว ต้องเทียบขนาด งวด อุตสาหกรรม และแนวโน้ม'
    if p=='earnings':
        return ('Positive','ค่าเป็นบวกในงวดที่ระบุ ยังต้องตรวจรายการพิเศษและความยั่งยืน') if value>0 else ('Risk flag','ผลขาดทุน/เงินสดไหลออกในงวดนี้ ไม่ใช่คำตัดสินว่าบริษัทล้มเหลว') if value<0 else ('Watch','ค่าเป็นศูนย์ ไม่ใช่ข้อมูลที่ขาด')
    if p=='equity':return ('Positive equity','ทุนเป็นบวก; ตรวจซื้อหุ้นคืน หนี้ และคุณภาพสินทรัพย์ร่วมด้วย') if value>0 else ('Risk flag','ทุนไม่เป็นบวก: อัตราส่วนที่หารด้วยทุนไม่ควรถูกอ่านว่าดี')
    if p=='net_debt':return ('Net cash','เงินสดไม่น้อยกว่าหนี้มีดอกเบี้ยตามนิยามนี้') if value<=0 else ('Net debt','มีหนี้สุทธิ ต้องดูดอกเบี้ย กำหนดชำระ และกระแสเงินสด')
    if p=='roic':
        if wacc is None:return ('Compare with WACC','ต้องเทียบต้นทุนเงินทุนก่อนสรุปการสร้างมูลค่า ไม่ใช้ระดับ ROIC เดี่ยว ๆ รับรองว่าดี')
        return ('Above WACC assumption','สูงกว่า WACC ที่ผู้ใช้ระบุ ไม่ใช่ต้นทุนเงินทุนที่ระบบยืนยันแล้ว') if value>wacc else ('Below WACC assumption','ยังไม่สูงกว่า WACC สมมติฐานที่ระบุ; ตรวจวิธีปรับทุนและกำไร')
    if p=='pb':return ('Below book','ต่ำกว่า 1 เท่า ไม่รับรองว่าถูก อาจสะท้อนสินทรัพย์ด้อยคุณภาพ') if value<1 else ('Mid-range (guide)','อยู่ช่วง 1–3 เท่าตาม guide ไม่ใช่ fair value') if value<=3 else ('Premium to book','สูงกว่า 3 เท่า อาจมาจากทุนต่ำหรือสินทรัพย์ไม่มีตัวตน ไม่ได้แปลว่าแพงเสมอ')
    if p in ('pe','ev'):
        low,high=(25,40) if p=='pe' else (10,15)
        return ('Lower multiple (guide)','อยู่ในช่วงตัวคูณต่ำของ guide; ตรวจโอกาสกำไรลดลงและคู่แข่ง') if value<=low else ('Premium (guide)','อยู่ระดับ premium ของ guide ต้องมีการเติบโต/คุณภาพรองรับ') if value<=high else ('High expectations','ตัวคูณสูงกว่า guide ความคาดหวังสูง แต่ยังไม่ใช่ข้อพิสูจน์ว่าแพง')
    if p=='de':return ('Low leverage (guide)','ต่ำกว่า 0.5 เท่า; ตรวจภาระอื่นนอกตัวเลขนี้') if value<.5 else ('Moderate leverage','อยู่ 0.5–1.5 เท่าตาม guide; ดูดอกเบี้ยและเงินสด') if value<=1.5 else ('Leverage watch','มากกว่า 1.5 เท่า ตรวจความสามารถจ่ายหนี้และทุนต่ำจาก buyback')
    if p=='net_debt_ebitda':return ('Lower leverage (guide)','ต่ำกว่า 2 เท่า; ค่าติดลบหมายถึง net cash') if value<2 else ('Watch','อยู่ 2–3 เท่าตาม guide') if value<=3 else ('Leverage watch','สูงกว่า 3 เท่า; EBITDA ไม่ใช่เงินสดชำระหนี้จริง')
    if p=='payout':return ('Retained cushion (guide)','ปันผลไม่เกิน 60% ของกำไรตามข้อมูลที่รายงาน') if value<=60 else ('Payout watch','จ่าย 60–100% ของกำไร ตรวจ FCF และความสม่ำเสมอ') if value<=100 else ('Above earnings','ปันผลมากกว่ากำไรในช่วงอ้างอิง; อาจไม่ยั่งยืน')
    thresholds={'higher_margin':(20,40),'operating_margin':(5,15),'net_margin':(0,10),'roe':(8,15),'roa':(2,5),'growth':(0,10),'current':(1,1.5),'quick':(1,1),'interest':(2,5),'conversion':(1,1)}
    if p in thresholds:
        low,high=thresholds[p]
        if value<0:return 'Risk flag','ค่าติดลบตามนิยามของตัวชี้วัดนี้; ตรวจบริบทและงวดบัญชี'
        if value>=high:return 'Favorable (guide)','สูงถึงช่วงอ้างอิงของ guide ไม่ใช่การรับประกันคุณภาพหรือราคาหุ้น'
        if value>=low:return 'Watch / middle','อยู่ช่วงกลางของ guide; เทียบอุตสาหกรรมและแนวโน้มหลายปี'
        return 'Below guide','ต่ำกว่าช่วงอ้างอิงของ guide; ต้องตรวจเหตุผลก่อนตัดสินบริษัท'
    return 'Context needed','พิจารณาข้อมูลอื่นประกอบ'


def build_review(ticker,info,reference=None,*,is_etf=False,as_of=None,wacc=None):
    info=info if isinstance(info,dict) else {};reference=reference if isinstance(reference,dict) else {}
    current=parse_time(as_of) or datetime.now(timezone.utc)
    wacc=finite(wacc)
    if wacc is not None and not 0<=wacc<=100:raise ValueError('WACC assumption must be between 0 and 100 percent')
    statements=reference.get('financial_statements',{})
    annual=statements.get('annual',[]) if statements.get('method')==STATEMENT_METHOD else []
    annual=[p for p in annual if isinstance(p,dict) and p.get('end') and p['end']<=current.date().isoformat() and p.get('filed') and p['filed']<=current.date().isoformat()]
    annual=sorted(annual,key=lambda p:p['end'],reverse=True)
    period=annual[0] if annual else None
    calculated=derived_metrics(period,annual[1] if len(annual)>1 else None) if period else {}
    sector=str(info.get('sector') or '').casefold()
    industry=str(info.get('industry') or '').casefold()
    special=sector in SPECIAL_SECTORS or any(x in industry for x in ('banks -','insurance','reit -')) or not sector
    fetched=parse_time(info.get('_Fetched_At_UTC'))
    financial_currency=str(info.get('financialCurrency') or 'currency not reported')
    quote_currency=str(info.get('currency') or 'currency not reported')
    results=[]
    for spec in METRICS:
        value=None;status='missing';basis='Not reported';source='';formula='';inputs={};note=''
        if is_etf:
            status='not_applicable';note='Company statements do not describe a fund; fund-specific values are shown below.'
        elif spec.key not in PROVIDER_ONLY and spec.key in calculated:
            entry=calculated[spec.key];value=entry['value'];inputs=entry['inputs'];formula=entry['formula']
            source=period['url'];basis=f"FY {period['start']} → {period['end']}"
            status='available';currency=period['currency']
        elif spec.provider:
            raw=info.get(spec.provider);n=finite(raw)
            state=field_state(ticker,info,spec.provider,is_etf=False)
            status={'not_meaningful':'not_meaningful','invalid':'invalid','not_applicable':'not_applicable'}.get(state,'available' if n is not None else 'missing')
            if status=='available':
                value=n*100 if spec.unit=='percent' else n/100 if spec.key=='de' else n
                formula=f'Provider {spec.provider}'+(' × 100' if spec.unit=='percent' else ' / 100 (percent to times)' if spec.key=='de' else '')
                inputs={spec.provider:n}
                source='Yahoo Finance reported profile';basis='Provider-reported; period not independently verified'
                if spec.key in ('trailing_pe','price_sales','eps'):basis='Provider trailing basis; end date not supplied per field'
                if spec.key=='forward_pe':basis='Provider forward estimate; horizon per source'
                if spec.unit=='money':currency=financial_currency
                elif spec.unit in ('quote_money','per_share'):currency=quote_currency
        # A valid source quote is not enough when the ratio denominator is non-positive.
        book=finite(info.get('bookValue'))
        if not is_etf and status=='available':
            if spec.key in NONNEGATIVE and value<0:status='invalid'
            if spec.key in RATIOS_POSITIVE and value<=0:status='not_meaningful'
            if spec.key=='de' and value<0:
                status='not_meaningful';note='A negative debt/equity ratio is not low leverage; investigate non-positive equity or source inconsistency.'
            if spec.key in ('price_book','de','roe') and source.startswith('Yahoo') and book is not None and book<=0:
                status='not_meaningful';note='Provider book value is non-positive; do not interpret this equity ratio as favorable.'
            if spec.key=='payout' and (finite(info.get('trailingEps')) is not None and finite(info['trailingEps'])<=0):status='not_meaningful'
        if status!='available':value=None
        if spec.unit=='money' and source.startswith('http'):unit=period['currency']
        elif spec.unit=='money':unit=financial_currency
        elif spec.unit=='quote_money':unit=quote_currency
        elif spec.unit=='per_share':unit=quote_currency+'/share (provider basis)'
        else:unit={'percent':'%','multiple':'x','count':'count'}[spec.unit]
        grade,interpretation=assess(spec,value,status,special=special,wacc=wacc)
        if status=='available' and source.startswith('http'):
            if (current.date()-date.fromisoformat(period['end'])).days>550:
                grade='Stale fiscal period';interpretation='งบสิ้นงวดเก่ากว่า 550 วัน ไม่สรุปเป็นคุณภาพปัจจุบัน'
        elif status=='available' and fetched and (current-fetched).total_seconds()>14*86400:
            grade='Stale profile';interpretation='ชุดข้อมูล provider เก่ากว่า 14 วัน ใช้อ้างอิง ไม่ยืนยันสถานะปัจจุบัน'
        if spec.key=='roic' and wacc is not None:note+=f' WACC assumption supplied by user: {wacc:.2f}%.'
        results.append({'key':spec.key,'group':spec.group,'metric':spec.label,'value':value,'unit':unit,
                        'status':status,'grade':grade,'guide':spec.guide,'interpretation':interpretation,
                        'basis':basis,'source':source,'formula':formula,'inputs':inputs,
                        'definition':spec.definition,'note':note,
                        'filed':period.get('filed') if source.startswith('http') else None,
                        'fetched_at':info.get('_Fetched_At_UTC') if source.startswith('Yahoo') else reference.get('financial_checked_at')})
    counts=Counter(r['status'] for r in results)
    return {'method':METHOD,'ticker':ticker,'is_fund':bool(is_etf),'sector':info.get('sector'),
            'sector_guides_suppressed':special,'wacc_assumption':wacc,'rows':results,
            'counts':dict(counts),'complete':counts.get('missing',0)==0 and counts.get('invalid',0)==0,
            'fiscal_period':period['end'] if period else None,'guide_note':GUIDE_NOTE}


def format_value(row):
    n=row['value']
    if n is None:return STATUS_TEXT[row['status']]
    unit=row['unit']
    if unit=='%':return f'{n:,.2f}%'
    if unit=='x':return f'{n:,.2f}x'
    if unit=='count':return f'{n:,.0f}'
    magnitude=abs(n);scale,suffix=(1e12,'T') if magnitude>=1e12 else (1e9,'B') if magnitude>=1e9 else (1e6,'M') if magnitude>=1e6 else (1e3,'K') if magnitude>=1e3 else (1,'')
    return f'{n/scale:,.2f}{suffix} {unit}'
