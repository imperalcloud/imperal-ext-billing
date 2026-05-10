"""Billing · Right panel — analytics dashboard + detail views.

Unified right panel (admin pattern): tabs for Overview/Transactions/Pricing,
plus detail sub-views for Transaction Detail, Extension Stats, Account Summary.
Builders split into panels_tabs.py and panels_views.py for <300L rule.

IMPORTANT: Every ui.Call("__panel__dashboard", ...) MUST explicitly set ALL
routing params (view, tab, event_id, app_id, period) to prevent stale state
from frontend param merging (usePanelDiscovery merges, not replaces).

NOTE: DataTable on_row_click passes clicked row as nested `row` dict in params.
Template syntax ${row.xxx} is NOT supported — read row[key] from kwargs instead.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, _user_id, get_user_timezone
from panels_views import (
    _build_transaction_detail,
    _build_extension_stats,
    _build_account_summary,
)
from panels_tabs import (
    _build_overview, _build_transactions, _build_pricing, _build_llm_costs,
)

log = logging.getLogger("billing")



# ─── Right Panel (main router) ────────────────────────────────────────── #

@ext.panel(
    "dashboard", slot="center", title="Analytics", icon="BarChart3",
    center_overlay=True,  # federal v4.1.8 — chat shifts to 380px right rail
    refresh="on_event:billing.deduct,billing.credit",
)
async def billing_dashboard(
    ctx,
    tab: str = "overview",
    period: str = "7d",
    filter_app: str = "",
    filter_type: str = "",
    offset: int = 0,
    view: str = "",
    event_id: str = "",
    app_id: str = "",
    **kwargs,
):
    """Right panel: tabs (Overview/Transactions/Pricing) + detail sub-views."""
    uid = _user_id(ctx)

    # DataTable on_row_click passes clicked row as nested dict in kwargs.
    # Extract event_id/app_id from row if not provided directly.
    row_data = kwargs.get("row")
    if isinstance(row_data, dict):
        if not event_id:
            event_id = str(row_data.get("event_id", ""))
        if not app_id:
            app_id = str(row_data.get("app_id", ""))

    try:
        # Detail sub-views (triggered by clicks)
        tz = await get_user_timezone(ctx)

        if view == "transaction" and event_id:
            return await _build_transaction_detail(event_id, period, tz=tz)
        if view == "extension" and app_id:
            return await _build_extension_stats(uid, app_id, period)
        if view == "account":
            return await _build_account_summary(ctx, period)

        # Tab bar — each button explicitly resets ALL routing params
        tab_buttons = []
        for tid, label, icon in [
            ("overview", "Overview", "BarChart3"),
            ("transactions", "Activity", "ArrowRightLeft"),
            ("llm_costs", "LLM Costs", "Cpu"),
            ("pricing", "Pricing", "Tag"),
        ]:
            tab_buttons.append(ui.Button(
                label, icon=icon, size="sm",
                variant="primary" if tab == tid else "ghost",
                on_click=ui.Call(
                    "__panel__dashboard",
                    tab=tid, period=period,
                    view="", event_id="", app_id="",
                    filter_app="", filter_type="", offset=0,
                ),
            ))
        # Account tab (goes to view, not tab)
        tab_buttons.append(ui.Button(
            "Account", icon="User", size="sm", variant="ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                view="account", period=period,
                tab="", event_id="", app_id="",
            ),
        ))
        tab_bar = ui.Stack(direction="h", gap=1, children=tab_buttons, sticky=True)

        # Route to tab builder
        if tab == "transactions":
            content = await _build_transactions(
                uid, period, filter_app, filter_type, offset, tz=tz,
            )
        elif tab == "llm_costs":
            content = await _build_llm_costs(uid, period, offset=offset, tz=tz)
        elif tab == "pricing":
            content = await _build_pricing()
        else:
            content = await _build_overview(uid, period)

        return ui.Stack(children=[tab_bar, content], gap=2)

    except Exception as e:
        log.error("Dashboard error tab=%s view=%s: %s", tab, view, e)
        return ui.Alert(title="Error", message=str(e), type="error")
