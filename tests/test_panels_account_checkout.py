import pytest
from conftest import StubBilling, make_ctx
from imperal_sdk.billing.client import SubscriptionInfo
from imperal_sdk.types.models import PaymentMethod
import panels_account as pa


def _flat(components):
    return str([c.to_dict() if hasattr(c, "to_dict") else repr(c) for c in components])


@pytest.mark.asyncio
async def test_tokens_card_has_clarifying_subtitle():
    flat = _flat(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "Usage credits" in flat or "Credit balance" in flat


@pytest.mark.asyncio
async def test_money_actions_carry_confirmation_prompts():
    flat = _flat(await pa.build_subscription_section(
        make_ctx(billing=StubBilling()), catalog=[{"id": "uuid-business", "name": "business", "price": 79}]))
    assert "Cancel your plan?" in flat
    assert "Renew now?" in flat
    assert "Change your plan?" in flat
    tokens = _flat(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "Buy these credits now?" in tokens
    assert "Save auto top-up?" in tokens


@pytest.mark.asyncio
async def test_payment_methods_renders_stripe_link_pm():
    b = StubBilling(cards=[PaymentMethod(id="pm_link", type="link", brand="link",
                                         last4="", exp_month=0, exp_year=0, is_default=True)])
    flat = _flat(await pa.build_payment_methods_section(make_ctx(billing=b)))
    assert "Stripe Link" in flat
    assert "No saved cards" not in flat


@pytest.mark.asyncio
async def test_payment_methods_no_remove_on_only_card():
    one = StubBilling(cards=[PaymentMethod(id="pm_1", type="card", brand="visa", last4="4242",
                                           exp_month=12, exp_year=2030, is_default=True)])
    assert "remove_payment_method" not in _flat(await pa.build_payment_methods_section(make_ctx(billing=one)))
    two = StubBilling(cards=[
        PaymentMethod(id="pm_1", type="card", brand="visa", last4="4242", exp_month=12, exp_year=2030, is_default=True),
        PaymentMethod(id="pm_2", type="card", brand="mc", last4="4444", exp_month=1, exp_year=2031, is_default=False)])
    assert "remove_payment_method" in _flat(await pa.build_payment_methods_section(make_ctx(billing=two)))


@pytest.mark.asyncio
async def test_subscription_section_free_user_gets_subscribe_buttons():
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29},
           {"id": "uuid-business", "name": "business", "price": 79},
           {"id": "uuid-free", "name": "free", "price": 0}]
    b = StubBilling(subscription=SubscriptionInfo(plan="free", status="active"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "__checkout__" in flat
    assert "Subscribe to Pro" in flat and "Subscribe to Business" in flat
    assert "change_plan" not in flat
    assert "cancel_subscription" not in flat


@pytest.mark.asyncio
async def test_subscription_section_free_subscribe_carries_plan_slug():
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29}]
    b = StubBilling(subscription=SubscriptionInfo(plan="free", status="active"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "'plan': 'pro'" in flat or '"plan": "pro"' in flat
    assert "monthly" in flat


@pytest.mark.asyncio
async def test_subscription_section_paid_user_keeps_change_plan_no_checkout():
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29},
           {"id": "uuid-business", "name": "business", "price": 79}]
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", expires_at="2099-01-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "change_plan" in flat
    assert "__checkout__" not in flat
