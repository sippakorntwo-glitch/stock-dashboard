"""Compact company evidence and completed-session moving averages for reports."""
from __future__ import annotations
import re

from short_term_engine import number, instant

CONTEXT_VERSION = 2


def pack_context(rows):
    """Keep public ranking below GitHub's 1 MB Contents limit, without data loss."""
    import base64
    import gzip
    import json
    data = {r['ticker']: {key: r.pop(key) for key in ('company', 'daily_context') if key in r}
            for r in rows}
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode()


def unpack_context(pool):
    import base64
    from copy import deepcopy
    import json
    import zlib
    rows = deepcopy(pool['items'])
    if not pool.get('context_blob'):
        return rows
    if pool.get('context_version') != CONTEXT_VERSION:
        raise ValueError('Unsupported company context version')
    try:
        compressed = base64.b64decode(pool['context_blob'], validate=True)
        decoder = zlib.decompressobj(31)
        raw = decoder.decompress(compressed, 4_000_001)
        if len(raw) > 4_000_000 or not decoder.eof or decoder.unused_data:
            raise ValueError('Company context size or envelope is invalid')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {r['ticker'] for r in rows}:
            raise ValueError('Company context symbols differ from the universe')
        for row in rows:
            details = data[row['ticker']]
            if not isinstance(details, dict) or set(details) - {'company', 'daily_context'}:
                raise ValueError('Invalid company context fields')
            row.update(details)
    except (ValueError, TypeError, zlib.error) as exc:
        raise ValueError('Cannot decode company context') from exc
    return rows


def daily_context(frame):
    close = frame.Close
    result = {'asof': frame.index[-1].date().isoformat(), 'bars': len(close)}
    for window in (20, 50, 200):
        values = close.tail(window)
        result['sma' + str(window)] = (round(float(values.mean()), 4) if len(values) == window
                                      and values.notna().all() and (values > 0).all() else None)
    return result


def company_context(ticker, info, meta, bundle, now):
    from company_metrics import metric_observations
    description = re.sub(r'\s+', ' ', str(info.get('longBusinessSummary') or '')).strip()
    # A short, complete opening sentence where available; preserve the original
    # for translation/source inspection rather than inventing the business.
    protected = re.sub(r'\b(Inc|Corp|Co|Ltd)\.', r'\1<dot>', description)
    first = re.split(r'(?<=[.!?])\s+(?=[A-Z])', protected, maxsplit=1)[0].replace('<dot>', '.')
    if len(first) > 260:
        first = ''
    at = instant(meta.get('fetched_at') or info.get('_Fetched_At_UTC'))
    result = {'business_en': first, 'country': info.get('country', ''),
              'profile_at': at.isoformat() if at else None, 'financials': []}
    values = metric_observations(ticker, info, bundle)
    for key, label in (('revenueGrowthFY', 'รายได้ทั้งปี'), ('profitMargins', 'อัตรากำไรสุทธิ')):
        item = values.get(key, {})
        value, end = number(item.get('value')), item.get('end')
        # Undated profile ratios cannot become dated company-outlook evidence.
        if item.get('state') == 'available' and value is not None and end and str(end) <= now.date().isoformat():
            result['financials'].append({'key': key, 'value': round(value, 6),
                                         'end': end, 'basis': item.get('basis', ''), 'source': item.get('source', '')})
    return result


def price_text(value):
    n = number(value)
    return '—' if n is None else f'${n:,.2f}'


def daily_values(row):
    daily = dict(row.get('daily_context') or {})
    close, average = number(row.get('previous_close')), number(daily.get('sma20'))
    # Corporate actions can appear in recent prices before the historic series
    # is restated. An extreme discontinuity needs review, not a bearish signal.
    if ('daily_price_scale_mismatch' in row.get('reasons', [])
            or close and average and not .55 <= close / average <= 1.8):
        daily.update(scale_review=True, sma20=None, sma50=None, sma200=None)
    return daily


def sma_line(row):
    daily = daily_values(row)
    if daily.get('scale_review'):
        return 'SMA20 — · SMA50 — · SMA200 — (รอตรวจฐานราคา)'
    return ' · '.join('SMA' + str(n) + ' ' + price_text(daily.get('sma' + str(n))) for n in (20, 50, 200))


def trend_view(row):
    daily = daily_values(row)
    price, vwap = number(row.get('price')), number(row.get('vwap'))
    short = ('วันนี้ยังอ่อนตัว' if row.get('change_pct', 0) <= -3 else
             'วันนี้มีแรงส่งบวก' if row.get('change_pct', 0) >= 1 else 'วันนี้ทิศทางยังไม่ชัด')
    if price and vwap:
        short += ' แต่กลับมายืนเหนือ VWAP' if row.get('change_pct', 0) < 0 and price > vwap else (
            ' และราคาเหนือ VWAP' if price > vwap else ' และราคายังต่ำกว่า VWAP')
    s20, s50, s200 = [number(daily.get('sma' + str(n))) for n in (20, 50, 200)]
    comparable = not daily.get('scale_review')
    if price and s20 and s50 and comparable:
        if price > s20 > s50:
            middle = 'โครงสร้างรายวันยังเอนขึ้น: ราคา > SMA20 > SMA50'
        elif price < s20 < s50:
            middle = 'โครงสร้างรายวันเอนลง: ราคา < SMA20 < SMA50'
        else:
            middle = 'โครงสร้างรายวันผสม ต้องรอราคาและ SMA20/50 เรียงตัวชัด'
        if s200:
            middle += '; ราคา' + ('เหนือ' if price > s200 else 'ต่ำกว่า') + ' SMA200'
    else:
        middle = ('ราคาฐานรายวันไม่สอดคล้องกับราคาสด จึงยังไม่เทียบแนวโน้ม SMA' if not comparable else
                  'ข้อมูล SMA รายวันยังไม่ครบ จึงยังไม่สรุปแนวโน้มกลาง–ยาว')
    return {'intraday': short, 'daily': middle}


def company_view(row):
    company = row.get('company') or {}
    stats = company.get('financials') or []
    lines = []
    for item in stats:
        suffix = ' เทียบปีก่อน' if item['key'] == 'revenueGrowthFY' else ''
        label = 'รายได้ทั้งปี' if item['key'] == 'revenueGrowthFY' else (
            'อัตรากำไรสุทธิ 4 ไตรมาส' if str(item.get('basis', '')).startswith('TTM') else
            'อัตรากำไรสุทธิทั้งปี' if str(item.get('basis', '')).startswith('FY') else 'อัตรากำไรสุทธิ')
        lines.append(f"{label} {item['value']*100:+.1f}%{suffix} (งวด {item['end']})")
    growth = next((v['value'] for v in stats if v['key'] == 'revenueGrowthFY'), None)
    margin = next((v['value'] for v in stats if v['key'] == 'profitMargins'), None)
    if growth is not None:
        outlook = ('รายได้ปีล่าสุดที่มีงบยังขยายตัว' if growth > 0 else
                   'รายได้ปีล่าสุดที่มีงบหดตัว' if growth < 0 else 'รายได้ปีล่าสุดที่มีงบทรงตัว')
        outlook += '; ต้องดูว่าปัจจัยในข่าวรอบนี้เปลี่ยนยอดขายหรืออำนาจกำหนดราคาในงวดถัดไปหรือไม่'
    elif margin is not None:
        outlook = ('งวดที่มีข้อมูลยังทำกำไรสุทธิได้' if margin > 0 else 'งวดที่มีข้อมูลยังขาดทุนสุทธิ')
        outlook += '; ยังไม่มีการเติบโตของรายได้ที่ยืนยันงวดได้พอให้สรุปการขยายธุรกิจ'
    else:
        outlook = 'ยังไม่มีงบที่ยืนยันงวดได้พอประเมินการเติบโต; ใช้ข่าวและแนวโน้มราคาเป็นเงื่อนไขติดตามก่อน'
    if margin is not None and abs(margin) > .5:
        outlook += '; อัตรากำไรสูงหรือต่ำผิดปกติ ต้องตรวจรายการพิเศษก่อนใช้คาดการณ์'
    impacts = [n.get('industry_impact') for n in row.get('news', []) if n.get('industry_impact')]
    if impacts:
        outlook += ' · ' + impacts[0]['impact_th']
    else:
        titles = ' '.join(n.get('title', '') for n in row.get('news', []))
        if re.search(r'exchange offers|consent solicitations|senior notes', titles, re.I):
            outlook += ' · ข่าวนี้เกี่ยวกับโครงสร้างหนี้ ต้องดูดอกเบี้ยและอายุหนี้หลังรายการ; ยังไม่ใช่หลักฐานว่ายอดขายเพิ่ม'
        elif re.search(r'FDA.{0,45}reject', titles, re.I):
            outlook += ' · การไม่อนุมัติยาอาจเลื่อนรายได้ผลิตภัณฑ์ ต้องดูว่าจะยื่นใหม่ได้เมื่อใดและเงินสดรองรับได้นานเพียงใด'
        elif re.search(r'FDA.{0,45}approv', titles, re.I):
            outlook += ' · การอนุมัติเปิดทางขายผลิตภัณฑ์ แต่ต้องติดตามวันเริ่มขาย ราคา และการยอมรับของตลาด'
        elif re.search(r'guidance|forecast|outlook', titles, re.I):
            outlook += ' · ต้องเทียบประมาณการใหม่กับเดิม และแยกการเติบโตของรายได้ออกจากการเปลี่ยนแปลงอัตรากำไร'
    positive = next((p['counterpoint_th'] for p in impacts if 'ภาวะขาดแคลน' in p['counterpoint_th']), '')
    from company_analysis_th import profile_text_th
    profile = profile_text_th(dict(sector=row.get('sector'), industry=row.get('industry'), country=company.get('country')))
    return {'business': company.get('business_th') or profile or 'รอข้อมูลบริษัท', 'profile': profile,
            'financials': ' · '.join(lines), 'outlook': outlook, 'counterpoint': positive,
            'financial_sources': ', '.join(dict.fromkeys(s.get('source', '') for s in stats if s.get('source'))),
            'profile_at': company.get('profile_at')}


def rvol_line(row):
    value = number(row.get('rvol'))
    return 'RVOL —' if value is None else f'RVOL {value:.2f}×'


GLOSSARY = ('RVOL = วอลุ่มเทียบเวลาเดียวกันในอดีต; 2× คือซื้อขาย 2 เท่าของปกติ ไม่ใช่ยอดซื้อสุทธิ\n'
            'VWAP = ราคาเฉลี่ยถ่วงน้ำหนักวอลุ่มช่วงนี้ คำนวณจากแท่ง 5 นาที; เหนือเส้น = แข็งแรงกว่าค่าเฉลี่ยช่วงนั้น\n'
            'SMA 20/50/200 = ราคาปิดเฉลี่ย 20/50/200 วันซื้อขาย ใช้ดูแนวโน้มสั้น/กลาง/ยาว')
