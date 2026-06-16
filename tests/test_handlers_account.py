# tests/test_handlers_account.py
import pytest, httpx
from conftest import make_ctx, StubBilling
from imperal_sdk.types.models import PlanInfo, AutoTopupSettings
import handlers_account as ha


class _P:  # generic params stand-in
    def __init__(self, **kw): self.__dict__.update(kw)


class _Empty: pass


def _http_error(status, detail):
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(status, request=req, json={"detail": detail})
    return httpx.HTTPStatusError(detail, request=req, response=resp)


# ---- reads (no confirm) ----

@pytest.mark.asyncio
async def test_list_plans_returns_planlist():
    b = StubBilling(plans=[PlanInfo(id="pro", name="Pro", price=29.0, interval="monthly", features={}, limits={})])
    res = await ha.fn_list_plans(make_ctx(billing=b), _Empty())
    assert res.status == "success"
    assert res.data.total == 1
    assert res.data.items[0].id == "pro"
    assert res.data.items[0].price == 29.0
    assert ("list_plans",) in b.calls


@pytest.mark.asyncio
async def test_get_auto_topup_reflects_settings():
    b = StubBilling(auto_topup=AutoTopupSettings(enabled=True, threshold_pct=10, recharge_tokens=20000))
    res = await ha.fn_get_auto_topup(make_ctx(billing=b), _Empty())
    assert res.status == "success"
    assert res.data.enabled is True
    assert res.data.threshold_pct == 10
    assert ("get_auto_topup",) in b.calls


@pytest.mark.asyncio
async def test_open_billing_portal_returns_portallink():
    b = StubBilling()
    res = await ha.fn_open_billing_portal(make_ctx(billing=b), _Empty())
    assert res.status == "success"
    assert res.data.url == b.portal_url
    assert b.portal_url in (res.summary or "")


@pytest.mark.asyncio
async def test_open_billing_portal_error():
    b = StubBilling(raise_on={"create_billing_portal_session": _http_error(500, "Stripe down.")})
    res = await ha.fn_open_billing_portal(make_ctx(billing=b), _Empty())
    assert res.status == "error"


# ---- guarded ----

@pytest.mark.asyncio
async def test_cancel_subscription_at_period_end():
    b = StubBilling()
    res = await ha.fn_cancel_subscription(make_ctx(billing=b), _Empty())
    assert res.status == "success"
    assert res.data.status == "cancel_at_period_end"
    assert res.data.plan == "pro"
    assert ("cancel_subscription",) in b.calls


@pytest.mark.asyncio
async def test_cancel_subscription_error():
    b = StubBilling(raise_on={"cancel_subscription": _http_error(409, "No active subscription to cancel.")})
    res = await ha.fn_cancel_subscription(make_ctx(billing=b), _Empty())
    assert res.status == "error"
    assert "No active subscription" in (res.error or res.summary or "")


@pytest.mark.asyncio
async def test_set_auto_topup_records_call_and_returns_enabled():
    b = StubBilling()
    res = await ha.fn_set_auto_topup(
        make_ctx(billing=b),
        _P(enabled=True, threshold_pct=10, recharge_tokens=20000, payment_method_id=""),
    )
    assert res.status == "success"
    assert res.data.enabled is True
    assert ("set_auto_topup", True, 10, 20000) in b.calls


@pytest.mark.asyncio
async def test_set_auto_topup_error():
    b = StubBilling(raise_on={"set_auto_topup": _http_error(400, "Need a card on file first.")})
    res = await ha.fn_set_auto_topup(
        make_ctx(billing=b),
        _P(enabled=True, threshold_pct=10, recharge_tokens=20000, payment_method_id=""),
    )
    assert res.status == "error"


@pytest.mark.asyncio
async def test_update_billing_profile_returns_profile():
    b = StubBilling()
    res = await ha.fn_update_billing_profile(
        make_ctx(billing=b),
        _P(name="Val", company="Imperal Inc", vat="EE123", country="EE"),
    )
    assert res.status == "success"
    assert res.data.company == "Imperal Inc"
    assert res.data.vat == "EE123"
    assert ("update_billing_profile", {"name": "Val", "company": "Imperal Inc", "vat": "EE123", "country": "EE"}) in b.calls


@pytest.mark.asyncio
async def test_update_billing_profile_error():
    b = StubBilling(raise_on={"update_billing_profile": _http_error(400, "Invalid VAT.")})
    res = await ha.fn_update_billing_profile(
        make_ctx(billing=b),
        _P(name="Val", company="Imperal Inc", vat="bad", country="EE"),
    )
    assert res.status == "error"
