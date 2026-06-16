# tests/test_panels_account.py
import pytest
from conftest import make_ctx, StubBilling
from imperal_sdk.types.models import PaymentMethod
from imperal_sdk.billing.client import SubscriptionInfo
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


@pytest.mark.asyncio
async def test_subscription_section_has_cancel_button_for_active_paid():
    # default StubBilling subscription = pro/active → Cancel plan button present.
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=StubBilling()), catalog=[]))
    assert "cancel_subscription" in flat


@pytest.mark.asyncio
async def test_subscription_section_no_cancel_for_free_plan():
    b = StubBilling(subscription=SubscriptionInfo(plan="free", status="active",
                                                  started_at="", expires_at=""))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=[]))
    assert "cancel_subscription" not in flat


@pytest.mark.asyncio
async def test_subscription_section_pending_cancel_shows_resume_banner():
    # cancel_at_period_end=True → banner + Resume button, NO Cancel button.
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", started_at="2026-06-15T00:00:00",
        expires_at="2026-07-15T00:00:00", cancel_at_period_end=True))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=[]))
    assert "resume_subscription" in flat
    assert "Cancellation scheduled" in flat
    assert "cancel_subscription" not in flat


@pytest.mark.asyncio
async def test_subscription_section_expired_badge():
    # expires_at in the past → "Expired" badge.
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", started_at="2020-01-01T00:00:00",
        expires_at="2020-02-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=[]))
    assert "Expired" in flat


@pytest.mark.asyncio
async def test_subscription_section_lapsed_paid_shows_renew_cancel_and_plan_change():
    # A lapsed self-serve PAID plan (expired date, not pending_cancel) offers all
    # three — they COEXIST: Renew (recover now), Cancel, and the plan-change
    # dropdown. The earlier "renew-first, hide everything" behavior was a regression.
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29},
           {"id": "uuid-business", "name": "business", "price": 79}]
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", started_at="2020-01-01T00:00:00",
        expires_at="2020-02-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "renew_subscription" in flat                 # Renew button wired
    assert "change_plan" in flat                        # plan-change dropdown STILL available
    assert "cancel_subscription" in flat                # Cancel STILL available
    assert "uuid-business" in flat                      # an upgrade target is offered


@pytest.mark.asyncio
async def test_subscription_section_enterprise_shows_all_three_no_expired_badge():
    # Enterprise (contract, price 0) shows ALL THREE management controls like any
    # paid plan (Change plan + Cancel + Renew), but is NOT flagged "Expired" even
    # with a stale past date. Renew on it hits the gateway's "managed by contract"
    # message, not the old bogus "The Free plan doesn't need renewing" error.
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29},
           {"id": "uuid-business", "name": "business", "price": 79},
           {"id": "uuid-ent", "name": "enterprise", "price": 0}]
    b = StubBilling(subscription=SubscriptionInfo(
        plan="enterprise", status="active", started_at="2026-04-14T00:58:26",
        expires_at="2026-05-14T00:58:26"))   # a month in the past
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "renew_subscription" in flat                 # Renew button present (3rd control)
    assert "cancel_subscription" in flat                # Cancel present
    assert "change_plan" in flat                        # Change-plan present
    assert "Expired" not in flat                        # NOT flagged Expired (contract plan)


@pytest.mark.asyncio
async def test_subscription_section_active_paid_always_shows_three_controls():
    # Per Valentin: an active paid plan ALWAYS shows all three controls together —
    # Change plan (dropdown) + Cancel + Renew — even with a future expiry. Renew on
    # a still-active sub just reports "nothing to renew" (no crash, no lie).
    cat = [{"id": "uuid-pro", "name": "pro", "price": 29},
           {"id": "uuid-business", "name": "business", "price": 79}]
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", started_at="2026-06-15T00:00:00",
        expires_at="2099-01-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "renew_subscription" in flat
    assert "cancel_subscription" in flat
    assert "change_plan" in flat


@pytest.mark.asyncio
async def test_tokens_section_has_custom_amount_input():
    # Buy-tokens form uses a free-form Input (param_name="tokens"), not a fixed Select.
    flat = _flat(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "buy_tokens" in flat
    assert "Input" in _types(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "tokens" in flat
    assert "$1 per 1,000 tokens" in flat


@pytest.mark.asyncio
async def test_tokens_section_has_auto_topup_form():
    flat = _flat(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "set_auto_topup" in flat
    assert "Auto top-up" in flat


@pytest.mark.asyncio
async def test_profile_section_is_editable_form():
    nodes = await pa.build_profile_section(
        make_ctx(billing=StubBilling(), attributes={"billing": {"company": "Imperal Inc", "vat": "EE123"}}))
    flat = _flat(nodes)
    assert "update_billing_profile" in flat
    assert "Form" in _types(nodes)
    assert "Imperal Inc" in flat


@pytest.mark.asyncio
async def test_subscription_plan_change_is_dropdown_using_plan_id_not_name():
    # ONE plan-change control: a Select of the OTHER self-service plans inside a
    # Form that submits to `change_plan`. Option value MUST be the UUID `id`,
    # label uses the plan name + price. Only Pro and Business are self-service —
    # Free (cancel-only), Enterprise (contract-only) and the current plan (pro)
    # are all excluded.
    cat = [
        {"id": "uuid-free", "name": "free", "price": 0},
        {"id": "uuid-pro", "name": "pro", "price": 29},
        {"id": "uuid-business", "name": "business", "price": 79},
        {"id": "uuid-ent", "name": "enterprise", "price": 0},
    ]
    nodes = await pa.build_subscription_section(make_ctx(billing=StubBilling()), catalog=cat)
    flat = _flat(nodes)
    types = _types(nodes)
    assert "Form" in types and "Select" in types               # single dropdown control
    assert "change_plan" in flat                               # form submits to ONE tool
    assert "uuid-business" in flat                             # Business is offered (option value = UUID id)
    assert "uuid-pro" not in flat                              # current plan excluded
    assert "uuid-free" not in flat                             # Free is NOT a self-service target
    assert "uuid-ent" not in flat                              # Enterprise is contract-only
    assert "Business" in flat and "$79/mo" in flat            # label by name + price
    # The per-plan upgrade/downgrade button loop is gone.
    assert "upgrade_plan" not in flat and "downgrade_plan" not in flat


@pytest.mark.asyncio
async def test_subscription_dropdown_offers_pro_when_on_business():
    # On Business → only Pro (the other self-service plan) is offered; ordered by price.
    from imperal_sdk.billing.client import SubscriptionInfo
    cat = [
        {"id": "uuid-pro", "name": "pro", "price": 29},
        {"id": "uuid-business", "name": "business", "price": 79},
        {"id": "uuid-ent", "name": "enterprise", "price": 0},
    ]
    b = StubBilling(subscription=SubscriptionInfo(plan="business", status="active",
                                                  started_at="", expires_at="2099-01-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=cat))
    assert "uuid-pro" in flat
    assert "uuid-business" not in flat   # current plan excluded
    assert "uuid-ent" not in flat


@pytest.mark.asyncio
async def test_subscription_card_has_clarifying_subtitle():
    # The Subscription card spells out plan vs tokens so users don't conflate them.
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=StubBilling()), catalog=[]))
    assert "Plan & access" in flat
    assert "monthly token allowance" in flat


@pytest.mark.asyncio
async def test_subscription_status_row_reads_expired_when_past_due():
    # When expired, the Status KeyValue row must agree with the Expired badge.
    b = StubBilling(subscription=SubscriptionInfo(
        plan="pro", status="active", started_at="2020-01-01T00:00:00",
        expires_at="2020-02-01T00:00:00"))
    flat = _flat(await pa.build_subscription_section(make_ctx(billing=b), catalog=[]))
    assert "Expired" in flat
    # The raw "active" status must NOT leak into the Status KeyValue row when expired.
    assert "'key': 'Status', 'value': 'active'" not in flat
    assert "'key': 'Status', 'value': 'Expired'" in flat


@pytest.mark.asyncio
async def test_tokens_card_has_clarifying_subtitle():
    flat = _flat(await pa.build_tokens_section(make_ctx(billing=StubBilling())))
    assert "Usage credits" in flat
