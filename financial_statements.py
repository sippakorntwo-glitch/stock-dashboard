"""Dated financial observations. Collection is separate from page rendering.

Never sum incomplete quarters, mix currencies/periods, assume a missing value is
zero, or substitute EBITDA for EBIT. Provider statements are retained alongside
derived values so a calculation can be inspected and audited.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math

SCHEMA = 1
SOURCE = 'Yahoo Finance financial statements'
FLOW_FIELDS = {
    'revenue': ('Total Revenue',),
    'grossProfit': ('Gross Profit',),
    'operatingIncome': ('Operating Income',),
    'ebit': ('EBIT',),
    'ebitda': ('EBITDA',),
    'netIncome': ('Net Income',),
    'dilutedEPS': ('Diluted EPS',),
    'interestExpense': ('Interest Expense',),
    'pretaxIncome': ('Pretax Income',),
    'taxProvision': ('Tax Provision',),
    'operatingCashflow': ('Operating Cash Flow', 'Total Cash From Operating Activities'),
    'capitalExpenditure': ('Capital Expenditure', 'Capital Expenditures'),
    'freeCashflow': ('Free Cash Flow',),
    'repurchaseOfCapitalStock': ('Repurchase Of Capital Stock',),
    'stockBasedCompensation': ('Stock Based Compensation',),
    'cashDividendsPaid': ('Cash Dividends Paid', 'Common Stock Dividend Paid'),
}
BALANCE_FIELDS = {
    'totalAssets': ('Total Assets',),
    'totalLiabilities': ('Total Liabilities Net Minority Interest',),
    'stockholdersEquity': ('Stockholders Equity',),
    'totalDebt': ('Total Debt',),
    'cash': ('Cash Cash Equivalents And Short Term Investments',),
    'currentAssets': ('Current Assets',),
    'currentLiabilities': ('Current Liabilities',),
    'receivables': ('Receivables', 'Accounts Receivable'),
    'inventory': ('Inventory',),
}
INCOME_KEYS = tuple(FLOW_FIELDS)[:10]
CASHFLOW_KEYS = tuple(FLOW_FIELDS)[10:]


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def statement_records(frame, fields, *, today=None):
    """Normalize provider frames without coercing missing observations to zero."""
    today = today or datetime.now(timezone.utc).date()
    if frame is None or getattr(frame, 'empty', True):
        return []
    records = []
    seen = set()
    for column in frame.columns:
        end = day(column)
        if end is None or end > today or end in seen:
            continue
        seen.add(end)
        values = {}
        for field, aliases in fields.items():
            for alias in aliases:
                # Duplicate statement labels are ambiguous, not first-wins.
                if list(frame.index).count(alias) != 1:
                    continue
                value = number(frame.loc[alias, column])
                if value is not None:
                    values[field] = value
                    break
        if values:
            records.append({'end': end.isoformat(), 'values': values})
    return sorted(records, key=lambda r: r['end'], reverse=True)[:6]


def consecutive_quarters(records):
    if len(records) < 4:
        return False
    dates = [day(r['end']) for r in records[:4]]
    return all(dates) and all(65 <= (a-b).days <= 115 for a, b in zip(dates, dates[1:]))


def observations(bundle):
    """Choose a common TTM window, else a common fiscal year, for flow ratios."""
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        return {}
    currency = bundle.get('currency') or 'Currency not reported'
    result = {}

    def put(key, value, basis, end, formula=None, state='available', reason=''):
        value = number(value)
        if key in ('revenue','totalAssets','totalLiabilities','totalDebt','cash',
                   'currentAssets','currentLiabilities','receivables','inventory') and value is not None and value < 0:
            value, state, reason = None, 'invalid', 'Unexpected negative source amount'
        result[key] = {'value': value, 'basis': basis, 'end': end,
                       'currency': currency, 'source': SOURCE, 'formula': formula,
                       'state': state if value is not None or state != 'available' else 'missing_inputs',
                       'reason': reason}

    quarterly = bundle.get('quarterly', {})
    annual = bundle.get('annual', {})
    qi, qc = quarterly.get('income', []), quarterly.get('cashflow', [])
    q_ok = (consecutive_quarters(qi) and consecutive_quarters(qc)
            and [r['end'] for r in qi[:4]] == [r['end'] for r in qc[:4]])
    if q_ok:
        flow_end = qi[0]['end']
        basis = 'TTM (4 reported quarters)'
        groups = [(qi[:4], INCOME_KEYS), (qc[:4], CASHFLOW_KEYS)]
        for rows, keys in groups:
            for key in keys:
                # Annual diluted EPS cannot safely be reconstructed by adding
                # quarterly EPS when weighted average share counts differ.
                if key == 'dilutedEPS':
                    continue
                values = [number(r['values'].get(key)) for r in rows]
                if all(v is not None for v in values):
                    put(key, sum(values), basis, flow_end, 'Sum of 4 consecutive reported quarters')
    else:
        ai, ac = annual.get('income', []), annual.get('cashflow', [])
        income_dates = {r['end'] for r in ai}
        cash_dates = {r['end'] for r in ac}
        common = sorted(income_dates & cash_dates, reverse=True)
        # Still display available single statements; only combine matched bases.
        flow_end = common[0] if common else None
        basis = 'FY'
        for rows, keys in [(ai, INCOME_KEYS), (ac, CASHFLOW_KEYS)]:
            selected = next((r for r in rows if r['end'] == flow_end), None) if flow_end else (rows[0] if rows else None)
            if selected:
                for key in keys:
                    if key in selected['values']:
                        put(key, selected['values'][key], basis, selected['end'])

    balances = {r['end']: r for r in annual.get('balance', [])}
    balances.update({r['end']: r for r in quarterly.get('balance', [])})
    latest_balance = balances[max(balances)] if balances else None
    if latest_balance:
        for key, value in latest_balance['values'].items():
            if key in BALANCE_FIELDS:
                put(key, value, 'Balance sheet', latest_balance['end'])

    def derived(key, inputs, fn, formula, *, denominator=None, same_basis=True):
        rows = [result.get(name, {}) for name in inputs]
        if not all(r.get('state') == 'available' and r.get('value') is not None for r in rows):
            return
        if len({r['currency'] for r in rows}) != 1 or (same_basis and len({(r['basis'], r['end']) for r in rows}) != 1):
            return
        values = [r['value'] for r in rows]
        if denominator is not None and values[denominator] <= 0:
            put(key, None, rows[0]['basis'], rows[0]['end'], formula,
                'not_meaningful', 'Denominator is zero or negative')
            return
        try:
            value = fn(*values)
        except (ZeroDivisionError, OverflowError):
            return
        put(key, value, rows[0]['basis'], rows[0]['end'], formula)

    for key, numerator in [('grossMargins', 'grossProfit'), ('operatingMargins', 'operatingIncome'),
                           ('profitMargins', 'netIncome'), ('fcfMargin', 'freeCashflow')]:
        derived(key, [numerator, 'revenue'], lambda x,y: x/y, f'{numerator} / revenue', denominator=1)
    derived('debtToEquity', ['totalDebt', 'stockholdersEquity'], lambda x,y: x/y,
            'Interest-bearing total debt / shareholders equity', denominator=1)
    derived('liabilitiesToEquity', ['totalLiabilities', 'stockholdersEquity'], lambda x,y: x/y,
            'Total liabilities / shareholders equity', denominator=1)
    derived('currentRatio', ['currentAssets', 'currentLiabilities'], lambda x,y: x/y,
            'Current assets / current liabilities', denominator=1)
    derived('cashRatio', ['cash', 'currentLiabilities'], lambda x,y: x/y,
            'Cash, equivalents and short-term investments / current liabilities', denominator=1)
    derived('quickRatio', ['cash', 'receivables', 'currentLiabilities'], lambda x,y,z: (x+y)/z,
            '(Cash, equivalents, short-term investments + receivables) / current liabilities', denominator=2)
    derived('netDebt', ['totalDebt', 'cash'], lambda x,y: x-y, 'Total debt - cash and short-term investments')
    derived('workingCapital', ['currentAssets', 'currentLiabilities'], lambda x,y: x-y,
            'Current assets - current liabilities')
    derived('interestCoverage', ['ebit', 'interestExpense'], lambda x,y: x/y,
            'EBIT / reported interest expense', denominator=1)
    derived('cashConversion', ['operatingCashflow', 'netIncome'], lambda x,y: x/y,
            'Operating cash flow / net income', denominator=1)
    for key, raw in [('capex', 'capitalExpenditure'), ('buybacks', 'repurchaseOfCapitalStock'),
                     ('dividendsPaid', 'cashDividendsPaid')]:
        if raw in result:
            row = result[raw]
            valid = row['value'] is not None and row['value'] <= 0
            put(key, -row['value'] if valid else None, row['basis'], row['end'],
                'Negative reported cash outflow displayed as spending',
                'available' if valid else 'invalid', '' if valid else 'Unexpected positive cash-outflow sign')
    if 'freeCashflow' not in result:
        derived('freeCashflow', ['operatingCashflow', 'capex'], lambda x,y: x-y,
                'Operating cash flow - capital expenditure spending')
        derived('fcfMargin', ['freeCashflow', 'revenue'], lambda x,y: x/y,
                'Free cash flow / revenue', denominator=1)

    # ROE / ROA / ROIC use balance dates one year apart ending at the flow date.
    end = day(flow_end)
    closing = balances.get(flow_end, {}).get('values', {})
    prior_dates = sorted((d for d in balances if end and 350 <= (end-day(d)).days <= 380), reverse=True)
    opening = balances[prior_dates[0]]['values'] if prior_dates else {}
    for key, capital in [('returnOnEquity', 'stockholdersEquity'), ('returnOnAssets', 'totalAssets')]:
        income = result.get('netIncome', {})
        start, finish = number(opening.get(capital)), number(closing.get(capital))
        if income.get('end') == flow_end and income.get('value') is not None and start is not None and finish is not None:
            good = start > 0 and finish > 0
            put(key, income['value']/((start+finish)/2) if good else None, basis, flow_end,
                f'Net income / average opening and closing {capital}',
                'available' if good else 'not_meaningful', '' if good else 'Opening or closing capital is non-positive')
    capital_fields = ('stockholdersEquity', 'totalDebt', 'cash')
    operating = result.get('operatingIncome', {})
    pretax, tax = result.get('pretaxIncome', {}), result.get('taxProvision', {})
    if (flow_end and all(number(r.get(k)) is not None for r in (opening, closing) for k in capital_fields)
            and all(r.get('end') == flow_end and r.get('value') is not None for r in (operating, pretax, tax))):
        first = opening['stockholdersEquity'] + opening['totalDebt'] - opening['cash']
        last = closing['stockholdersEquity'] + closing['totalDebt'] - closing['cash']
        effective_tax = tax['value']/pretax['value'] if pretax['value'] > 0 else None
        good = (first > 0 and last > 0 and effective_tax is not None and 0 <= effective_tax <= 1
                and all(r['totalDebt'] >= 0 and r['cash'] >= 0 for r in (opening, closing)))
        put('roic', operating['value']*(1-effective_tax)/((first+last)/2) if good else None,
            basis, flow_end, 'Operating income × (1 - tax provision / pretax income) / average (equity + debt - cash)',
            'available' if good else 'not_meaningful',
            '' if good else 'Non-positive invested capital or tax rate outside 0–100%; no assumed tax rate used')

    # Historical growth always compares two reported full fiscal years.
    ai = annual.get('income', [])
    if len(ai) >= 2 and 350 <= (day(ai[0]['end'])-day(ai[1]['end'])).days <= 380:
        for key, raw in [('revenueGrowthFY', 'revenue'), ('netIncomeGrowthFY', 'netIncome'), ('epsGrowthFY', 'dilutedEPS')]:
            current, previous = (number(r['values'].get(raw)) for r in ai[:2])
            if current is not None and previous is not None:
                good = previous > 0
                put(key, current/previous-1 if good else None, 'FY vs prior FY', ai[0]['end'],
                    f'{raw} / prior fiscal-year {raw} - 1',
                    'available' if good else 'not_meaningful', '' if good else 'Prior year is zero or a loss')
    return result


def collect(ticker, info, provider=None, *, now=None):
    """Called only by the authorized collector, never during a Streamlit rerun."""
    if provider is None:
        import yfinance as yf
        provider = yf.Ticker(ticker)
    stamp = now or datetime.now(timezone.utc).isoformat()
    bundle = {'schema': SCHEMA, 'ticker': ticker, 'currency': info.get('financialCurrency'),
              'fetched_at': stamp, 'source': SOURCE, 'annual': {}, 'quarterly': {}, 'errors': []}
    for period, frequency in [('annual', 'yearly'), ('quarterly', 'quarterly')]:
        for kind, method, fields in [('income', 'get_income_stmt', {k: FLOW_FIELDS[k] for k in INCOME_KEYS}),
                                     ('balance', 'get_balance_sheet', BALANCE_FIELDS),
                                     ('cashflow', 'get_cash_flow', {k: FLOW_FIELDS[k] for k in CASHFLOW_KEYS})]:
            try:
                frame = getattr(provider, method)(pretty=True, freq=frequency)
                bundle[period][kind] = statement_records(frame, fields, today=day(stamp))
            except Exception as exc:
                # Rate limiting must stop the caller's batch, not six more attempts.
                if any(s in str(exc).lower() for s in ('429', 'rate limit', 'too many')):
                    raise
                bundle['errors'].append({'statement': f'{period}.{kind}', 'error': type(exc).__name__})
    bundle['observations'] = observations(bundle)
    return bundle
