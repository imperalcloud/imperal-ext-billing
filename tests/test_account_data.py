# tests/test_account_data.py
import account_data as ad
from conftest import make_ctx

def test_price_cents_for_tokens_dollar_per_1000():
    assert ad.price_cents_for_tokens(1000) == 100
    assert ad.price_cents_for_tokens(5000) == 500

def test_is_unavailable_balance_sentinel():
    from imperal_sdk.types.models import BalanceInfo
    assert ad.balance_unavailable(BalanceInfo(balance=0, plan="unknown", cap=0)) is True
    assert ad.balance_unavailable(BalanceInfo(balance=50000, plan="pro", cap=250000)) is False

def test_read_billing_profile_from_attributes():
    ctx = make_ctx(attributes={"billing": {"company": "Imperal Inc", "vat": "EE123"}})
    prof = ad.read_billing_profile(ctx)
    assert prof["company"] == "Imperal Inc"
    assert prof["vat"] == "EE123"

def test_read_billing_profile_empty():
    assert ad.read_billing_profile(make_ctx(attributes={})) == {"company": "", "vat": "", "country": "", "name": ""}
