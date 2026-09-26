"""Billing · Left panel — clean navigation sidebar."""
from __future__ import annotations

import logging
from imperal_sdk import ui
from app import ext, get_wallet

log = logging.getLogger("billing")


@ext.panel(
    "sidebar", slot="left", title="Billing", icon="Wallet",
    default_width=280, min_width=240, max_width=360,
    refresh="on_event:billing.deduct,billing.credit",
)
async def billing_sidebar(ctx, section: str = "account", period: str = "7d", **kwargs):
    """Clean navigation sidebar — clear, focused, no duplicate clutter."""
    wallet = await get_wallet(ctx)
    balance = wallet.get("balance", 0)
    plan = wallet.get("plan", "free")

    # 1. Compact Header: Clean summary showing active Plan and Balance
    header_card = ui.Card(
        title="Billing & Wallet",
        subtitle=f"{plan.title()} Plan · {balance:,} credits",
        content=ui.Stack(direction="h", gap=1, children=[
            ui.Badge(plan.title(), color="blue"),
            ui.Badge(f"{balance:,} credits", color="green"),
        ]),
    )

    # 2. Clean Navigation items matching the center panel tabs
    is_overview = section in ("account", "overview", "")
    is_invoices = section == "invoices"
    is_analytics = section == "analytics"

    nav_items = [
        ui.Button(
            "Overview & Plan",
            icon="LayoutDashboard",
            size="sm",
            variant="primary" if is_overview else "ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                section="account", tab="overview", period=period,
                view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
            ),
        ),
        ui.Button(
            "Invoices & Receipts",
            icon="Receipt",
            size="sm",
            variant="primary" if is_invoices else "ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                section="invoices", tab="overview", period=period,
                view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
            ),
        ),
        ui.Button(
            "Detailed Analytics",
            icon="BarChart3",
            size="sm",
            variant="primary" if is_analytics else "ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                section="analytics", tab="overview", period=period,
                view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
            ),
        ),
    ]

    nav_section = ui.Section(
        title="Navigation",
        children=[ui.Stack(direction="v", gap=1, children=nav_items)],
    )

    # 3. Quick Actions
    quick_actions = ui.Section(
        title="Quick Actions",
        children=[ui.Stack(direction="v", gap=1, children=[
            ui.Button(
                "Export CSV",
                icon="Download",
                size="sm",
                variant="secondary",
                on_click=ui.Call("export_csv", period=period),
            ),
        ])],
    )

    root = ui.Stack(
        children=[header_card, nav_section, quick_actions],
        gap=2,
        className="min-h-full p-2",
    )

    # Auto-trigger center overlay on first sidebar mount
    active_sec = "invoices" if is_invoices else ("analytics" if is_analytics else "account")
    root.props["auto_action"] = ui.Call(
        "__panel__dashboard",
        section=active_sec, tab="overview", period=period,
        view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
    )
    return root
