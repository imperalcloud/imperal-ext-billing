"""Billing · SDL return models (additive, non-breaking).

These model the return shape of clearly-typed read functions as `sdl.Entity`
subclasses so the platform can read them via the Structured Data Layer. The
ADDITIVE contract: every existing data key is kept verbatim (panels / dashboard
consumers rely on them); the canonical `id`/`title`/`kind` are derived from the
existing fields via a mode="before" validator, so existing construction calls
keep working unchanged.
"""
from __future__ import annotations

from imperal_sdk import sdl
from pydantic import model_validator


class WalletBalance(sdl.Entity):
    """Single wallet/balance entity — the return shape of `get_balance`.

    Existing keys kept verbatim: balance, plan, cap. Token balance is an integer
    token count (NOT a money.amount currency value), so the Balanced money facet
    is intentionally NOT mixed in — that would re-type `balance` to Decimal and
    break int-reading panels.
    """
    # --- existing fields kept verbatim (dashboard/skeleton rely on them) ---
    balance: int | None = None
    plan: str | None = None
    cap: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "wallet")
            data.setdefault(
                "title",
                f"{data.get('plan')} plan" if data.get("plan") else "Wallet",
            )
        return data


class PlanSubscription(sdl.Entity):
    """Single subscription entity — the return shape of `get_plan`.

    Existing keys kept verbatim: plan, status, started_at, expires_at. The
    Subscribable money facet is intentionally NOT mixed in: its
    `subscription_status` is a strict Literal and its period fields are strict
    `datetime`, either of which could reject the live billing values and break
    construction. The free-form Entity `status` carries the plan status instead.
    """
    # --- existing fields kept verbatim ---
    plan: str | None = None
    started_at: str | None = None
    expires_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("plan") or "subscription")
            data.setdefault("title", f"{data.get('plan')} plan" if data.get("plan") else "Subscription")
            # The existing `status` key maps directly onto Entity.status
            # (same name, already free-form str|None) — no rename, no new key.
        return data
