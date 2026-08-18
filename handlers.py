"""Billing · Chat function handlers."""
from __future__ import annotations

import csv
import io

from pydantic import BaseModel, Field

from app import chat, ActionResult, _user_id, get_user_usage
from models import (
    WalletBalance, PlanSubscription, MeterUsage, SpendingReport, CsvExport,
)
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
    description="Get current credit balance, plan name, and cap.",
    data_model=WalletBalance,
)
async def fn_get_balance(ctx, params: EmptyParams) -> ActionResult:
    try:
        info = await ctx.billing.get_balance()
        return ActionResult.success(
            data=WalletBalance(
                balance=info.balance,
                plan=info.plan,
                cap=info.cap,
            ),
            summary=(
                f"Balance: {info.balance:,} credits on the {info.plan} plan "
                f"(cap: {info.cap:,})"
            ),
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch balance: {e}")


@chat.function(
    "get_plan",
    action_type="read",
    description="Get subscription details: plan, status, billing period.",
    data_model=PlanSubscription,
)
async def fn_get_plan(ctx, params: EmptyParams) -> ActionResult:
    try:
        sub = await ctx.billing.get_subscription()
        return ActionResult.success(
            data=PlanSubscription(
                plan=sub.plan,
                status=sub.status,
                started_at=sub.started_at,
                expires_at=sub.expires_at,
            ),
            summary=f"Plan: {sub.plan} ({sub.status})",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch subscription: {e}")


@chat.function(
    "spending_report",
    action_type="read",
    description="Show usage and spending breakdown by meter.",
    data_model=SpendingReport,
)
async def fn_spending_report(ctx, params: EmptyParams) -> ActionResult:
    try:
        # Usage comes from the gateway's on-demand internal endpoint, NOT from
        # ctx.billing.check_limits(): with a service token the SDK resolves
        # check_limits() to /internal/user-limits/{uid}, which answers
        # {plan, limits} with no usage at all -- which is why this report read
        # "No usage recorded" while metering was perfectly healthy. That
        # endpoint is on the kernel's per-turn hot path and is deliberately
        # kept small, so usage lives on its own endpoint instead.
        plan = ""
        usage: dict = {}
        plan_limits: dict = {}
        exceeded: list = []

        report = await get_user_usage(_user_id(ctx))
        if report:
            plan = report.get("plan") or ""
            usage = report.get("usage") or {}
            plan_limits = report.get("limits") or {}
            exceeded = report.get("exceeded") or []
        else:
            # Degrade to the SDK path rather than failing the read outright.
            limits = await ctx.billing.check_limits()
            plan = limits.plan
            usage = limits.usage or {}
            plan_limits = limits.limits or {}
            exceeded = limits.exceeded or []

        # Biggest spend first — a 343-meter report is only useful if the
        # meaningful rows are at the top.
        ordered = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)

        usage_lines = [f"  {meter}: {count:,}" for meter, count in ordered]
        usage_text = "\n".join(usage_lines) if usage_lines else "  No usage recorded"
        exceeded_text = f" | Exceeded: {', '.join(exceeded)}" if exceeded else ""
        # SDL: one MeterUsage item per meter (entity-list), plan/exceeded as
        # list-level scalars. NO legacy {usage{},limits{}} wrapper.
        items = [
            {
                "meter": meter,
                "count": count,
                "limit": plan_limits.get(meter),
                "exceeded": meter in exceeded,
            }
            for meter, count in ordered
        ]
        return ActionResult.success(
            data=SpendingReport(
                items=[MeterUsage(**it) for it in items],
                total=len(items),
                plan=plan,
                exceeded=exceeded,
            ),
            summary=f"Plan: {plan}{exceeded_text}\nUsage:\n{usage_text}",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to fetch spending report: {e}")


# ─── New: Export CSV ──────────────────────────────────────────────────── #

@chat.function(
    "export_csv",
    action_type="read",
    description="Export transaction history as CSV.",
    data_model=CsvExport,
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
            data=CsvExport(
                csv=csv_str,
                filename=f"billing-export-{params.period}.csv",
                count=count,
            ),
            summary=f"Exported {count} transactions ({params.period})",
        )
    except Exception as e:
        return ActionResult.error(f"Failed to export: {e}")
