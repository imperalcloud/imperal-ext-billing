"""Account-first billing panel sections (Layer 2d). Pure builders returning
ui.* node lists. Reads via ctx.billing (safe-degrading) + account_data. Card
capture (Add card / invoices via Stripe Customer Portal) + Buy-tokens are added
in Phase 2 (panels_account_capture wiring)."""
import logging
from datetime import datetime, timezone
from imperal_sdk import ui
from app import _user_id
import account_data as ad

log = logging.getLogger("ext.billing.panels_account")

# Self-service plan changes are restricted to Pro and Business. Free is reached
# only by cancelling (period-end revert), and Enterprise is contract-only — so
# neither appears in the plan-change dropdown. Keep this in sync with the
# name-based guard in handlers_money._change_plan.
_SELF_SERVICE_PLANS = ("pro", "business")

# Priced, self-serve renewable plans (chargeable on a saved card). Used ONLY to
# decide the "Expired" badge — a contract plan (enterprise, price 0) or free is
# never flagged Expired on a stale date. The Renew BUTTON itself is shown for any
# active paid plan; the gateway returns "managed by contract" for a price-0 renew.
_RENEWABLE_PLANS = ("starter", "pro", "business")

# Plans with no paid subscription to cancel.
_FREE_LIKE = ("free", "unknown")


def _confirm(action, message: str):
    """Attach a confirmation prompt to a ui.Call so the panel asks BEFORE firing
    it (no accidental charges/changes). The panel frontend honours a top-level
    `confirm` on any action — the same field DList already uses. Works because
    UIAction.to_dict() spreads its params to the action's top level, so adding it
    to `params` surfaces it as `action.confirm` with NO SDK change needed."""
    action.params["confirm"] = message
    return action


def _is_expired(expires_at) -> bool:
    """True if the ISO `expires_at` is in the past. Parse errors → not expired."""
    if not expires_at:
        return False
    try:
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


async def build_subscription_section(ctx, catalog=None):
    sub = await ctx.billing.get_subscription()
    if ad.subscription_unavailable(sub):
        return [ui.Alert(title="Billing unavailable", message="Could not load your subscription. Try again shortly.", type="warning")]
    plan_l = (sub.plan or "").lower()
    pending_cancel = bool(getattr(sub, "cancel_at_period_end", False))
    is_paid = plan_l not in _FREE_LIKE
    renewable = plan_l in _RENEWABLE_PLANS
    # Only a self-serve, priced plan can "lapse" in the panel: it's renewable by
    # charging a saved card. A contract plan (enterprise, price 0) keeps its DB
    # status — its renewal happens off self-serve — so it never shows Expired/Renew.
    lapsed = renewable and _is_expired(sub.expires_at)
    status_badge = (ui.Badge("Expired", color="red") if lapsed
                    else ui.Badge(sub.status, color="green" if sub.status == "active" else "yellow"))
    # When lapsed the Status line must agree with the (red) badge, not the raw "active".
    status_value = "Expired" if lapsed else sub.status
    # HOW this subscription settles — stated by the gateway, never guessed here
    # (2026-08-13, contract: auth-gw app/billing/billing_mode.py). A contract or
    # comped seat must never be shown card-shaped copy: it is not on a card.
    mode = (getattr(sub, "billing_mode", "card") or "card").lower()
    off_stripe = mode in ("manual", "free")
    kv = [
        {"key": "Plan", "value": sub.plan.title()},
        {"key": "Status", "value": status_value},
    ]
    if mode == "manual":
        kv.append({"key": "Billing", "value": "By invoice / agreement (no card needed)"})
    elif mode == "free":
        kv.append({"key": "Billing", "value": "Included — nothing to pay"})
    # "Renews" is a card promise. For an off-Stripe seat the date is a period
    # end the owner controls, and a blank date genuinely means "no end date" —
    # saying "—" there would read as broken rather than as unlimited.
    if off_stripe:
        kv.append({"key": "Period ends", "value": sub.expires_at or "No end date"})
    else:
        kv.append({"key": "Renews", "value": sub.expires_at or "—"})
    children = [
        ui.Stack(direction="h", gap=1, children=[
            ui.Badge(sub.plan.title(), color="blue"),
            status_badge,
        ]),
        ui.KeyValue(items=kv),
    ]
    if off_stripe:
        note = (getattr(sub, "billing_note", None) or "").strip()
        children.append(ui.Alert(
            type="info",
            title=("Billed by agreement" if mode == "manual" else "Complimentary access"),
            message=(
                (f"{note} — no card is required on this account."
                 if note else
                 "This account is settled directly with us, not by card — "
                 "there is nothing to add here.")
                if mode == "manual" else
                (f"{note} — no payment is required on this account."
                 if note else
                 "Your access is on the house — no card, no charges.")
            )))
    # Scheduled-cancellation banner — surfaces the effective date and a Resume action.
    if pending_cancel:
        children.append(ui.Alert(
            type="warning", title="Cancellation scheduled",
            message=f"Your {sub.plan} plan is set to cancel on {sub.expires_at}. Resume to keep it."))
    # Plan controls split by WHO the user is (mirrors the gateway's change-plan
    # contract — a first subscription MUST go through checkout, change-plan 409s):
    #   * free/unknown (no paid sub)  -> Subscribe buttons emitting `__checkout__`
    #     (the panel shell intercepts it and opens the native Stripe checkout
    #     modal — card capture happens in the browser, never here);
    #   * everyone else (paid/contract) -> the change-plan dropdown, unchanged
    #     (the gateway charges a prorated upgrade / schedules a downgrade;
    #     enterprise keeps all three controls per Valentin 2026-06-16).
    cat = catalog if catalog is not None else await ad.fetch_plan_catalog(ctx)
    if not is_paid and not pending_cancel:
        # First subscription: one button per self-service plan. ui.Call params
        # spread to the action's top level, so the shell reads plan/period
        # directly. No confirm layer — the checkout modal itself shows the
        # price and takes the card; nothing is charged by this click alone.
        _subscribable = sorted(
            (p for p in cat if (p.get("name") or "").lower() in _SELF_SERVICE_PLANS),
            key=lambda p: p.get("price") or 0,
        )
        sub_btns = [
            ui.Button(
                f"Subscribe to {(p.get('name') or '').title()} — ${p.get('price')}/mo",
                icon="Zap", variant="primary", size="sm",
                on_click=ui.Call("__checkout__", plan=(p.get("name") or "").lower(),
                                 period="monthly"))
            for p in _subscribable
        ]
        if sub_btns:
            children.append(ui.Text("Pick a plan — checkout takes one card step:"))
            children.append(ui.Stack(direction="h", gap=1, children=sub_btns))
    else:
        selectable = sorted(
            (p for p in cat
             if (p.get("name") or "").lower() in _SELF_SERVICE_PLANS
             and (p.get("name") or "").lower() != (sub.plan or "").lower()),
            key=lambda p: p.get("price") or 0,
        )
        plan_options = [
            {"value": p.get("id") or p.get("name"),
             "label": f"{(p.get('name') or '').title()} — ${p.get('price')}/mo"}
            for p in selectable
        ]
        # Plan-change stays available whether the plan is active or lapsed — only a
        # pending cancellation hides it (Resume is the one action that makes sense there).
        if plan_options and not pending_cancel:
            # Preselect the first option (value=) so plan_id is ALWAYS submitted — an
            # unpicked dropdown otherwise submits nothing → "plan_id Field required" 500.
            _change_form = ui.Form(
                children=[ui.Select(param_name="plan_id", value=plan_options[0]["value"],
                                    placeholder="Change plan…", options=plan_options)],
                action="change_plan", submit_label="Change plan")
            # Confirm before changing plan (DForm asks first — see frontend confirm prop).
            _change_form.props["confirm"] = ("Change your plan? An upgrade is charged now (prorated); "
                                             "a downgrade applies at the end of the current period.")
            children.append(_change_form)
    # Active paid plan → ALWAYS the three management actions together (Valentin,
    # 2026-06-16): Change plan (the dropdown above) + Cancel plan + Renew plan.
    # Each confirm-gates automatically (write/destructive). The gateway returns a
    # clean message for the no-op cases so a button never lies or crashes: Renew on
    # a still-active sub → "nothing to renew"; Renew on a contract plan (enterprise,
    # price 0) → "managed by contract — contact us to renew".
    btns = []
    if pending_cancel:
        # A cancellation is already scheduled — the actionable button is Resume (undo).
        btns.append(ui.Button("Resume subscription", icon="RotateCcw", variant="primary", size="sm",
                              on_click=_confirm(ui.Call("resume_subscription"),
                                                "Resume your subscription and keep this plan?")))
    elif is_paid and sub.status == "active":
        btns.append(ui.Button("Cancel plan", icon="XCircle", variant="danger", size="sm",
                              on_click=_confirm(ui.Call("cancel_subscription"),
                                                "Cancel your plan? It stays active until the period ends, then reverts to Free.")))
        btns.append(ui.Button("Renew plan", icon="RefreshCw", variant="primary", size="sm",
                              on_click=_confirm(ui.Call("renew_subscription"),
                                                "Renew now? Your saved payment method will be charged for a fresh period.")))
    if btns:
        children.append(ui.Stack(direction="h", gap=1, children=btns))
    return [ui.Card(
        title="Plan & access",
        subtitle="Your subscription = panel access, features, and your monthly credit allowance + cap.",
        content=ui.Stack(direction="v", gap=2, children=children))]


async def build_payment_methods_section(ctx):
    # Does this account settle by card at all? (2026-08-13) A 'manual'
    # (invoice/agreement) or 'free' seat does not, so the whole card section must
    # stop implying otherwise: "No saved cards yet" reads as a demand, and it is
    # what left contract customers re-entering a card that was never the point.
    off_stripe = False
    try:
        _sub = await ctx.billing.get_subscription()
        off_stripe = (getattr(_sub, "billing_mode", "card") or "card").lower() in ("manual", "free")
    except Exception as e:
        # Never let a billing read failure hide card management from someone who
        # DOES pay by card — fall back to the card-shaped view.
        log.warning("payment methods: subscription read failed: %s", e)

    # Stripe Customer Portal session for card capture / invoices (per-request URL;
    # create_billing_portal_session RAISES on error → fall back to an info Alert).
    portal_url = ""
    try:
        portal_url = await ctx.billing.create_billing_portal_session()
    except Exception as e:
        log.warning("portal session failed: %s", e)
    manage_btn = (ui.Button("Manage cards & invoices", icon="ExternalLink", variant="primary",
                            on_click=ui.Open(url=portal_url))
                  if portal_url else
                  ui.Alert(title="Card management", message="Temporarily unavailable.", type="info"))

    cards = await ctx.billing.list_payment_methods()  # safe-degrades to []
    if not cards:
        # No card AND none needed: say so plainly instead of showing an empty
        # slot that looks like an unfinished setup step.
        if off_stripe:
            return [ui.Card(title="Payment methods", content=ui.Stack(direction="v", gap=2, children=[
                ui.Alert(type="info", title="No card needed",
                         message="This account is billed by agreement, so there is nothing to "
                                 "set up here. You can still add a card if you prefer to use one."),
                manage_btn,
            ]))]
        return [ui.Card(title="Payment methods", content=ui.Stack(direction="v", gap=2, children=[
            ui.Empty(message="No saved cards yet", icon="CreditCard"),
            manage_btn,
        ]))]
    items = []
    only_one = len(cards) <= 1
    for c in cards:
        # ListItem.actions is a list of DICTS (icon/label/on_click/confirm), NOT ui.Button nodes.
        actions = []
        if not c.is_default:
            actions.append({"label": "Make default", "icon": "Star",
                            "on_click": ui.Call("set_default_payment_method", pm_id=c.id)})
        # Never offer Remove on the ONLY payment method — at least one must stay on
        # file (the gateway also enforces this with a 409 backstop).
        if not only_one:
            actions.append({"label": "Remove", "icon": "Trash2", "confirm": "Remove this payment method?",
                            "on_click": ui.Call("remove_payment_method", pm_id=c.id)})
        # Card PMs show brand ···· last4 + expiry; non-card PMs (e.g. Stripe Link)
        # expose no raw card number — label them honestly so the user still sees
        # that a payment method IS on file.
        if c.last4:
            title = f"{(c.brand or 'Card').title()} ···· {c.last4}"
            subtitle = (f"exp {c.exp_month:02d}/{c.exp_year}"
                        if c.exp_month and c.exp_year else "Saved card")
        else:
            title = "Stripe Link" if (c.brand or "").lower() == "link" else (c.brand or "Payment method").title()
            subtitle = "Saved payment method"
        items.append(ui.ListItem(
            id=c.id,   # ListItem REQUIRES id (first positional, no default)
            title=title,
            subtitle=subtitle,
            badge=ui.Badge("Default", color="green") if c.is_default else None,
            actions=actions,
        ))
    return [ui.Card(title="Payment methods",
                    content=ui.Stack(direction="v", gap=2, children=[ui.List(items=items), manage_btn]))]


from panels_account_sections import (
    build_tokens_section, build_history_section, build_profile_section,
)
