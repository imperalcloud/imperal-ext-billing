"""Time formatting and label humanizers for billing views."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("billing.formatting")

_tz_cache: dict[str, str] = {}


async def get_user_timezone(uid: str) -> str:
    """Fetch user's timezone from auth-gw (cached)."""
    if not uid:
        return "UTC"
    if uid in _tz_cache:
        return _tz_cache[uid]
    try:
        import httpx
        gw = os.environ.get("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
        token = os.environ.get("AUTH_SERVICE_TOKEN", "")
        async with httpx.AsyncClient(base_url=gw, timeout=5) as c:
            r = await c.get(f"/v1/users/{uid}", headers={"X-Service-Token": token})
            if r.status_code == 200:
                attrs = r.json().get("attributes") or {}
                tz = attrs.get("timezone", "UTC")
                _tz_cache[uid] = tz
                return tz
    except Exception:
        pass
    _tz_cache[uid] = "UTC"
    return "UTC"


def format_time(utc_str: str, tz_name: str = "UTC") -> str:
    """Convert UTC datetime string to user's timezone. Returns 'Apr 15, 14:32'."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        if "T" in utc_str:
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        return local.strftime("%b %d, %H:%M")
    except Exception:
        return utc_str[:16] if len(utc_str) > 16 else utc_str


def format_time_full(utc_str: str, tz_name: str = "UTC") -> str:
    """Full datetime in user timezone: 'Apr 15, 2026 14:32:05'."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        if "T" in utc_str:
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        return local.strftime("%b %d, %Y %H:%M:%S")
    except Exception:
        return utc_str[:19] if len(utc_str) > 19 else utc_str


def humanize_tool(tool_name: str, app_id: str = "") -> str:
    """Convert tool_name to human-readable: tool_notes_chat → 'Notes Chat'."""
    if not tool_name:
        return app_id.replace("-", " ").replace("_", " ").title() if app_id else "—"
    name = tool_name
    for prefix in ("tool_", "skeleton_", "__panel__"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").replace("-", " ").title()


def humanize_reason(reason: str, amount: int = 0) -> str:
    """Convert reason code to friendly label."""
    labels = {
        "action": "Used extension",
        "topup": "Top-up",
        "commission": "Platform fee",
        "adjustment": "Adjustment",
        "refund": "Refund",
        "plan_credit": "Plan credit",
        "bonus": "Bonus",
    }
    return labels.get(reason, reason.replace("_", " ").title())
