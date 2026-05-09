"""Billing · Detail sub-views — Account Summary, Transaction Detail, Extension Stats."""
from __future__ import annotations

from imperal_sdk import ui

from app import (_user_id, get_wallet, get_pricing_config,
                 humanize_tool, humanize_reason, format_time_full)
import queries


def _back_button(period: str, label: str = "Back", target_tab: str = "overview"):
    return ui.Button(
        label, icon="ArrowLeft", variant="ghost", size="sm",
        on_click=ui.Call(
            "__panel__dashboard",
            tab=target_tab, period=period,
            view="", event_id="", app_id="",
        ),
    )


# ─── Account Summary ─────────────────────────────────────────────────── #


async def _build_account_summary(ctx, period: str):
    wallet = await get_wallet(ctx)
    plan = wallet["plan"]
    features = wallet["features"]

    feat_items = []
    tok = features.get("tokens")
    feat_items.append(ui.ListItem(
        id="f1",
        title=f"{tok:,} monthly tokens" if tok else "Unlimited tokens",
        icon="Check",
    ))
    ext_count = features.get("extensions")
    feat_items.append(ui.ListItem(
        id="f2",
        title=f"{ext_count} extensions" if ext_count else "Unlimited extensions",
        icon="Check",
    ))
    for tier in ["economy", "standard", "premium"]:
        has = tier in features.get("models", [])
        feat_items.append(ui.ListItem(
            id=f"m_{tier}",
            title=f"{tier.title()} models",
            icon="Check" if has else "X",
        ))

    try:
        credits = await queries.get_transaction_history(
            _user_id(ctx), limit=5, period="all", tx_type="credit",
        )
        credit_items = [
            {"title": f"+{tx['amount']:,} tokens",
             "description": tx["description"] or humanize_reason(tx["reason"]),
             "time": tx["created_at"][:10], "icon": "Plus", "color": "green"}
            for tx in credits["transactions"]
        ]
    except Exception:
        credit_items = []

    children = [
        _back_button(period),
        ui.Header("Account Summary", level=3),
        ui.KeyValue(items=[
            {"key": "Plan", "value": plan.title()},
            {"key": "Status", "value": "Active"},
            {"key": "Balance", "value": f"{wallet['balance']:,} tokens"},
            {"key": "Monthly Cap", "value": f"{wallet['cap']:,} tokens"},
        ]),
        ui.Divider(),
        ui.Header("Plan Features", level=4),
        ui.List(items=feat_items),
    ]

    if credit_items:
        children.extend([
            ui.Divider(),
            ui.Header("Billing History", level=4),
            ui.Timeline(items=credit_items),
        ])

    children.extend([
        ui.Divider(),
        ui.Stack(direction="v", gap=1, children=[
            ui.Stack(direction="h", gap=1, children=[
                ui.Button("Top Up", icon="CreditCard", disabled=True),
                ui.Badge("Soon", color="gray"),
            ]),
            ui.Stack(direction="h", gap=1, children=[
                ui.Button("Upgrade Plan", icon="ArrowUpCircle", disabled=True),
                ui.Badge("Soon", color="gray"),
            ]),
        ]),
    ])

    return ui.Stack(children=children, gap=2)


# ─── Transaction Detail (redesigned) ─────────────────────────────────── #


async def _build_transaction_detail(event_id: str, period: str, tz: str = "UTC"):
    """Clear, human-readable transaction detail."""
    detail = await queries.get_transaction_detail(event_id)

    if not detail.get("user_entry"):
        return ui.Stack(children=[
            _back_button(period, "Back to Transactions", "transactions"),
            ui.Alert(type="warning", message="Transaction not found."),
        ], gap=2)

    entry = detail["user_entry"]
    amount = entry["amount"]
    app_id = entry.get("app_id") or ""
    tool = entry.get("tool_name") or ""
    reason = entry.get("reason", "")

    # Human-readable header
    if amount < 0:
        title = f"Spent {abs(amount)} tokens"
        badge = ui.Badge("Spending", color="red")
        what = humanize_tool(tool, app_id)
        ext_name = app_id.replace("-", " ").replace("_", " ").title() if app_id else "System"
    elif reason == "topup":
        title = f"Added {amount} tokens"
        badge = ui.Badge("Top-up", color="green")
        what = entry.get("description") or "Token purchase"
        ext_name = "Billing"
    elif reason == "refund":
        title = f"Refunded {amount} tokens"
        badge = ui.Badge("Refund", color="yellow")
        what = entry.get("description") or "Refund"
        ext_name = app_id.replace("-", " ").title() if app_id else "System"
    else:
        title = f"Received {amount} tokens"
        badge = ui.Badge(humanize_reason(reason), color="green")
        what = entry.get("description") or humanize_reason(reason)
        ext_name = "System"

    time_str = format_time_full(entry["created_at"], tz)

    children = [
        _back_button(period, "Back to Transactions", "transactions"),
        ui.Stack(direction="h", gap=1, children=[
            ui.Header(title, level=3),
            badge,
        ]),
        ui.KeyValue(items=[
            {"key": "When", "value": time_str},
            {"key": "What", "value": what},
            {"key": "Extension", "value": ext_name},
            {"key": "Tokens", "value": f"{amount:+,}"},
        ], columns=2),
    ]

    # Cost breakdown (for deductions)
    if entry.get("base_price") is not None and amount < 0:
        children.extend([
            ui.Divider(),
            ui.Section(title="Cost Breakdown", children=[
                ui.KeyValue(items=[
                    {"key": "Extension fee", "value": f"{entry['base_price']} tokens"},
                    {"key": "Platform fee", "value": f"{entry['platform_fee']} tokens"},
                    {"key": "Total", "value": f"{abs(amount)} tokens"},
                ], columns=3),
                ui.Text(
                    f"Model: {entry.get('model', '—')} ({entry.get('model_tier', '—')} tier)",
                    variant="caption",
                ),
            ]),
        ])

    # Technical details (collapsed feel)
    children.extend([
        ui.Divider(),
        ui.Section(title="Details", children=[
            ui.KeyValue(items=[
                {"key": "Transaction ID", "value": (entry.get("transaction_id") or "—")[:20]},
                {"key": "Event ID", "value": event_id[:20]},
                {"key": "Type", "value": entry.get("action_type") or reason},
                {"key": "Function", "value": tool or "—"},
            ], columns=2),
        ]),
    ])

    # Double entry verification
    platform = detail.get("platform_entry")
    if platform:
        balanced = "Verified" if detail["balanced"] else "Mismatch"
        bal_color = "green" if detail["balanced"] else "red"
        children.append(ui.Section(title="Ledger", children=[
            ui.Stack(direction="h", gap=1, children=[
                ui.Text(f"User: {amount:+,}", variant="caption"),
                ui.Text(f"Platform: {platform['amount']:+,}", variant="caption"),
                ui.Badge(balanced, color=bal_color),
            ]),
        ]))

    return ui.Stack(children=children, gap=2)


# ─── Extension Stats ─────────────────────────────────────────────────── #


async def _build_extension_stats(uid: str, app_id: str, period: str):
    stats = await queries.get_extension_stats(uid, app_id, period)
    config = await get_pricing_config()

    ext_name = app_id.replace("-", " ").replace("_", " ").title()

    children = [
        _back_button(period),
        ui.Header(f"{ext_name} — Usage Stats", level=3),
        ui.Stats(columns=3, children=[
            ui.Stat(label="Total Spent", value=f"{stats['total_spent']:,}", color="red"),
            ui.Stat(label="Actions", value=str(stats["tx_count"]), color="blue"),
            ui.Stat(label="Avg Cost", value=str(stats["avg_cost"]), color="gray"),
        ]),
    ]

    if stats["top_functions"]:
        fn_rows = []
        for fn in stats["top_functions"]:
            fn_rows.append({
                "tool_name": humanize_tool(fn["tool_name"], app_id),
                "spent": fn["spent"],
                "count": fn["count"],
            })
        children.extend([
            ui.Divider(),
            ui.Header("Top Functions", level=4),
            ui.DataTable(
                columns=[
                    ui.DataColumn(key="tool_name", label="Function", width=180),
                    ui.DataColumn(key="spent", label="Spent", width=80),
                    ui.DataColumn(key="count", label="Count", width=60),
                ],
                rows=fn_rows,
            ),
        ])

    if stats["daily_trend"]:
        children.extend([
            ui.Divider(),
            ui.Header("Spending Trend", level=4),
            ui.Chart(type="line", data=stats["daily_trend"], x_key="date", height=150),
        ])

    ext_pricing = next(
        (e for e in config["extensions"] if e["app_id"] == app_id), None,
    )
    if ext_pricing:
        children.extend([
            ui.Divider(),
            ui.Header("Pricing", level=4),
            ui.KeyValue(items=[
                {"key": "Mode", "value": ext_pricing["mode"]},
                {"key": "Read", "value": f"{ext_pricing['read']} tokens"},
                {"key": "Write", "value": f"{ext_pricing['write']} tokens"},
                {"key": "Destructive", "value": f"{ext_pricing['destructive']} tokens"},
            ]),
        ])

    return ui.Stack(children=children, gap=2)
