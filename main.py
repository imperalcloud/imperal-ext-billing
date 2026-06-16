"""Billing v2.0.0 · Enterprise billing dashboard — system extension."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in (
    "app", "handlers", "handlers_payment", "handlers_money", "skeleton",
    "queries", "queries_analytics", "models_account", "account_data",
    "panels", "panels_account", "panels_dashboard", "panels_tabs", "panels_views",
    "panels_center", "panels_right",
)]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers           # noqa: F401
import handlers_payment   # noqa: F401
import handlers_money     # noqa: F401  (registers guarded write/destructive tools)
import skeleton           # noqa: F401
import panels             # noqa: F401
import panels_dashboard   # noqa: F401
import panels_tabs        # noqa: F401
import panels_views       # noqa: F401
