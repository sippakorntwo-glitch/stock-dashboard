"""Transparent terminal-price scenarios, never a DCF or an investment rating.

Only positive, explicitly identified per-share bases can feed a multiple model.
The model discounts a terminal share price; it does not value interim dividends.
"""
from __future__ import annotations

from datetime import date
import math
import re

from asset_semantics import kind_for
from company_metrics import metric_observations
from financial_statements import SCHEMA, day, number

MODEL_LABELS = {
    'eps': 'กำไรต่อหุ้น × P/E',
    'book': 'มูลค่าตามบัญชีต่อหุ้น × P/B',
    'ffo': 'FFO ต่อหุ้น × P/FFO',
}


def valuation_basis(ticker, info, row, bundle=None):
    """Keep source states and units; never combine FY EPS with newer TTM margins."""
    info = info or {}
    row = row if row is not None else {}
    fund = kind_for(ticker, info, str(row.get('Asset_Type', '')).upper() == 'ETF') != 'company'
    industry = str(info.get('industry') or '').casefold()
    sector = str(info.get('sector') or '').casefold()
    model = ('ffo' if 'reit' in industry else 'book'
             if sector in ('financial services', 'financial') or any(
                 word in industry for word in ('banks', 'insurance', 'credit services')) else 'eps')
    price = number(row.get('Close'))
    # The screener close is dated. Avoid silently substituting a stale profile quote.
    price_end = str(row.get('Price_AsOf') or '')
    if price is None or price <= 0 or day(price_end) is None or day(price_end) > date.today():
        price = None
    quote_currency = info.get('currency')
    result = dict(model=model, state='not_reported', value=None, currency=None,
                  period=None, source=None, margin=None, revenue=None, net_income=None,
                  quote_price=price, quote_currency=quote_currency, quote_as_of=price_end,
                  manual=False, reason='ยังไม่มีฐานต่อหุ้นที่ยืนยันหน่วยและรอบบัญชี')
    if fund:
        return {**result, 'state': 'not_applicable', 'reason': 'ETF / ETP ใช้การวิเคราะห์กองทุน ไม่ใช้แบบจำลองกำไรบริษัท'}
    if model != 'eps':
        label = 'FFO ต่อหุ้น' if model == 'ffo' else 'มูลค่าตามบัญชีต่อหุ้น (BVPS)'
        return {**result, 'reason': f'กรอก {label} จากรายงานที่ตรวจสอบแล้ว พร้อมวันที่ สกุลเงิน และหน่วยหุ้นที่ซื้อขาย'}
    item = metric_observations(ticker, info, bundle).get('dilutedEPS', {})
    value = number(item.get('value'))
    result.update(value=value, state=item.get('state', 'not_reported'), currency=item.get('currency'),
                  period=item.get('end') or item.get('basis'), source=item.get('source'))
    if result['state'] != 'available' or value is None:
        result['reason'] = 'แหล่งข้อมูลยังไม่มี EPS ที่ใช้เป็นฐานได้'
        return result
    if value <= 0:
        result.update(state='not_meaningful', reason='EPS เป็นศูนย์หรือติดลบ จึงใช้ P/E สร้างราคาจำลองไม่ได้')
        return result
    result['reason'] = ''
    valid = (isinstance(bundle, dict) and bundle.get('schema') == SCHEMA
             and bundle.get('ticker') == ticker and bundle.get('currency')
             and item.get('basis') == 'FY')
    if valid:
        matches = [record for record in bundle.get('annual', {}).get('income', [])
                   if record.get('end') == item.get('end')]
        if len(matches) == 1:
            values = matches[0].get('values', {})
            revenue, income, eps = (number(values.get(k)) for k in ('revenue', 'netIncome', 'dilutedEPS'))
            if (revenue is not None and revenue > 0 and income is not None and income > 0
                    and eps is not None and math.isclose(eps, value, rel_tol=1e-9)):
                result.update(margin=income / revenue, revenue=revenue, net_income=income)
    return result


def verified_basis(original, *, value, currency, period, source, confirmed):
    """Explicit user-supplied research assumption; does not replace canonical data."""
    result = {**original, 'manual': True, 'margin': None, 'revenue': None, 'net_income': None,
              'value': number(value), 'currency': str(currency or '').strip().upper(),
              'period': str(period or '').strip(), 'source': str(source or '').strip()}
    valid = (original.get('state') != 'not_applicable' and confirmed
             and result['value'] is not None and result['value'] > 0
             and re.fullmatch(r'[A-Z]{3}', result['currency'])
             and day(result['period']) is not None and day(result['period']) <= date.today()
             and bool(result['source']))
    result.update(state='available' if valid else 'unverified',
                  reason='' if valid else 'ต้องยืนยันค่าฐานบวก วันที่ไม่อยู่ในอนาคต สกุลเงิน 3 ตัวอักษร และแหล่งอ้างอิง')
    return result


def market_comparison(basis, *, share_unit_confirmed=False):
    if not share_unit_confirmed:
        return False, 'ยังไม่ยืนยันว่าฐานต่อหุ้นใช้หน่วยเดียวกับหุ้น / ADR ที่ซื้อขาย'
    quote, currency = basis.get('quote_currency'), basis.get('currency')
    if not quote or not currency or quote != currency:
        return False, 'สกุลเงินราคาและฐานต่อหุ้นต่างกันหรือไม่ระบุ จึงไม่เปรียบเทียบกับราคาตลาด'
    if number(basis.get('quote_price')) is None or basis['quote_price'] <= 0:
        return False, 'ยังไม่มีราคาบวกพร้อมวันที่อ้างอิงที่ใช้ได้'
    return True, ''


def price_scenario(basis, *, growth, multiple, required_return, years, dilution=0.0,
                   terminal_margin=None, share_unit_confirmed=False):
    """Rates are decimals. Growth is revenue when margin is set, else total base.

    Per-share base_t = base_0 * ((1+growth)/(1+dilution))**years
                      * (terminal_margin/base_margin, when matched).
    """
    fail = dict(state='invalid', terminal_base=None, terminal_price=None, present_price=None,
                price_gap=None, price_cagr=None, implied_growth=None, comparable=False)
    if basis.get('state') != 'available' or number(basis.get('value')) is None or basis['value'] <= 0:
        return {**fail, 'reason': basis.get('reason') or 'ไม่มีฐานต่อหุ้นบวกที่ใช้ได้'}
    fields = [number(v) for v in (growth, multiple, required_return, years, dilution)]
    if any(v is None for v in fields):
        return {**fail, 'reason': 'สมมติฐานต้องเป็นตัวเลขที่มีค่าจำกัด'}
    growth, multiple, required_return, years, dilution = fields
    if not (-1 < growth <= 10 and 0 < multiple <= 1000 and -1 < required_return <= 10
            and 1 <= years <= 30 and years.is_integer() and -1 < dilution <= 10):
        return {**fail, 'reason': 'สมมติฐานอยู่นอกช่วงที่แบบจำลองรองรับ'}
    margin_factor = 1.0
    if terminal_margin is not None:
        margin, starting_margin = number(terminal_margin), number(basis.get('margin'))
        if margin is None or margin <= 0 or starting_margin is None or starting_margin <= 0:
            return {**fail, 'reason': 'การปรับอัตรากำไรต้องมีฐานรายได้ กำไร และ EPS ปีเดียวกันที่เป็นบวก'}
        margin_factor = margin / starting_margin
    try:
        future_base = basis['value'] * ((1 + growth) / (1 + dilution)) ** years * margin_factor
        terminal = future_base * multiple
        present = terminal / (1 + required_return) ** years
    except (OverflowError, ZeroDivisionError):
        return {**fail, 'reason': 'ผลคำนวณอยู่นอกช่วงตัวเลขที่รองรับ'}
    if not all(math.isfinite(v) and v > 0 for v in (future_base, terminal, present)):
        return {**fail, 'reason': 'ผลคำนวณไม่มีค่าจำกัดหรือเป็นศูนย์'}
    comparable, reason = market_comparison(basis, share_unit_confirmed=share_unit_confirmed)
    result = dict(state='available', terminal_base=future_base, terminal_price=terminal,
                  present_price=present, price_gap=None, price_cagr=None, implied_growth=None,
                  comparable=comparable, reason=reason)
    if comparable:
        price = basis['quote_price']
        try:
            gap = present / price - 1
            cagr = (terminal / price) ** (1 / years) - 1
            implied = (price * (1 + required_return) ** years /
                       (basis['value'] * multiple * margin_factor)) ** (1 / years) * (1 + dilution) - 1
        except (OverflowError, ZeroDivisionError):
            gap = cagr = implied = float('inf')
        if all(math.isfinite(v) for v in (gap, cagr, implied)):
            result.update(price_gap=gap, price_cagr=cagr, implied_growth=implied)
        else:
            result.update(comparable=False, reason='ผลเปรียบเทียบอยู่นอกช่วงตัวเลขที่รองรับ')
    return result


def sensitivity(basis, *, growths, multiples, required_return, years, dilution=0.0,
                terminal_margin=None):
    return [dict(growth=growth, multiple=multiple, **price_scenario(
        basis, growth=growth, multiple=multiple, required_return=required_return,
        years=years, dilution=dilution, terminal_margin=terminal_margin))
        for growth in growths for multiple in multiples]
