"""Billing · Left panel — wallet sidebar."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, _user_id, get_wallet
import queries

log = logging.getLogger("billing")


# ─── Left Panel ───────────────────────────────────────────────────────── #

@ext.panel(
    "sidebar", slot="left", title="Billing", icon="Wallet",
    default_width=320, min_width=260, max_width=420,
    refresh="on_event:billing.deduct,billing.credit",
)
async def billing_sidebar(ctx, period: str = "7d", **kwargs):
    """Wallet overview, quick stats, alerts, actions, extension breakdown."""
    uid = _user_id(ctx)
    wallet = await get_wallet(ctx)
    balance = wallet["balance"]
    plan = wallet["plan"]
    cap = wallet["cap"]
    pct = wallet["pct"]

    # Spending stats from DB
    try:
        stats = await queries.get_spending_aggregation(uid, period)
    except Exception as e:
        log.error("Sidebar stats error: %s", e)
        stats = {"total_spent": 0, "total_credits": 0, "action_count": 0,
                 "refund_count": 0, "by_extension": []}

    children = []

    # ── Wallet Card ───────────────────────────────────────────────
    unlimited = cap == 0
    if unlimited:
        balance_color = "green"
        progress_label = f"{balance:,} / Unlimited"
        progress_value = 100
    else:
        balance_color = "green" if pct > 50 else ("yellow" if pct > 20 else "red")
        progress_label = f"{balance:,} / {cap:,}"
        progress_value = min(pct, 100)
    children.append(ui.Card(
        title="Token Balance",
        content=ui.Stack([
            ui.Stat(label="Balance", value=f"{balance:,}", color=balance_color),
            ui.Progress(value=progress_value, label=progress_label),
            ui.Badge(plan.title(), color="blue"),
        ]),
    ))

    # ── Quick Stats ───────────────────────────────────────────────
    try:
        today_stats = await queries.get_spending_aggregation(uid, "today")
        spent_today = today_stats["total_spent"]
    except Exception:
        spent_today = 0

    action_count = stats.get("action_count", 0)
    refund_count = stats.get("refund_count", 0)
    net = stats["total_spent"] - stats["total_credits"]

    children.append(ui.Section(
        title="Quick Stats",
        children=[ui.KeyValue(items=[
            {"key": "Spent today", "value": f"-{spent_today:,}"},
            {"key": f"Spent {period}", "value": f"-{stats['total_spent']:,}"},
            {"key": "Refunded", "value": f"+{stats['total_credits']:,}"},
            {"key": "Net cost", "value": f"-{net:,}"},
            {"key": "Actions", "value": str(action_count)},
            {"key": "Refunds", "value": str(refund_count)},
        ], columns=2)],
    ))

    # ── Alerts (conditional) ──────────────────────────────────────
    if pct <= 20 and cap > 0 and not unlimited:
        alert_type = "error" if pct <= 5 else "warn"
        children.append(ui.Alert(
            message=f"Only {pct}% of tokens remaining ({balance:,} / {cap:,})",
            type=alert_type,
        ))

    # ── Actions ───────────────────────────────────────────────────
    children.append(ui.Section(
        title="Actions",
        children=[ui.Stack(direction="v", gap=1, children=[
            ui.Button(
                label="Export CSV", icon="Download", variant="secondary",
                on_click=ui.Call("export_csv", period=period),
            ),
            ui.Button(
                label="Top Up", icon="CreditCard", variant="primary",
                on_click=ui.Call("__topup__"),
            ),
            ui.Stack(direction="h", gap=1, children=[
                ui.Button(label="Change Plan", icon="ArrowUpCircle", disabled=True),
                ui.Badge("Soon", color="gray"),
            ]),
        ])],
    ))

    # ── Extension Breakdown ───────────────────────────────────────
    if stats["by_extension"]:
        ext_items = []
        for entry in stats["by_extension"]:
            ext_items.append(ui.ListItem(
                id=entry["app_id"],
                title=entry["app_id"],
                subtitle=f"{entry['pct']}% · {entry['spent']:,} tokens",
                badge=ui.Badge(f"{entry['pct']}%", color="blue"),
                on_click=ui.Call(
                    "__panel__dashboard",
                    view="extension", app_id=entry["app_id"], period=period,
                    tab="", event_id="",
                ),
            ))
        children.append(ui.Section(
            title="Extensions",
            children=[ui.List(items=ext_items)],
        ))

    # Auto-trigger center overlay (Analytics dashboard) on first sidebar mount.
    # Frontend's isCenterOverlay reads center_overlay=True from unified_config
    # and routes __panel__dashboard to setCenterOverlay → chat shifts to right.
    root = ui.Stack(children=children, gap=2, className="min-h-full")
    root.props["auto_action"] = ui.Call("__panel__dashboard")
    return root
