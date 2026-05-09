"""Billing · Skeleton tools for AI context (V13 @ext.skeleton decorator)."""
from __future__ import annotations

import logging

from app import ext

log = logging.getLogger("billing")


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton(
    "billing_status",
    description="Background refresh: billing status for AI context.",
)
async def refresh_billing_status(ctx, **kwargs) -> dict:
    try:
        info = await ctx.billing.get_balance()
        alert_level = None
        if info.balance <= 0:
            alert_level = "empty"
        elif info.cap > 0 and info.balance < info.cap * 0.05:
            alert_level = "critical"
        elif info.cap > 0 and info.balance < info.cap * 0.20:
            alert_level = "low"

        return {
            "response": {
                "balance": info.balance,
                "plan": info.plan,
                "cap": info.cap,
                "alert_level": alert_level,
            }
        }
    except Exception as e:
        log.error("Skeleton billing refresh failed: %s", e)
        return {
            "response": {
                "balance": 0,
                "plan": "unknown",
                "cap": 0,
                "alert_level": None,
            }
        }
