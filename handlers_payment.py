"""Billing · Payment-related chat functions."""
from __future__ import annotations

from pydantic import BaseModel

from app import chat, ActionResult, _user_id
from models import TopupRecord, TopupStatusResponse
from models_account import PaymentMethodList, PaymentHistory


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
    description="List the user's saved payment methods (credit/debit cards): brand, last 4 digits, expiry, and which is the default.",
    data_model=PaymentMethodList,
)
async def fn_list_payment_methods(ctx, params: EmptyParams) -> ActionResult:
    cards = await ctx.billing.list_payment_methods()  # list[PaymentMethod]; safe-degrades to []
    items = [{
        "id": c.id, "brand": c.brand, "last4": c.last4,
        "exp_month": c.exp_month, "exp_year": c.exp_year,
        "is_default": c.is_default, "type": c.type,
    } for c in cards]
    default = next((c for c in cards if c.is_default), None)
    summary = (
        f"{len(items)} saved card(s)."
        + (f" Default: {default.brand.title()} ····{default.last4}." if default else "")
    ) if items else "No saved cards yet."
    return ActionResult.success(
        data=PaymentMethodList(items=items, total=len(items)), summary=summary,
    )


@chat.function(
    "list_payments",
    action_type="read",
    description="List the user's payment history (subscriptions and token top-ups): amount, date, status, and a receipt link where available.",
    data_model=PaymentHistory,
)
async def fn_list_payments(ctx, params: EmptyParams) -> ActionResult:
    pays = await ctx.billing.list_payments(limit=50, offset=0)  # list[PaymentRecord]; safe-degrades to []
    items = [{
        "payment_intent_id": p.payment_intent_id, "amount_cents": p.amount_cents,
        "currency": p.currency, "tokens": p.tokens, "status": p.status, "type": p.type,
        "created_at": p.created_at, "completed_at": p.completed_at, "receipt_url": p.receipt_url,
    } for p in pays]
    summary = f"{len(items)} payment(s) on file." if items else "No payments yet."
    return ActionResult.success(
        data=PaymentHistory(items=items, total=len(items), has_more=len(items) >= 50),
        summary=summary,
    )
