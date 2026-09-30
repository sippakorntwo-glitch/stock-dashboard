"""Thai industry labels and evidence-based daily technical/news interpretation.

Pure transformations only. A reading guide does not turn a headline into a
verified event, and daily indicators never change the existing entry policy.
"""
from __future__ import annotations

from datetime import date
import math

import pandas as pd

from market_pulse import _number, _text

SECTORS = {
    'Basic Materials': 'วัตถุดิบ', 'Communication Services': 'สื่อสารและสื่อ',
    'Consumer Cyclical': 'สินค้าและบริการตามวัฏจักรเศรษฐกิจ',
    'Consumer Defensive': 'สินค้าอุปโภคบริโภคจำเป็น', 'Energy': 'พลังงาน',
    'Financial Services': 'การเงิน', 'Healthcare': 'สุขภาพ',
    'Industrials': 'อุตสาหกรรม', 'Real Estate': 'อสังหาริมทรัพย์',
    'Technology': 'เทคโนโลยี', 'Utilities': 'สาธารณูปโภค',
}
INDUSTRIES = {
    'Entertainment': 'สื่อบันเทิง', 'Medical Devices': 'อุปกรณ์การแพทย์',
    'Security & Protection Services': 'ระบบความปลอดภัยและการป้องกัน',
    'REIT - Hotel & Motel': 'REIT โรงแรม', 'Apparel Retail': 'ค้าปลีกเสื้อผ้า',
    'Banks - Regional': 'ธนาคารภูมิภาค', 'Semiconductors': 'เซมิคอนดักเตอร์',
    'Software - Infrastructure': 'ซอฟต์แวร์โครงสร้างพื้นฐาน',
    'Software - Application': 'ซอฟต์แวร์ประยุกต์',
    'Oil & Gas E&P': 'สำรวจและผลิตน้ำมันและก๊าซ',
    'Oil & Gas Integrated': 'น้ำมันและก๊าซครบวงจร',
    'Marine Shipping': 'ขนส่งทางเรือ', 'Tools': 'เครื่องมืออุตสาหกรรม',
}


def industry_labels(row):
    info = row.get('info') if isinstance(row.get('info'), dict) else {}
    sector = _text(info.get('sector'), 90)
    industry = _text(info.get('industry') or row.get('industry'), 100)
    if row.get('asset_type') == 'ETF':
        return {'sector': 'ETF', 'sector_th': 'กองทุน ETF',
                'industry': _text(info.get('category'), 100),
                'industry_th': _text(info.get('category'), 100) or 'ยังไม่ทราบหมวดกองทุน'}
    return {'sector': sector, 'sector_th': SECTORS.get(sector, sector or 'ยังไม่ทราบหมวด'),
            'industry': industry, 'industry_th': INDUSTRIES.get(industry, industry or 'ยังไม่ทราบอุตสาหกรรม')}


def daily_technicals(history, rsi=None):
    """Compute real EMA20/50/200 from the same cached daily closes as ranking.

Require 200 valid observations; never substitute a provider's SMA200 for EMA200.
The observation date belongs to the daily bars, not the report delivery clock.
"""
    if not isinstance(history, pd.DataFrame) or 'Close' not in history or len(history) < 200:
        return {}
    closes = pd.to_numeric(history['Close'], errors='coerce')
    if (not isinstance(closes, pd.Series) or closes.isna().any()
            or not closes.map(lambda x: math.isfinite(x) and x > 0).all()
            or not history.index.is_monotonic_increasing or not history.index.is_unique):
        return {}
    try:
        asof = pd.Timestamp(history.index[-1]).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return {}
    value = _number(rsi)
    return {'asof': asof, 'interval': '1d', 'close': float(closes.iloc[-1]),
            'ema20': float(closes.ewm(span=20, adjust=False, min_periods=20).mean().iloc[-1]),
            'ema50': float(closes.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1]),
            'ema200': float(closes.ewm(span=200, adjust=False, min_periods=200).mean().iloc[-1]),
            'rsi14': value if value is not None and 0 <= value <= 100 else None,
            'basis': 'ราคาปิดกราฟรายวันจากชุดข้อมูลจัดอันดับ; EMA adjust=False'}


def technical_analysis(row, now):
    source = row.get('technical') if isinstance(row.get('technical'), dict) else {}
    asof = source.get('asof') or row.get('price_asof')
    local_day = pd.Timestamp(now).tz_convert('America/New_York').date()
    try:
        day = date.fromisoformat(asof)
        current = 0 <= (local_day - day).days <= 4
    except (ValueError, TypeError):
        current, asof = False, None
    values = {key: _number(source.get(key)) for key in ('close', 'ema20', 'ema50', 'ema200', 'rsi14')}
    if values['close'] is None:
        values['close'] = _number(row.get('daily_close'))
    if values['rsi14'] is None:
        values['rsi14'] = _number(row.get('rsi'))
    for key in ('close', 'ema20', 'ema50', 'ema200'):
        if values[key] is not None and values[key] <= 0:
            values[key] = None
    if values['rsi14'] is not None and not 0 <= values['rsi14'] <= 100:
        values['rsi14'] = None
    close, e20, e50, e200, rsi = (values[key] for key in ('close', 'ema20', 'ema50', 'ema200', 'rsi14'))
    short, long, momentum = 'ข้อมูล EMA20/50 ยังไม่ครบ', 'ข้อมูล EMA200 ยังไม่ครบ', 'ยังไม่มี RSI14'
    if current and all(x is not None for x in (close, e20, e50)):
        short = ('ระยะสั้นเอนขึ้น: ราคาปิด > EMA20 > EMA50' if close > e20 > e50 else
                 'ระยะสั้นเอนลง: ราคาปิด < EMA20 < EMA50' if close < e20 < e50 else
                 'ระยะสั้นยังผสม: ราคาและเส้น EMA ยังไม่เรียงในทิศเดียวกัน')
    if current and close is not None and e200 is not None:
        long = ('ระยะยาวอยู่เหนือ EMA200' if close > e200 else
                'ระยะยาวอยู่ใต้ EMA200' if close < e200 else 'ราคาปิดอยู่ใกล้ EMA200')
    if current and rsi is not None:
        momentum = (f'RSI14 {rsi:.1f}: แรงขายมาก รอสัญญาณกลับตัว' if rsi < 30 else
                    f'RSI14 {rsi:.1f}: แรงซื้อมาก ระวังไล่ราคา' if rsi > 70 else
                    f'RSI14 {rsi:.1f}: ยังไม่อยู่โซนแรงซื้อ/ขายสุดโต่ง')
    if not current:
        short = long = 'ข้อมูลกราฟเก่าหรือไม่ทราบวันที่ รออัปเดต'
        momentum = 'รอ RSI14 จากกราฟที่อัปเดต'
    return {**values, 'asof': asof, 'interval': '1d', 'current': current,
            'short_term': short, 'long_term': long, 'momentum': momentum,
            'summary': short + '; ' + long,
            'basis': 'กราฟรายวัน ณ วันที่ระบุ; ใช้ราคาปิดของแท่งเดียวกันเปรียบเทียบ EMA'}


_OPINION = ('should you', 'should investors', 'is it a buy', 'is still a buy',
            'good buy', 'worth buying', 'here\'s how', 'here’s how', 'passive income',
            'บทวิเคราะห์', 'ควรซื้อ', 'น่าลงทุน')
_IMPACTS = {
    'ผลประกอบการ': ('หากกำไรและแนวโน้มสูงกว่าคาด อาจหนุนราคา',
                   'หากกำไรต่ำกว่าคาดหรือลดประมาณการ อาจกดดันราคา'),
    'ข้อตกลง/การซื้อกิจการ': ('หากรายได้หรือประโยชน์จากดีลมากกว่าต้นทุน อาจหนุนมูลค่า',
                         'หากต้องเพิ่มหนี้มากหรือรวมธุรกิจไม่สำเร็จ อาจกดดันกำไร'),
    'การคืนเงินผู้ถือหุ้น': ('หากมีเงินสดรองรับการจ่ายหรือซื้อคืน อาจช่วยผู้ถือหุ้น',
                       'หากจ่ายเกินกระแสเงินสดหรือต้องลดปันผล อาจกดดันราคา'),
    'สินค้า/กำลังผลิต': ('หากสินค้าเพิ่มยอดขายจริงและรักษากำไรได้ อาจหนุนธุรกิจ',
                    'หากยอดขายไม่ถึงเป้าหรือต้นทุนเพิ่มเร็ว อาจกดดันกำไร'),
    'มุมมองมูลค่าจากบทวิเคราะห์': ('หากสมมติฐานกำไรที่เพิ่มขึ้นเกิดจริง อาจหนุนมูลค่า',
                              'หากราคาไปรับข่าวแล้วหรือสมมติฐานผิด อาจย่อตัว'),
    'กฎเกณฑ์/คดี/การดำเนินงาน': ('หากผลอนุมัติหรือข้อยุติลดข้อจำกัด อาจหนุนธุรกิจ',
                              'หากมีค่าปรับ ข้อจำกัด หรือต้นทุนใหม่ อาจกดดันกำไร'),
}


def news_analysis(article):
    reviewed = article.get('evidence_type') == 'reviewed_source'
    title = _text(article.get('title'), 240)
    topic = _text(article.get('topic'), 100) or 'ข่าวบริษัท'
    opinion = any(word in title.casefold() for word in _OPINION)
    positive, negative = _IMPACTS.get(topic, (
        'หากเหตุการณ์เพิ่มรายได้หรือเงินสดสุทธิ อาจหนุนธุรกิจ',
        'หากเหตุการณ์เพิ่มต้นทุน หนี้ หรือข้อจำกัด อาจกดดันธุรกิจ'))
    if reviewed:
        positive = _text(article.get('positive_th'), 240) or positive
        negative = _text(article.get('negative_th'), 240) or negative
    return {'type_label': 'บทวิเคราะห์/ความเห็น' if opinion else 'ข่าว/ประกาศบริษัท' if reviewed else 'ข่าว/รายงาน',
            'topic': topic, 'evidence_label': 'อ่านและตรวจสอบต้นฉบับแล้ว' if reviewed else 'มีหัวข้อข่าวจากต้นทาง',
            'positive_case': positive, 'negative_case': negative,
            'watch': _text(article.get('context'), 240),
            'direction': _text(article.get('direction'), 30) if reviewed else 'unassessed'}
