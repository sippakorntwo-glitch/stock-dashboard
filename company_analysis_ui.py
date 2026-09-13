"""English company research tables with metric-only, keyboard-accessible help."""
from __future__ import annotations

from collections import Counter
from html import escape
import json
import pandas as pd
import streamlit as st
from company_metrics import METRICS, BY_KEY, GROUPS, REFERENCE_URLS, build_rows, format_value
from financial_statements import INCOME_KEYS, CASHFLOW_KEYS, BALANCE_FIELDS, number, day

COLORS = {'Positive': 'good', 'Growing': 'good', 'Positive equity': 'good',
          'Positive coverage': 'good', 'At or above reference': 'good',
          'Negative': 'bad', 'Negative equity': 'bad', 'Loss-making': 'bad',
          'EBIT below interest': 'bad', 'Above reported earnings': 'bad',
          'Liquidity review': 'watch', 'Higher leverage': 'watch',
          'Thin coverage': 'watch', 'High multiple': 'watch', 'Contracting': 'watch'}
CSS = '''<style>
.company-analysis{border:1px solid #2c415b;border-radius:12px;margin:12px 0 22px;overflow:hidden;background:rgba(15,28,46,.4)}
.company-analysis h4{margin:0;padding:13px 16px;background:linear-gradient(110deg,#17354e,#18263c);font:600 17px sans-serif;color:#dceef8}
.company-table-scroll{overflow:auto;max-height:650px}.company-table{border-collapse:collapse;width:100%;font:13px/1.5 sans-serif;color:#dfebf6}
.company-table td,.company-table th{text-align:left;vertical-align:top;padding:11px 14px;border-bottom:1px solid #25374e}
.company-table thead th{position:sticky;top:0;background:#14273c;color:#a8bfd4;font-weight:500;z-index:1}
.company-table tbody th{min-width:165px;font-weight:600}
.company-table td:first-child{min-width:165px;font-weight:600}.company-table td:nth-child(2){min-width:125px;font-variant-numeric:tabular-nums}
.company-table td:nth-child(3){min-width:210px}.company-table td:nth-child(5){min-width:260px}.company-table td:nth-child(6){min-width:150px;color:#b2c4d5}
.company-table abbr{border:0;text-decoration:none;cursor:help}.company-table abbr:focus{outline:2px solid #58cdb7;outline-offset:4px}.company-table small{color:#68c9cf}
.company-rating{display:inline-block;padding:3px 7px;border-radius:5px;background:#263b53;color:#d3dfed;white-space:normal;min-width:95px}
.company-rating.good{background:#123e37;color:#81e2bf}.company-rating.bad{background:#492c3b;color:#ffb6c5}.company-rating.watch{background:#473d26;color:#f5d68c}
.company-glossary{padding:10px 16px;font:13px/1.6 sans-serif;color:#bacde0}.company-glossary summary{cursor:pointer}.company-glossary dt{font-weight:600;margin-top:10px}.company-glossary dd{margin:3px 0 10px;white-space:pre-line}
</style>'''


def analysis_html(rows, ticker, *, group=None):
    groups = [group] if group else GROUPS
    html = [CSS]
    for name in groups:
        selected = [r for r in rows if r['Group'] == name]
        if not selected:
            continue
        header = ''.join(f'<th scope="col">{escape(c)}</th>' for c in ('Metric', 'Current Value', 'Reference / Benchmark', 'Assessment', 'Interpretation', 'Period'))
        body, glossary = [], []
        for row in selected:
            label, tip = escape(row['Metric']), escape(row['_help'], quote=True)
            cells = f'<th scope="row"><abbr tabindex="0" title="{tip}" aria-label="{escape(row["Metric"]+": "+row["_help"],quote=True)}">{label} <small>ⓘ</small></abbr></th>'
            cells += '<td>'+escape(row['Current Value'])+'</td><td>'+escape(row['Reference / Benchmark'])+'</td>'
            css = COLORS.get(row['Assessment'], '')
            cells += f'<td><span class="company-rating {css}">{escape(row["Assessment"])}</span></td>'
            cells += '<td>'+escape(row['Interpretation'])+'</td><td>'+escape(row['Period'])+'</td>'
            body.append(f'<tr data-metric="{escape(row["_key"],quote=True)}" data-state="{escape(row["_state"],quote=True)}">{cells}</tr>')
            glossary.append(f'<dt>{label}</dt><dd>{escape(row["_help"])}</dd>')
        html.append(f'<section class="company-analysis" data-ticker="{escape(ticker,quote=True)}" data-group="{escape(name,quote=True)}"><h4>{escape(name)}</h4>'
                    f'<div class="company-table-scroll"><table class="company-table"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                    '<details class="company-glossary"><summary>Metric definitions — keyboard & mobile</summary><dl>'+''.join(glossary)+'</dl></details></section>')
    return ''.join(html)


def statement_table(bundle, kind):
    keys = INCOME_KEYS if kind == 'income' else CASHFLOW_KEYS if kind == 'cashflow' else tuple(BALANCE_FIELDS)
    aliases = {'capitalExpenditure': 'capex', 'repurchaseOfCapitalStock': 'buybacks', 'cashDividendsPaid': 'dividendsPaid'}
    records = bundle.get('annual', {}).get(kind, [])[:4]
    rows = []
    for raw in keys:
        key = aliases.get(raw, raw)
        metric = BY_KEY.get(key)
        if not metric:
            continue
        row = {'Metric': metric.label, '_help': metric.definition}
        for period in records:
            value = number(period['values'].get(raw))
            if raw in aliases and value is not None:
                value = -value if value <= 0 else None
            row[period['end']] = format_value(metric, {'state': 'available' if value is not None else 'not_reported',
                'value': value, 'currency': bundle.get('currency')}, {'financialCurrency': bundle.get('currency')})
        rows.append(row)
    return rows


def history_html(rows, title):
    if not rows:
        return ''
    cols = [c for c in rows[0] if not c.startswith('_')]
    heads = ''.join('<th>'+escape(col)+'</th>' for col in cols)
    body = []
    for row in rows:
        first = '<th scope="row"><abbr tabindex="0" title="'+escape(row['_help'],quote=True)+'">'+escape(row['Metric'])+' <small>ⓘ</small></abbr></th>'
        body.append('<tr>'+first+''.join('<td>'+escape(str(row[c]))+'</td>' for c in cols[1:])+'</tr>')
    return CSS+'<section class="company-analysis"><h4>'+escape(title)+'</h4><div class="company-table-scroll"><table class="company-table"><thead><tr>'+heads+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>'


def render_company_research(ticker, info, bundle=None):
    st.subheader('Company Financial Analysis', anchor='company-financial-analysis')
    st.caption('Illustrative reference bands support comparison. They are not industry averages, fair values or buy/sell signals. Amounts, percentages and multiples use explicit units; fiscal-year data and TTM data keep separate period labels.')
    profile = ' · '.join(str(info.get(k)) for k in ('sector', 'industry', 'country') if info.get(k))
    if profile:
        st.write(profile)
    st.caption('Profile fetched: '+str(info.get('_Fetched_At_UTC') or 'Not reported')+' · Financial statements fetched: '+str((bundle or {}).get('fetched_at') or 'Not yet collected'))
    if bundle and bundle.get('errors'):
        st.caption('Some statement requests were incomplete. Available figures retain their period; missing inputs are not estimated.')
    rows = build_rows(ticker, info, bundle)
    # One stable element holds all grouped sections; switching symbols replaces it.
    with st.container(key='company_financial_analysis'):
        st.html(analysis_html(rows, ticker))
    export = [{k:v for k,v in row.items() if not k.startswith('_')} | {'Definition & Calculation':row['_help'], 'Availability':row['_state']} for row in rows]
    st.download_button('Download company analysis', pd.DataFrame(export).to_csv(index=False).encode('utf-8-sig'),
                       f'{ticker}_company_analysis.csv', 'text/csv', key=f'company_export_{ticker}', on_click='ignore')
    if bundle and any(bundle.get('annual', {}).values()):
        with st.expander('Financial Statements — up to 4 fiscal years', expanded=True):
            st.caption('Annual statement dates below are fiscal year ends. Values are reported observations; they are not market-price returns.')
            for kind, title in [('income', 'Income Statement'), ('balance', 'Balance Sheet'), ('cashflow', 'Cash Flow Statement')]:
                if bundle.get('annual', {}).get(kind):
                    st.html(history_html(statement_table(bundle, kind), title))
                else:
                    st.caption(title+': not reported')
    with st.expander('How to interpret these comparisons'):
        st.write('No single ratio establishes company quality. Compare the same industry, the company’s history, accounting policies, debt maturities and recurring cash generation. Banks, insurers and REITs require specialized capital and cash-flow measures.')
        st.write('N/A means not applicable; N/M means the ratio cannot be meaningfully interpreted. Not reported and insufficient inputs are missing observations, not zeros or negative investment ratings. Fiscal statements update when the company reports, not every price tick.')
        for label, url in REFERENCE_URLS:
            st.link_button(label, url)
