"""Billing · bulk payment-method operations.

Most billing objects are singular by nature — one subscription, one plan,
one balance — so "bulk" would be meaningless for them. Saved cards are the
exception: people accumulate expired and duplicate cards and then want to
clear several at once ("remove the two old visas", "drop everything except
the amex").

Only ONE bulk handler therefore exists here, deliberately:

  * bulk_remove_payment_methods — remove several saved cards in one call.

Shared contract with the other extensions' bulk tools:

  * cards resolve FIRST, and by how a human actually refers to them — the
    Stripe pm_id, the last four digits, or "visa 4242". Nobody remembers a
    pm_id, so a bulk tool that only accepted them would go unused;
  * duplicates collapse on the RESOLVED pm_id, so naming one card twice
    attempts it once;
  * partial success is reported as SUCCESS with per-card detail, because the
    server legitimately refuses some removals (the last card on an active
    paid plan) and that refusal must not hide the cards that DID go;
  * the real single-card path does the work, so the server-side guard stays
    authoritative — this module never decides on its own that a removal is
    safe.

Note on the "remove them all" case: the server blocks removing the only card
on an active paid plan. Rather than fire N doomed calls and report a wall of
identical failures, the handler refuses upfront when the batch would clear
every saved card while a paid plan is active, and says why.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import chat

log = logging.getLogger("billing.handlers_bulk")

_MAX_CARDS = 25


# ─── Models ───────────────────────────────────────────────────────────── #

class BulkPaymentMethodsParams(BaseModel):
    """Target SEVERAL saved cards at once."""
    pm_ids: list[str] = Field(
        description=(
            "The cards to remove. Each entry may be a Stripe payment-method "
            "id, the card's last four digits ('4242'), or brand + last four "
            "('visa 4242'). Pass EVERY card the user named in ONE call; do "
            "not loop the single-card tool."
        ),
        min_length=1,
        max_length=_MAX_CARDS,
    )


class BulkBillingReceipt(BaseModel):
    """Uniform outcome shape for bulk billing actions."""
    model_config = {"extra": "allow"}

    action: str = ""
    succeeded: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failure_count: int = 0


# ─── Shared plumbing ──────────────────────────────────────────────────── #

def _norm(v: str) -> str:
    return " ".join(str(v or "").strip().lower().split())


def _digits(v: str) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _resolve_cards(raw: list[str], cards: list) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve every term to a real pm_id against the user's saved cards.

    Returns ``(resolved, failures)`` where resolved is ``(term, pm_id)``.

    Matching order: exact pm_id, then exact last4, then a brand+last4 phrase
    ("visa 4242"). An ambiguous term (two cards ending 4242) is reported WITH
    its candidates instead of guessed — removing the wrong card is not
    something the user can undo from chat.
    """
    resolved: list[tuple[str, str]] = []
    failures: list[str] = []
    seen: set[str] = set()

    def _pm(c) -> str:
        return getattr(c, "id", "") or ""

    def _l4(c) -> str:
        return str(getattr(c, "last4", "") or "")

    def _brand(c) -> str:
        return _norm(getattr(c, "brand", "") or "")

    for term in raw:
        t = _norm(term)
        if not t:
            continue

        hit = None
        for c in cards:                                    # 1. exact pm_id
            if _norm(_pm(c)) == t:
                hit = _pm(c)
                break

        if hit is None:                                    # 2. last4
            d = _digits(term)
            if len(d) == 4:
                cands = [c for c in cards if _l4(c) == d]
                uniq = {_pm(c) for c in cands}
                if len(uniq) == 1:
                    hit = next(iter(uniq))
                elif uniq:
                    # disambiguate by brand if the term carries one
                    brands = [c for c in cands if _brand(c) and _brand(c) in t]
                    ubrand = {_pm(c) for c in brands}
                    if len(ubrand) == 1:
                        hit = next(iter(ubrand))
                    else:
                        listing = ", ".join(
                            f"{_brand(c).title() or 'card'} ····{_l4(c)}"
                            for c in cands[:4]
                        )
                        failures.append(f"{term} — ambiguous ({listing})")
                        continue

        if hit is None:
            failures.append(f"{term} — no saved card matches")
            continue
        if hit in seen:
            continue
        seen.add(hit)
        resolved.append((term, hit))

    return resolved, failures


def _label(cards: list, pm_id: str) -> str:
    """Human label for a pm_id ('Visa ····4242') for honest reporting."""
    for c in cards:
        if getattr(c, "id", "") == pm_id:
            brand = str(getattr(c, "brand", "") or "card").title()
            return f"{brand} ····{getattr(c, 'last4', '') or '????'}"
    return pm_id


def _receipt(action: str, ok: list[str], failed: list[str], **extra) -> ActionResult:
    """One uniform shape + honest summary for every bulk billing action."""
    data = {
        "action": action,
        "succeeded": ok,
        "failed": failed,
        "total": len(ok) + len(failed),
        "success_count": len(ok),
        "failure_count": len(failed),
        **extra,
    }
    if ok and failed:
        summary = (
            f"{action} {len(ok)} card(s); {len(failed)} could not be done: "
            + "; ".join(failed[:4])
        )
    elif ok:
        summary = f"{action} {len(ok)} card(s): " + ", ".join(ok)
    else:
        summary = f"Nothing was removed. {'; '.join(failed[:4])}"

    # Partial success stays a SUCCESS: work that completed must never be
    # hidden behind an error. Only a total wipe-out is an error.
    if not ok:
        return ActionResult.error(summary)
    return ActionResult.success(data=data, summary=summary,
                                refresh_panels=["sidebar", "dashboard"])


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "bulk_remove_payment_methods",
    action_type="destructive",
    effects=["delete:payment_method"],
    data_model=BulkBillingReceipt,
    description=(
        "Remove SEVERAL saved cards in one call. Each entry may be a "
        "payment-method id, the last four digits, or 'visa 4242'. Use "
        "whenever the user names more than one card ('remove the two old "
        "visas') instead of calling remove_payment_method repeatedly. The "
        "server still blocks removing the only card on an active paid plan."
    ),
)
async def fn_bulk_remove_payment_methods(
    ctx, params: BulkPaymentMethodsParams,
) -> ActionResult:
    """Remove many saved cards, reporting per-card outcomes."""
    try:
        cards = await ctx.billing.list_payment_methods()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("bulk_remove_payment_methods: card list failed: %s", exc)
        return ActionResult.error(
            f"Could not load your saved cards ({type(exc).__name__}); "
            "nothing was removed."
        )

    cards = list(cards or [])
    if not cards:
        return ActionResult.error("You have no saved cards to remove.")

    targets, failures = _resolve_cards(params.pm_ids, cards)

    # Refuse upfront rather than firing N doomed calls: the server blocks
    # removing the last card on an active paid plan, and a wall of identical
    # failures is a worse answer than one clear sentence.
    if targets and len(targets) >= len(cards):
        try:
            sub = await ctx.billing.get_subscription()
            plan = str(getattr(sub, "plan", "") or "").lower()
            status = str(getattr(sub, "status", "") or "").lower()
        except Exception:                                     # noqa: BLE001
            plan, status = "", ""
        if status == "active" and plan not in ("", "free"):
            return ActionResult.error(
                f"That would remove every saved card while your {plan} plan "
                "is active — renewals would fail, so the server blocks it. "
                "Keep at least one card, or cancel the plan first."
            )

    ok: list[str] = []
    for term, pm_id in targets:
        label = _label(cards, pm_id)
        try:
            removed = await ctx.billing.remove_payment_method(pm_id)
            if removed:
                ok.append(label)
            else:
                failures.append(f"{label} — not removed")
        except Exception as exc:                              # noqa: BLE001
            log.warning("bulk remove %s: %s", pm_id, exc)
            failures.append(f"{label} — {str(exc)[:120]}")

    return _receipt("Removed", ok, failures)
