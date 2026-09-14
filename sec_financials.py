"""Conservative SEC fact recovery for already dated provider statements.

This module performs no network requests. The collector supplies an SEC
submission and Company Facts document, fetched through the bounded SecClient.
Only directly reported, unambiguous facts can fill an existing missing cell.
No annual-to-quarter subtraction, zero filling, currency conversion, share/ADR
conversion, new statement periods, or replacement of conflicting provider values
occurs. An SEC-owned cell may follow a verified later filing for the same context.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re

from financial_statements import SCHEMA, number
from sec_reference import identity

SOURCE = 'SEC EDGAR'
FORMS = {'10-K', '10-K/A', '10-Q', '10-Q/A'}
# Restrict aliases to the same accounting meaning. Debt, cash plus investments,
# EBITDA, EPS, shares and common-only repurchases need additional reconciliation
# and intentionally are not substituted by a superficially similar SEC tag.
FIELDS = {
    'revenue': ('income', ('RevenueFromContractWithCustomerExcludingAssessedTax',
                           'Revenues', 'SalesRevenueNet'), 1),
    'grossProfit': ('income', ('GrossProfit',), 1),
    'operatingIncome': ('income', ('OperatingIncomeLoss',), 1),
    'netIncome': ('income', ('NetIncomeLoss',), 1),
    'taxProvision': ('income', ('IncomeTaxExpenseBenefit',), 1),
    'totalAssets': ('balance', ('Assets',), 1),
    'totalLiabilities': ('balance', ('Liabilities',), 1),
    'stockholdersEquity': ('balance', ('StockholdersEquity',), 1),
    'currentAssets': ('balance', ('AssetsCurrent',), 1),
    'currentLiabilities': ('balance', ('LiabilitiesCurrent',), 1),
    'inventory': ('balance', ('InventoryNet',), 1),
    'operatingCashflow': ('cashflow', ('NetCashProvidedByUsedInOperatingActivities',), 1),
    'capitalExpenditure': ('cashflow', ('PaymentsToAcquirePropertyPlantAndEquipment',), -1),
    'stockBasedCompensation': ('cashflow', ('ShareBasedCompensation',), 1),
    'cashDividendsPaid': ('cashflow', ('PaymentsOfDividends',), -1),
}
PREFERRED_TAGS = ('RedeemableConvertiblePreferredStockCarryingAmount',
                  'RedeemablePreferredStockCarryingAmount',
                  'TemporaryEquityCarryingAmountAttributableToParent')


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _currency(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Z]{3}', value)


def _candidates(payload, cik, currency, as_of):
    if isinstance(cik, bool) or not isinstance(cik, int) or not 0 < cik < 10**10:
        raise ValueError('Invalid SEC CIK')
    if not isinstance(payload, dict) or payload.get('cik') != cik:
        raise ValueError('SEC Company Facts CIK mismatch')
    if not _currency(currency):
        raise ValueError('A reported financial currency is required')
    today = _day(str(as_of or date.today()))
    if today is None:
        raise ValueError('Invalid SEC as-of date')
    gaap = payload.get('facts', {}).get('us-gaap', {})
    if not isinstance(gaap, dict):
        raise ValueError('Invalid SEC US GAAP facts')
    mappings = {**FIELDS, '_preferredEquity': ('balance', PREFERRED_TAGS, 1)}
    for field, (kind, tags, sign) in mappings.items():
        for priority, tag in enumerate(tags):
            concept = gaap.get(tag, {})
            values = concept.get('units', {}).get(currency, []) if isinstance(concept, dict) else []
            if not isinstance(values, list):
                continue
            for fact in values:
                if not isinstance(fact, dict):
                    continue
                value = number(fact.get('val'))
                end, filed = _day(fact.get('end')), _day(fact.get('filed'))
                start = _day(fact.get('start')) if 'start' in fact else None
                accession, form = fact.get('accn'), fact.get('form')
                if (value is None or not end or not filed or end > today or filed > today
                        or filed < end or form not in FORMS or not isinstance(accession, str)
                        or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession)):
                    continue
                if kind == 'balance':
                    if 'start' in fact:
                        continue
                    period = 'instant'
                elif not start:
                    continue
                elif 330 <= (end-start).days <= 380 and form in {'10-K', '10-K/A'}:
                    period = 'annual'
                elif 65 <= (end-start).days <= 115:
                    period = 'quarterly'
                else:
                    # Six/nine-month YTD cash flows never become a quarter.
                    continue
                if sign == -1 and value < 0:
                    # SEC payment tags are nonnegative spending, whereas the
                    # provider's canonical cash-flow fields are negative outflows.
                    continue
                yield {'field': field, 'statement': kind, 'period': period,
                       'value': sign*value, 'currency': currency,
                       'start': str(start) if start else None, 'end': str(end),
                       'filed': str(filed), 'form': form, 'accession': accession,
                       'tag': tag, 'source': SOURCE, '_priority': priority,
                       'url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/'}


def _select(payload, cik, currency, as_of=None):
    grouped = defaultdict(list)
    for record in _candidates(payload, cik, currency, as_of):
        grouped[(record['period'], record['statement'], record['end'], record['field'])].append(record)
    selected, ambiguous = [], []
    for key, records in sorted(grouped.items()):
        filed = max(r['filed'] for r in records)
        latest = [r for r in records if r['filed'] == filed]
        # Even alternative revenue tags cannot select between differing totals,
        # fiscal starts or filings. Identical duplicates alone are harmless.
        contexts = {(r['value'], r['currency'], r['start'], r['accession']) for r in latest}
        if len(contexts) != 1:
            ambiguous.append({'period': key[0], 'statement': key[1], 'end': key[2],
                              'field': key[3], 'filed': filed,
                              'reason': 'Conflicting SEC values, starts or filing accessions'})
            continue
        winner = deepcopy(min(latest, key=lambda r: r['_priority']))
        winner.pop('_priority')
        selected.append(winner)
    return selected, ambiguous


def historical_facts(payload, cik, currency, as_of=None):
    """Return unambiguous direct FY, direct quarter, and instant observations.

    Identity beyond Company Facts CIK is deliberately the merge caller's duty;
    merge_missing additionally checks the SEC submissions ticker association.
    """
    records, _ = _select(payload, cik, currency, as_of)
    return [r for r in records if r['field'] != '_preferredEquity']


def _verified_origin(origin, fact, cik):
    """A source label alone is insufficient authority to revise a reported cell."""
    if not isinstance(origin, dict) or origin.get('source') != SOURCE:
        return False
    accession = origin.get('accession')
    filed = _day(origin.get('filed'))
    if (not filed or not isinstance(accession, str)
            or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession)
            or origin.get('form') not in FORMS
            or origin.get('url') != f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/'
            or origin.get('tag') not in FIELDS[fact['field']][1]
            or any(origin.get(key) != fact.get(key) for key in ('start', 'end', 'currency'))):
        return False
    return filed >= _day(fact['end'])


def _provenance(fact, fetched_at):
    return {**{key: fact[key] for key in ('source', 'tag', 'accession', 'filed',
                                        'start', 'end', 'currency', 'url', 'form')},
            'fetched_at': fetched_at}


def merge_missing(bundle, payload, submission, *, cik, fetched_at=None, as_of=None):
    """Return (copy of bundle, audit), filling only existing dated missing cells.

    Rows retain provider values, and each added cell receives field_provenance.
    The caller must recompute canonical observations after applying this result
    so derived values incorporate their own source and period metadata.
    """
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        raise ValueError('Incompatible financial schema')
    ticker = bundle.get('ticker')
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError('A financial ticker identity is required')
    identity(submission, ticker, cik)
    currency = bundle.get('currency')
    records, ambiguous = _select(payload, cik, currency, as_of)
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    try:
        received = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Invalid SEC received timestamp') from exc
    if received.tzinfo is None:
        raise ValueError('SEC received timestamp must have a timezone')
    indexed = {(r['period'], r['statement'], r['end'], r['field']): r for r in records}
    merged = deepcopy(bundle)
    target_dates = {(period, kind, row.get('end')) for period in ('annual', 'quarterly')
                    for kind in ('income', 'balance', 'cashflow')
                    for row in bundle.get(period, {}).get(kind, [])}
    ambiguous = [item for item in ambiguous if any(
        (period, item['statement'], item['end']) in target_dates
        for period in (('annual', 'quarterly') if item['period']=='instant' else (item['period'],)))]
    report = {'ticker': ticker, 'cik': cik, 'currency': currency, 'filled': [], 'revised': [],
              'conflicts': [], 'rejected_alignment': [], 'ambiguous': ambiguous}
    for period in ('annual', 'quarterly'):
        for kind in ('income', 'balance', 'cashflow'):
            rows = merged.get(period, {}).get(kind, [])
            ends = [row.get('end') for row in rows]
            for row in rows:
                end = row.get('end')
                if not _day(end) or ends.count(end) != 1:
                    continue
                values = row.get('values', {})
                if not isinstance(values, dict):
                    continue
                for field, (mapped_kind, _, _) in FIELDS.items():
                    if mapped_kind != kind:
                        continue
                    fact = indexed.get(('instant' if kind == 'balance' else period, kind, end, field))
                    previous = number(values.get(field))
                    existing_origin = row.get('field_provenance', {}).get(field, {})
                    if not isinstance(existing_origin, dict):
                        existing_origin = {}
                    if not fact:
                        # An existing SEC value cannot remain silently current
                        # when its latest filing now supplies ambiguous facts.
                        uncertain = next((item for item in ambiguous
                            if item['statement'] == kind and item['end'] == end
                            and item['field'] == field
                            and item['period'] == ('instant' if kind == 'balance' else period)), None)
                        if (uncertain and previous is not None and isinstance(existing_origin, dict)
                                and existing_origin.get('source') == SOURCE):
                            report['conflicts'].append({**uncertain, 'period': period,
                                'currency': currency, 'provider_value': previous,
                                'sec_value': None, 'existing_source': SOURCE,
                                'existing_provenance': deepcopy(existing_origin),
                                'requires_review': True, 'ambiguous': True})
                        continue
                    audit = {'period': period, 'statement': kind, 'end': end,
                             'field': field, 'sec_value': fact['value'],
                             'tag': fact['tag'], 'accession': fact['accession'],
                             'filed': fact['filed'], 'start': fact['start'],
                             'currency': currency, 'url': fact['url']}
                    known_starts = {p.get('start') for p in row.get('field_provenance', {}).values()
                                    if isinstance(p, dict) and p.get('start')}
                    if row.get('start'):
                        known_starts.add(row['start'])
                    if kind != 'balance' and known_starts and known_starts != {fact['start']}:
                        report['rejected_alignment'].append({**audit, 'reason': 'Existing period start differs'})
                        if previous is not None and existing_origin.get('source') == SOURCE:
                            report['conflicts'].append({**audit, 'provider_value': previous,
                                'existing_source': SOURCE, 'existing_provenance': deepcopy(existing_origin),
                                'requires_review': True, 'reason': 'Existing SEC period start differs'})
                        continue
                    if previous is not None:
                        if previous != fact['value']:
                            if (existing_origin.get('source') == SOURCE
                                    and _verified_origin(existing_origin, fact, cik)
                                    and fact['filed'] > existing_origin['filed']):
                                values[field] = fact['value']
                                row.setdefault('field_provenance', {})[field] = _provenance(fact, fetched_at)
                                row.setdefault('field_fetched_at', {})[field] = fetched_at
                                report['revised'].append({**audit, 'previous_value': previous,
                                    'previous_provenance': deepcopy(existing_origin)})
                                continue
                            conflict = {**audit, 'provider_value': previous}
                            if existing_origin.get('source') == SOURCE:
                                conflict.update(existing_source=SOURCE,
                                    existing_provenance=deepcopy(existing_origin), requires_review=True)
                            preferred = indexed.get(('instant', 'balance', end, '_preferredEquity'))
                            if (field == 'totalLiabilities' and preferred
                                    and preferred['accession'] == fact['accession']
                                    and preferred['filed'] == fact['filed']
                                    and preferred['value'] > 0
                                    and math.isclose(previous-fact['value'], preferred['value'],
                                                     rel_tol=0, abs_tol=1)):
                                conflict['preferred_equity_reconciliation'] = {
                                    'value': preferred['value'], 'tag': preferred['tag'],
                                    'explanation': 'Provider amount equals SEC liabilities plus separately reported temporary/preferred equity'}
                            report['conflicts'].append(conflict)
                        continue
                    values[field] = fact['value']
                    row.setdefault('field_provenance', {})[field] = _provenance(fact, fetched_at)
                    row.setdefault('field_fetched_at', {})[field] = fetched_at
                    report['filled'].append(audit)
    report['filled_count'] = len(report['filled'])
    report['revised_count'] = len(report['revised'])
    report['conflict_count'] = len(report['conflicts'])
    return merged, report
