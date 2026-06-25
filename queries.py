"""Billing · MySQL analytics queries for DUI panels.

Read-only queries against token_ledger for dashboard analytics,
transaction history, and extension breakdowns.

Split into two files for <300 lines rule:
- queries.py: connection pool, transaction history, transaction detail
- queries_analytics.py: spending aggregation, extension stats
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

log = logging.getLogger("billing")

# ─── Connection Pool ──────────────────────────────────────────────────── #

_engine = None
_session_factory = None

PERIOD_DAYS = {"today": 0, "7d": 7, "30d": 30, "all": None}


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL env var is required for billing extension "
            "(no fallback -- federal/CJIS no plaintext credentials in code)"
        )
    if url.startswith("mysql://"):
        url = url.replace("mysql://", "mysql+aiomysql://", 1)
    elif not url.startswith("mysql+aiomysql://"):
        url = f"mysql+aiomysql://{url}"
    return url


async def _get_session() -> AsyncSession:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            _get_database_url(),
            pool_size=3, max_overflow=1, pool_recycle=3600, echo=False,
        )
        _session_factory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False,
        )
    return _session_factory()


async def get_app_display_names() -> dict:
    """Canonical app_id -> display_name map from `developer_apps` (the SAME table
    the marketplace reads — single source of truth). Used so the billing UI shows
    real extension names, not raw app_ids. Empty/missing names are omitted; the
    caller falls back to a humanized app_id."""
    session = await _get_session()
    try:
        r = await session.execute(text(
            "SELECT app_id, display_name FROM developer_apps "
            "WHERE display_name IS NOT NULL AND display_name <> ''"
        ))
        return {row[0]: row[1] for row in r.fetchall()}
    except Exception as e:
        log.warning("get_app_display_names: %s", e)
        return {}
    finally:
        await session.close()


def _period_clause(period: str) -> str:
    """Return SQL WHERE clause fragment for time filtering."""
    days = PERIOD_DAYS.get(period)
    if period == "today":
        return "AND DATE(created_at) = CURDATE()"
    if days is not None:
        return f"AND created_at >= NOW() - INTERVAL {days} DAY"
    return ""


def _serialize_dt(val) -> str:
    """Convert datetime/date to ISO string."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


# ─── Re-exports from queries_analytics ────────────────────────────────── #
# Keeps `import queries; queries.get_spending_aggregation(...)` working.

from queries_analytics import get_spending_aggregation, get_extension_stats  # noqa: E402, F401


# ─── Transaction History ──────────────────────────────────────────────── #


async def get_transaction_history(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    period: str = "all",
    app_id: str | None = None,
    tx_type: str | None = None,
    user_only: bool = False,
) -> dict:
    """Paginated transaction history for a user.

    user_only=True filters out system internals (skeleton, commission)
    so only real user actions + credits/refunds are shown.
    """
    period_sql = _period_clause(period)

    where_parts = [
        "account_type = 'user'",
        "account_id = :user_id",
    ]
    params: dict = {"user_id": user_id, "limit": limit, "offset": offset}

    if user_only:
        where_parts.append("reference_id NOT LIKE 'skeleton_%'")
        where_parts.append("reason != 'commission'")

    if app_id:
        where_parts.append("app_id = :app_id")
        params["app_id"] = app_id

    if tx_type == "deduct":
        where_parts.append("amount < 0")
    elif tx_type == "credit":
        where_parts.append("amount > 0")

    where = " AND ".join(where_parts)

    session = await _get_session()
    try:
        # Count total
        count_sql = f"SELECT COUNT(*) FROM token_ledger WHERE {where} {period_sql}"
        r = await session.execute(text(count_sql), params)
        total = r.scalar() or 0

        # Fetch page
        data_sql = (
            f"SELECT event_id, transaction_id, amount, reason, "
            f"app_id, reference_id, description, metadata_json, created_at "
            f"FROM token_ledger WHERE {where} {period_sql} "
            f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        r = await session.execute(text(data_sql), params)
        rows = r.fetchall()

        transactions = []
        for row in rows:
            meta = {}
            try:
                meta = json.loads(row[7]) if row[7] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            transactions.append({
                "event_id": row[0],
                "transaction_id": row[1],
                "amount": row[2],
                "reason": row[3],
                "app_id": row[4],
                "tool_name": row[5] or meta.get("tool_name"),
                "description": row[6],
                "action_type": meta.get("action_type", ""),
                "created_at": _serialize_dt(row[8]),
            })

        return {
            "transactions": transactions,
            "total": total,
            "has_more": (offset + limit) < total,
        }
    finally:
        await session.close()


# ─── Transaction Detail ──────────────────────────────────────────────── #


async def get_transaction_detail(event_id: str) -> dict:
    """Get both ledger entries (user + platform) for double-entry view."""
    session = await _get_session()
    try:
        sql = text(
            "SELECT event_id, account_type, account_id, amount, reason, "
            "app_id, reference_id, description, metadata_json, created_at "
            "FROM token_ledger "
            "WHERE event_id = :eid OR event_id = :eid_platform"
        )
        r = await session.execute(sql, {
            "eid": event_id,
            "eid_platform": f"{event_id}:platform",
        })
        rows = r.fetchall()

        user_entry = None
        platform_entry = None

        for row in rows:
            meta = {}
            try:
                meta = json.loads(row[8]) if row[8] else {}
            except (json.JSONDecodeError, TypeError):
                pass

            entry = {
                "event_id": row[0],
                "account_type": row[1],
                "account_id": row[2],
                "amount": row[3],
                "reason": row[4],
                "app_id": row[5],
                "tool_name": row[6] or meta.get("tool_name"),
                "description": row[7],
                "base_price": meta.get("base_price"),
                "platform_fee": meta.get("platform_fee"),
                "model": meta.get("model"),
                "model_tier": meta.get("model_tier"),
                "action_type": meta.get("action_type"),
                "created_at": _serialize_dt(row[9]),
            }
            if row[1] == "user":
                user_entry = entry
            else:
                platform_entry = entry

        balanced = False
        if user_entry and platform_entry:
            balanced = (user_entry["amount"] + platform_entry["amount"]) == 0

        return {
            "user_entry": user_entry,
            "platform_entry": platform_entry,
            "balanced": balanced,
        }
    finally:
        await session.close()
