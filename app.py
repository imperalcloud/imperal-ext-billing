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

ext = Extension("billing", version="2.1.2", capabilities=["billing:read"],
    display_name='Billing',
    description=(
        'Billing dashboard — check token balance, review spending history, manage subscription plan, view payment transactions, export usage reports for accounting.'
    ),
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(
    ext=ext,
    tool_name="tool_billing_chat",
    description=(
        "Billing assistant — check token balance, view spending history, "
        "subscription plans, and export transactions. All actions cost 0 tokens."
    ),
    system_prompt=(
        "Billing module — manage wallet, token balance, plans, and spending analytics.\n\n"
        "The user can see their billing dashboard with:\n"
        "- Left panel: wallet balance, plan, quick stats, extension breakdown\n"
        "- Right panel: analytics tabs (Overview, Transactions, Pricing), "
        "account summary, transaction details, extension stats\n\n"
        "Available actions:\n"
        "- export_csv: Export transaction history as CSV\n"
        "- get_balance: Check current balance\n"
        "- get_plan: Check subscription details\n"
        "- spending_report: Detailed spending breakdown\n\n"
        "Coming soon: Top up tokens, Change/upgrade plan."
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
    """Get all extension pricing + model rates from Redis."""
    r = _get_redis()
    ext_keys = await r.keys("imperal:billing:pricing:*")
    extensions = []
    for key in sorted(ext_keys):
        app_id = key.split(":")[-1]
        data = await r.hgetall(key)
        mode = data.get("mode", "category")
        extensions.append({
            "app_id": app_id,
            "mode": mode,
            "read": int(data.get("price_read", 1)) if mode != "free" else 0,
            "write": int(data.get("price_write", 5)) if mode != "free" else 0,
            "destructive": int(data.get("price_destructive", 10)) if mode != "free" else 0,
        })

    model_rates = []
    raw = await r.hgetall("imperal:billing:model_rates")
    for model_name, val in sorted(raw.items()):
        try:
            info = json.loads(val)
            model_rates.append({
                "model": model_name,
                "tier": info.get("tier", "economy"),
                "platform_fee": info.get("fee", 2),
            })
        except (json.JSONDecodeError, TypeError):
            pass

    return {"extensions": extensions, "model_rates": model_rates}



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
