"""Billing · Spending aggregation and extension stats queries.

Split from queries.py to stay under 300 lines per file.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

from queries import _get_session, _period_clause

log = logging.getLogger("billing")


# ─── Spending Aggregation ─────────────────────────────────────────────── #


async def get_spending_aggregation(
    user_id: str,
    period: str = "7d",
) -> dict:
    """Aggregate spending data for overview charts."""
    period_sql = _period_clause(period)
    params: dict = {"user_id": user_id}

    session = await _get_session()
    try:
        sql = (
            f"SELECT amount, reason, app_id, metadata_json, "
            f"DATE(created_at) as dt "
            f"FROM token_ledger "
            f"WHERE account_type = 'user' AND account_id = :user_id "
            f"{period_sql} ORDER BY created_at"
        )
        r = await session.execute(text(sql), params)
        rows = r.fetchall()

        total_spent = 0
        total_credits = 0
        action_count = 0
        refund_count = 0
        by_ext: dict[str, dict] = {}
        by_action: dict[str, dict] = {}
        by_day: dict[str, dict] = {}

        for amount, reason, app_id, meta_json, dt in rows:
            # Skip zero-amount entries (historical artifacts — B13)
            if amount == 0:
                continue

            meta = {}
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (json.JSONDecodeError, TypeError):
                pass

            day_key = dt.isoformat() if dt else "unknown"
            action_type = meta.get("action_type", "other")

            if amount < 0:
                cost = abs(amount)
                total_spent += cost
                action_count += 1

                ext_key = app_id or "unknown"
                if ext_key not in by_ext:
                    by_ext[ext_key] = {"app_id": ext_key, "spent": 0, "tx_count": 0}
                by_ext[ext_key]["spent"] += cost
                by_ext[ext_key]["tx_count"] += 1

                if action_type not in by_action:
                    by_action[action_type] = {"action_type": action_type, "spent": 0, "tx_count": 0}
                by_action[action_type]["spent"] += cost
                by_action[action_type]["tx_count"] += 1

                if day_key not in by_day:
                    by_day[day_key] = {"date": day_key, "spent": 0, "credits": 0}
                by_day[day_key]["spent"] += cost
            else:
                total_credits += amount
                refund_count += 1
                if day_key not in by_day:
                    by_day[day_key] = {"date": day_key, "spent": 0, "credits": 0}
                by_day[day_key]["credits"] += amount

        for entry in by_ext.values():
            entry["pct"] = round(entry["spent"] / total_spent * 100, 1) if total_spent else 0
        for entry in by_action.values():
            entry["pct"] = round(entry["spent"] / total_spent * 100, 1) if total_spent else 0

        avg_cost = round(total_spent / max(1, action_count), 1)
        tx_count = action_count + refund_count  # only non-zero entries

        return {
            "total_spent": total_spent,
            "total_credits": total_credits,
            "tx_count": tx_count,
            "action_count": action_count,
            "refund_count": refund_count,
            "avg_cost": avg_cost,
            "daily_spending": sorted(by_day.values(), key=lambda d: d["date"]),
            "by_extension": sorted(by_ext.values(), key=lambda e: e["spent"], reverse=True),
            "by_action_type": sorted(by_action.values(), key=lambda a: a["spent"], reverse=True),
        }
    finally:
        await session.close()


# ─── Extension Stats ──────────────────────────────────────────────────── #


async def get_extension_stats(
    user_id: str,
    app_id: str,
    period: str = "7d",
) -> dict:
    """Stats for a single extension — top functions, daily trend."""
    period_sql = _period_clause(period)
    params: dict = {"user_id": user_id, "app_id": app_id}

    session = await _get_session()
    try:
        sql = (
            f"SELECT amount, reference_id, DATE(created_at) as dt "
            f"FROM token_ledger "
            f"WHERE account_type = 'user' AND account_id = :user_id "
            f"AND app_id = :app_id AND amount < 0 "
            f"{period_sql}"
        )
        r = await session.execute(text(sql), params)
        rows = r.fetchall()

        total_spent = 0
        by_fn: dict[str, dict] = {}
        by_day: dict[str, dict] = {}

        for amount, ref_id, dt in rows:
            cost = abs(amount)
            total_spent += cost
            fn = ref_id or "unknown"
            day_key = dt.isoformat() if dt else "unknown"

            if fn not in by_fn:
                by_fn[fn] = {"tool_name": fn, "spent": 0, "count": 0}
            by_fn[fn]["spent"] += cost
            by_fn[fn]["count"] += 1

            if day_key not in by_day:
                by_day[day_key] = {"date": day_key, "spent": 0}
            by_day[day_key]["spent"] += cost

        tx_count = len(rows)
        avg_cost = round(total_spent / max(1, tx_count), 1)

        return {
            "total_spent": total_spent,
            "tx_count": tx_count,
            "avg_cost": avg_cost,
            "top_functions": sorted(by_fn.values(), key=lambda f: f["spent"], reverse=True),
            "daily_trend": sorted(by_day.values(), key=lambda d: d["date"]),
        }
    finally:
        await session.close()


# ---------------------------------------------------------------------
# Sprint 4 (2026-04-28) - LLM Costs query (action_ledger direct DB read).
# ---------------------------------------------------------------------

import json as _json


async def get_llm_costs_history(
    user_id: str,
    period: str = "7d",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Fetch action_ledger history with per-purpose LLM breakdown.

    Reads action_ledger directly: the Sprint 4 columns
    (llm_per_purpose, llm_total_cost_usd, is_byollm_chain) are populated
    by the kernel extension_runner aggregator + cost-compute callback.

    Returns:
        {
            "actions": [...action rows with parsed llm_per_purpose...],
            "total_cost_usd": float,
            "total_tokens": int,
            "byollm_count": int,
            "total_actions": int,
        }
    """
    period_sql = _period_clause(period)
    params = {"user_id": user_id, "limit": int(limit), "offset": int(offset)}

    sql = (
        "SELECT trace_id, chain_id, app_id, tool_name, action_type, "
        "status, duration_ms, llm_provider, llm_model, llm_total_calls, "
        "llm_total_tokens, llm_per_purpose, llm_total_cost_usd, "
        "is_byollm_chain, created_at "
        "FROM action_ledger "
        "WHERE user_id = :user_id "
        f"{period_sql} "
        "ORDER BY created_at DESC "
        "LIMIT :limit OFFSET :offset"
    )

    session = await _get_session()
    try:
        r = await session.execute(text(sql), params)
        rows = r.fetchall()
    except Exception as e:
        log.warning("get_llm_costs_history SQL error: %s", e)
        return {"actions": [], "total_cost_usd": 0.0, "total_tokens": 0,
                "byollm_count": 0, "total_actions": 0}

    items = []
    total_cost_usd = 0.0
    total_tokens = 0
    byollm_count = 0
    for row in rows:
        per_purpose_raw = row[11]
        per_purpose = {}
        if per_purpose_raw:
            try:
                per_purpose = _json.loads(per_purpose_raw)
            except Exception:
                per_purpose = {}
        cost_usd = float(row[12]) if row[12] is not None else 0.0
        tokens = int(row[10] or 0)
        is_byollm = bool(row[13])
        if is_byollm:
            byollm_count += 1
        total_cost_usd += cost_usd
        total_tokens += tokens
        items.append({
            "trace_id": row[0],
            "chain_id": row[1],
            "app_id": row[2],
            "tool_name": row[3],
            "action_type": row[4],
            "status": row[5],
            "duration_ms": int(row[6] or 0),
            "llm_provider": row[7],
            "llm_model": row[8],
            "llm_total_calls": int(row[9] or 0),
            "llm_total_tokens": tokens,
            "llm_per_purpose": per_purpose,
            "llm_total_cost_usd": cost_usd,
            "is_byollm_chain": is_byollm,
            "created_at": row[14].isoformat() if row[14] else "",
        })

    return {
        "actions": items,
        "total_cost_usd": round(total_cost_usd, 4),
        "total_tokens": total_tokens,
        "byollm_count": byollm_count,
        "total_actions": len(items),
    }
