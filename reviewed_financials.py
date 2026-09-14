"""Narrow, reviewed historical source corrections; never a general estimator.

This release reviewed the issuer's 2026-03-23 financial release on 2026-09-14.
Its FY2024 balance sheet separates convertible preferred stock from liabilities.
An exact previously observed Yahoo tuple must establish the balance context.
Compatible partial copies at that same instant share its reviewed liability.
No network request occurs while rendering, and a changed tuple is not revised.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite


ISSUER_SOURCE = 'Issuer financial release'
PROVIDER_SOURCE = 'Yahoo Finance financial statements'
AARD_RELEASE_URL = ('https://ir.aardvarktherapeutics.com/news-releases/news-release-details/'
                    'aardvark-therapeutics-reports-fourth-quarter-and-full-year-2025')


@dataclass(frozen=True)
class ReviewedCorrection:
    identifier: str = 'aard-fy2024-liabilities-20260323-v1'
    ticker: str = 'AARD'
    currency: str = 'USD'
    end: str = '2024-12-31'
    total_assets: int = 77_507_000
    stockholders_equity: int = -54_643_000
    provider_liabilities: int = 132_150_000
    issuer_liabilities: int = 5_394_000
    convertible_preferred: int = 126_756_000
    url: str = AARD_RELEASE_URL
    published: str = '2026-03-23'
    reviewed_on: str = '2026-09-14'


AARD_CORRECTION = ReviewedCorrection()


def _same(value, expected):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and value == expected)


def apply_reviewed(bundle):
    """Return a corrected copy only for an exact reviewed provider observation.

    The original bundle remains available to audits. Changed copies discard old
    cached calculations, which must be recomputed through observations().
    Per-cell provenance preserves the original amount, source and retrieval time.
    """
    c = AARD_CORRECTION
    if (not isinstance(bundle, dict) or type(bundle.get('schema')) is not int
            or bundle['schema'] != 1 or bundle.get('ticker') != c.ticker
            or bundle.get('currency') != c.currency
            or bundle.get('source') != PROVIDER_SOURCE):
        return bundle
    matches, anchors = [], []
    context = (('totalAssets', c.total_assets), ('stockholdersEquity', c.stockholders_equity))
    for period in ('annual', 'quarterly'):
        section = bundle.get(period, {})
        records = section.get('balance', []) if isinstance(section, dict) else []
        if not isinstance(records, list):
            continue
        for index, row in enumerate(records):
            if (not isinstance(row, dict) or row.get('end') != c.end
                    or row.get('currency', c.currency) != c.currency):
                continue
            values = row.get('values', {})
            provenance = row.get('field_provenance', {})
            if not isinstance(values, dict) or not isinstance(provenance, dict):
                continue
            origin = provenance.get('totalLiabilities', {})
            if not isinstance(origin, dict):
                continue
            if (origin.get('currency', c.currency) != c.currency
                    or origin.get('end', c.end) != c.end):
                continue
            complete_context = all(_same(values.get(key), expected) for key, expected in context)
            # A persisted correction may anchor a newly received partial copy,
            # but only while its full reviewed balance context still matches.
            previous = origin.get('original_observation', {})
            if (complete_context and _same(values.get('totalLiabilities'), c.issuer_liabilities)
                    and origin.get('source') == ISSUER_SOURCE and origin.get('url') == c.url
                    and origin.get('correction_id') == c.identifier and isinstance(previous, dict)
                    and previous.get('source') == PROVIDER_SOURCE
                    and _same(previous.get('value'), c.provider_liabilities)):
                anchors.append(period)
            if origin.get('source', PROVIDER_SOURCE) != PROVIDER_SOURCE:
                continue
            if (_same(values.get('totalLiabilities'), c.provider_liabilities)
                    and all(values.get(key) is None or _same(values.get(key), expected)
                            for key, expected in context)):
                matches.append((period, index, complete_context))
                if complete_context:
                    anchors.append(period)
    if not matches or not anchors:
        return bundle
    result = deepcopy(bundle)
    result.pop('observations', None)
    for period, index, complete_context in matches:
        row = result[period]['balance'][index]
        original = deepcopy(row.get('field_provenance', {}).get('totalLiabilities', {}))
        original.update(source=PROVIDER_SOURCE, value=c.provider_liabilities,
                        fetched_at=original.get('fetched_at') or
                        row.get('field_fetched_at', {}).get('totalLiabilities', bundle.get('fetched_at')))
        row['values']['totalLiabilities'] = c.issuer_liabilities
        row.setdefault('field_provenance', {})['totalLiabilities'] = {
            'source': ISSUER_SOURCE, 'url': c.url, 'published': c.published,
            'reviewed_on': c.reviewed_on, 'fetched_at': c.reviewed_on,
            'end': c.end, 'currency': c.currency, 'correction_id': c.identifier,
            'original_observation': original,
            'convertible_preferred_stock': c.convertible_preferred,
            'reason': 'The issuer separately reports convertible preferred stock; the provider amount combines it with total liabilities.',
        }
        if not complete_context:
            row['field_provenance']['totalLiabilities']['same_date_balance_context'] = {
                'period': anchors[0], 'end': c.end, 'currency': c.currency,
                'totalAssets': c.total_assets, 'stockholdersEquity': c.stockholders_equity,
                'provider_liabilities': c.provider_liabilities,
            }
        row.setdefault('field_fetched_at', {})['totalLiabilities'] = c.reviewed_on
    return result
