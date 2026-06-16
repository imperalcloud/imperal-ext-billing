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
    children = [
        ui.Stack(direction="h", gap=1, children=[
            ui.Badge(sub.plan.title(), color="blue"),
            status_badge,
        ]),
        ui.KeyValue(items=[
            {"key": "Plan", "value": sub.plan.title()},
            {"key": "Status", "value": status_value},
            {"key": "Renews", "value": sub.expires_at or "—"},
        ]),
    ]
    # Scheduled-cancellation banner — surfaces the effective date and a Resume action.
    if pending_cancel:
        children.append(ui.Alert(
            type="warning", title="Cancellation scheduled",
            message=f"Your {sub.plan} plan is set to cancel on {sub.expires_at}. Resume to keep it."))
    # ONE plan-change control: a dropdown of the OTHER plans submitting to change_plan.
    # The gateway decides upgrade-vs-downgrade by price. Option value = the catalog
    # `id` (a UUID, which change_plan resolves by Plan.id); label = plan name + price.
    cat = catalog if catalog is not None else await ad.fetch_plan_catalog(ctx)
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


async def build_tokens_section(ctx):
    bal = await ctx.billing.get_balance()
    if ad.balance_unavailable(bal):
        return [ui.Alert(title="Balance unavailable", message="Could not load your credit balance.", type="warning")]
    pct = int(round(100 * bal.balance / bal.cap)) if bal.cap else 0
    color = "green" if pct > 40 else ("yellow" if pct > 15 else "red")
    children = [
        ui.Stat(label="Credit balance", value=f"{bal.balance:,}", icon="Zap"),
        ui.Progress(value=pct, color=color),
        ui.Text(f"{bal.balance:,} / {bal.cap:,} credits"),
    ]
    if pct <= 15:
        children.append(ui.Alert(title="Low balance", message="Your credit balance is running low.", type="warning"))
    # Buy-tokens (off-session charge to the saved default card; confirm gate auto-fires).
    # Use a Select of presets, NOT a free-form Input: a Select's value= reliably enters
    # the form submission, whereas an untouched Input's prefill does NOT (that 500'd
    # buy_tokens — "tokens Field required"). Any custom amount is available by asking
    # Webbee in chat ("buy 37000 tokens"); buy_tokens(tokens:int) accepts any int.
    children.append(ui.Text("$1 per 1,000 credits"))
    _buy_form = ui.Form(
        children=[
            ui.Select(param_name="tokens", value="10000", options=[
                {"value": str(n), "label": f"{n:,} credits — ${n // 1000}"}
                for n in (5000, 10000, 25000, 50000, 100000, 250000)
            ]),
        ],
        action="buy_tokens", submit_label="Buy credits")
    # Confirm before charging (DForm asks first).
    _buy_form.props["confirm"] = ("Buy these credits now? Your saved payment method will be "
                                  "charged at $1 per 1,000 credits.")
    children.append(_buy_form)
    # Auto-top-up: current state + a save form (set_auto_topup is write; confirm gate auto-fires).
    at = await ctx.billing.get_auto_topup()  # AutoTopupSettings; safe-degrades to disabled defaults
    children.append(ui.Badge("Auto top-up on" if at.enabled else "Auto top-up off",
                             color="green" if at.enabled else "gray"))
    _at_form = ui.Form(
        children=[
            ui.Toggle(param_name="enabled", label="Auto top-up", value=bool(at.enabled)),
            ui.Select(param_name="recharge_tokens", value=str(at.recharge_tokens or 20000), options=[
                {"value": "20000", "label": "20,000"},
                {"value": "50000", "label": "50,000"},
            ]),
            ui.Select(param_name="threshold_pct", value=str(at.threshold_pct or 10), options=[
                {"value": "10", "label": "10%"},
                {"value": "20", "label": "20%"},
            ]),
        ],
        action="set_auto_topup", submit_label="Save auto top-up")
    # Confirm — enabling auto top-up means the saved card is charged automatically.
    _at_form.props["confirm"] = ("Save auto top-up? When on, your saved payment method is charged "
                                 "automatically whenever your balance runs low.")
    children.append(_at_form)
    return [ui.Card(
        title="Credits",
        subtitle="Usage credits — spent on Webbee actions; top up here.",
        content=ui.Stack(direction="v", gap=2, children=children))]


async def build_history_section(ctx):
    pays = await ctx.billing.list_payments(limit=50, offset=0)  # safe-degrades to []
    if not pays:
        return [ui.Card(title="Payment history", content=ui.Empty(message="No payments yet", icon="Receipt"))]
    items = []
    for p in pays:
        amt = f"${(p.amount_cents or 0) / 100:,.2f}"
        sub = f"{(p.type or 'payment').title()} · {p.status} · {(p.created_at or '')[:10]}"
        # ListItem has no free-form child slot; the receipt opens via on_click (new tab).
        on_click = ui.Open(url=p.receipt_url) if p.receipt_url else None
        items.append(ui.ListItem(id=p.payment_intent_id or amt, title=amt, subtitle=sub, on_click=on_click))
    return [ui.Card(title="Payment history", content=ui.List(items=items))]


async def build_profile_section(ctx):
    # Editable billing/VAT profile (update_billing_profile is write; confirm gate auto-fires).
    prof = ad.read_billing_profile(ctx)
    return [ui.Card(title="Billing profile", content=ui.Form(
        children=[
            ui.Input(param_name="name", placeholder="Name", value=prof["name"]),
            ui.Input(param_name="company", placeholder="Company", value=prof["company"]),
            ui.Input(param_name="vat", placeholder="VAT / GST", value=prof["vat"]),
            ui.Input(param_name="country", placeholder="Country", value=prof["country"]),
        ],
        action="update_billing_profile", submit_label="Save"))]
