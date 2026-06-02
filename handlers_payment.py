"""Billing · Payment-related chat functions."""
from __future__ import annotations

from pydantic import BaseModel

from app import chat, ActionResult, _user_id
from models import TopupRecord, TopupStatusResponse, PaymentMethodsSummary


class EmptyParams(BaseModel):
    pass


@chat.function(
    "topup_status",
    action_type="read",
    description="Check status of recent top-up payments.",
    data_model=TopupStatusResponse,
)
async def fn_topup_status(ctx, params: EmptyParams) -> ActionResult:
    try:
        import queries
        uid = _user_id(ctx)
        result = await queries.get_transaction_history(
            uid, limit=5, period="30d", tx_type="credit",
        )
        credits = [t for t in result["transactions"] if t.get("reason") == "topup"]
        if not credits:
            return ActionResult.success(
                data=TopupStatusResponse(items=[], total=0),
                summary="No recent top-up payments found.",
            )

        lines = []
        for c in credits:
            lines.append(f"  +{c['amount']:,} tok — {c['created_at'][:10]}")

        return ActionResult.success(
            data=TopupStatusResponse(
                items=[TopupRecord(**c) for c in credits],
                total=len(credits),
            ),
            summary=f"Recent top-ups:\n" + "\n".join(lines),
        )
    except Exception as e:
        return ActionResult.error(f"Failed: {e}")


@chat.function(
    "list_payment_methods",
    action_type="read",
    description="List saved payment methods (credit cards).",
    data_model=PaymentMethodsSummary,
)
async def fn_list_payment_methods(ctx, params: EmptyParams) -> ActionResult:
    try:
        info = await ctx.billing.get_balance()
        return ActionResult.success(
            data=PaymentMethodsSummary(balance=info.balance, plan=info.plan),
            summary=(
                f"Balance: {info.balance:,} tokens on {info.plan} plan. "
                "Use the Payment Methods section in the billing dashboard to manage cards."
            ),
        )
    except Exception as e:
        return ActionResult.error(f"Failed: {e}")
