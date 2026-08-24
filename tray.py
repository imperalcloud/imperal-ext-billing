"""Billing · System tray item (credit balance).

WHY THIS FILE EXISTS
--------------------
The credit counter in the Panel's system tray used to be a hard-coded React
component (`BalanceCounter`) wrapped in a hard-coded `<Link href="/ext/billing">`
inside the Panel's own built-in tray list. The Panel had to know that an app
called "billing" exists, that it owns a number called "balance", and where
clicking that number should go.

That is backwards. `@ext.tray` is the public contract for the tray, and the
app that owns the number is the app that should publish it. While the
platform's own apps bypassed that contract, it stayed theoretical -- a
third-party developer could never have reproduced what billing had.

The balance is read through `ctx.billing.get_balance()`, the same call the
skeleton uses, so the tray and the AI context cannot disagree about how much
credit the user has.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext

log = logging.getLogger("billing")


def _tone(balance: int, cap: int) -> str:
    """Colour by URGENCY, not by taste.

    The thresholds mirror the skeleton's `alert_level` exactly (empty /
    critical <5% / low <20%) so a user cannot see a calm grey pill in the tray
    while the assistant is telling them their balance is critical.

    HEALTHY IS GREEN, NOT GREY. The built-in counter this replaced drew a
    healthy balance in emerald and only cooled toward amber and red as it
    fell; returning "gray" here made the glyph beside the digits go out
    entirely, because 'gray' is an alias for `muted` and `muted` is dimmer
    than the strip's own ink rather than equal to it. The tray then read as
    black-and-white for every user whose balance was fine -- which is most of
    them, most of the time -- and the at-a-glance signal was gone.

    The thresholds themselves are untouched on purpose: they are shared with
    the skeleton, and a second ladder of cut-offs would be free to drift.
    """
    if balance <= 0:
        return "red"
    if cap > 0 and balance < cap * 0.05:
        return "red"
    if cap > 0 and balance < cap * 0.20:
        return "yellow"
    return "green"


def _compact(value: int) -> str:
    """1_240_000 -> '1.2M'. The tray is ~40px wide; a raw integer does not fit.

    This is the same shortening the Panel's own counter did, kept identical on
    purpose: the number in the corner must not visibly change the day it stops
    being hard-coded.
    """
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}M"
        return text.replace(".0M", "M")
    if value >= 1_000:
        text = f"{value / 1_000:.1f}K"
        return text.replace(".0K", "K")
    return str(value)


@ext.tray(
    "balance",
    # "credits", not "Coins": the platform's own credit mark, asked for BY
    # NAME through the host's icon registry. "Coins" was a lucide look-alike
    # picked because a name for the real glyph did not exist yet -- so the
    # number stayed right while the mark silently changed under the user.
    icon="credits",
    tooltip="Credit balance",
    zone="status",
    # The built-in it replaces sat at order 40, and keeping that number means
    # the tray looks identical after the move. A strip that reshuffles itself
    # because an app was re-implemented is a regression the user can see.
    order=40,
    # A balance is READ, not cleared: it belongs beside the glyph in tabular
    # figures, exactly as the built-in counter drew it. On a corner disc a
    # value like "1.2M" is unreadable.
    badge_style="inline",
    # RESTING colour: the state the item is in nearly all of the time, which
    # for a balance is "healthy" -- and healthy is GREEN, the colour the
    # built-in counter used. This is what the item looks like before its
    # handler has read anything: the first frame of a page load, and every
    # frame of a load the tray serves from memory.
    #
    # It was "muted", on the reasoning that a healthy balance is unremarkable.
    # That reasoning was wrong twice over: `muted` is DIMMER than the strip's
    # ink, not equal to it, and the resting colour is not a rare fallback --
    # it is what most users see most of the time.
    icon_color="success",
)
async def tray_balance(ctx, **kwargs) -> ui.UINode:
    """The credit balance, as a pill that turns red before the user runs out."""
    try:
        info = await ctx.billing.get_balance()
        balance = int(getattr(info, "balance", 0) or 0)
        cap = int(getattr(info, "cap", 0) or 0)
    except Exception as exc:
        # A billing read that fails must not blank the tray. Returning no
        # badge leaves a plain icon that still opens the dashboard, which is
        # strictly better than an icon showing a wrong or stale number.
        log.warning("tray: balance fetch failed: %s", exc, exc_info=True)
        return ui.TrayResponse()

    tone = _tone(balance, cap)

    return ui.TrayResponse(
        badge=ui.Badge(value=_compact(balance), color=tone),
        # The GLYPH takes the SAME tone as the number, from the SAME function.
        # Deriving it here rather than re-deciding the thresholds is the whole
        # point: a second ladder of cut-offs would be free to drift out of
        # step with the first, and the day it did, the mark would say "calm"
        # while the digits beside it said "empty". One reading, one colour.
        #
        # The badge vocabulary ('red'/'yellow'/'gray') is accepted for the
        # glyph as an alias, so no translation table is needed here either.
        icon_color=tone,
    )
