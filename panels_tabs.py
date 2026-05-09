"""Billing · Dashboard tab builders — Overview, Transactions, Pricing."""
from __future__ import annotations

from imperal_sdk import ui
from queries_analytics import get_llm_costs_history  # Sprint 4 — top-level to avoid cross-ext re-import

from app import get_pricing_config, humanize_tool, humanize_reason, format_time
# Sprint 4 (2026-04-28) — _period_selector inlined below to break circular import


_PERIODS = [
    ("today", "Today"),
    ("7d", "7 Days"),
    ("30d", "30 Days"),
    ("all", "All Time"),
]


def _period_selector(current: str, tab: str):
    buttons = []
    for val, label in _PERIODS:
        buttons.append(ui.Button(
            label, size="sm",
            variant="primary" if current == val else "ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                tab=tab, period=val,
                view="", event_id="", app_id="",
            ),
        ))
    return ui.Stack(direction="h", gap=1, children=buttons)

import queries


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
        return desc or "Token top-up"
    if reason == "refund":
        return f"Refund{f' — {ext_name}' if ext_name else ''}"
    if reason == "plan_credit":
        return "Monthly plan tokens"
    if reason == "bonus":
        return desc or "Bonus tokens"
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
                "__panel__dashboard", tab="transactions",
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
                "__panel__dashboard", tab="transactions",
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
            ui.DataColumn(key="tokens", label="Tokens", width="25%"),
        ],
        rows=rows,
        on_row_click=ui.Call(
            "__panel__dashboard",
            view="transaction", period=period,
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
# ---------------------------------------------------------------------

async def _build_llm_costs(
    user_id: str,
    period: str = "7d",
    offset: int = 0,
    tz: str = "UTC",
) -> object:
    """Render LLM Costs tab - per-action card with per-purpose breakdown."""
    result = await get_llm_costs_history(
        user_id=user_id, period=period, limit=20, offset=offset,
    )

    stats_row = ui.Stats(columns=4, children=[
        ui.Stat(
            label="Total Cost",
            value=f"${result['total_cost_usd']:.4f}",
            color="green",
        ),
        ui.Stat(
            label="Total Tokens",
            value=f"{result['total_tokens']:,}",
            color="cyan",
        ),
        ui.Stat(
            label="BYOLLM Actions",
            value=f"{result['byollm_count']} / {result['total_actions']}",
            color="purple",
        ),
        ui.Stat(
            label="Total Actions",
            value=str(result["total_actions"]),
            color="blue",
        ),
    ])

    intro = ui.Alert(
        title="LLM Costs (action_ledger, NOT wallet)",
        message=(
            "Per-purpose breakdown of every LLM call your actions made: "
            "routing / execution / navigate / chain_narrative / judge - "
            "each with provider, model, input/output tokens, and USD cost "
            "computed from the admin Pricing table. BYOLLM actions show "
            "$0.00 (you pay your provider directly). Pre-Sprint-4 rows "
            "lack per-purpose data and show 'Pre-Sprint-4 audit data' - "
            "new chains populate the full breakdown."
        ),
        type="info",
    )

    actions = result["actions"]
    if not actions:
        empty = ui.Alert(
            title="No LLM activity",
            message=f"No actions in the last {period}. Adjust period filter or check back later.",
            type="info",
        )
        return ui.Stack(children=[
            _period_selector(period, "llm_costs"),
            intro,
            stats_row,
            empty,
        ], gap=2)

    cards = []
    for action in actions:
        is_byollm = bool(action.get("is_byollm_chain"))
        per_purpose = action.get("llm_per_purpose") or {}
        total_cost = float(action.get("llm_total_cost_usd", 0) or 0)
        total_in = sum(int(p.get("input_tokens", 0) or 0) for p in per_purpose.values())
        total_out = sum(int(p.get("output_tokens", 0) or 0) for p in per_purpose.values())

        header_label = (
            f"{action.get('app_id', '?')}/{action.get('tool_name', '?')}  "
            f"-  {action.get('action_type', '?')}  "
            f"-  {int(action.get('duration_ms', 0) or 0)/1000:.1f}s  "
            f"-  {action.get('status', '?')}"
        )

        if per_purpose:
            purpose_rows = []
            for purpose, agg in per_purpose.items():
                cost_label = "$0.00 (BYOLLM)" if agg.get("is_byollm") else f"${agg.get('cost_usd', 0):.4f}"
                purpose_rows.append({
                    "purpose": purpose,
                    "provider": agg.get("provider", ""),
                    "model": agg.get("model", ""),
                    "input": f"{agg.get('input_tokens', 0):,}",
                    "output": f"{agg.get('output_tokens', 0):,}",
                    "cost": cost_label,
                })
            purpose_table = ui.DataTable(
                columns=[
                    {"key": "purpose", "label": "Purpose"},
                    {"key": "provider", "label": "Provider"},
                    {"key": "model", "label": "Model"},
                    {"key": "input", "label": "Input"},
                    {"key": "output", "label": "Output"},
                    {"key": "cost", "label": "Cost"},
                ],
                rows=purpose_rows,
            )
        else:
            if action.get("llm_model"):
                purpose_table = ui.Alert(
                    title="Pre-Sprint-4 audit data",
                    message=(
                        f"Legacy: {action.get('llm_provider', '?')}/{action.get('llm_model', '?')}, "
                        f"{action.get('llm_total_calls', 0)} calls, "
                        f"{action.get('llm_total_tokens', 0):,} tokens"
                    ),
                    type="info",
                )
            else:
                purpose_table = ui.Alert(
                    title="No LLM calls",
                    message="This action did not invoke any LLM (cache hit or system-only).",
                    type="info",
                )

        footer_label = f"Total: {total_in:,} in / {total_out:,} out"
        if is_byollm:
            footer_label += "  -  $0.00 (BYOLLM)"
        else:
            footer_label += f"  -  ${total_cost:.4f}"

        cards.append(ui.Card(
            title=header_label,
            content=ui.Stack(children=[
                ui.Text(
                    f"trace_id: {action.get('trace_id', '?')}  -  "
                    f"chain_id: {action.get('chain_id', '?') or '-'}  -  "
                    f"{action.get('created_at', '?')}",
                    variant="caption",
                ),
                purpose_table,
                ui.Text(footer_label, variant="body"),
            ], gap=1),
        ))

    return ui.Stack(children=[
        _period_selector(period, "llm_costs"),
        intro,
        stats_row,
        *cards,
    ], gap=2)

