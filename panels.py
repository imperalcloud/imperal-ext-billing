"""Billing · Left panel — clean navigation sidebar."""
from __future__ import annotations

import logging
from imperal_sdk import ui
from imperal_sdk.ui.base import UINode
from app import ext

log = logging.getLogger("billing")

_SECTIONS = [
    {"id": "account", "label": "Overview & Plan", "icon": "LayoutDashboard"},
    {"id": "invoices", "label": "Invoices & Receipts", "icon": "Receipt"},
    {"id": "analytics", "label": "Usage Analytics", "icon": "BarChart3"},
]


def _nav_item(sec: dict, active: str, period: str) -> UINode:
    props = {
        "id": sec["id"],
        "title": sec["label"],
        "icon": sec["icon"],
        "on_click": ui.Call(
            "__panel__dashboard",
            section=sec["id"], tab="overview", period=period,
            view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
        ),
    }
    if sec["id"] == active:
        props["selected"] = True
    return UINode(type="ListItem", props=props)


@ext.panel(
    "sidebar", slot="left", title="Billing", icon="Wallet",
    default_width=240, min_width=200, max_width=320,
    refresh="on_event:billing.deduct,billing.credit",
)
async def billing_sidebar(ctx, section: str = "account", period: str = "7d", **kwargs):
    """Clean navigation sidebar — 100% focused menu, zero duplicate clutter."""
    current_section = "account" if section in ("account", "overview", "") else section
    items = [_nav_item(s, current_section, period) for s in _SECTIONS]
    root = ui.List(items=items)
    root.props["auto_action"] = ui.Call(
        "__panel__dashboard",
        section=current_section, tab="overview", period=period,
        view="", event_id="", app_id="", filter_app="", filter_type="", offset=0,
    )
    return root
