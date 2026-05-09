"""Billing · Chat function handlers."""
from __future__ import annotations

import csv
import io

from pydantic import BaseModel, Field

from app import chat, ActionResult, _user_id
import queries


# ─── Models ───────────────────────────────────────────────────────────── #

class EmptyParams(BaseModel):
    """No parameters needed."""
    pass


class ExportCsvParams(BaseModel):
    """Parameters for CSV export."""
    period: str = Field(default="all", description="Time period: today, 7d, 30d, all")
    app_id: str = Field(default="", description="Filter by extension (optional)")
    tx_type: str = Field(default="", description="Filter by type: deduct, credit (optional)")


# ─── Existing Handlers ────────────────────────────────────────────────── #

@chat.function(
    "get_balance",
    action_type="read",
    description="Get current token balance, plan name, and cap.",
)
async def fn_get_balance(ctx, params: EmptyParams) -> ActionResult:
    try:
        info = await ctx.billing.get_balance()
        return ActionResult.success(
            data={
                "balance": info.balance,
                "plan": info.plan,
                "cap": info.cap,
            },
            summary=(
                f"Balance: {info.balance:,} tokens on the {info.plan} plan "
                f"(cap: {info.cap:,})"
            ),
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch balance: {e}")


@chat.function(
    "get_plan",
    action_type="read",
    description="Get subscription details: plan, status, billing period.",
)
async def fn_get_plan(ctx, params: EmptyParams) -> ActionResult:
    try:
        sub = await ctx.billing.get_subscription()
        return ActionResult.success(
            data={
                "plan": sub.plan,
                "status": sub.status,
                "started_at": sub.started_at,
                "expires_at": sub.expires_at,
            },
            summary=f"Plan: {sub.plan} ({sub.status})",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch subscription: {e}")


@chat.function(
    "spending_report",
    action_type="read",
    description="Show usage and spending breakdown by meter.",
)
async def fn_spending_report(ctx, params: EmptyParams) -> ActionResult:
    try:
        limits = await ctx.billing.check_limits()
        usage_lines = [
            f"  {meter}: {count:,}" for meter, count in limits.usage.items()
        ]
        usage_text = "\n".join(usage_lines) if usage_lines else "  No usage recorded"
        exceeded_text = (
            f" | Exceeded: {', '.join(limits.exceeded)}" if limits.exceeded else ""
        )
        return ActionResult.success(
            data={
                "plan": limits.plan,
                "usage": limits.usage,
                "limits": limits.limits,
                "exceeded": limits.exceeded,
            },
            summary=f"Plan: {limits.plan}{exceeded_text}\nUsage:\n{usage_text}",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch spending report: {e}")


# ─── New: Export CSV ──────────────────────────────────────────────────── #

@chat.function(
    "export_csv",
    action_type="read",
    description="Export transaction history as CSV.",
)
async def fn_export_csv(ctx, params: ExportCsvParams) -> ActionResult:
    try:
        uid = _user_id(ctx)
        result = await queries.get_transaction_history(
            uid, limit=10_000, offset=0,
            period=params.period,
            app_id=params.app_id or None,
            tx_type=params.tx_type or None,
        )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Time", "Extension", "Function", "Type", "Amount", "Description",
        ])
        for tx in result["transactions"]:
            writer.writerow([
                tx["created_at"],
                tx["app_id"] or "",
                tx["tool_name"] or "",
                tx["reason"],
                tx["amount"],
                tx["description"] or "",
            ])

        csv_str = buf.getvalue()
        count = len(result["transactions"])

        return ActionResult.success(
            data={
                "csv": csv_str,
                "filename": f"billing-export-{params.period}.csv",
                "count": count,
            },
            summary=f"Exported {count} transactions ({params.period})",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to export: {e}")
