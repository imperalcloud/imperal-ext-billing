"""Guarded money/destructive billing chat tools (Layer 2d).

action_type='write'/'destructive' ALONE arms the federal confirm-handshake
(kernel sets ctx._confirmation_actions; SDK guards.py intercepts the first
call). NO confirm logic here. All ctx.billing writes RAISE on gateway 4xx —
each is wrapped and translated to an actionable ActionResult.error."""
import logging
import httpx
from pydantic import BaseModel, Field

from app import chat, ActionResult
from models_account import (
    ChangePlanOutcome, PaymentMethodRemoved, PaymentMethodDefaultSet,
    TokenPurchaseOutcome,
)

log = logging.getLogger("ext.billing.money")


class ChangePlanParams(BaseModel):
    plan_id: str = Field(description="Target plan id (e.g. 'pro', 'business').")
    period: str = Field(default="monthly", description="Billing period: 'monthly' (default).")


class PaymentMethodIdParams(BaseModel):
    pm_id: str = Field(description="Stripe payment-method id of the card to remove.")


class BuyTokensParams(BaseModel):
    tokens: int = Field(description="How many tokens to buy.")


def _detail(e: httpx.HTTPStatusError) -> str:
    try:
        return e.response.json().get("detail") or str(e)
    except Exception:
        return str(e)


async def _change_plan(ctx, plan_id: str, period: str) -> ActionResult:
    try:
        r = await ctx.billing.change_plan(plan_id, period)
    except httpx.HTTPStatusError as e:
        msg = _detail(e)
        log.warning("change_plan %s failed: %s", plan_id, msg)
        return ActionResult.error(msg)
    except Exception as e:
        return ActionResult.error(f"Could not change plan: {e}")
    data = ChangePlanOutcome(action=r.action, plan=r.plan, succeeded=r.succeeded,
                             requires_action=r.requires_action, effective_at=r.effective_at,
                             pending=r.pending)
    if r.requires_action:
        summary = f"Your bank needs to confirm the payment for {r.plan}. Open the billing panel to finish."
    elif r.pending:
        summary = f"Scheduled: you'll move to {r.plan} on {r.effective_at or 'your renewal date'}."
    else:
        summary = f"Done — you're on the {r.plan} plan now."
    return ActionResult.success(data=data, summary=summary)


@chat.function(
    "upgrade_plan",
    action_type="write",
    effects=["update:subscription"],
    event="billing.plan_changed",
    data_model=ChangePlanOutcome,
    description=("Upgrade the user's subscription to a higher plan. The prorated "
                 "difference is charged immediately to the saved default card. "
                 "Confirmation gate fires automatically; the user must confirm first."),
)
async def fn_upgrade_plan(ctx, params: ChangePlanParams) -> ActionResult:
    return await _change_plan(ctx, params.plan_id, params.period)


@chat.function(
    "downgrade_plan",
    action_type="write",
    effects=["update:subscription"],
    event="billing.plan_changed",
    data_model=ChangePlanOutcome,
    description=("Schedule a downgrade to a lower plan, effective at the end of the "
                 "current period (no charge now; the user keeps what they paid for). "
                 "Confirmation gate fires automatically; the user must confirm first."),
)
async def fn_downgrade_plan(ctx, params: ChangePlanParams) -> ActionResult:
    return await _change_plan(ctx, params.plan_id, params.period)


@chat.function(
    "remove_payment_method",
    action_type="destructive",
    effects=["delete:payment_method"],
    id_projection="pm_id",
    event="billing.payment_method_removed",
    data_model=PaymentMethodRemoved,
    description=("Remove a saved card. Blocked by the server if it is the only card "
                 "on an active paid plan. Confirmation gate fires automatically."),
)
async def fn_remove_payment_method(ctx, params: PaymentMethodIdParams) -> ActionResult:
    try:
        ok = await ctx.billing.remove_payment_method(params.pm_id)
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not remove card: {e}")
    return ActionResult.success(data=PaymentMethodRemoved(pm_id=params.pm_id, removed=bool(ok)),
                                summary="Card removed." if ok else "Card not removed.")


@chat.function(
    "set_default_payment_method",
    action_type="write",
    effects=["update:payment_method"],
    id_projection="pm_id",
    event="billing.default_card_changed",
    data_model=PaymentMethodDefaultSet,
    description=("Set a saved card as the default for renewals and charges. "
                 "Confirmation gate fires automatically; the user must confirm first."),
)
async def fn_set_default_payment_method(ctx, params: PaymentMethodIdParams) -> ActionResult:
    try:
        ok = await ctx.billing.set_default_payment_method(params.pm_id)
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not set default card: {e}")
    return ActionResult.success(data=PaymentMethodDefaultSet(pm_id=params.pm_id, is_default=bool(ok)),
                                summary="Default card updated." if ok else "Default card not changed.")


@chat.function(
    "buy_tokens",
    action_type="write",
    effects=["create:topup"],
    event="billing.topup_initiated",
    data_model=TokenPurchaseOutcome,
    description=("Buy more tokens. Charges the prorated price to the saved default card. "
                 "Confirmation gate fires automatically; the user must confirm first."),
)
async def fn_buy_tokens(ctx, params: BuyTokensParams) -> ActionResult:
    import account_data as ad
    price_cents = ad.price_cents_for_tokens(params.tokens)
    try:
        r = await ctx.billing.topup(params.tokens, price_cents, off_session=True)
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))      # 402 "Add a payment method first..." surfaces here
    except Exception as e:
        return ActionResult.error(f"Could not buy tokens: {e}")
    data = TokenPurchaseOutcome(tokens=params.tokens, succeeded=r.succeeded,
                                requires_action=r.requires_action, payment_intent_id=r.payment_intent_id)
    if r.succeeded:
        summary = f"Added {params.tokens:,} tokens to your balance."
    elif r.requires_action:
        summary = "Your bank needs to confirm this payment — open Manage billing to finish."
    else:
        summary = f"Top-up of {params.tokens:,} tokens initiated."
    return ActionResult.success(data=data, summary=summary)
