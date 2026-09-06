"""Token, history and billing profile section builders for panels_account."""
from __future__ import annotations

from imperal_sdk import ui
import account_data as ad


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
    children.append(ui.Text("$1 per 1,000 credits"))
    _buy_form = ui.Form(
        children=[
            ui.Select(param_name="tokens", value="10000", options=[
                {"value": str(n), "label": f"{n:,} credits — ${n // 1000}"}
                for n in (5000, 10000, 25000, 50000, 100000, 250000)
            ]),
        ],
        action="buy_tokens", submit_label="Buy credits")
    _buy_form.props["confirm"] = ("Buy these credits now? Your saved payment method will be "
                                  "charged at $1 per 1,000 credits.")
    children.append(_buy_form)
    at = await ctx.billing.get_auto_topup()
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
    _at_form.props["confirm"] = ("Save auto top-up? When on, your saved payment method is charged "
                                 "automatically whenever your balance runs low.")
    children.append(_at_form)
    return [ui.Card(
        title="Credits",
        subtitle="Usage credits — spent on Webbee actions; top up here.",
        content=ui.Stack(direction="v", gap=2, children=children))]


async def build_history_section(ctx):
    pays = await ctx.billing.list_payments(limit=50, offset=0)
    if not pays:
        return [ui.Card(title="Payment history", content=ui.Empty(message="No payments yet", icon="Receipt"))]
    items = []
    for p in pays:
        amt = f"${(p.amount_cents or 0) / 100:,.2f}"
        sub = f"{(p.type or 'payment').title()} · {p.status} · {(p.created_at or '')[:10]}"
        on_click = ui.Open(url=p.receipt_url) if p.receipt_url else None
        items.append(ui.ListItem(id=p.payment_intent_id or amt, title=amt, subtitle=sub, on_click=on_click))
    return [ui.Card(title="Payment history", content=ui.List(items=items))]


async def build_profile_section(ctx):
    prof = ad.read_billing_profile(ctx)
    return [ui.Card(title="Billing profile", content=ui.Form(
        children=[
            ui.Input(param_name="name", placeholder="Name", value=prof["name"]),
            ui.Input(param_name="company", placeholder="Company", value=prof["company"]),
            ui.Input(param_name="vat", placeholder="VAT / GST", value=prof["vat"]),
            ui.Input(param_name="country", placeholder="Country", value=prof["country"]),
        ],
        action="update_billing_profile", submit_label="Save"))]
