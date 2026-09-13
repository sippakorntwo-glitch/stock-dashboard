"""One definition of company metrics for the UI and whole-universe audits.

Reference bands are illustrative screening guides, not fair-value estimates or
industry norms. ROIC requires a cost-of-capital comparison; no WACC is invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from financial_statements import number, observations, SCHEMA, day
from asset_semantics import kind_for, field_state


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    group: str
    unit: str
    policy: str
    definition: str
    provider: str = ''


def m(key, label, group, unit, policy, definition, provider=''):
    return Metric(key, label, group, unit, policy, definition, provider)


METRICS = (
    m('marketCap', 'Market Capitalization', 'Valuation', 'quote_money', 'context', 'Share price multiplied by shares outstanding. Company size is not an assessment of quality.', 'marketCap'),
    m('enterpriseValue', 'Enterprise Value', 'Valuation', 'quote_money', 'context', 'Provider enterprise value includes market equity and debt-like claims less cash; inspect the provider methodology.', 'enterpriseValue'),
    m('trailingPE', 'Trailing P/E', 'Valuation', 'x', 'pe', 'Price divided by trailing earnings per share. A loss or zero earnings makes P/E not meaningful; a low multiple can reflect risk.', 'trailingPE'),
    m('forwardPE', 'Forward P/E', 'Valuation', 'x', 'pe', 'Price divided by forecast earnings per share. Analyst forecasts can change and are not realized profits.', 'forwardPE'),
    m('priceToBook', 'P/B (Price / Book)', 'Valuation', 'x', 'pb', 'Price divided by book value per share. This is P/B, sometimes written P/BV. Negative book equity makes it not meaningful. Asset-light businesses and banks need different comparisons.', 'priceToBook'),
    m('priceToSales', 'P/S (Price / Sales)', 'Valuation', 'x', 'peers', 'Market equity value relative to trailing sales. Sales alone do not measure profitability.', 'priceToSalesTrailing12Months'),
    m('evRevenue', 'EV / Revenue', 'Valuation', 'x', 'peers', 'Enterprise value relative to revenue. Compare businesses with similar margins, growth and accounting.', 'enterpriseToRevenue'),
    m('evEbitda', 'EV / EBITDA', 'Valuation', 'x', 'peers', 'Enterprise value divided by EBITDA. EBITDA excludes capital expenditure and working-capital needs; it is not free cash flow.', 'enterpriseToEbitda'),
    m('grossMargins', 'Gross Margin', 'Profitability & Returns', '%', 'margin', 'Gross profit divided by revenue. Cost classification and business model materially affect comparisons.', 'grossMargins'),
    m('operatingMargins', 'Operating Margin', 'Profitability & Returns', '%', 'margin', 'Operating income divided by revenue, before financing costs and tax. Prefer same-industry and historical comparisons.', 'operatingMargins'),
    m('profitMargins', 'Net Margin', 'Profitability & Returns', '%', 'margin', 'Net income divided by revenue. One-time items, taxes and financing costs can materially change this ratio.', 'profitMargins'),
    m('returnOnEquity', 'ROE', 'Profitability & Returns', '%', 'roe', 'Net income divided by average shareholders equity when matched statements are available; otherwise provider ROE. Buybacks, high leverage or a small equity base can inflate the result.', 'returnOnEquity'),
    m('returnOnAssets', 'ROA', 'Profitability & Returns', '%', 'roa', 'Net income divided by average assets when matched statements are available; otherwise provider ROA. Compare similar asset intensity.', 'returnOnAssets'),
    m('roic', 'ROIC', 'Profitability & Returns', '%', 'roic', 'After-tax operating income divided by average invested capital. Here invested capital is equity + interest-bearing debt - reported cash and short-term investments. The effective reported tax rate is used only within 0–100%. This approximation can differ from adjusted analyst ROIC. Compare with company WACC; no WACC is assumed.'),
    m('revenueGrowth', 'Revenue Growth (Provider)', 'Growth', '%', 'growth', 'Growth reported by the provider, generally a year-over-year quarterly comparison. Check its fiscal period; it is not automatically annual or forward growth.', 'revenueGrowth'),
    m('earningsGrowth', 'Earnings Growth (Provider)', 'Growth', '%', 'growth', 'Provider-reported earnings growth. Losses, near-zero bases and exceptional items can distort percentage comparisons.', 'earningsGrowth'),
    m('revenueGrowthFY', 'Revenue Growth (FY)', 'Growth', '%', 'growth', 'Most recent full fiscal-year revenue divided by prior full-year revenue minus one. Both observations come from the income statement.'),
    m('netIncomeGrowthFY', 'Net Income Growth (FY)', 'Growth', '%', 'growth', 'Full fiscal-year net income divided by prior fiscal-year net income minus one. A non-positive prior year is shown as not meaningful, not a conventional growth rate.'),
    m('epsGrowthFY', 'Diluted EPS Growth (FY)', 'Growth', '%', 'growth', 'Full fiscal-year diluted EPS divided by prior full-year diluted EPS minus one. A zero or negative base is not rated.'),
    m('revenue', 'Revenue', 'Income Statement', 'money', 'context', 'Reported sales over the stated accounting period. Revenue is not cash collected and size alone is not a quality signal.', 'totalRevenue'),
    m('grossProfit', 'Gross Profit', 'Income Statement', 'money', 'profit', 'Revenue less reported cost of revenue. Taken from an income statement; no unknown expense is assumed to be zero.'),
    m('operatingIncome', 'Operating Income', 'Income Statement', 'money', 'profit', 'Profit from operations before financing and tax. Kept separate from EBIT because non-operating items can create differences.'),
    m('ebit', 'EBIT', 'Income Statement', 'money', 'profit', 'Reported earnings before interest and tax. It is not substituted with EBITDA or an estimated profit-margin calculation.'),
    m('ebitda', 'EBITDA', 'Income Statement', 'money', 'profit', 'Earnings before interest, taxes, depreciation and amortization. Positive EBITDA does not guarantee positive cash generation.', 'ebitda'),
    m('netIncome', 'Net Income', 'Income Statement', 'money', 'profit', 'Net earnings after expenses and taxes for the stated period. When only the profile is available the source is net income attributable to common shareholders.', 'netIncomeToCommon'),
    m('dilutedEPS', 'Diluted EPS', 'Income Statement', 'per_share', 'profit', 'Income per diluted weighted-average share. Annual EPS is reported directly; quarterly EPS values are not added to create an annual figure.', 'trailingEps'),
    m('debtToEquity', 'D/E (Debt / Equity)', 'Financial Strength', 'x', 'debt', 'Interest-bearing total debt divided by shareholders equity, displayed in times. Yahoo profile debtToEquity is a percentage and is divided by 100. This differs from total liabilities/equity. Non-positive equity makes the ratio not meaningful.', 'debtToEquity'),
    m('liabilitiesToEquity', 'Total Liabilities / Equity', 'Financial Strength', 'x', 'peers', 'All reported liabilities divided by shareholders equity. Includes obligations beyond interest-bearing debt; do not confuse it with the D/E row.'),
    m('currentRatio', 'Current Ratio', 'Financial Strength', 'x', 'current', 'Current assets divided by current liabilities. Less than 1 can indicate liquidity pressure; high values are not automatically efficient. The rule is unsuitable for banks.', 'currentRatio'),
    m('quickRatio', 'Quick Ratio', 'Financial Strength', 'x', 'quick', 'Here (cash, equivalents, short-term investments + receivables) / current liabilities. A provider fallback may use a different quick-asset definition; inspect its source.', 'quickRatio'),
    m('cashRatio', 'Cash Ratio', 'Financial Strength', 'x', 'peers', 'Cash, equivalents and short-term investments divided by current liabilities. An intentionally narrower liquidity view than current ratio.'),
    m('interestCoverage', 'Interest Coverage', 'Financial Strength', 'x', 'interest', 'EBIT divided by reported interest expense for the same accounting period. Zero interest expense has no finite coverage multiple; it is not a data failure or an infinite score.'),
    m('totalAssets', 'Total Assets', 'Balance Sheet', 'money', 'context', 'Resources recognized on the balance sheet at the displayed date, not assets under management of an ETF.'),
    m('totalLiabilities', 'Total Liabilities', 'Balance Sheet', 'money', 'context', 'Recognized obligations at the balance-sheet date. Includes operating and financing liabilities.'),
    m('stockholdersEquity', 'Shareholders Equity', 'Balance Sheet', 'money', 'equity', 'Reported equity attributable to shareholders. Negative equity needs investigation and makes ordinary ROE, P/B and D/E comparisons unreliable.'),
    m('cash', 'Cash & Short-Term Investments', 'Balance Sheet', 'money', 'context', 'Reported cash, cash equivalents and short-term investments. Not operating cash flow and not necessarily all excess cash.', 'totalCash'),
    m('totalDebt', 'Total Debt', 'Balance Sheet', 'money', 'context', 'Provider interest-bearing debt at the balance-sheet date. Accounting for leases may differ between data providers.', 'totalDebt'),
    m('netDebt', 'Net Debt', 'Balance Sheet', 'money', 'net_debt', 'Total debt minus reported cash and short-term investments at the same balance-sheet date. A negative value indicates net cash.'),
    m('currentAssets', 'Current Assets', 'Balance Sheet', 'money', 'context', 'Assets expected to be realized or consumed within the operating cycle or a year.'),
    m('currentLiabilities', 'Current Liabilities', 'Balance Sheet', 'money', 'context', 'Obligations expected to settle within the operating cycle or a year.'),
    m('workingCapital', 'Working Capital', 'Balance Sheet', 'money', 'working', 'Current assets minus current liabilities at the same date. Some retail and subscription businesses sustainably operate with negative working capital.'),
    m('operatingCashflow', 'Operating Cash Flow', 'Cash Flow', 'money', 'cashflow', 'Cash generated or consumed by operations during the stated period. Inspect working-capital changes and recurring versus temporary effects.', 'operatingCashflow'),
    m('capex', 'Capital Expenditure', 'Cash Flow', 'money', 'context', 'Cash spent on capital assets, displayed as positive spending. A missing source cash outflow is not treated as zero.'),
    m('freeCashflow', 'Free Cash Flow', 'Cash Flow', 'money', 'cashflow', 'Reported free cash flow, or operating cash flow minus capital expenditure when both inputs share the accounting period. This is not automatically cash distributable to shareholders.', 'freeCashflow'),
    m('fcfMargin', 'Free Cash Flow Margin', 'Cash Flow', '%', 'margin', 'Free cash flow divided by revenue for the same fiscal period. Capital intensity affects the appropriate level.'),
    m('cashConversion', 'Cash Conversion (OCF / Net Income)', 'Cash Flow', 'x', 'conversion', 'Operating cash flow divided by positive net income over the same period. Sustained values below 1 merit investigation; working-capital timing can create temporary variation.'),
    m('stockBasedCompensation', 'Stock-Based Compensation', 'Cash Flow', 'money', 'context', 'Non-cash employee compensation reported in the cash flow statement. Cash-flow add-backs do not eliminate shareholder dilution.'),
    m('dividendYield', 'Dividend Yield (Trailing)', 'Shareholder Returns', '%', 'yield', 'Provider trailing annual dividend yield, displayed as a percentage. It is not forward yield or total return and future payments are not guaranteed.', 'trailingAnnualDividendYield'),
    m('payoutRatio', 'Dividend Payout Ratio', 'Shareholder Returns', '%', 'payout', 'Provider dividends relative to earnings. A ratio above 100% can be unsustainable; it is not meaningful with non-positive earnings. REITs need FFO/AFFO-based analysis.', 'payoutRatio'),
    m('dividendsPaid', 'Cash Dividends Paid', 'Shareholder Returns', 'money', 'context', 'Cash dividends paid during the stated accounting period, displayed as positive spending. This differs from per-share ex-dividend-date history.'),
    m('buybacks', 'Share Repurchases', 'Shareholder Returns', 'money', 'context', 'Gross cash spent on share repurchases. This is not net buyback yield: new issuance and stock compensation can offset repurchases.'),
    m('targetMeanPrice', 'Analyst Target Price', 'Analyst Expectations', 'quote_per_share', 'context', 'Mean analyst price target reported by the provider. The contributing forecasts can have different dates; it is not a guaranteed future price.', 'targetMeanPrice'),
    m('analystCount', 'Analyst Opinions', 'Analyst Expectations', 'count', 'context', 'Number of analyst opinions included in the provider consensus. More opinions do not guarantee accuracy.', 'numberOfAnalystOpinions'),
    m('forwardEps', 'Forward EPS', 'Analyst Expectations', 'per_share', 'context', 'Provider forecast earnings per share. This is an estimate, distinct from the reported fiscal-year diluted EPS above.', 'forwardEps'),
)
BY_KEY = {metric.key: metric for metric in METRICS}
GROUPS = tuple(dict.fromkeys(metric.group for metric in METRICS))
AUDIT_PROVIDER_FIELDS = tuple(dict.fromkeys(metric.provider for metric in METRICS if metric.provider))
SPECIALIZED = frozenset(('returnOnEquity', 'returnOnAssets', 'grossMargins', 'operatingMargins', 'profitMargins',
                        'debtToEquity', 'liabilitiesToEquity', 'currentRatio', 'quickRatio', 'cashRatio',
                        'interestCoverage', 'roic', 'evEbitda', 'evRevenue', 'fcfMargin', 'cashConversion'))
NONNEGATIVE = frozenset(('revenue', 'totalAssets', 'totalLiabilities', 'cash', 'totalDebt',
                        'currentAssets', 'currentLiabilities', 'capex', 'buybacks', 'dividendsPaid'))
REFERENCE_URLS = (
    ('SEC: Reading financial statements', 'https://www.sec.gov/investor/pubs/begfinstmtguide.htm'),
    ('NYU Stern: Return on capital', 'https://pages.stern.nyu.edu/~adamodar/'),
)


def specialized_company(info):
    sector = str(info.get('sector') or '').casefold()
    industry = str(info.get('industry') or '').casefold()
    return sector in ('financial services', 'financial') or any(s in industry for s in ('banks', 'insurance', 'credit services', 'reit'))


def evaluate(metric, value, info):
    """Return a reference, an assessment and an explanation, never a buy signal."""
    if specialized_company(info) and (metric.key in SPECIALIZED or metric.policy == 'payout'):
        return ('Industry-specific analysis', 'Specialized comparison',
                'Generic operating-company bands are not applied to banks, insurers, credit businesses or REITs; use sector-specific capital and cash-flow measures.')
    p = metric.policy
    if p == 'pe':
        band = 'Illustrative: 0–25× / 25–40× / >40×'
        assessment = 'Lower multiple' if value <= 25 else 'Elevated multiple' if value <= 40 else 'High multiple'
        return band, assessment, 'Compare peers, growth and earnings quality; this band does not establish fair value.'
    if p == 'pb':
        return 'Illustrative: <1× / 1–3× / >3×', ('Below book' if value < 1 else '1–3× book' if value <= 3 else 'Premium to book'), 'A low P/B can reflect weak asset quality; high P/B is common in asset-light businesses.'
    if p == 'roe':
        return 'Illustrative: <8% / 8–15% / >15%', ('Loss-making' if value < 0 else 'Low return' if value < .08 else 'Moderate return' if value <= .15 else 'High return; inspect equity base'), 'Review leverage and buybacks. A very small equity base can inflate ROE.'
    if p == 'roa':
        return 'Illustrative: <2% / 2–5% / >5%', ('Loss-making' if value < 0 else 'Low return' if value < .02 else 'Moderate return' if value <= .05 else 'Higher return'), 'These are example bands, not norms for every industry; asset intensity matters.'
    if p == 'roic':
        return 'Above company WACC; WACC not supplied', ('Negative operating return' if value < 0 else 'WACC comparison needed'), 'A positive ROIC alone does not establish value creation. Compare with a defensible company-specific cost of capital.'
    if p == 'debt':
        return 'Illustrative: <0.5× / 0.5–1.5× / >1.5×', ('Lower leverage' if value < .5 else 'Moderate leverage' if value <= 1.5 else 'Higher leverage'), 'Debt maturity, interest coverage and cash-flow stability matter as much as the ratio.'
    if p == 'current':
        return 'Illustrative: <1× / 1–2× / >2×', ('Liquidity review' if value < 1 else 'Positive coverage' if value <= 2 else 'High current assets'), 'Inspect the quality and turnover of assets; a high value is not automatically more efficient.'
    if p == 'quick':
        return 'Illustrative: at least 1×', ('Below reference' if value < 1 else 'At or above reference'), 'Compare near-term obligations with realizable quick assets and sector working-capital patterns.'
    if p == 'interest':
        return 'Illustrative: <1× / 1–3× / >3×', ('EBIT below interest' if value < 1 else 'Thin coverage' if value <= 3 else 'Higher coverage'), 'Check debt repricing, maturities and recurring operating income; no guarantee of solvency.'
    if p == 'conversion':
        return 'Illustrative: at least 1× over time', ('Below net income' if value < 1 else 'At or above net income'), 'One period can be distorted by working capital. Compare several years and review non-cash compensation.'
    if p == 'payout':
        return 'Illustrative: 0–60% / 60–100% / >100%', ('More earnings retained' if value <= .6 else 'High payout' if value <= 1 else 'Above reported earnings'), 'Review cash coverage, debt and the dividend policy. A zero payout can be a deliberate reinvestment choice.'
    if p == 'growth':
        return 'Positive growth; compare prior periods and peers', ('Contracting' if value < 0 else 'Flat' if value == 0 else 'Growing'), 'Check base effects, acquisitions, currency effects and whether the accounting periods are comparable.'
    if p in ('margin', 'profit', 'cashflow'):
        return 'Positive and sustainable; compare history and peers', ('Negative' if value < 0 else 'Break-even' if value == 0 else 'Positive'), 'The sign alone is not a company-quality verdict; inspect recurring performance, scale and business model.'
    if p == 'equity':
        return 'Positive equity; inspect capital structure', ('Negative equity' if value < 0 else 'Zero equity' if value == 0 else 'Positive equity'), 'Negative equity needs investigation; ordinary equity-denominator ratios are not meaningfully comparable.'
    if p == 'net_debt':
        return 'Compare with recurring cash generation', ('Net cash' if value < 0 else 'No net debt' if value == 0 else 'Net debt'), 'Net cash does not remove operating risk; restricted cash and debt maturities require separate review.'
    if p == 'working':
        return 'Business-model-specific', ('Negative working capital' if value < 0 else 'Non-negative working capital'), 'Evaluate the operating cycle and liquidity; negative working capital can be normal for some businesses.'
    if p == 'yield':
        return 'Sustainable payouts; no universal target', 'Income context', 'A high yield can reflect a falling price or a distribution at risk; it is not a higher total-return forecast.'
    return ('Same-industry and historical comparison', 'Context only', 'No universal good/bad threshold applies to this amount or multiple.')


def metric_observations(ticker, info, bundle=None, *, is_etf=False):
    """Normalize source values once for both display and semantic audits."""
    info = info or {}
    derived = observations(bundle) if bundle else {}
    fund = kind_for(ticker, info, is_etf) != 'company'
    result = {}
    for metric in METRICS:
        item = dict(derived.get(metric.key, {}))
        # The statement collection must identify the requested symbol and currency.
        if bundle and (bundle.get('ticker') != ticker or not bundle.get('currency')):
            item = {}
        if not item and metric.provider:
            value = number(info.get(metric.provider))
            state = field_state(ticker, info, metric.provider, is_etf=is_etf)
            if metric.key == 'debtToEquity' and value is not None:
                value /= 100.0
            item = {'value': value, 'state': state, 'source': 'Yahoo Finance profile',
                    'basis': 'Provider period', 'end': None,
                    'currency': info.get('currency') if metric.unit in ('quote_money','quote_per_share') else info.get('financialCurrency'),
                    'formula': 'Provider debtToEquity percentage / 100' if metric.key == 'debtToEquity' else None}
        if not item:
            item = {'value': None, 'state': 'missing_inputs' if metric.key in ('roic', 'interestCoverage', 'cashConversion', 'fcfMargin') and bundle else 'not_reported' if bundle else 'pending',
                    'basis': 'Not reported', 'end': None, 'currency': info.get('financialCurrency'), 'source': 'Financial statements', 'formula': None}
        if fund:
            item.update(value=None, state='not_applicable', reason='Corporate financial statements do not apply to this ETF / ETP.')
        value = item.get('value')
        if value is not None and metric.key in NONNEGATIVE and value < 0:
            item.update(value=None, state='invalid', reason='Unexpected negative source amount')
        if metric.key in ('trailingPE', 'forwardPE', 'priceToBook', 'evEbitda') and value is not None and value <= 0:
            item.update(value=None, state='not_meaningful', reason='Non-positive valuation denominator or multiple')
        equity = derived.get('stockholdersEquity', {}).get('value')
        book_value = number(info.get('bookValue'))
        if metric.key in ('debtToEquity', 'priceToBook', 'returnOnEquity', 'liabilitiesToEquity') and ((equity is not None and equity <= 0) or (book_value is not None and book_value <= 0)):
            item.update(value=None, state='not_meaningful', reason='Reported equity or book value is non-positive')
        if metric.key == 'payoutRatio':
            eps = number(info.get('trailingEps'))
            if value is not None and (value < 0 or (eps is not None and eps <= 0)):
                item.update(value=None, state='not_meaningful', reason='Non-positive earnings or negative payout ratio')
        result[metric.key] = item
    return result


def format_value(metric, item, info):
    state, value = item['state'], item.get('value')
    if state != 'available' or value is None:
        return {'not_applicable': 'N/A — Not applicable', 'not_meaningful': 'N/M — Not meaningful',
                'pending': 'Awaiting statements', 'missing_inputs': 'Insufficient inputs',
                'invalid': 'Invalid source value', 'not_reported': 'Not reported'}.get(state, 'Not reported')
    if metric.unit == '%':
        return f'{value*100:,.2f}%'
    if metric.unit == 'x':
        return f'{value:,.2f}×'
    if metric.unit == 'count':
        return f'{value:,.0f}'
    currency = item.get('currency') or (info.get('currency') if metric.unit in ('quote_money','quote_per_share') else info.get('financialCurrency')) or 'Currency not reported'
    if metric.unit in ('per_share','quote_per_share'):
        return f'{value:,.2f} {currency}/share'
    for scale, label in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M')):
        if abs(value) >= scale:
            return f'{value/scale:,.2f}{label} {currency}'
    return f'{value:,.2f} {currency}'


def build_rows(ticker, info, bundle=None, *, is_etf=False):
    values = metric_observations(ticker, info, bundle, is_etf=is_etf)
    rows = []
    for metric in METRICS:
        item = values[metric.key]
        value = item.get('value')
        if item['state'] == 'available' and value is not None:
            benchmark, assessment, meaning = evaluate(metric, value, info)
        else:
            benchmark = 'Assessment requires applicable, valid inputs'
            assessment = {'pending': 'Awaiting data', 'not_applicable': 'Not applicable',
                          'not_meaningful': 'Not meaningful', 'invalid': 'Needs source review',
                          'missing_inputs': 'Insufficient inputs'}.get(item['state'], 'Not reported')
            meaning = item.get('reason') or 'A missing observation is not zero and is not a weak-company score.'
        period = item.get('basis') or 'Provider period'
        if item.get('end'):
            period += ' · ' + item['end']
        tooltip = metric.definition
        if item.get('formula'):
            tooltip += '\nCalculation: ' + item['formula']
        tooltip += '\nSource: ' + item['source'] + '\nPeriod: ' + period
        if value is not None:
            tooltip += f'\nUnrounded value: {value:.12g}' + (' (fraction before × 100)' if metric.unit == '%' else '')
        rows.append({'Group': metric.group, 'Metric': metric.label, 'Current Value': format_value(metric, item, info),
                     'Reference / Benchmark': benchmark, 'Assessment': assessment,
                     'Interpretation': meaning, 'Period': period, '_key': metric.key,
                     '_state': item['state'], '_value': value, '_help': tooltip})
    return rows


def audit_profile(ticker, info, bundle=None, *, is_etf=False):
    values = metric_observations(ticker, info, bundle, is_etf=is_etf)
    return {key: item['state'] for key, item in values.items()}
