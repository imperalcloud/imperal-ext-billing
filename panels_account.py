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

# Priced, self-serve renewable plans — chargeable on a saved card, so they can
# "lapse" and offer Renew. Enterprise is contract-only (price 0 in the catalog)
# and free/micro carry no charge: none of these ever show an Expired/Renew state.
# Keep in sync with the priced plans in the catalog (and the gateway renew guard).
_RENEWABLE_PLANS = ("starter", "pro", "business")

# Plans with no paid subscription to cancel.
_FREE_LIKE = ("free", "unknown")


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
        children.append(ui.Form(
            children=[ui.Select(param_name="plan_id", placeholder="Change plan…", options=plan_options)],
            action="change_plan", submit_label="Change plan"))
    # Action buttons COEXIST (no longer mutually exclusive — that was the regression):
    #   • pending cancel  → Resume only
    #   • lapsed paid plan → Renew (instant recovery by charging the saved card)
    #   • any active paid plan (incl. lapsed) → Cancel
    btns = []
    if pending_cancel:
        # Pending cancellation: offer Resume instead of Cancel (write; confirm gate auto-fires).
        btns.append(ui.Button("Resume subscription", icon="RotateCcw", variant="primary", size="sm",
                              on_click=ui.Call("resume_subscription")))
    else:
        if lapsed:
            # Lapsed self-serve PAID plan: offer Renew (write; confirm gate auto-fires).
            btns.append(ui.Button("Renew subscription", icon="RefreshCw", variant="primary", size="sm",
                                  on_click=ui.Call("renew_subscription")))
        if is_paid and sub.status == "active":
            # Cancel plan (destructive; confirm gate auto-fires) — paid plans only.
            btns.append(ui.Button("Cancel plan", icon="XCircle", variant="danger", size="sm",
                                  on_click=ui.Call("cancel_subscription")))
    if btns:
        children.append(ui.Stack(direction="h", gap=1, children=btns))
    return [ui.Card(
        title="Plan & access",
        subtitle="Your subscription = panel access, features, and your monthly token allowance + cap.",
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
    for c in cards:
        # ListItem.actions is a list of DICTS (icon/label/on_click/confirm), NOT ui.Button nodes.
        actions = []
        if not c.is_default:
            actions.append({"label": "Make default", "icon": "Star",
                            "on_click": ui.Call("set_default_payment_method", pm_id=c.id)})
        actions.append({"label": "Remove", "icon": "Trash2", "confirm": "Remove this card?",
                        "on_click": ui.Call("remove_payment_method", pm_id=c.id)})
        items.append(ui.ListItem(
            id=c.id,   # ListItem REQUIRES id (first positional, no default)
            title=f"{(c.brand or 'Card').title()} ···· {c.last4}",
            subtitle=f"exp {c.exp_month:02d}/{c.exp_year}",
            badge=ui.Badge("Default", color="green") if c.is_default else None,
            actions=actions,
        ))
    return [ui.Card(title="Payment methods",
                    content=ui.Stack(direction="v", gap=2, children=[ui.List(items=items), manage_btn]))]


async def build_tokens_section(ctx):
    bal = await ctx.billing.get_balance()
    if ad.balance_unavailable(bal):
        return [ui.Alert(title="Balance unavailable", message="Could not load your token balance.", type="warning")]
    pct = int(round(100 * bal.balance / bal.cap)) if bal.cap else 0
    color = "green" if pct > 40 else ("yellow" if pct > 15 else "red")
    children = [
        ui.Stat(label="Token balance", value=f"{bal.balance:,}", icon="Zap"),
        ui.Progress(value=pct, color=color),
        ui.Text(f"{bal.balance:,} / {bal.cap:,} tokens"),
    ]
    if pct <= 15:
        children.append(ui.Alert(title="Low balance", message="Your token balance is running low.", type="warning"))
    # Buy-tokens (off-session charge to the saved default card; confirm gate auto-fires).
    # Free-form amount — buy_tokens(tokens:int) accepts any int (pydantic coerces the string).
    children.append(ui.Form(
        children=[
            ui.Input(param_name="tokens", value="10000", placeholder="Tokens (e.g. 25000)"),
            ui.Text("$1 per 1,000 tokens"),
        ],
        action="buy_tokens", submit_label="Buy tokens"))
    # Auto-top-up: current state + a save form (set_auto_topup is write; confirm gate auto-fires).
    at = await ctx.billing.get_auto_topup()  # AutoTopupSettings; safe-degrades to disabled defaults
    children.append(ui.Badge("Auto top-up on" if at.enabled else "Auto top-up off",
                             color="green" if at.enabled else "gray"))
    children.append(ui.Form(
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
        action="set_auto_topup", submit_label="Save auto top-up"))
    return [ui.Card(
        title="Tokens",
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
