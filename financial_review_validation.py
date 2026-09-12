"""Independent audit of displayed-value arithmetic, not a second provider.

This deliberately does not call the production financial-ratio functions. It
checks reproducibility and formatting inputs; it cannot certify issuer reports.
"""
from __future__ import annotations
import math


def expected_value(row):
    x=row['inputs'];key=row['key'];formula=row['formula']
    if set(x)=={'numerator','denominator'}:
        if x['denominator']<=0:raise ValueError('Invalid ratio denominator')
        return x['numerator']/x['denominator']*(100 if row['unit']=='%' else 1)
    if set(x)=={'current','prior'}:
        if x['prior']<=0:raise ValueError('Invalid growth base')
        return (x['current']/x['prior']-1)*100
    if key=='gross_profit' and set(x)=={'revenue','cost_of_revenue'}:return x['revenue']-x['cost_of_revenue']
    if key=='ebit' and set(x)=={'pretax_income','interest_expense'}:return x['pretax_income']+x['interest_expense']
    if key=='ebitda' and set(x)=={'ebit','da'}:return x['ebit']+x['da']
    if key=='fcf' and set(x)=={'ocf','capex'}:return x['ocf']-x['capex']
    if key=='debt' and set(x)=={'debt_current','debt_long','debt_short'}:return sum(x.values())
    if key=='net_debt' and set(x)=={'debt','cash'}:return x['debt']-x['cash']
    if key=='working_capital' and set(x)=={'assets','liabilities'}:return x['assets']-x['liabilities']
    if key=='nopat' and set(x)=={'operating_income','tax_rate'}:return x['operating_income']*(1-x['tax_rate'])
    if len(x)==1:
        value=next(iter(x.values()))
        if formula.startswith('Provider '):
            if key=='de':return value/100
            return value*100 if row['unit']=='%' else value
        return value
    raise ValueError('Unrecognized arithmetic provenance')


def validate_review(review):
    errors=[];checked=0
    for row in review['rows']:
        if row['status']!='available':
            if row['value'] is not None:errors.append({'metric':row['key'],'error':'Unavailable value was numeric'})
            continue
        try:
            expected=expected_value(row);actual=row['value'];checked+=1
            if actual is None or not math.isfinite(actual) or not math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-7):
                errors.append({'metric':row['key'],'error':'Arithmetic mismatch','actual':actual,'expected':expected})
        except (ValueError,ZeroDivisionError,TypeError,KeyError) as exc:
            errors.append({'metric':row['key'],'error':str(exc)})
    return {'checked_values':checked,'errors':errors}
