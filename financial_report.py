"""Bounded public financial audit summaries; full evidence stays in run artifacts.

The public report drives the scheduled queue guards, so control values and audit
totals must remain exact. Only diagnostic samples are reduced. In particular, a
sample's completeness must never replace the whole-catalog ``data_complete``.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path


# Leave room for verification_report's recorded_at/run_id/source_sha envelope.
# Its independent 300,000-byte safety limit applies unchanged to every caller.
MAX_PUBLIC_BYTES = 280_000
SAMPLE_ITEMS = 50
LIST_SAMPLE_BYTES = 10_000
EXAMPLE_SAMPLE_BYTES = 50_000


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2,
                      default=str).encode('utf-8')


def _sample(items, *, limit, budget):
    """Keep a prefix of whole entries, never truncate a value or source label."""
    result = []
    for item in items[:limit]:
        candidate = [*result, item]
        if len(_encoded(candidate)) > budget:
            break
        result.append(deepcopy(item))
    return result, {'total': len(items), 'included': len(result),
                    'omitted': len(items) - len(result), 'selection': 'prefix'}


def _lists_summary(section, *, limit):
    result = {}
    for key, value in section.items():
        if isinstance(value, list):
            result[key], result[key + '_summary'] = _sample(
                value, limit=limit, budget=LIST_SAMPLE_BYTES)
        else:
            result[key] = deepcopy(value)
    return result


def _example_summary(examples, *, limit):
    # Source identities, metric states/reasons, values and periods remain intact.
    # Repeating the input cells for every derived ratio caused the size failure.
    # Nested evidence is explicitly counted here and retained in the full JSON.
    projected = {}
    states = Counter()
    evidence = Counter()
    total_metrics = 0
    for ticker, metrics in examples.items():
        compact = {}
        for key, observation in metrics.items():
            total_metrics += 1
            states[observation.get('state', 'unknown')] += 1
            evidence['provenance_records'] += len(observation.get('provenance', []))
            disagreements = len(observation.get('source_disagreements', []))
            evidence['source_disagreement_records'] += disagreements
            evidence['metrics_with_source_disagreements'] += bool(disagreements)
            value = {field: deepcopy(item) for field, item in observation.items()
                     if not isinstance(item, (list, dict)) or field == 'period_ends'}
            omitted = {field: len(item) for field, item in observation.items()
                       if isinstance(item, (list, dict)) and field != 'period_ends'}
            if omitted:
                value['details_omitted'] = omitted
            compact[key] = value
        if len(projected) < limit:
            candidate = {**projected, ticker: compact}
            if len(_encoded(candidate)) <= EXAMPLE_SAMPLE_BYTES:
                projected[ticker] = compact
    included_metrics = sum(len(metrics) for metrics in projected.values())
    return projected, {
        'symbols_total': len(examples), 'symbols_included': len(projected),
        'symbols_omitted': len(examples) - len(projected),
        'metrics_total': total_metrics, 'metrics_included': included_metrics,
        'metrics_omitted': total_metrics - included_metrics,
        'all_example_states': dict(states), **dict(evidence),
        'selection': 'Whole examples in report order that fit the sample budget',
        'nested_evidence': 'Full provenance and source disagreements are in the full report artifact',
    }


def _audit_summary(audit, *, limit):
    result = _lists_summary({key: value for key, value in audit.items()
                             if key != 'examples'}, limit=limit)
    if 'examples' in audit:
        result['examples'], result['examples_summary'] = _example_summary(
            audit['examples'], limit=limit)
    return result


def public_summary(report, report_path, *, sec=False):
    """Project a saved full audit for either Yahoo or SEC public publication.

    The full report must already exist so every diagnostic omission has an exact
    artifact and checksum. The workflow uploads these files even after failures.
    """
    path = Path(report_path)
    raw = path.read_bytes()
    repository = os.environ.get('GITHUB_REPOSITORY')
    run_id = os.environ.get('GITHUB_RUN_ID')
    artifact_prefix = 'sec-financials-audit-' if sec else 'company-financials-audit-'
    artifacts = {
        'report': path.name, 'report_bytes': len(raw),
        'report_sha256': hashlib.sha256(raw).hexdigest(),
        'per_security': 'company-financials-all-securities.csv',
        'per_metric': 'company-financials-all-metrics.csv',
        'recovery': 'company-financials-recovery.json.gz',
        'recovery_manifest': 'company-financials-recovery.manifest.json',
        'artifact_name': os.environ.get('FINANCIAL_AUDIT_ARTIFACT_NAME'),
        'artifact_name_prefix': artifact_prefix,
        'run_url': f'https://github.com/{repository}/actions/runs/{run_id}'
                   if repository and run_id else None,
        'availability': 'Scheduled for upload by this run; availability depends on the artifact step and retention',
    }
    for limit in (SAMPLE_ITEMS, 0):
        summary = {key: deepcopy(value) for key, value in report.items()
                   if key not in ('before', 'after', 'collection')}
        summary.update(
            report_format='financial-audit-summary-v1',
            summary_policy='Control values and whole-catalog totals are exact. Diagnostic lists '
                           'are samples with omission counts; example nested evidence is in full_artifacts.',
            full_artifacts=artifacts)
        for phase in ('before', 'after'):
            if phase in report:
                summary[phase] = _audit_summary(report[phase], limit=limit)
        if 'collection' in report:
            summary['collection'] = _lists_summary(report['collection'], limit=limit)
        if len(_encoded(summary)) <= MAX_PUBLIC_BYTES:
            return summary
    # Never make a queue/cooldown/completeness decision appear smaller to fit.
    raise ValueError('Financial audit control totals exceed public report size; full report is saved')
