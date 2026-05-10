"""Billing · shared dashboard tab helpers (split from panels_tabs.py).

Contains the period selector + period list used by every tab builder.
Lives in its own module so panels_tabs.py and panels_tabs_llm.py can both
import it without circular dependency.
"""
from __future__ import annotations

from imperal_sdk import ui


_PERIODS = [
    ("today", "Today"),
    ("7d", "7 Days"),
    ("30d", "30 Days"),
    ("all", "All Time"),
]


def _period_selector(current: str, tab: str):
    buttons = []
    for val, label in _PERIODS:
        buttons.append(ui.Button(
            label, size="sm",
            variant="primary" if current == val else "ghost",
            on_click=ui.Call(
                "__panel__dashboard",
                tab=tab, period=val,
                view="", event_id="", app_id="",
            ),
        ))
    return ui.Stack(direction="h", gap=1, children=buttons)
