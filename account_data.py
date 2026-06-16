"""Account/billing data helpers for Layer 2d panels + handlers.

Pure, side-effect-light functions: token pricing, degraded-sentinel detection,
billing-profile read, and the plan catalog fetch (public gateway endpoint —
the SDK has no list_plans())."""
import os
import logging

log = logging.getLogger("ext.billing.account_data")

TOKEN_RATE_CENTS_PER_1000 = 100  # $1 / 1000 tokens (editorial; gateway is authoritative on charge)
_PROFILE_KEYS = ("name", "company", "vat", "country")


def price_cents_for_tokens(tokens: int) -> int:
    """Editorial top-up price preview ($1 / 1000 tokens). The gateway recomputes
    server-side on the actual charge — this is only for UI display."""
    return int(round((int(tokens) / 1000) * TOKEN_RATE_CENTS_PER_1000))


def balance_unavailable(balance) -> bool:
    """True when get_balance() returned its safe-degraded sentinel."""
    return getattr(balance, "balance", 0) == 0 and getattr(balance, "plan", "") == "unknown"


def subscription_unavailable(sub) -> bool:
    """True when get_subscription() returned its safe-degraded sentinel."""
    return getattr(sub, "status", "") == "unavailable" or getattr(sub, "plan", "") == "unknown"


def read_billing_profile(ctx) -> dict:
    """Read the billing/VAT profile from ctx.user.attributes.billing (read-only in Phase 1)."""
    attrs = getattr(ctx.user, "attributes", None) or {}
    billing = attrs.get("billing") if isinstance(attrs, dict) else {}
    billing = billing or {}
    return {k: (billing.get(k) or "") for k in _PROFILE_KEYS}


async def fetch_plan_catalog(ctx) -> list[dict]:
    """Fetch the public plan catalog from the gateway. Returns [] on any failure
    (panel shows current plan only). Source: GET {GATEWAY}/v1/billing/plans."""
    import httpx
    base = os.getenv("IMPERAL_GATEWAY_URL", "https://auth.imperal.io").rstrip("/")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/v1/billing/plans", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("plans", [])
    except Exception as e:
        log.warning("plan catalog fetch failed: %s", e)
        return []
