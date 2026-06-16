"""Test harness for imperal-ext-billing. The SDK MockBilling lacks the 2b
write/payment methods, so we stub ctx.billing directly with the real LIVE
client.py dataclass shapes."""
import sys, os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional
import pytest

# Make the ext modules importable (they use bare `import app`, `from app import …`)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# Make `conftest` importable by name from test modules (`from conftest import …`)
# even though tests/ is a package (tests/__init__.py) under pytest's prepend mode.
sys.path.insert(0, os.path.dirname(__file__))

from imperal_sdk.types.models import (  # the LIVE return dataclasses
    PaymentMethod, PaymentRecord, ChangePlanResult, TopupResult,
    SetupIntentResult, BalanceInfo,
)
from imperal_sdk.billing.client import SubscriptionInfo, LimitsResult  # the LIVE inlined ones


@dataclass
class StubBilling:
    """In-memory ctx.billing. Reads return canned data; writes record calls and
    return canned results (or raise the injected exc to test error paths)."""
    cards: list = field(default_factory=list)
    payments: list = field(default_factory=list)
    balance: BalanceInfo = field(default_factory=lambda: BalanceInfo(balance=50000, plan="pro", cap=250000))
    subscription: SubscriptionInfo = field(default_factory=lambda: SubscriptionInfo(
        plan="pro", status="active", started_at="2026-06-15T00:00:00", expires_at="2026-07-15T00:00:00"))
    limits: LimitsResult = field(default_factory=lambda: LimitsResult(
        plan="pro", usage={"tokens": 12000}, limits={"tokens": 50000}, exceeded=[]))
    change_plan_result: Optional[ChangePlanResult] = None
    topup_result: Optional[TopupResult] = None
    portal_url: str = "https://billing.stripe.com/p/session_test"
    raise_on: dict = field(default_factory=dict)   # method_name -> Exception to raise
    calls: list = field(default_factory=list)

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise self.raise_on[name]

    async def get_balance(self, user=None): self.calls.append(("get_balance",)); return self.balance
    async def get_subscription(self, user=None): self.calls.append(("get_subscription",)); return self.subscription
    async def check_limits(self, user=None): self.calls.append(("check_limits",)); return self.limits
    async def list_payment_methods(self, user=None): self.calls.append(("list_payment_methods",)); return list(self.cards)
    async def list_payments(self, user=None, limit=50, offset=0):
        self.calls.append(("list_payments", limit, offset)); return list(self.payments)
    async def change_plan(self, plan_id, period="monthly", user=None):
        self.calls.append(("change_plan", plan_id, period)); self._maybe_raise("change_plan")
        return self.change_plan_result or ChangePlanResult(action="upgrade", plan=plan_id, succeeded=True)
    async def topup(self, tokens, price_cents, save_payment_method=True, user=None):
        self.calls.append(("topup", tokens, price_cents)); self._maybe_raise("topup")
        return self.topup_result or TopupResult(payment_intent_id="pi_test", client_secret="cs_test")
    async def set_default_payment_method(self, pm_id, user=None):
        self.calls.append(("set_default_payment_method", pm_id)); self._maybe_raise("set_default_payment_method"); return True
    async def remove_payment_method(self, pm_id, user=None):
        self.calls.append(("remove_payment_method", pm_id)); self._maybe_raise("remove_payment_method"); return True
    async def create_setup_intent(self, user=None):
        self.calls.append(("create_setup_intent",)); self._maybe_raise("create_setup_intent")
        return SetupIntentResult(client_secret="cs_setup", publishable_key="pk_test")
    async def create_billing_portal_session(self, user=None):  # Phase 2 (prereq adds this)
        self.calls.append(("create_billing_portal_session",)); self._maybe_raise("create_billing_portal_session")
        return self.portal_url


def make_ctx(billing=None, imperal_id="imp_u_TEST", attributes=None):
    user = SimpleNamespace(imperal_id=imperal_id, id=imperal_id, email="t@example.com",
                           attributes=attributes or {})
    return SimpleNamespace(user=user, billing=billing or StubBilling(),
                           store=SimpleNamespace(), http=None)


@pytest.fixture
def billing(): return StubBilling()

@pytest.fixture
def ctx(billing): return make_ctx(billing=billing)
