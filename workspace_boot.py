"""Validate one coherent release without replacing live Python modules.

Production disables source watching and deploys releases with a clean restart.
Existing sessions never delete or reload shared modules during an import.
"""
from __future__ import annotations

import importlib
import threading
from pathlib import Path
from types import ModuleType

_LOCK = threading.RLock()
_ROOT = Path(__file__).resolve().parent
_MODULES = ('dashboard_ui', 'dashboard_views', 'dashboard_runtime', 'dashboard_core', 'data_sync', 'github_store', 'analytics', 'dashboard_help', 'chart_ranges', 'dashboard_selection', 'chart_performance', 'ranking_board', 'ranking_engine', 'ranking_policy', 'data_quality', 'metadata_repair', 'quality_views', 'chart_inspector', 'return_periods', 'catalog_extension', 'screening', 'filters_ui', 'return_audit_ui', 'workspace_theme', 'live_quotes', 'live_quote_ui', 'ui_stability', 'asset_semantics', 'sec_reference', 'reference_ui', 'chart_commentary')
_MODULES += ('financial_statements', 'company_metrics', 'company_analysis_th', 'company_analysis_ui', 'volume_split', 'read_view')
_MODULES += ('chart_levels', 'stock_brief_ui', 'stock_brief_service', 'stock_news_analysis')
_MODULES += ('screener_view', 'financial_trends', 'financial_trends_ui', 'peer_analysis', 'peer_analysis_ui',
             'valuation', 'valuation_ui', 'etf_research', 'etf_research_ui', 'research_workspace',
             'research_workspace_ui', 'research_summary', 'research_updates')


def needs_refresh(runtime: ModuleType, ui: ModuleType, expected: str) -> bool:
    return (getattr(runtime, 'APP_VERSION', None) != expected
            or not callable(getattr(ui, '_poll_data', None)))


def ensure_release(expected: str) -> tuple[ModuleType, ModuleType]:
    """Load a coherent local release; never download or execute remote code."""
    with _LOCK:
        runtime = importlib.import_module('dashboard_runtime')
        ui = importlib.import_module('dashboard_ui')
        if not needs_refresh(runtime, ui, expected):
            return runtime, ui
        # Removing modules while another session imports them causes importlib
        # KeyError and mixed module identities. Deployment must restart the
        # process; an active interpreter never upgrades its own module graph.
        raise RuntimeError('The application release changed; a clean hosting restart is required.')
