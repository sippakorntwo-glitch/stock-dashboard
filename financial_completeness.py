"""Preserve dated observations during incomplete provider refreshes."""
from copy import deepcopy
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
        return deepcopy(incoming)
    if (previous.get('schema') != SCHEMA or incoming.get('schema') != SCHEMA
            or previous.get('ticker') != incoming.get('ticker')
            or not incoming.get('currency')
            or previous.get('currency') != incoming.get('currency')):
        raise ValueError('Incompatible financial identity, schema or currency')
    merged = deepcopy(incoming)
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
                values, dates = {}, {}
                for key in old.get('values', {}).keys() | new.get('values', {}).keys():
                    before, after = number(old.get('values', {}).get(key)), number(new.get('values', {}).get(key))
                    keep = before is not None and (after is None or partial)
                    if keep:
                        values[key] = before
                        dates[key] = old.get('field_fetched_at', {}).get(key, previous.get('fetched_at'))
                        if after is None or after != before:
                            retained.append({'period': period, 'statement': kind, 'end': end,
                                             'field': key, 'fetched_at': dates[key]})
                    elif after is not None:
                        values[key] = after
                        dates[key] = new.get('field_fetched_at', {}).get(key, incoming.get('fetched_at'))
                row['values'], row['field_fetched_at'] = values, dates
                records.append(row)
            merged[period][kind] = records
    merged['retained_observations'] = retained
    merged['observations'] = observations(merged)
    return merged
