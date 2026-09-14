"""Period-matched historical financial research from the published bundle only.

No network requests, profile substitutes, missing-to-zero conversions, summed
EPS/share counts, or inferred issuance. Each chart and export uses these rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from financial_statements import SCHEMA, SOURCE, day, number, consecutive_quarters

LABELS = {
    'revenue': 'รายได้ (Revenue)',
    'grossProfit': 'กำไรขั้นต้น (GP)',
    'operatingIncome': 'กำไรจากการดำเนินงาน (Operating Income)',
    'netIncome': 'กำไรสุทธิ (NI)',
    'operatingCashflow': 'กระแสเงินสดจากการดำเนินงาน (OCF)',
    'freeCashflow': 'กระแสเงินสดอิสระ (FCF)',
    'capex': 'เงินลงทุนในสินทรัพย์ (CapEx)',
    'stockBasedCompensation': 'ค่าตอบแทนเป็นหุ้น (SBC)',
    'grossMargins': 'อัตรากำไรขั้นต้น (GPM)',
    'operatingMargins': 'อัตรากำไรจากการดำเนินงาน (OPM)',
    'profitMargins': 'อัตรากำไรสุทธิ (NPM)',
    'fcfMargin': 'อัตรากระแสเงินสดอิสระ (FCF Margin)',
    'cashConversion': 'เงินสดเทียบกำไรสุทธิ (OCF / NI)',
    'sbcToRevenue': 'ค่าตอบแทนเป็นหุ้นต่อรายได้ (SBC / Revenue)',
    'totalDebt': 'หนี้ที่มีดอกเบี้ย (Total Debt)',
    'cash': 'เงินสดและเงินลงทุนระยะสั้น (Cash & Short-Term Investments)',
    'netDebt': 'หนี้สุทธิ (Net Debt)',
    'buybacks': 'เงินสดซื้อหุ้นคืนขั้นต้น (Gross Share Repurchases)',
    'issuanceOfCapitalStock': 'เงินสดรับจากการออกหุ้น (Stock Issuance)',
    'netBuybackCash': 'เงินสดซื้อหุ้นคืนหักเงินรับออกหุ้น (Net Repurchase Cash)',
    'dilutedAverageShares': 'หุ้นถัวเฉลี่ยถ่วงน้ำหนักปรับลด (Diluted Average Shares)',
    'ordinarySharesNumber': 'หุ้นสามัญ ณ วันสิ้นงวด (Ordinary Shares Number)',
    'dilutedEPS': 'กำไรต่อหุ้นปรับลด (Diluted EPS)',
    'revenueGrowth': 'การเติบโตของรายได้เทียบปีก่อน (Revenue YoY)',
    'netIncomeGrowth': 'การเติบโตของกำไรเทียบปีก่อน (Net Income YoY)',
    'shareCountGrowth': 'การเปลี่ยนหุ้นสามัญเทียบปีก่อน (Ordinary Shares YoY)',
    'dilutedSharesGrowth': 'การเปลี่ยนหุ้นถัวเฉลี่ยเทียบปีก่อน (Diluted Shares YoY)',
}
PERCENT_KEYS = frozenset(('grossMargins', 'operatingMargins', 'profitMargins', 'fcfMargin',
                         'sbcToRevenue', 'revenueGrowth', 'netIncomeGrowth', 'shareCountGrowth',
                         'dilutedSharesGrowth'))
STATE_LABELS = {
    'available': 'มีข้อมูล', 'not_reported': 'ไม่มีข้อมูลรายงาน',
    'missing_inputs': 'ข้อมูลสำหรับคำนวณไม่ครบ', 'invalid': 'พักใช้ข้อมูลผิดปกติ',
    'not_meaningful': 'คำนวณอัตราส่วนอย่างมีความหมายไม่ได้',
    'period_mismatch': 'รอบบัญชีไม่ตรงกัน', 'currency_mismatch': 'สกุลเงินไม่ตรงกัน',
    'not_applicable': 'ไม่ใช้กับหลักทรัพย์ประเภทนี้',
}
INCOME = ('revenue', 'grossProfit', 'operatingIncome', 'netIncome', 'dilutedEPS', 'dilutedAverageShares')
CASHFLOW = ('operatingCashflow', 'capitalExpenditure', 'freeCashflow',
            'stockBasedCompensation', 'repurchaseOfCapitalStock', 'issuanceOfCapitalStock')
BALANCE = ('totalDebt', 'cash', 'ordinarySharesNumber')


def _item(value=None, state='not_reported', reason='', *, end=None, basis=None,
          currency=None, source=SOURCE, formula='', period_ends=()):
    return {'value': value, 'state': state, 'reason': reason, 'end': end,
            'basis': basis, 'currency': currency, 'source': source,
            'formula': formula, 'period_ends': list(period_ends)}


def _records(bundle, period, kind, today, issues):
    """Reject ambiguous periods and explicit currency/duration mismatches."""
    section = bundle.get(period, {})
    records = section.get(kind, []) if isinstance(section, dict) else []
    if not isinstance(records, list):
        issues.append(f'{period}.{kind}: รูปแบบงบไม่ถูกต้อง')
        return {}
    result, blocked = {}, set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('values'), dict):
            issues.append(f'{period}.{kind}: รูปแบบรายการไม่ถูกต้อง')
            continue
        end = day(record.get('end'))
        if end is None or end > today:
            issues.append(f'{period}.{kind}: ไม่ใช้วันที่ไม่ถูกต้องหรือวันที่ในอนาคต')
            continue
        key = end.isoformat()
        if key in blocked:
            continue
        # A conflicting duplicate date cannot be chosen arbitrarily.
        if key in result:
            if result[key] != record:
                blocked.add(key)
                reason = f'{period}.{kind} {key}: รายการวันเดียวกันขัดแย้งกัน'
                result[key] = {'end': key, 'values': {}, '_blocked': reason}
                issues.append(reason)
            continue
        result[key] = {**record, 'end': key}
    return result


def _raw(record, key, bundle, basis, *, end):
    currency = bundle.get('currency')
    common = dict(end=end, basis=basis, currency=currency,
                  source=bundle.get('source') or SOURCE, period_ends=(end,))
    if record is None:
        return _item(reason='ไม่มีงบประเภทนี้สำหรับวันสิ้นงวดเดียวกัน', **common)
    if record.get('_blocked'):
        return _item(state='invalid', reason=record['_blocked'], **common)
    explicit_currency = record.get('currency')
    if explicit_currency and explicit_currency != currency:
        return _item(state='currency_mismatch', reason='สกุลเงินของรายการต่างจากสกุลเงินงบ', **common)
    explicit_basis = str(record.get('basis') or '').upper()
    allowed = ('FY', 'ANNUAL', 'YEARLY') if basis == 'FY' else ('Q', 'QUARTERLY', 'QUARTER')
    if explicit_basis and explicit_basis not in allowed:
        return _item(state='period_mismatch', reason='ระยะเวลารายการไม่ตรงกับงบรายปีหรือรายไตรมาสที่เลือก', **common)
    value = record['values'].get(key)
    if value is None:
        return _item(reason='ผู้ให้ข้อมูลไม่ได้รายงานรายการนี้', **common)
    parsed = number(value)
    if parsed is None:
        return _item(state='invalid', reason='ค่าที่รายงานไม่ใช่จำนวนจำกัดที่ใช้คำนวณได้', **common)
    if key in ('totalDebt', 'cash', 'ordinarySharesNumber', 'dilutedAverageShares', 'issuanceOfCapitalStock') and parsed < 0:
        return _item(state='invalid', reason='เครื่องหมายของข้อมูลต้นทางผิดจากนิยามรายการ', **common)
    if key in ('capitalExpenditure', 'repurchaseOfCapitalStock') and parsed > 0:
        return _item(state='invalid', reason='เงินสดจ่ายในข้อมูลต้นทางเป็นบวก จึงพักใช้เพื่อไม่กลับความหมาย', **common)
    return _item(parsed, 'available', formula=f'รายการที่รายงาน: {key}', **common)


def _derived(items, keys, fn, formula, *, denominator=None, match_period=True, percent=False):
    rows = [items.get(k, _item()) for k in keys]
    lead = rows[0]
    common = {k: lead[k] for k in ('end', 'basis', 'currency', 'source', 'period_ends')}
    if any(r['state'] != 'available' for r in rows):
        failures = [r for r in rows if r['state'] != 'available']
        state = next((r['state'] for r in failures if r['state'] in ('invalid', 'currency_mismatch', 'period_mismatch')), 'missing_inputs')
        return _item(state=state, reason='; '.join(dict.fromkeys(r['reason'] for r in failures)), formula=formula, **common)
    if len({r['currency'] for r in rows}) != 1:
        return _item(state='currency_mismatch', reason='ไม่รวมรายการต่างสกุลเงิน', formula=formula, **common)
    if match_period and len({(r['basis'], r['end'], tuple(r['period_ends'])) for r in rows}) != 1:
        return _item(state='period_mismatch', reason='ต้องใช้รายการของงวดและชุดไตรมาสเดียวกัน', formula=formula, **common)
    values = [r['value'] for r in rows]
    if denominator is not None and values[denominator] <= 0:
        return _item(state='not_meaningful', reason='ฐานเปรียบเทียบเป็นศูนย์หรือติดลบ ไม่แสดงเป็นอัตราส่วนปกติ', formula=formula, **common)
    try:
        value = number(fn(*values))
    except (ZeroDivisionError, OverflowError):
        value = None
    if value is not None and percent and number(value * 100) is None:
        value = None
    return _item(value, 'available' if value is not None else 'invalid',
                 '' if value is not None else 'ผลคำนวณไม่ใช่จำนวนจำกัด', formula=formula, **common)


def _finish(items):
    for key, raw in (('capex', 'capitalExpenditure'), ('buybacks', 'repurchaseOfCapitalStock')):
        items[key] = _derived(items, [raw], lambda x: -x, 'เปลี่ยนเงินสดจ่ายที่รายงานเป็นจำนวนเงินที่ใช้จ่าย')
    calculated_fcf = _derived(items, ['operatingCashflow', 'capex'], lambda x, y: x-y, 'OCF − CapEx ของงวดเดียวกัน')
    source_fcf = items['freeCashflow']
    if source_fcf['state'] == 'not_reported':
        items['freeCashflow'] = calculated_fcf
    elif source_fcf['state'] == calculated_fcf['state'] == 'available':
        tolerance = max(1., abs(source_fcf['value']) * 1e-6,
                        abs(items['operatingCashflow']['value']) * 1e-6,
                        abs(items['capex']['value']) * 1e-6)
        if abs(source_fcf['value'] - calculated_fcf['value']) > tolerance:
            items['freeCashflow'] = {**source_fcf, 'value': None, 'state': 'invalid',
                'reason': 'FCF ที่รายงานไม่สอดคล้องกับ OCF − CapEx ของงวดเดียวกัน จึงพักใช้'}
    for key, top in (('grossMargins', 'grossProfit'), ('operatingMargins', 'operatingIncome'),
                     ('profitMargins', 'netIncome'), ('fcfMargin', 'freeCashflow'),
                     ('sbcToRevenue', 'stockBasedCompensation')):
        items[key] = _derived(items, [top, 'revenue'], lambda x, y: x/y, f'{top} / revenue ของงวดเดียวกัน', denominator=1, percent=True)
    items['cashConversion'] = _derived(items, ['operatingCashflow', 'netIncome'], lambda x, y: x/y, 'OCF / กำไรสุทธิที่เป็นบวกของงวดเดียวกัน', denominator=1)
    items['netDebt'] = _derived(items, ['totalDebt', 'cash'], lambda x, y: x-y, 'หนี้ที่มีดอกเบี้ย − เงินสดและเงินลงทุนระยะสั้น ณ วันเดียวกัน')
    items['netBuybackCash'] = _derived(items, ['buybacks', 'issuanceOfCapitalStock'], lambda x, y: x-y, 'เงินสดซื้อหุ้นคืนขั้นต้น − เงินสดรับออกหุ้นของงวดเดียวกัน')
    return items


def _growth(rows):
    for row in rows:
        current_end = day(row['end'])
        candidates = [r for r in rows if 350 <= (current_end-day(r['end'])).days <= 380]
        prior = candidates[0] if len(candidates) == 1 else None
        for target, raw in (('revenueGrowth', 'revenue'), ('netIncomeGrowth', 'netIncome'),
                            ('shareCountGrowth', 'ordinarySharesNumber'), ('dilutedSharesGrowth', 'dilutedAverageShares')):
            current = row['metrics'][raw]
            old = prior['metrics'][raw] if prior else _item(reason='ยังไม่มีงวดเทียบปีก่อนที่ห่างกัน 350–380 วัน')
            row['metrics'][target] = _derived({'current': current, 'prior': old}, ['current', 'prior'],
                lambda x, y: x/y-1, f'{raw} / {raw} งวดเทียบปีก่อน − 1', denominator=1, match_period=False, percent=True)
            row['metrics'][target]['comparison_end'] = prior['end'] if prior else None


def build_financial_trends(ticker, info, bundle, *, today=None):
    """Return ascending FY/Q/TTM rows; balance values always retain point dates."""
    today = day(today) if today is not None else datetime.now(timezone.utc).date()
    if today is None:
        raise ValueError('today must be a valid calendar date')
    info = info or {}
    result = {'state': 'available', 'reason': '', 'currency': None, 'source': SOURCE,
              'fetched_at': None, 'periods': {'FY': [], 'Q': [], 'TTM': []}, 'issues': []}
    if str(info.get('quoteType') or '').upper() in ('ETF', 'MUTUALFUND'):
        return {**result, 'state': 'not_applicable', 'reason': 'กองทุนใช้การวิเคราะห์เฉพาะกองทุนแทนงบบริษัท'}
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA or bundle.get('ticker') != ticker:
        return {**result, 'state': 'missing_inputs', 'reason': 'ยังไม่มีชุดงบที่ตรวจสอบรหัสหุ้นและรูปแบบได้'}
    currency = bundle.get('currency')
    if not isinstance(currency, str) or not currency.strip():
        return {**result, 'state': 'missing_inputs', 'reason': 'ยังไม่มีสกุลเงินงบที่รายงาน จึงไม่แสดงจำนวนเงินหรือคำนวณรวม'}
    if info.get('financialCurrency') and info['financialCurrency'] != currency:
        return {**result, 'state': 'currency_mismatch', 'reason': 'สกุลเงินงบต่างจากสกุลเงินรายงานของบริษัท ต้องตรวจสอบแหล่งข้อมูลก่อน'}
    result.update(currency=currency, source=bundle.get('source') or SOURCE, fetched_at=bundle.get('fetched_at'))
    records = {}
    for basis, period in (('FY', 'annual'), ('Q', 'quarterly')):
        records[basis] = {kind: _records(bundle, period, kind, today, result['issues']) for kind in ('income', 'cashflow', 'balance')}
        ends = sorted(set().union(*(set(r) for r in records[basis].values())))
        for end in ends:
            items = {}
            for kind, keys in (('income', INCOME), ('cashflow', CASHFLOW), ('balance', BALANCE)):
                record = records[basis][kind].get(end)
                for key in keys:
                    # Balance values refer to a point in time, not a flow duration.
                    items[key] = _raw(record, key, bundle, basis, end=end)
                    if kind == 'balance':
                        items[key]['basis'] = 'Balance sheet'
            result['periods'][basis].append({'end': end, 'basis': basis, 'metrics': _finish(items)})
        _growth(result['periods'][basis])
    # Preserve each statement's actual quarter window. A shifted or missing
    # cash-flow quarter cannot accidentally pass a same-end-only ratio check.
    quarter_ends = sorted(set(records['Q']['income']) | set(records['Q']['cashflow']))
    for end in quarter_ends:
        items = {}
        any_window = False
        for kind, keys in (('income', INCOME), ('cashflow', CASHFLOW)):
            available = [records['Q'][kind][d] for d in sorted(records['Q'][kind], reverse=True) if d <= end][:4]
            complete = bool(available and available[0]['end'] == end and consecutive_quarters(available))
            any_window |= complete
            for key in keys:
                base = dict(end=end, basis='TTM', currency=currency, source=result['source'])
                if key in ('dilutedEPS', 'dilutedAverageShares'):
                    items[key] = _item(state='not_reported', reason='ไม่บวก EPS หรือหุ้นถัวเฉลี่ยรายไตรมาสเป็น TTM; ดูค่าที่รายงานใน FY หรือ Q', **base)
                elif not complete:
                    items[key] = _item(state='missing_inputs', reason='ยังไม่มี 4 ไตรมาสต่อเนื่องที่สิ้นสุดในงวดนี้', **base)
                else:
                    if key == 'freeCashflow':
                        # Validate each quarter before summing: opposite source
                        # errors must not cancel into a seemingly correct TTM.
                        quarter_rows = {r['end']: r for r in result['periods']['Q']}
                        parts = [quarter_rows[r['end']]['metrics'][key] for r in available]
                    else:
                        parts = [_raw(r, key, bundle, 'Q', end=r['end']) for r in available]
                    failures = [p for p in parts if p['state'] != 'available']
                    failure = next((p for state in ('invalid', 'currency_mismatch', 'period_mismatch')
                                    for p in failures if p['state'] == state), failures[0] if failures else None)
                    # Missing reported FCF can still derive from complete OCF and
                    # CapEx; an invalid reported value must remain quarantined.
                    state = failure['state'] if failure else 'available'
                    total = number(sum(p['value'] for p in parts)) if not failure else None
                    if not failure and total is None:
                        state = 'invalid'
                    items[key] = _item(total, state,
                        failure['reason'] if failure else '' if total is not None else 'ผลรวมไม่ใช่จำนวนจำกัด',
                        formula='ผลรวม 4 ไตรมาสที่รายงานต่อเนื่อง', period_ends=[r['end'] for r in available], **base)
        if not any_window:
            continue
        # Use the same-end quarterly balance, or its annual copy if missing.
        # Conflicting overlapping values are withheld, not arbitrarily selected.
        annual_balance = records['FY']['balance'].get(end)
        quarterly_balance = records['Q']['balance'].get(end)
        for key in BALANCE:
            a = _raw(annual_balance, key, bundle, 'FY', end=end)
            q = _raw(quarterly_balance, key, bundle, 'Q', end=end)
            chosen = q if q['state'] != 'not_reported' else a
            if a['state'] == q['state'] == 'available' and a['value'] != q['value']:
                chosen = {**q, 'value': None, 'state': 'invalid', 'reason': 'งบรายปีและรายไตรมาสวันเดียวกันรายงานยอดต่างกัน'}
            items[key] = {**chosen, 'basis': 'Balance sheet'}
        result['periods']['TTM'].append({'end': end, 'basis': 'TTM', 'metrics': _finish(items)})
    _growth(result['periods']['TTM'])
    if not any(result['periods'].values()):
        result.update(state='missing_inputs', reason='ยังไม่มีรายการงบที่มีวันสิ้นงวดถูกต้อง')
    return result


def export_trends(result, basis=None):
    """Long-form exact observations, including unavailable states and provenance."""
    rows = []
    for selected in ([basis] if basis else ('FY', 'Q', 'TTM')):
        for period in result['periods'].get(selected, []):
            for key, label in LABELS.items():
                item = period['metrics'][key]
                unit = '%' if key in PERCENT_KEYS else 'เท่า' if key == 'cashConversion' else 'หุ้น' if key in ('dilutedAverageShares', 'ordinarySharesNumber') else f'{result["currency"]}/หุ้น' if key == 'dilutedEPS' else result['currency']
                value = item['value']
                rows.append({'รอบบัญชี': selected, 'วันสิ้นงวด': period['end'], 'รายการ': label,
                    'รหัสรายการ': key, 'ค่า': value * 100 if value is not None and key in PERCENT_KEYS else value,
                    'หน่วย': unit, 'สถานะ': STATE_LABELS.get(item['state'], item['state']),
                    'เหตุผล': item['reason'], 'สูตร': item['formula'], 'สกุลเงินงบ': result['currency'],
                    'ประเภทข้อมูล': item['basis'], 'วันสิ้นงวดที่ใช้คำนวณ': ', '.join(item['period_ends']),
                    'วันสิ้นงวดเทียบปีก่อน': item.get('comparison_end'),
                    'แหล่งข้อมูล': item['source'], 'ดึงข้อมูลเมื่อ': result['fetched_at']})
    return rows
