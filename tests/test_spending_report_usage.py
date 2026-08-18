"""spending_report must report REAL metered usage.

Regression cover for the defect found on 2026-08-18: the report rendered
"No usage recorded" for every user while metering was perfectly healthy.

Two independent causes, both fixed:

1. Gateway: check_limits() returned {plan, limits, usage} but LimitsResponse
   requires `exceeded`, so GET /v1/billing/usage answered 500 for EVERY
   caller and the SDK swallowed it into an empty result.

2. This extension: with a service token the SDK resolves check_limits() to
   /internal/user-limits/{uid}, which answers {plan, limits} with NO usage
   at all. The handler now reads the gateway's dedicated on-demand endpoint
   via app.get_user_usage() instead -- deliberately NOT by widening the
   hot-path endpoint the kernel hits every turn.

These tests pin the handler's contract, not the transport: get_user_usage is
patched, so they never touch the network.
"""
import pytest

import app as app_mod
import handlers
from conftest import make_ctx, StubBilling


class _P:
    """Stand-in for EmptyParams (the handler ignores it)."""


def _patch_usage(monkeypatch, payload):
    async def _fake(user_id: str) -> dict:
        _fake.called_with = user_id
        return payload
    monkeypatch.setattr(handlers, "get_user_usage", _fake)
    return _fake


@pytest.mark.asyncio
async def test_reports_real_usage_from_gateway(monkeypatch):
    """The per-tool usage the gateway returns must reach the report."""
    fake = _patch_usage(monkeypatch, {
        "plan": "enterprise",
        "limits": {},
        "usage": {"notes.create_note": 3, "tasks.skeleton_refresh_tasks": 8340},
        "exceeded": [],
    })

    ctx = make_ctx(imperal_id="imp_u_TEST")
    res = await handlers.fn_spending_report(ctx, _P())

    assert res.data.total == 2
    assert fake.called_with == "imp_u_TEST"          # asked for THIS user
    assert "No usage recorded" not in res.summary     # the actual bug symptom
    assert "tasks.skeleton_refresh_tasks: 8,340" in res.summary
    # Biggest spend first — a 343-meter report is only useful sorted.
    assert [i.meter for i in res.data.items] == [
        "tasks.skeleton_refresh_tasks", "notes.create_note",
    ]


@pytest.mark.asyncio
async def test_plan_limited_meter_keeps_its_limit_and_exceeded_flag(monkeypatch):
    """A metered row that IS plan-limited must carry limit + exceeded."""
    _patch_usage(monkeypatch, {
        "plan": "pro",
        "limits": {"automations": 500},
        "usage": {"automations": 500, "notes.create_note": 2},
        "exceeded": ["automations"],
    })

    res = await handlers.fn_spending_report(make_ctx(), _P())

    rows = {i.meter: i for i in res.data.items}
    assert rows["automations"].limit == 500
    assert rows["automations"].exceeded is True
    # An unlimited per-tool meter has no limit — and is never "exceeded".
    assert rows["notes.create_note"].limit is None
    assert rows["notes.create_note"].exceeded is False
    assert "Exceeded: automations" in res.summary


@pytest.mark.asyncio
async def test_degrades_to_sdk_when_endpoint_unavailable(monkeypatch):
    """If the usage endpoint fails, degrade to ctx.billing — never error out."""
    _patch_usage(monkeypatch, {})  # get_user_usage returns {} on any failure

    billing = StubBilling()  # canned: usage={"tokens": 12000}, limits={"tokens": 50000}
    res = await handlers.fn_spending_report(make_ctx(billing=billing), _P())

    assert res.data.total == 1
    assert res.data.items[0].meter == "tokens"
    assert res.data.items[0].limit == 50000
    assert "tokens: 12,000" in res.summary


@pytest.mark.asyncio
async def test_empty_usage_still_renders(monkeypatch):
    """No usage at all is a valid answer, not a crash."""
    _patch_usage(monkeypatch, {
        "plan": "free", "limits": {}, "usage": {}, "exceeded": [],
    })

    res = await handlers.fn_spending_report(make_ctx(), _P())

    assert res.data.total == 0
    assert res.data.items == []
    assert "No usage recorded" in res.summary


@pytest.mark.asyncio
async def test_get_user_usage_returns_empty_dict_on_failure(monkeypatch):
    """app.get_user_usage is fail-soft: a broken gateway must not raise."""
    class _Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("gateway down")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    assert await app_mod.get_user_usage("imp_u_TEST") == {}
