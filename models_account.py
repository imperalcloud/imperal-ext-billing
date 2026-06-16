"""SDL return entities for the account-first billing surface (Layer 2d).

Doctrine: REAL sdl.Entity / sdl.EntityList[T] (x-sdl markers, fixed core
id/title/kind) — NO {cards:[dict]} legacy wrappers. Money facets are NOT mixed
in: card exp / amount_cents / token counts are plain int/str and the strict
Subscribable/Invoiced Literal+datetime+Decimal fields would reject live values
(same deliberate decision as models.WalletBalance/PlanSubscription)."""
from typing import Optional
from pydantic import model_validator
from imperal_sdk import sdl


def _fmt_amount(cents) -> str:
    try:
        return f"${int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


class PaymentMethodCard(sdl.Entity):
    """One saved card. Fields mirror SDK PaymentMethod verbatim
    (id/type/brand/last4/exp_month/exp_year/is_default)."""
    brand: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    is_default: Optional[bool] = None
    type: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("id") or "")
            brand = (data.get("brand") or "card").title()
            last4 = data.get("last4") or "????"
            data.setdefault("title", f"{brand} ···· {last4}")
        return data


class PaymentMethodList(sdl.EntityList[PaymentMethodCard]):
    """sdl.EntityList of saved cards (items=[...], total)."""
    pass


class PaymentRecordEntry(sdl.Entity):
    """One payment / invoice row. Fields mirror SDK PaymentRecord verbatim."""
    payment_intent_id: Optional[str] = None
    amount_cents: Optional[int] = None
    currency: Optional[str] = None
    tokens: Optional[int] = None
    type: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    receipt_url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("payment_intent_id") or "")
            kind = (data.get("type") or "payment").title()
            data.setdefault("title", f"{kind} · {_fmt_amount(data.get('amount_cents'))}")
            if data.get("receipt_url"):
                data.setdefault("url", data["receipt_url"])
        return data


class PaymentHistory(sdl.EntityList[PaymentRecordEntry]):
    """sdl.EntityList of payment / invoice rows."""
    pass


class ChangePlanOutcome(sdl.Entity):
    """Result of upgrade_plan / downgrade_plan. Mirrors SDK ChangePlanResult."""
    action: Optional[str] = None
    plan: Optional[str] = None
    succeeded: Optional[bool] = None
    requires_action: Optional[bool] = None
    effective_at: Optional[str] = None
    pending: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("plan") or "")
            action = (data.get("action") or "change").title()
            data.setdefault("title", f"{action} → {data.get('plan') or '?'}")
        return data


class PaymentMethodRemoved(sdl.Entity):
    """Result of remove_payment_method."""
    pm_id: Optional[str] = None
    removed: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("pm_id") or "")
            data.setdefault("title", f"Card {data.get('pm_id') or ''} removed")
        return data


class PaymentMethodDefaultSet(sdl.Entity):
    """Result of set_default_payment_method."""
    pm_id: Optional[str] = None
    is_default: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("pm_id") or "")
            data.setdefault("title", f"Card {data.get('pm_id') or ''} set as default")
        return data


class TokenPurchaseOutcome(sdl.Entity):
    """Result of buy_tokens. Mirrors SDK TopupResult (off-session)."""
    tokens: Optional[int] = None
    succeeded: Optional[bool] = None
    requires_action: Optional[bool] = None
    payment_intent_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "topup")
            data.setdefault("title", f"Top-up {data.get('tokens') or ''} tokens")
        return data


class PlanEntity(sdl.Entity):
    """One available plan (GET /v1/billing/plans). Mirrors PlanResponse(id,name,price,interval,features,limits)."""
    price: Optional[float] = None
    interval: Optional[str] = None
    features: Optional[dict] = None
    limits: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("id") or data.get("name") or "")
            data.setdefault("title", (data.get("name") or data.get("id") or "").title())
        return data


class PlanList(sdl.EntityList[PlanEntity]):
    pass


class AutoTopupSettingsEntity(sdl.Entity):
    """Auto-top-up settings. Mirrors AutoTopUpSettings(enabled,threshold_pct,recharge_tokens,recharge_cents,payment_method_id)."""
    enabled: Optional[bool] = None
    threshold_pct: Optional[int] = None
    recharge_tokens: Optional[int] = None
    recharge_cents: Optional[int] = None
    payment_method_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "auto_topup")
            data.setdefault("title", "Auto top-up " + ("on" if data.get("enabled") else "off"))
        return data


class CancelOutcome(sdl.Entity):
    """Result of cancel_subscription."""
    plan: Optional[str] = None
    status: Optional[str] = None
    effective_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "subscription")
            data.setdefault("title", "Subscription cancellation scheduled")
        return data


class BillingProfileUpdated(sdl.Entity):
    """Result of update_billing_profile."""
    name: Optional[str] = None
    company: Optional[str] = None
    vat: Optional[str] = None
    country: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "billing_profile")
            data.setdefault("title", "Billing profile updated")
        return data


class PortalLink(sdl.Entity):
    """A Stripe Customer Portal link (open_billing_portal)."""
    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "billing_portal")
            data.setdefault("title", "Manage cards & invoices")
            # `url` is a core sdl.Entity field — Webbee surfaces it as the link.
        return data
