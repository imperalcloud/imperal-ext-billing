# tests/test_models_account.py
from models_account import (
    PaymentMethodCard, PaymentMethodList, PaymentRecordEntry, PaymentHistory,
)

def test_payment_method_card_canon():
    c = PaymentMethodCard(id="pm_1", brand="visa", last4="4242",
                          exp_month=12, exp_year=2027, is_default=True)
    assert c.id == "pm_1"
    assert c.title == "Visa ···· 4242"
    assert c.kind == "paymentmethodcard"
    assert c.is_default is True

def test_payment_method_list_is_entitylist():
    lst = PaymentMethodList(items=[{"id": "pm_1", "brand": "visa", "last4": "4242",
                                    "exp_month": 1, "exp_year": 2030, "is_default": False}],
                            total=1)
    assert lst.items[0].title == "Visa ···· 4242"
    assert lst.total == 1
    assert lst.items[0].kind == "paymentmethodcard"

def test_payment_record_entry_canon():
    r = PaymentRecordEntry(payment_intent_id="pi_1", amount_cents=2900, tokens=0,
                           status="completed", type="subscription",
                           created_at="2026-06-15T00:00:00", receipt_url="https://r")
    assert r.id == "pi_1"
    assert "$29.00" in r.title
    assert r.status == "completed"
    assert r.url == "https://r"   # receipt link projected onto Entity.url

def test_payment_history_is_entitylist():
    h = PaymentHistory(items=[{"payment_intent_id": "pi_1", "amount_cents": 900,
                               "tokens": 0, "status": "completed", "type": "topup"}],
                       total=1, has_more=False)
    assert h.items[0].id == "pi_1"
    assert h.total == 1

# tests/test_models_account.py  (append)
from models_account import ChangePlanOutcome, PaymentMethodRemoved, PaymentMethodDefaultSet

def test_payment_method_default_set():
    d = PaymentMethodDefaultSet(pm_id="pm_2", is_default=True)
    assert d.id == "pm_2"
    assert d.is_default is True
    assert d.kind == "paymentmethoddefaultset"

def test_change_plan_outcome_upgrade():
    o = ChangePlanOutcome(action="upgrade", plan="business", succeeded=True,
                          requires_action=False, effective_at="", pending=False)
    assert o.id == "business"
    assert o.kind == "changeplanoutcome"
    assert o.succeeded is True

def test_change_plan_outcome_downgrade_pending():
    o = ChangePlanOutcome(action="downgrade", plan="pro", succeeded=False,
                          pending=True, effective_at="2026-07-15T00:00:00")
    assert o.pending is True
    assert o.title.startswith("Downgrade")

def test_payment_method_removed():
    r = PaymentMethodRemoved(pm_id="pm_1", removed=True)
    assert r.id == "pm_1"
    assert r.removed is True

def test_token_purchase_outcome_canon():
    from models_account import TokenPurchaseOutcome
    o = TokenPurchaseOutcome(tokens=10000, succeeded=True, requires_action=False,
                             payment_intent_id="pi_x")
    assert o.id == "topup"
    assert o.kind == "tokenpurchaseoutcome"
    assert o.title == "Top-up 10000 tokens"
    assert o.succeeded is True
