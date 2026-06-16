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
