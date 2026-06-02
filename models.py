"""Billing · SDL return models (additive, non-breaking).

These model the return shape of clearly-typed read functions as `sdl.Entity`
subclasses so the platform can read them via the Structured Data Layer. The
ADDITIVE contract: every existing data key is kept verbatim (panels / dashboard
consumers rely on them); the canonical `id`/`title`/`kind` are derived from the
existing fields via a mode="before" validator, so existing construction calls
keep working unchanged.
"""
from __future__ import annotations

from typing import Any, Optional

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


# ─── spending_report (list-shaped) ───────────────────────────────────────── #

class MeterUsage(sdl.Entity):
    """A single usage meter row — one item of `spending_report`.

    Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: the field names mirror the REAL
    keys the handler builds per meter from `LimitsResult` (verified vs
    `ctx.billing.check_limits()` -> {plan, usage{meter:count}, limits{meter:n},
    exceeded[meter]}). Each item carries the per-meter facts:
    {meter, count, limit, exceeded}. id = title = meter.
    """
    meter: Optional[str] = None
    count: Optional[Any] = None
    limit: Optional[Any] = None
    exceeded: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("meter") or data.get("id") or ""
            data.setdefault("title", data.get("meter") or "")
            data.setdefault("kind", "meterusage")
        return data


class SpendingReport(sdl.EntityList[MeterUsage]):
    """`spending_report` return shape — a REAL sdl.EntityList[MeterUsage] whose
    items are the per-meter usage rows, PLUS the plan-level scalars carried as
    extra typed fields (EntityList is a pydantic BaseModel — additive allowed).

    The handler returns:
        data={"items": [...meter dicts...], "total": <meter_count>,
              "plan": <str>, "exceeded": [<meter names...>]}
    NO legacy {plan, usage{}, limits{}, exceeded[]} wrapper.
    """
    plan: Optional[str] = None
    exceeded: Optional[list] = None


# ─── export_csv (single artifact) ─────────────────────────────────────────── #

class CsvExport(sdl.Entity):
    """`export_csv` return shape — a single CSV-artifact entity (kind='csvexport').

    Field names mirror the REAL runtime keys verbatim (verified vs
    handlers.fn_export_csv): {csv, filename, count}. id = filename; title =
    filename; the row count is carried as `count`.
    """
    csv: Optional[str] = None
    filename: Optional[str] = None
    count: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("filename") or data.get("id") or "export"
            data.setdefault("title", data.get("filename") or "Billing export")
            data.setdefault("kind", "csvexport")
        return data


# ─── topup_status (list-shaped) ──────────────────────────────────────────── #

class TopupRecord(sdl.Entity):
    """A single top-up payment — one item of `topup_status`.

    Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the REAL
    transaction dict keys (verified vs queries.get_transaction_history rows):
    {event_id, transaction_id, amount, reason, app_id, tool_name, description,
    action_type, created_at}. id = event_id; title = the human top-up label.
    """
    event_id: Optional[Any] = None
    transaction_id: Optional[Any] = None
    amount: Optional[Any] = None
    reason: Optional[str] = None
    app_id: Optional[str] = None
    tool_name: Optional[str] = None
    description: Optional[str] = None
    action_type: Optional[str] = None
    created_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("event_id") or data.get("id") or ""
            _amt = data.get("amount")
            _date = (data.get("created_at") or "")[:10]
            data.setdefault(
                "title",
                f"+{_amt} tok — {_date}" if _amt is not None else "Top-up",
            )
            data.setdefault("kind", "topuprecord")
        return data


class TopupStatusResponse(sdl.EntityList[TopupRecord]):
    """`topup_status` return shape — a REAL sdl.EntityList[TopupRecord] whose
    items are the recent top-up transactions.

    The handler returns:
        data={"items": [...topup dicts...], "total": <count>}
    NO legacy {payments:[dict]} wrapper.
    """
    pass


# ─── list_payment_methods (single summary entity) ────────────────────────── #

class PaymentMethodsSummary(sdl.Entity):
    """`list_payment_methods` return shape — a single summary entity
    (kind='paymentmethods').

    Field names mirror the REAL runtime keys verbatim (verified vs
    handlers_payment.fn_list_payment_methods, which currently returns the wallet
    summary {balance, plan} pending real card storage). Behavior is unchanged —
    this only stamps the SDL canon over the existing keys. id = title =
    'payment_methods'.
    """
    balance: Optional[int] = None
    plan: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "payment_methods")
            data.setdefault("title", "Payment methods")
            data.setdefault("kind", "paymentmethods")
        return data
