"""Functional tests for bulk payment-method removal.

Cards are the one genuinely plural billing object, and removing the wrong
one is not something a user can undo from chat. These tests pin:

  * every named card is removed — not just the first;
  * humans name cards by last4 or "visa 4242", not by Stripe pm_id, so
    those forms must resolve;
  * an ambiguous term (two cards ending 4242) is REPORTED, never guessed;
  * duplicates collapse on the resolved pm_id;
  * a server refusal on one card does not hide the cards that did go;
  * the batch refuses upfront to clear every card while a paid plan is
    active, instead of firing N doomed calls.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk as hb  # noqa: E402

from conftest import StubBilling, make_ctx  # noqa: E402

from imperal_sdk.types.models import PaymentMethod  # noqa: E402
from imperal_sdk.billing.client import SubscriptionInfo  # noqa: E402


def _card(pm_id, brand, last4, is_default=False):
    return PaymentMethod(
        id=pm_id, brand=brand, last4=last4,
        exp_month=12, exp_year=2030, is_default=is_default, type="card",
    )


VISA = _card("pm_visa1", "visa", "4242", is_default=True)
MC = _card("pm_mc1", "mastercard", "5555")
AMEX = _card("pm_amex1", "amex", "9999")


def _free_plan(billing):
    """Default fixture is an ACTIVE PRO plan; most tests want no plan guard."""
    billing.subscription = SubscriptionInfo(
        plan="free", status="inactive", started_at="", expires_at="",
    )
    return billing


def _removals(billing):
    return [c[1] for c in billing.calls if c[0] == "remove_payment_method"]


# ─── the basic promise ────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_removes_every_named_card_in_one_call(billing):
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_visa1", "pm_mc1"]),
    )

    assert res.status == "success"
    assert _removals(billing) == ["pm_visa1", "pm_mc1"], (
        "both named cards must be removed in the one call"
    )
    assert res.data["success_count"] == 2


@pytest.mark.asyncio
async def test_a_card_can_be_named_by_its_last_four(billing):
    """Nobody remembers a Stripe pm_id — last4 is how humans refer to cards."""
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["5555"]),
    )

    assert res.status == "success"
    assert _removals(billing) == ["pm_mc1"], (
        f"'5555' must resolve to the mastercard, got {_removals(billing)}"
    )


@pytest.mark.asyncio
async def test_a_card_can_be_named_by_brand_and_last_four(billing):
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["visa 4242"]),
    )

    assert res.status == "success"
    assert _removals(billing) == ["pm_visa1"]


# ─── ambiguity must never be guessed ──────────────────────────────────── #

@pytest.mark.asyncio
async def test_an_ambiguous_last_four_is_reported_not_guessed(billing):
    """Two cards ending 4242: removing the wrong one is unrecoverable."""
    twin = _card("pm_visa2", "visa", "4242")
    billing.cards = [VISA, twin, MC]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["4242"]),
    )

    assert not _removals(billing), (
        "an ambiguous card reference must remove NOTHING"
    )
    blob = " ".join(res.data.get("failed", [])) + (res.summary or "") + (res.error or "")
    assert "ambiguous" in blob.lower(), blob


# ─── de-duplication ───────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_naming_one_card_twice_removes_it_once(billing):
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(
            pm_ids=["pm_visa1", "4242", "visa 4242"],
        ),
    )

    assert _removals(billing) == ["pm_visa1"], (
        f"one card named three ways must be removed ONCE, got {_removals(billing)}"
    )
    assert res.data["success_count"] == 1


# ─── partial success ──────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_one_unknown_card_does_not_cancel_the_rest(billing):
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_mc1", "0000"]),
    )

    assert res.status == "success", "partial success stays a success result"
    assert _removals(billing) == ["pm_mc1"], (
        "the real card must still be removed despite the bad reference"
    )
    assert res.data["success_count"] == 1
    assert res.data["failure_count"] == 1
    assert any("0000" in f for f in res.data["failed"]), res.data["failed"]


@pytest.mark.asyncio
async def test_a_server_refusal_is_reported_per_card(billing):
    """The server legitimately refuses some removals; say which, and go on."""
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    billing.raise_on["remove_payment_method"] = RuntimeError("card is in use")
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_mc1"]),
    )

    assert res.status == "error", (
        "when NOTHING could be removed there is no partial success to report"
    )
    assert "in use" in (res.error or ""), res.error


@pytest.mark.asyncio
async def test_a_refusal_on_one_card_does_not_hide_the_one_that_went(billing):
    """The real partial case: one card gone, one refused — report BOTH."""
    billing.cards = [VISA, MC, AMEX]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    failing = {"pm_mc1"}
    original = billing.remove_payment_method

    async def _selective(pm_id, user=None):
        if pm_id in failing:
            billing.calls.append(("remove_payment_method", pm_id))
            raise RuntimeError("card is in use")
        return await original(pm_id, user=user)

    billing.remove_payment_method = _selective

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_amex1", "pm_mc1"]),
    )

    assert res.status == "success", (
        "the amex WAS removed — that must not be hidden behind an error"
    )
    assert res.data["success_count"] == 1
    assert res.data["failure_count"] == 1
    assert any("in use" in f for f in res.data["failed"]), res.data["failed"]


# ─── the money-safety guard ───────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_refuses_to_clear_every_card_while_a_paid_plan_is_active(billing):
    """Renewals would fail. Refuse ONCE with a reason, not N doomed calls."""
    billing.cards = [VISA, MC]
    # default fixture subscription is an ACTIVE PRO plan
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_visa1", "pm_mc1"]),
    )

    assert res.status == "error"
    assert not _removals(billing), (
        "nothing may be removed when the batch would leave a paid plan cardless"
    )
    assert "pro" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_clearing_every_card_is_allowed_without_a_paid_plan(billing):
    """No active paid plan means no renewal to protect — let it through."""
    billing.cards = [VISA, MC]
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["pm_visa1", "pm_mc1"]),
    )

    assert res.status == "success"
    assert _removals(billing) == ["pm_visa1", "pm_mc1"]


# ─── empty / edge ─────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_no_saved_cards_is_a_clear_error(billing):
    billing.cards = []
    _free_plan(billing)
    ctx = make_ctx(billing=billing)

    res = await hb.fn_bulk_remove_payment_methods(
        ctx, hb.BulkPaymentMethodsParams(pm_ids=["4242"]),
    )

    assert res.status == "error"
    assert not _removals(billing)
