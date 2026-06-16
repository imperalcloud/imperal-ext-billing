"""Billing · Dashboard tab builders — Overview, Transactions, Pricing."""
from __future__ import annotations

from imperal_sdk import ui
from queries_analytics import get_llm_costs_history  # Sprint 4 — top-level to avoid cross-ext re-import

from app import get_pricing_config, humanize_tool, humanize_reason, format_time
# Sprint 4 (2026-04-28) — _period_selector inlined below to break circular import


import queries
from panels_tabs_helpers import _PERIODS, _period_selector  # noqa: F401  (re-exported for callers)


# ─── Tab 1: Overview ──────────────────────────────────────────────────── #


async def _build_overview(uid: str, period: str):
    stats = await queries.get_spending_aggregation(uid, period)

    children = [
        _period_selector(period, "overview"),
        ui.Stats(columns=4, children=[
            ui.Stat(label="Total Spent", value=f"{stats['total_spent']:,}",
                    icon="TrendingDown", color="red"),
            ui.Stat(label="Credits", value=f"+{stats['total_credits']:,}",
                    icon="TrendingUp", color="green"),
            ui.Stat(label="Transactions", value=str(stats["tx_count"]),
                    icon="ArrowRightLeft", color="blue"),
            ui.Stat(label="Avg Cost", value=str(stats["avg_cost"]),
                    icon="Calculator", color="gray"),
        ]),
    ]

    if stats["daily_spending"]:
        children.append(ui.Chart(
            type="line", data=stats["daily_spending"],
            x_key="date", height=250,
        ))

    charts = []
    if stats["by_extension"]:
        charts.append(ui.Stack([
            ui.Header("By Extension", level=4),
            ui.Chart(type="pie", data=stats["by_extension"], x_key="app_id", height=200),
        ]))
    if stats["by_action_type"]:
        charts.append(ui.Stack([
            ui.Header("By Action Type", level=4),
            ui.Chart(type="pie", data=stats["by_action_type"], x_key="action_type", height=200),
        ]))
    if charts:
        children.append(ui.Grid(columns=len(charts), gap=2, children=charts))

    return ui.Stack(children=children, gap=2)


# ─── Tab 2: Transactions (user-friendly) ─────────────────────────────── #

def _describe_transaction(tx: dict) -> str:
    """Build a clear, human-readable description of what happened."""
    amount = tx["amount"]
    app = tx["app_id"] or ""
    tool = tx["tool_name"] or ""
    reason = tx["reason"]
    desc = tx.get("description") or ""

    ext_name = app.replace("-", " ").replace("_", " ").title() if app else ""

    if reason == "topup":
        return desc or "Credit top-up"
    if reason == "refund":
        return f"Refund{f' — {ext_name}' if ext_name else ''}"
    if reason == "plan_credit":
        return "Monthly plan credits"
    if reason == "bonus":
        return desc or "Bonus credits"
    if reason == "adjustment":
        return desc or "Balance adjustment"

    if amount < 0 and tool:
        action = humanize_tool(tool, app)
        if ext_name:
            return f"{ext_name} — {action}"
        return action

    if amount > 0:
        return desc or "Credit"

    return desc or f"{ext_name}: action" if ext_name else "Action"


async def _build_transactions(
    uid: str, period: str, filter_app: str, filter_type: str, offset: int,
    tz: str = "UTC",
):
    result = await queries.get_transaction_history(
        uid, limit=50, offset=int(offset),
        period=period,
        app_id=filter_app or None,
        tx_type=filter_type or None,
        user_only=True,
    )

    ext_options = [{"value": "", "label": "All Extensions"}]
    agg = await queries.get_spending_aggregation(uid, period)
    for entry in agg["by_extension"]:
        name = entry["app_id"].replace("-", " ").replace("_", " ").title()
        ext_options.append({"value": entry["app_id"], "label": name})

    filters = ui.Stack(direction="h", gap=1, children=[
        _period_selector(period, "transactions"),
        ui.Select(
            options=ext_options, value=filter_app,
            placeholder="Extension", param_name="filter_app",
            on_change=ui.Call(
                "__panel__dashboard", section="analytics", tab="transactions",
                period=period, filter_type=filter_type, filter_app="${value}",
                view="", event_id="", app_id="",
            ),
        ),
        ui.Select(
            options=[
                {"value": "", "label": "All Types"},
                {"value": "deduct", "label": "Spending"},
                {"value": "credit", "label": "Credits"},
            ],
            value=filter_type, placeholder="Type", param_name="filter_type",
            on_change=ui.Call(
                "__panel__dashboard", section="analytics", tab="transactions",
                period=period, filter_app=filter_app, filter_type="${value}",
                view="", event_id="", app_id="",
            ),
        ),
    ])

    rows = []
    for tx in result["transactions"]:
        amount = tx["amount"]
        desc = _describe_transaction(tx)

        if amount < 0:
            tokens_str = f"-{abs(amount)}"
        else:
            tokens_str = f"+{amount}"

        rows.append({
            "time": format_time(tx["created_at"], tz),
            "description": desc,
            "tokens": tokens_str,
            "event_id": tx["event_id"],
        })

    # on_row_click: row dict is passed with event_id key
    table = ui.DataTable(
        columns=[
            ui.DataColumn(key="time", label="When", width="20%"),
            ui.DataColumn(key="description", label="What happened", width="55%"),
            ui.DataColumn(key="tokens", label="Credits", width="25%"),
        ],
        rows=rows,
        on_row_click=ui.Call(
            "__panel__dashboard",
            section="analytics", view="transaction", period=period,
            tab="", app_id="",
        ),
    )

    footer = ui.Text(f"Showing {len(rows)} of {result['total']} actions", variant="caption")

    return ui.Stack(children=[filters, table, footer], gap=2)


# ─── Tab 3: Pricing ──────────────────────────────────────────────────── #


async def _build_pricing():
    config = await get_pricing_config()

    return ui.Stack(children=[
        ui.Header("Extension Pricing", level=3),
        ui.DataTable(
            columns=[
                ui.DataColumn(key="app_id", label="Extension", width=150),
                ui.DataColumn(key="mode", label="Mode", width=120),
                ui.DataColumn(key="read", label="Read", width=80),
                ui.DataColumn(key="write", label="Write", width=80),
                ui.DataColumn(key="destructive", label="Destructive", width=100),
            ],
            rows=config["extensions"],
        ),
        ui.Divider(),
        ui.Header("Model Rates", level=3),
        ui.DataTable(
            columns=[
                ui.DataColumn(key="model", label="Model", width=180),
                ui.DataColumn(key="tier", label="Tier", width=120),
                ui.DataColumn(key="platform_fee", label="Platform Fee", width=120),
            ],
            rows=config["model_rates"],
        ),
        ui.Alert(
            title="Guaranteed Pricing",
            message="Total cost = base_price + platform_fee. "
                    "Price is shown before execution. No surprises.",
            type="info",
        ),
    ], gap=2)


# ---------------------------------------------------------------------
# Sprint 4 (2026-04-28) - LLM Costs tab builder.
# Reads via auth-gw /v1/actions with Sprint 4 ActionResponse extension
# (llm_per_purpose + llm_total_cost_usd + is_byollm_chain).

# Sprint 4: _build_llm_costs lives in panels_tabs_llm; re-exported for panels_dashboard.
from panels_tabs_llm import _build_llm_costs  # noqa: E402,F401
