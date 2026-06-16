# tests/test_handlers_money.py
import pytest, httpx
from conftest import make_ctx, StubBilling
from imperal_sdk.types.models import ChangePlanResult
import handlers_money as hm

class _P:  # generic params stand-in
    def __init__(self, **kw): self.__dict__.update(kw)

def _http_error(status, detail):
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(status, request=req, json={"detail": detail})
    return httpx.HTTPStatusError(detail, request=req, response=resp)

@pytest.mark.asyncio
async def test_upgrade_plan_success():
    b = StubBilling(change_plan_result=ChangePlanResult(action="upgrade", plan="business", succeeded=True))
    res = await hm.fn_upgrade_plan(make_ctx(billing=b), _P(plan_id="business", period="monthly"))
    assert res.status == "success" and res.data.succeeded is True
    assert ("change_plan", "business", "monthly") in b.calls

@pytest.mark.asyncio
async def test_upgrade_plan_no_card_402_is_actionable_error():
    b = StubBilling(raise_on={"change_plan": _http_error(402, "Add a payment method first, then upgrade.")})
    res = await hm.fn_upgrade_plan(make_ctx(billing=b), _P(plan_id="business", period="monthly"))
    assert res.status == "error"
    assert "Add a payment method" in (res.error or res.summary or "")

@pytest.mark.asyncio
async def test_upgrade_plan_free_to_paid_409_routes_to_checkout():
    b = StubBilling(raise_on={"change_plan": _http_error(409, "Start your subscription from checkout.")})
    res = await hm.fn_upgrade_plan(make_ctx(billing=b), _P(plan_id="pro", period="monthly"))
    assert res.status == "error" and "checkout" in (res.error or res.summary or "").lower()

@pytest.mark.asyncio
async def test_change_plan_unified_tool_delegates_to_change_plan():
    # The unified change_plan tool reuses _change_plan; the gateway decides
    # upgrade-vs-downgrade by price. Success path returns a ChangePlanOutcome.
    b = StubBilling(change_plan_result=ChangePlanResult(action="upgrade", plan="business", succeeded=True))
    res = await hm.fn_change_plan(make_ctx(billing=b), _P(plan_id="uuid-business", period="monthly"))
    assert res.status == "success" and res.data.succeeded is True
    assert ("change_plan", "uuid-business", "monthly") in b.calls

@pytest.mark.asyncio
async def test_change_plan_unified_tool_surfaces_error():
    b = StubBilling(raise_on={"change_plan": _http_error(402, "Add a payment method first.")})
    res = await hm.fn_change_plan(make_ctx(billing=b), _P(plan_id="uuid-pro", period="monthly"))
    assert res.status == "error" and "payment method" in (res.error or "").lower()

@pytest.mark.asyncio
async def test_downgrade_plan_pending():
    b = StubBilling(change_plan_result=ChangePlanResult(action="downgrade", plan="pro", pending=True, effective_at="2026-07-15T00:00:00"))
    res = await hm.fn_downgrade_plan(make_ctx(billing=b), _P(plan_id="pro", period="monthly"))
    assert res.status == "success" and res.data.pending is True

@pytest.mark.asyncio
async def test_remove_payment_method_only_card_409():
    b = StubBilling(raise_on={"remove_payment_method": _http_error(409, "Keep a card on file while you have an active paid plan.")})
    res = await hm.fn_remove_payment_method(make_ctx(billing=b), _P(pm_id="pm_1"))
    assert res.status == "error" and "Keep a card" in (res.error or res.summary or "")

@pytest.mark.asyncio
async def test_remove_payment_method_ok():
    b = StubBilling()
    res = await hm.fn_remove_payment_method(make_ctx(billing=b), _P(pm_id="pm_1"))
    assert res.status == "success" and res.data.removed is True

@pytest.mark.asyncio
async def test_set_default_payment_method_ok():
    b = StubBilling()
    res = await hm.fn_set_default_payment_method(make_ctx(billing=b), _P(pm_id="pm_2"))
    assert res.status == "success" and res.data.is_default is True
    assert ("set_default_payment_method", "pm_2") in b.calls

@pytest.mark.asyncio
async def test_set_default_payment_method_error():
    b = StubBilling(raise_on={"set_default_payment_method": _http_error(400, "Stripe failure.")})
    res = await hm.fn_set_default_payment_method(make_ctx(billing=b), _P(pm_id="pm_2"))
    assert res.status == "error"

@pytest.mark.asyncio
async def test_buy_tokens_success():
    from imperal_sdk.types.models import TopupResult
    b = StubBilling(topup_result=TopupResult(succeeded=True, payment_intent_id="pi_x"))
    res = await hm.fn_buy_tokens(make_ctx(billing=b), _P(tokens=10000))
    assert res.status == "success" and res.data.succeeded is True

@pytest.mark.asyncio
async def test_buy_tokens_no_card_402():
    b = StubBilling(raise_on={"topup": _http_error(402, "Add a payment method first, then buy tokens.")})
    res = await hm.fn_buy_tokens(make_ctx(billing=b), _P(tokens=10000))
    assert res.status == "error" and "payment method" in (res.error or "").lower()
