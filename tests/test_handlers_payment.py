# tests/test_handlers_payment.py
import pytest
from conftest import make_ctx, StubBilling
from imperal_sdk.types.models import PaymentMethod, PaymentRecord
import handlers_payment as hp

class _Empty: pass

@pytest.mark.asyncio
async def test_list_payment_methods_returns_real_cards():
    billing = StubBilling(cards=[
        PaymentMethod(id="pm_1", brand="visa", last4="4242", exp_month=12, exp_year=2027, is_default=True),
        PaymentMethod(id="pm_2", brand="mastercard", last4="4444", exp_month=1, exp_year=2030, is_default=False),
    ])
    res = await hp.fn_list_payment_methods(make_ctx(billing=billing), _Empty())
    assert res.status == "success"
    assert res.data.total == 2
    assert res.data.items[0].title == "Visa ···· 4242"
    assert res.data.items[0].is_default is True
    assert ("list_payment_methods",) in billing.calls   # the stub was called, not get_balance

@pytest.mark.asyncio
async def test_list_payments_returns_history():
    billing = StubBilling(payments=[
        PaymentRecord(payment_intent_id="pi_1", amount_cents=2900, tokens=0,
                      status="completed", type="subscription", receipt_url="https://r"),
    ])
    res = await hp.fn_list_payments(make_ctx(billing=billing), _Empty())
    assert res.status == "success"
    assert res.data.items[0].url == "https://r"
