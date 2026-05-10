"""Billing · LLM Costs tab builder (split from panels_tabs.py).

Sprint 4 (2026-04-28). Imported back into panels_tabs.py for compatibility
with panels_dashboard.py's existing import line.
"""
from __future__ import annotations

from imperal_sdk import ui

from queries_analytics import get_llm_costs_history
from panels_tabs_helpers import _period_selector


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
