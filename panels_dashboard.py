"""Billing · Center panel — Account (primary) + Invoices + Analytics.

Structured for human clarity:
- Top-level `section` switcher:
  1. "account" / "overview" (default): 2-column clean layout for Plan, Tokens, Payment Methods, Profile
  2. "invoices": Payment history, receipts and downloadable invoices
  3. "analytics": Detailed usage charts, extension breakdowns, LLM costs and activity log
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
import panels_account as pa

log = logging.getLogger("billing")


@ext.panel(
    "dashboard", slot="center", title="Billing", icon="Wallet",
    center_overlay=True,  # federal v4.1.8 — chat shifts to 380px right rail
    refresh="on_event:billing.deduct,billing.credit",
)
async def billing_dashboard(
    ctx,
    section: str = "account",
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
    """Center panel: clean 2-column Overview, dedicated Invoices tab, and Detailed Analytics."""
    uid = _user_id(ctx)

    # DataTable on_row_click passes clicked row as nested dict in kwargs.
    row_data = kwargs.get("row")
    if isinstance(row_data, dict):
        if not event_id:
            event_id = str(row_data.get("event_id", ""))
        if not app_id:
            app_id = str(row_data.get("app_id", ""))

    try:
        # Normalize section name: "account" and "overview" are equivalent
        current_section = "account" if section in ("account", "overview", "") else section

        # ── Top Navigation Bar ──
        section_bar = ui.Stack(direction="h", gap=1, children=[
            ui.Button(
                "Overview & Plan", icon="LayoutDashboard", size="sm",
                variant="primary" if current_section == "account" else "ghost",
                on_click=ui.Call(
                    "__panel__dashboard", section="account", tab="overview",
                    period=period, view="", event_id="", app_id="",
                    filter_app="", filter_type="", offset=0,
                ),
            ),
            ui.Button(
                "Invoices & Receipts", icon="Receipt", size="sm",
                variant="primary" if current_section == "invoices" else "ghost",
                on_click=ui.Call(
                    "__panel__dashboard", section="invoices", tab="overview",
                    period=period, view="", event_id="", app_id="",
                    filter_app="", filter_type="", offset=0,
                ),
            ),
            ui.Button(
                "Detailed Analytics", icon="BarChart3", size="sm",
                variant="primary" if current_section == "analytics" else "ghost",
                on_click=ui.Call(
                    "__panel__dashboard", section="analytics", tab="overview",
                    period=period, view="", event_id="", app_id="",
                    filter_app="", filter_type="", offset=0,
                ),
            ),
        ], sticky=True)

        # ── Section 1: Overview & Plan (Clean 2-Column Grid) ──
        if current_section == "account":
            sub_sections = await pa.build_subscription_section(ctx)
            token_sections = await pa.build_tokens_section(ctx)
            pm_sections = await pa.build_payment_methods_section(ctx)
            prof_sections = await pa.build_profile_section(ctx)

            # Row 1: Plan & Subscription (Col 1) + Credits & Top-Up (Col 2)
            grid_row1 = ui.Grid(columns=2, gap=3, children=[*sub_sections, *token_sections])

            # Row 2: Payment Methods (Col 1) + Billing Profile (Col 2)
            grid_row2 = ui.Grid(columns=2, gap=3, children=[*pm_sections, *prof_sections])

            return ui.Stack(
                direction="v",
                gap=3,
                children=[grid_row1, grid_row2],
                className="p-3 max-w-5xl mx-auto"
            )

        # ── Section 2: Invoices & Receipts Tab ──
        if current_section == "invoices":
            hist_sections = await pa.build_history_section(ctx)
            return ui.Stack(
                direction="v",
                gap=3,
                children=[*hist_sections],
                className="p-3 max-w-4xl mx-auto"
            )

        # ── Section 3: Detailed Analytics Tab ──
        tz = await get_user_timezone(ctx)

        if view == "transaction" and event_id:
            return await _build_transaction_detail(event_id, period, tz=tz)
        if view == "extension" and app_id:
            return await _build_extension_stats(uid, app_id, period)
        if view == "account":
            return await _build_account_summary(ctx, period)

        # Analytics Sub-tabs
        tab_buttons = []
        for tid, label, icon in [
            ("overview", "Usage Overview", "BarChart3"),
            ("transactions", "Activity Log", "ArrowRightLeft"),
            ("llm_costs", "LLM Costs", "Cpu"),
            ("pricing", "Pricing Table", "Tag"),
        ]:
            tab_buttons.append(ui.Button(
                label, icon=icon, size="sm",
                variant="primary" if tab == tid else "ghost",
                on_click=ui.Call(
                    "__panel__dashboard",
                    section="analytics", tab=tid, period=period,
                    view="", event_id="", app_id="",
                    filter_app="", filter_type="", offset=0,
                ),
            ))

        tab_bar = ui.Stack(direction="h", gap=1, children=tab_buttons, sticky=True)

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

        return ui.Stack(
            children=[tab_bar, content],
            gap=2,
            className="p-3 max-w-5xl mx-auto"
        )

    except Exception as e:
        log.error("Dashboard error section=%s tab=%s view=%s: %s", section, tab, view, e)
        return ui.Alert(title="Error", message=str(e), type="error")
