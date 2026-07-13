"""Billing · Shared state, extension setup, and data helpers."""
from __future__ import annotations

import json
import logging
import os

import redis.asyncio as aioredis

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult

log = logging.getLogger("billing")


# ─── Extension ────────────────────────────────────────────────────────── #

ext = Extension("billing", version="2.7.1", capabilities=["billing:read", "billing:write"],
    display_name='Billing',
    description=(
        'Billing dashboard — check credit balance, review spending history, manage subscription plan, view payment transactions, export usage reports for accounting.'
    ),
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(
    ext,
    "tool_billing_chat",
    description=(
        "Billing assistant — check credit balance, view spending history, "
        "subscription plans, and export transactions. All actions cost 0 credits."
    ),
    system_prompt=(
        "Billing module — the user's account, subscription, saved cards, "
        "credit balance, payment history, and spending analytics.\n\n"
        "You can show the user's plan, balance, saved cards, and payment "
        "history; upgrade or downgrade their plan; and remove a saved card or "
        "set a different card as the default.\n\n"
        "Money and destructive actions (upgrade_plan, downgrade_plan, "
        "set_default_payment_method, remove_payment_method) require the user to "
        "confirm — the system handles the confirmation prompt automatically, so "
        "do not invent your own confirmation step.\n\n"
        "Read tools (no confirmation): get_balance, get_plan, "
        "list_payment_methods, list_payments, spending_report, topup_status, "
        "export_csv.\n\n"
        "Adding a card and buying credits are done in the billing panel."
    ),
)


# ─── Health Check ─────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    return {"status": "ok", "version": ext.version}


@ext.on_install
async def on_install(ctx):
    uid = ctx.user.imperal_id if ctx and hasattr(ctx, "user") and ctx.user else "system"
    log.info(f"billing installed for user {uid}")


# ─── Context Helpers ──────────────────────────────────────────────────── #

def _user_id(ctx) -> str:
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


# ─── Redis Client ─────────────────────────────────────────────────────── #

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "104.224.88.155"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASS"),
            db=0, decode_responses=True,
        )
    return _redis


# ─── Wallet Data (Redis) ─────────────────────────────────────────────── #

PLAN_FEATURES = {
    "micro":      {"tokens": 500,     "extensions": 2,    "models": ["economy"]},
    "starter":    {"tokens": 15_000,  "extensions": 5,    "models": ["economy", "standard"]},
    "pro":        {"tokens": 50_000,  "extensions": 10,   "models": ["economy", "standard", "premium"]},
    "business":   {"tokens": 200_000, "extensions": 25,   "models": ["economy", "standard", "premium"]},
    "enterprise": {"tokens": None,    "extensions": None, "models": ["economy", "standard", "premium"]},
}


async def get_wallet(ctx) -> dict:
    """Get balance, plan, cap from Redis + SDK."""
    try:
        info = await ctx.billing.get_balance()
        balance, plan, cap = info.balance, info.plan, info.cap
    except Exception:
        balance, plan, cap = 0, "unknown", 0
    pct = round(balance / cap * 100) if cap > 0 else 0
    features = PLAN_FEATURES.get(plan, PLAN_FEATURES["micro"])
    return {
        "balance": balance, "plan": plan, "cap": cap,
        "pct": pct, "features": features,
    }


async def get_pricing_config() -> dict:
    """Live extension pricing (the kernel resolver's own source) + platform fee per tier.

    Source of truth = the per-extension hashes ``imperal:billing:pricing:{app_id}``
    written by the gateway on deploy (``mode`` + a per-function price map) and read by
    the kernel for every billed action. We surface the REAL data: the per-function
    base prices and the platform fee per model tier (Imperal's LLM-resale markup) —
    NOT the legacy ``price_read/write/destructive`` fields, which nothing writes
    anymore (they used to render a meaningless hardcoded 1/5/10 fallback).
    """
    r = _get_redis()
    ext_keys = await r.keys("imperal:billing:pricing:*")
    extensions = []
    for key in sorted(ext_keys):
        app_id = key.split(":")[-1]
        data = await r.hgetall(key)
        mode = data.get("mode", "category")

        functions: dict[str, int] = {}
        raw_fn = data.get("functions")
        if raw_fn:
            try:
                functions = {str(k): int(v) for k, v in json.loads(raw_fn).items()}
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                functions = {}

        prices = sorted(functions.values())
        if mode == "free":
            price_range = "free"
        elif prices:
            lo, hi = prices[0], prices[-1]
            price_range = str(lo) if lo == hi else f"{lo}–{hi}"
        else:
            # per_function with no map → kernel falls back to CATEGORY_DEFAULTS (1/5/10)
            price_range = "default 1/5/10"

        extensions.append({
            "app_id": app_id,
            "mode": mode,
            "functions": functions,
            "fn_count": len(functions),
            "price_range": price_range,
        })

    # Real display names from the canonical source (developer_apps — same as marketplace);
    # fall back to a humanized app_id for system apps not in the table.
    try:
        import queries
        names = await queries.get_app_display_names()
    except Exception:
        names = {}
    for e in extensions:
        e["name"] = names.get(e["app_id"]) or e["app_id"].replace("-", " ").replace("_", " ").title()

    platform_fees = await get_platform_fees()
    return {"extensions": extensions, "platform_fees": platform_fees}


async def get_platform_fees() -> dict:
    """Per-tier platform fee (Imperal's LLM-resale markup), live from the gateway
    ``/v1/internal/billing/platform-fees`` (unified_config = single source of truth,
    same endpoint the kernel reads). Falls back to the kernel defaults on any miss."""
    fallback = {"economy": 60, "standard": 250, "premium": 2200}
    try:
        import httpx
        gw = os.environ.get("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
        token = os.environ.get("AUTH_SERVICE_TOKEN", "")
        async with httpx.AsyncClient(base_url=gw, timeout=5) as c:
            resp = await c.get("/v1/internal/billing/platform-fees",
                               headers={"X-Service-Token": token})
            if resp.status_code == 200:
                data = resp.json() or {}
                fees = {t: int(data[t]) for t in ("economy", "standard", "premium")
                        if isinstance(data.get(t), (int, float))}
                if fees:
                    return {**fallback, **fees}
    except Exception:
        pass
    return fallback



# ─── Timezone Helper ──────────────────────────────────────────────────── #

_tz_cache: dict[str, str] = {}


async def get_user_timezone(ctx) -> str:
    """Get user's timezone from Auth GW profile. Cached per session."""
    uid = _user_id(ctx)
    if uid in _tz_cache:
        return _tz_cache[uid]
    try:
        import httpx
        gw = os.environ.get("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
        token = os.environ.get("AUTH_SERVICE_TOKEN", "")
        async with httpx.AsyncClient(base_url=gw, timeout=5) as c:
            r = await c.get(f"/v1/users/{uid}",
                            headers={"X-Service-Token": token})
            if r.status_code == 200:
                attrs = r.json().get("attributes") or {}
                tz = attrs.get("timezone", "UTC")
                _tz_cache[uid] = tz
                return tz
    except Exception:
        pass
    _tz_cache[uid] = "UTC"
    return "UTC"


def format_time(utc_str: str, tz_name: str = "UTC") -> str:
    """Convert UTC datetime string to user's timezone. Returns 'Apr 15, 14:32'."""
    from datetime import datetime, timezone
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        if "T" in utc_str:
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        return local.strftime("%b %d, %H:%M")
    except Exception:
        return utc_str[:16] if len(utc_str) > 16 else utc_str


def format_time_full(utc_str: str, tz_name: str = "UTC") -> str:
    """Full datetime in user timezone: 'Apr 15, 2026 14:32:05'."""
    from datetime import datetime, timezone
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        if "T" in utc_str:
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        return local.strftime("%b %d, %Y %H:%M:%S")
    except Exception:
        return utc_str[:19] if len(utc_str) > 19 else utc_str


def humanize_tool(tool_name: str, app_id: str = "") -> str:
    """Convert tool_name to human-readable: tool_notes_chat → 'Notes Chat'."""
    if not tool_name:
        return app_id.replace("-", " ").replace("_", " ").title() if app_id else "—"
    name = tool_name
    for prefix in ("tool_", "skeleton_", "__panel__"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").replace("-", " ").title()


def humanize_reason(reason: str, amount: int = 0) -> str:
    """Convert reason code to friendly label."""
    labels = {
        "action": "Used extension",
        "topup": "Top-up",
        "commission": "Platform fee",
        "adjustment": "Adjustment",
        "refund": "Refund",
        "plan_credit": "Plan credit",
        "bonus": "Bonus",
    }
    return labels.get(reason, reason.replace("_", " ").title())
