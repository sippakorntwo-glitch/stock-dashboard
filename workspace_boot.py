"""Recover stale Python imports when hosting updates files without a process restart.

Only this application's modules are replaced, once per detected mismatch. Old
sessions keep references to their old module objects; their globals are not
mutated through importlib.reload. No market data, secrets or settings are erased.
"""
from __future__ import annotations

import importlib
import re
import sys
import threading
from pathlib import Path
from types import ModuleType

_LOCK = threading.RLock()
_ROOT = Path(__file__).resolve().parent
_MODULES = ('dashboard_ui', 'dashboard_views', 'dashboard_runtime',
            'dashboard_core', 'data_sync', 'github_store', 'analytics',
            'dashboard_help', 'chart_ranges', 'dashboard_selection', 'chart_performance', 'ranking_board', 'ranking_engine', 'ranking_policy', 'data_quality', 'metadata_repair', 'quality_views', 'chart_inspector', 'return_periods', 'catalog_extension', 'screening', 'filters_ui', 'return_audit_ui')


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
        # Do not pretend to upgrade before hosting has copied the new source.
        text = (_ROOT / 'dashboard_runtime.py').read_text(encoding='utf-8')
        match = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)", text)
        if not match or match.group(1) != expected:
            raise RuntimeError('Hosting has not synchronized the complete release yet; reload after the build completes.')
        previous = {name: sys.modules.get(name) for name in _MODULES}
        try:
            for name in _MODULES:
                sys.modules.pop(name, None)
            importlib.invalidate_caches()
            runtime = importlib.import_module('dashboard_runtime')
            ui = importlib.import_module('dashboard_ui')
            if needs_refresh(runtime, ui, expected):
                raise RuntimeError('The local research modules do not match the expected release.')
        except Exception:
            # Preserve existing sessions' import references if initialization fails.
            for name in _MODULES:
                sys.modules.pop(name, None)
            for name, module in previous.items():
                if module is not None:
                    sys.modules[name] = module
            raise
        return runtime, ui
