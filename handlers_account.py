"""Webbee full-control parity tools (Layer 2d Phase 2). Reads (no confirm):
list_plans, get_auto_topup, open_billing_portal. Guarded (confirm-handshake):
cancel_subscription, set_auto_topup, update_billing_profile. All reuse ctx.billing
(SDK methods added in the portal-prereq plan Part A+D); NO HTTP / NO parallel confirm."""
import logging
import httpx
from pydantic import BaseModel, Field

from app import chat, ActionResult
from handlers_payment import EmptyParams
from handlers_money import _detail  # shared gateway-error message extractor (Rule 9: no copy-paste)
from models_account import (
    PlanList, AutoTopupSettingsEntity, PortalLink,
    CancelOutcome, ResumeOutcome, BillingProfileUpdated,
)

log = logging.getLogger("ext.billing.account")


@chat.function("list_plans", action_type="read",
               description="List the subscription plans the user can choose from, with prices and what each includes.",
               data_model=PlanList)
async def fn_list_plans(ctx, params: EmptyParams) -> ActionResult:
    plans = await ctx.billing.list_plans()  # list[PlanInfo]; safe-degrades to []
    items = [{"id": p.id, "name": p.name, "price": p.price, "interval": p.interval,
              "features": p.features, "limits": p.limits} for p in plans]
    return ActionResult.success(
        data=PlanList(items=items, total=len(items)),
        summary=(", ".join(f"{p.name} (${p.price:g}/{p.interval})" for p in plans)
                 if plans else "Plan catalog is unavailable right now."),
    )


@chat.function("get_auto_topup", action_type="read",
               description="Show the user's automatic top-up settings (whether it is on, the low-balance threshold, and the recharge amount).",
               data_model=AutoTopupSettingsEntity)
async def fn_get_auto_topup(ctx, params: EmptyParams) -> ActionResult:
    s = await ctx.billing.get_auto_topup()  # AutoTopupSettings; safe-degrades to disabled defaults
    return ActionResult.success(
        data=AutoTopupSettingsEntity(enabled=s.enabled, threshold_pct=s.threshold_pct,
                                     recharge_tokens=s.recharge_tokens, recharge_cents=s.recharge_cents,
                                     payment_method_id=s.payment_method_id),
        summary=(f"Auto top-up is ON: add {s.recharge_tokens:,} tokens when balance drops below {s.threshold_pct}%."
                 if s.enabled else "Auto top-up is off."),
    )


@chat.function("open_billing_portal", action_type="read",
               description="Get a secure link to the Stripe billing portal where the user can add/remove cards, set a default, and download invoices.",
               data_model=PortalLink)
async def fn_open_billing_portal(ctx, params: EmptyParams) -> ActionResult:
    try:
        url = await ctx.billing.create_billing_portal_session()
    except Exception as e:
        return ActionResult.error(f"Could not open the billing portal: {e}")
    return ActionResult.success(data=PortalLink(url=url),
                                summary=f"Open your billing portal to manage cards & invoices: {url}")


class AutoTopupParams(BaseModel):
    enabled: bool = Field(description="Turn auto top-up on or off.")
    threshold_pct: int = Field(default=10, ge=1, le=50, description="Recharge when balance drops below this percent of cap.")
    recharge_tokens: int = Field(default=20000, gt=0, description="How many tokens to add on each recharge.")
    payment_method_id: str = Field(default="", description="Card to charge (optional; defaults to the default card).")


class BillingProfileParams(BaseModel):
    name: str = Field(default="", description="Billing contact name.")
    company: str = Field(default="", description="Company / legal entity name.")
    vat: str = Field(default="", description="VAT / GST number.")
    country: str = Field(default="", description="Billing country (ISO code or name).")


@chat.function("cancel_subscription", action_type="destructive",
               effects=["update:subscription"], event="billing.subscription_cancelled",
               data_model=CancelOutcome,
               description="Cancel the user's paid subscription. It stays active until the end of the current billing period (no further charges). Confirmation gate fires automatically.")
async def fn_cancel_subscription(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await ctx.billing.cancel_subscription()  # dict {status, plan, expires_at, cancel_at_period_end}
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not cancel: {e}")
    plan = r.get("plan")
    eff = r.get("expires_at")
    return ActionResult.success(
        data=CancelOutcome(plan=plan, status="cancel_at_period_end", effective_at=eff),
        summary=(f"Your {plan or 'plan'} plan stays active until {eff or 'the end of the period'}, "
                 "then cancels. No further charges."),
    )


@chat.function("resume_subscription", action_type="write",
               effects=["update:subscription"], event="billing.subscription_resumed",
               data_model=ResumeOutcome,
               description="Undo a scheduled cancellation — keep the subscription active. Confirmation gate fires automatically.")
async def fn_resume_subscription(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await ctx.billing.resume_subscription()  # dict {plan, status, expires_at}
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not resume: {e}")
    return ActionResult.success(
        data=ResumeOutcome(plan=r.get("plan"), status=r.get("status"), expires_at=r.get("expires_at")),
        summary="Your subscription will continue — cancellation undone.",
    )


@chat.function("renew_subscription", action_type="write",
               effects=["update:subscription"], event="billing.subscription_renewed",
               data_model=ResumeOutcome,
               description="Renew an expired subscription for the same plan by charging the saved default card; access is restored immediately. Confirmation gate fires automatically.")
async def fn_renew_subscription(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await ctx.billing.renew_subscription()  # dict {status, plan, expires_at, payment_intent_id}
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))       # 402 add-a-card / 409 not-expired surface verbatim
    except Exception as e:
        return ActionResult.error(f"Could not renew: {e}")
    return ActionResult.success(
        data=ResumeOutcome(plan=r.get("plan"), status=r.get("status"), expires_at=r.get("expires_at")),
        summary=f"Your subscription has been renewed — active until {r.get('expires_at') or 'the next period'}.",
    )


@chat.function("set_auto_topup", action_type="write",
               effects=["update:auto_topup"], event="billing.auto_topup_changed",
               data_model=AutoTopupSettingsEntity,
               description="Turn automatic token top-up on/off and set the low-balance threshold and recharge amount. Confirmation gate fires automatically.")
async def fn_set_auto_topup(ctx, params: AutoTopupParams) -> ActionResult:
    try:
        ok = await ctx.billing.set_auto_topup(enabled=params.enabled, threshold_pct=params.threshold_pct,
                                              recharge_tokens=params.recharge_tokens,
                                              payment_method_id=params.payment_method_id)
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not update auto top-up: {e}")
    return ActionResult.success(
        data=AutoTopupSettingsEntity(enabled=params.enabled, threshold_pct=params.threshold_pct,
                                     recharge_tokens=params.recharge_tokens, payment_method_id=params.payment_method_id),
        summary=("Auto top-up enabled." if params.enabled else "Auto top-up disabled.") if ok else "No change.",
    )


@chat.function("update_billing_profile", action_type="write",
               effects=["update:profile"], event="billing.profile_updated",
               data_model=BillingProfileUpdated,
               description="Update the user's billing/VAT profile (name, company, VAT/GST number, country). Confirmation gate fires automatically.")
async def fn_update_billing_profile(ctx, params: BillingProfileParams) -> ActionResult:
    profile = {"name": params.name, "company": params.company, "vat": params.vat, "country": params.country}
    try:
        ok = await ctx.billing.update_billing_profile(profile)
    except httpx.HTTPStatusError as e:
        return ActionResult.error(_detail(e))
    except Exception as e:
        return ActionResult.error(f"Could not update profile: {e}")
    return ActionResult.success(data=BillingProfileUpdated(**profile),
                                summary="Billing profile updated." if ok else "No change.")
