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

_PLAN_ORDER = {"free": 0, "starter": 1, "pro": 2, "business": 3, "enterprise": 4}


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
    expired = _is_expired(sub.expires_at)
    pending_cancel = bool(getattr(sub, "cancel_at_period_end", False))
    status_badge = (ui.Badge("Expired", color="red") if expired
                    else ui.Badge(sub.status, color="green" if sub.status == "active" else "yellow"))
    children = [
        ui.Stack(direction="h", gap=1, children=[
            ui.Badge(sub.plan.title(), color="blue"),
            status_badge,
        ]),
        ui.KeyValue(items=[
            {"key": "Plan", "value": sub.plan.title()},
            {"key": "Status", "value": sub.status},
            {"key": "Renews", "value": sub.expires_at or "—"},
        ]),
    ]
    # Scheduled-cancellation banner — surfaces the effective date and a Resume action.
    if pending_cancel:
        children.append(ui.Alert(
            type="warning", title="Cancellation scheduled",
            message=f"Your {sub.plan} plan is set to cancel on {sub.expires_at}. Resume to keep it."))
    # Upgrade/downgrade controls vs the catalog (charges off-session against the saved default card).
    cat = catalog if catalog is not None else await ad.fetch_plan_catalog(ctx)
    cur_rank = _PLAN_ORDER.get((sub.plan or "").lower(), 0)
    btns = []
    for plan in cat:
        pid = plan.get("id") or plan.get("name") or ""
        rank = _PLAN_ORDER.get(pid.lower(), -1)
        if rank < 0 or pid.lower() == (sub.plan or "").lower():
            continue
        if rank > cur_rank:
            btns.append(ui.Button(label=f"Upgrade to {pid.title()}", icon="ArrowUpCircle",
                                  variant="primary", size="sm",
                                  on_click=ui.Call("upgrade_plan", plan_id=pid, period="monthly")))
        else:
            btns.append(ui.Button(label=f"Downgrade to {pid.title()}", icon="ArrowDownCircle",
                                  variant="secondary", size="sm",
                                  on_click=ui.Call("downgrade_plan", plan_id=pid, period="monthly")))
    if pending_cancel:
        # Pending cancellation: offer Resume instead of Cancel (write; confirm gate auto-fires).
        btns.append(ui.Button("Resume subscription", icon="RotateCcw", variant="primary", size="sm",
                              on_click=ui.Call("resume_subscription")))
    elif sub.status == "active" and (sub.plan or "").lower() not in ("free", "unknown"):
        # Cancel plan (destructive; confirm gate auto-fires) — only for an active PAID plan.
        btns.append(ui.Button("Cancel plan", icon="XCircle", variant="danger", size="sm",
                              on_click=ui.Call("cancel_subscription")))
    if btns:
        children.append(ui.Stack(direction="h", gap=1, children=btns))
    return [ui.Card(title="Subscription", content=ui.Stack(direction="v", gap=2, children=children))]


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
    return [ui.Card(title="Tokens", content=ui.Stack(direction="v", gap=2, children=children))]


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
