"""Preserve dated observations during incomplete provider refreshes."""
from copy import deepcopy
from reviewed_financials import apply_reviewed
from financial_statements import (SCHEMA, number, observations, INCOME_KEYS,
                                  CASHFLOW_KEYS, BALANCE_FIELDS)

COLLECTION_REVISION = 2


def statement_gaps(bundle):
    """Inventory missing raw cells, not a claim every accounting item applies."""
    result = []
    bundle = bundle or {}
    for period in ('annual', 'quarterly'):
        for kind, keys in (('income', INCOME_KEYS), ('balance', tuple(BALANCE_FIELDS)),
                           ('cashflow', CASHFLOW_KEYS)):
            records = bundle.get(period, {}).get(kind, [])
            if not records:
                result.append({'period': period, 'statement': kind, 'end': None,
                               'missing': list(keys)})
            for row in records:
                missing = [key for key in keys if number(row.get('values', {}).get(key)) is None]
                if missing:
                    result.append({'period': period, 'statement': kind,
                                   'end': row['end'], 'missing': missing})
    return result


def preserve_refresh(previous, incoming):
    """Never lose a dated field because an endpoint temporarily omits it.

    A conflicting reported revision is accepted only from an error-free refresh.
    Preserved fields retain their original fetched time. Currency changes are
    rejected instead of silently combining two reporting currencies.
    """
    if not previous:
        merged = apply_reviewed(deepcopy(incoming))
        merged['observations'] = observations(merged)
        return merged
    if (previous.get('schema') != SCHEMA or incoming.get('schema') != SCHEMA
            or previous.get('ticker') != incoming.get('ticker')
            or not incoming.get('currency')
            or previous.get('currency') != incoming.get('currency')):
        raise ValueError('Incompatible financial identity, schema or currency')
    merged = deepcopy(incoming)
    # A Yahoo refresh cannot erase an independently checked filing comparison.
    # Consumers match its exact date/currency/original value, so a subsequently
    # revised provider value is not quarantined by an obsolete comparison.
    if 'sec_reconciliation' not in merged and previous.get('sec_reconciliation'):
        merged['sec_reconciliation'] = deepcopy(previous['sec_reconciliation'])
    partial = bool(incoming.get('errors'))
    retained = []
    for period in ('annual', 'quarterly'):
        merged.setdefault(period, {})
        for kind in ('income', 'balance', 'cashflow'):
            old_rows = {r['end']: r for r in previous.get(period, {}).get(kind, [])}
            new_rows = {r['end']: r for r in incoming.get(period, {}).get(kind, [])}
            records = []
            for end in sorted(old_rows.keys() | new_rows.keys(), reverse=True)[:6]:
                old, new = old_rows.get(end, {}), new_rows.get(end, {})
                row = deepcopy(new or old)
                values, dates, provenance = {}, {}, {}
                for key in old.get('values', {}).keys() | new.get('values', {}).keys():
                    before, after = number(old.get('values', {}).get(key)), number(new.get('values', {}).get(key))
                    keep = before is not None and (after is None or partial)
                    if keep:
                        values[key] = before
                        dates[key] = old.get('field_fetched_at', {}).get(key, previous.get('fetched_at'))
                        if key in old.get('field_provenance', {}):
                            provenance[key] = deepcopy(old['field_provenance'][key])
                            dates[key] = provenance[key].get('fetched_at') or dates[key]
                        if after is None or after != before:
                            retained.append({'period': period, 'statement': kind, 'end': end,
                                             'field': key, 'fetched_at': dates[key]})
                    elif after is not None:
                        values[key] = after
                        dates[key] = new.get('field_fetched_at', {}).get(key, incoming.get('fetched_at'))
                        if key in new.get('field_provenance', {}):
                            provenance[key] = deepcopy(new['field_provenance'][key])
                            dates[key] = provenance[key].get('fetched_at') or dates[key]
                row['values'], row['field_fetched_at'] = values, dates
                # A newly reported Yahoo value replaces both the value and its
                # source. Never leave an old SEC filing attached to that cell.
                row.pop('field_provenance', None)
                if provenance:
                    row['field_provenance'] = provenance
                records.append(row)
            merged[period][kind] = records
    merged['retained_observations'] = retained
    merged = apply_reviewed(merged)
    merged['observations'] = observations(merged)
    return merged
