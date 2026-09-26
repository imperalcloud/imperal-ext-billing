"""Token, history and billing profile section builders for panels_account."""
from __future__ import annotations

import logging
from imperal_sdk import ui
from app import _user_id
import account_data as ad
import queries

log = logging.getLogger("ext.billing.panels_account")


async def build_tokens_section(ctx):
    """Crystal-clear human-first tokens & monthly spending overview.
    
    Shows:
    - Current token balance + progress towards monthly cap
    - Spent this month (30d) & spent today
    - 1-click token top-up options ($1 per 1,000 credits)
    - Auto top-up status & configuration
    """
    bal = await ctx.billing.get_balance()
    if ad.balance_unavailable(bal):
        return [ui.Alert(title="Balance unavailable", message="Could not load your credit balance.", type="warning")]
    
    uid = _user_id(ctx)
    spent_month = 0
    spent_today = 0
    try:
        m_stats = await queries.get_spending_aggregation(uid, "30d")
        spent_month = m_stats.get("total_spent", 0)
        t_stats = await queries.get_spending_aggregation(uid, "today")
        spent_today = t_stats.get("total_spent", 0)
    except Exception as e:
        log.debug("Spending aggregation fetch skipped or failed: %s", e)

    cap_val = bal.cap or 0
    pct = int(round(100 * bal.balance / cap_val)) if cap_val else 100
    color = "green" if pct > 40 else ("yellow" if pct > 15 else "red")
    
    # ── Top Headline Stats: Balance, Spent this month, Spent today ──
    stat_items = [
        ui.Stat(label="Credit balance", value=f"{bal.balance:,}", icon="Zap", color="green"),
        ui.Stat(label="Spent this month", value=f"-{spent_month:,} credits", icon="TrendingDown", color="blue"),
        ui.Stat(label="Spent today", value=f"-{spent_today:,} credits", icon="Clock"),
    ]
    
    children = [
        ui.Stack(direction="h", gap=2, children=stat_items),
        ui.Progress(value=pct, color=color),
        ui.Text(f"{bal.balance:,} / {cap_val:,} credits available this billing cycle"),
    ]
    
    if pct <= 15 and cap_val > 0:
        children.append(ui.Alert(
            title="Low balance",
            message="Your credit balance is running low. Top up below or turn on auto top-up to avoid service pauses.",
            type="warning"
        ))
        
    children.append(ui.Text("$1 per 1,000 credits — spent on Webbee actions, AI models and automations."))
    
    # ── Buy Credits Preset Form ──
    _buy_form = ui.Form(
        children=[
            ui.Select(
                param_name="tokens",
                value="10000",
                options=[
                    {"value": str(n), "label": f"{n:,} credits — ${n // 1000}"}
                    for n in (5000, 10000, 25000, 50000, 100000, 250000)
                ]
            ),
        ],
        action="buy_tokens",
        submit_label="Buy credits"
    )
    _buy_form.props["confirm"] = (
        "Buy these credits now? Your saved payment method will be charged at $1 per 1,000 credits."
    )
    children.append(_buy_form)
    
    # ── Auto Top-up Controls ──
    at = await ctx.billing.get_auto_topup()
    children.append(ui.Badge(
        "Auto top-up on" if at.enabled else "Auto top-up off",
        color="green" if at.enabled else "gray"
    ))
    _at_form = ui.Form(
        children=[
            ui.Toggle(param_name="enabled", label="Auto top-up", value=bool(at.enabled)),
            ui.Select(
                param_name="recharge_tokens",
                value=str(at.recharge_tokens or 20000),
                options=[
                    {"value": "20000", "label": "20,000"},
                    {"value": "50000", "label": "50,000"},
                ]
            ),
            ui.Select(
                param_name="threshold_pct",
                value=str(at.threshold_pct or 10),
                options=[
                    {"value": "10", "label": "10%"},
                    {"value": "20", "label": "20%"},
                ]
            ),
        ],
        action="set_auto_topup",
        submit_label="Save auto top-up"
    )
    _at_form.props["confirm"] = (
        "Save auto top-up? When on, your saved payment method is charged automatically whenever your balance runs low."
    )
    children.append(_at_form)
    
    return [ui.Card(
        title="Credits",
        subtitle="Usage credits — spent on Webbee actions; top up here.",
        content=ui.Stack(direction="v", gap=2, children=children)
    )]


async def build_history_section(ctx):
    """Payment history section."""
    pays = await ctx.billing.list_payments(limit=50, offset=0)
    if not pays:
        return [ui.Card(
            title="Payment history",
            subtitle="All past subscription invoices and token top-up charges",
            content=ui.Empty(message="No payments yet", icon="Receipt")
        )]
    items = []
    for p in pays:
        amt = f"${(p.amount_cents or 0) / 100:,.2f}"
        sub = f"{(p.type or "payment").title()} · {p.status} · {(p.created_at or "")[:10]}"
        on_click = ui.Open(url=p.receipt_url) if p.receipt_url else None
        items.append(ui.ListItem(id=p.payment_intent_id or amt, title=amt, subtitle=sub, on_click=on_click))
    return [ui.Card(
        title="Payment history",
        subtitle="All past subscription invoices and token top-up charges (click to view receipt)",
        content=ui.List(items=items)
    )]


async def build_profile_section(ctx):
    """Billing profile section."""
    prof = ad.read_billing_profile(ctx)
    return [ui.Card(
        title="Billing profile",
        subtitle="Company and contact details used for official tax invoices and receipts.",
        content=ui.Form(
            children=[
                ui.Input(param_name="name", placeholder="Full Name / Contact", value=prof["name"]),
                ui.Input(param_name="company", placeholder="Company / Legal Entity", value=prof["company"]),
                ui.Input(param_name="vat", placeholder="VAT / GST / Tax ID", value=prof["vat"]),
                ui.Input(param_name="country", placeholder="Country", value=prof["country"]),
            ],
            action="update_billing_profile",
            submit_label="Save"
        )
    )]
