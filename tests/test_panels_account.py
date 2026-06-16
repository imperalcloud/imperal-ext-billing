# tests/test_panels_account.py
import pytest
from conftest import make_ctx, StubBilling
from imperal_sdk.types.models import PaymentMethod
import panels_account as pa


def _types(nodes):
    """Every ui node 'type' anywhere in the rendered tree (recurses content/items/actions/children)."""
    out = []
    def rec(n):
        if isinstance(n, dict):
            if "type" in n:
                out.append(n["type"])
            for v in n.values():
                rec(v)
        elif isinstance(n, list):
            for v in n:
                rec(v)
    for n in nodes:
        rec(n.to_dict())
    return out


def _flat(nodes):
    """The full rendered tree as one string (for substring assertions)."""
    return str([n.to_dict() for n in nodes])


@pytest.mark.asyncio
async def test_subscription_section_shows_plan():
    # catalog=[] avoids the live /v1/billing/plans fetch in unit tests.
    nodes = await pa.build_subscription_section(make_ctx(billing=StubBilling()), catalog=[])
    assert "Card" in _types(nodes)
    assert "pro" in _flat(nodes).lower()


@pytest.mark.asyncio
async def test_payment_methods_section_lists_cards_and_actions():
    b = StubBilling(cards=[
        PaymentMethod(id="pm_1", brand="visa", last4="4242", exp_month=12, exp_year=2027, is_default=True),
        PaymentMethod(id="pm_2", brand="mastercard", last4="4444", exp_month=1, exp_year=2030, is_default=False),
    ])
    flat = _flat(await pa.build_payment_methods_section(make_ctx(billing=b)))
    assert "4242" in flat
    assert "remove_payment_method" in flat        # actions[].on_click ui.Call (both cards)
    assert "set_default_payment_method" in flat   # rendered only for the non-default card


@pytest.mark.asyncio
async def test_payment_methods_empty_state():
    flat = _flat(await pa.build_payment_methods_section(make_ctx(billing=StubBilling(cards=[]))))
    assert "Empty" in flat or "No saved cards" in flat


@pytest.mark.asyncio
async def test_tokens_section_shows_progress():
    types = _types(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "Progress" in types or "Stat" in types


@pytest.mark.asyncio
async def test_payment_methods_has_portal_button():
    flat = _flat(await pa.build_payment_methods_section(make_ctx(billing=StubBilling(cards=[]))))
    assert "billing.stripe.com" in flat   # ui.Open(url=portal_url) wired in (StubBilling portal_url)
