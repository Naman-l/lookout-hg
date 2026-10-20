"""Agent tool over the Action list: read one item with its computed evidence."""

from __future__ import annotations

from decimal import Decimal

from app.domain.common import AS_OF

from claude_agent_sdk import tool

from ...organism.context import RunContext
from ...organism.schemas import Number
from ...organism.toolkit import READ, refuse, reply
from ..common import Money, Provenance, Quantity, Unknown
from .schema import DateValue


def _as_number(item_key: str, n_id: str, label: str, v) -> Number | None:
    nid = f"item:{item_key}:{n_id}"
    if isinstance(v, Money):
        return Number(id=nid, name=label, value=v.usd if v.usd is not None else v.amount, unit="USD" if v.usd is not None else v.currency, provenance=v.provenance)
    if isinstance(v, Quantity):
        return Number(id=nid, name=label, value=v.ea if v.ea is not None else v.value, unit=v.uom, provenance=v.provenance)
    return None  # an Unknown is not a number


def read_item(it):
    """The item's computed numbers (with stable ids), its open questions and its dates, exactly as the Action list holds them.
    The workflow calls this itself before the model runs, so the model can neither skip nor forget them."""
    numbers, unknowns = [], list(it.unknowns)
    if it.at_stake is not None:
        n = _as_number(it.key, "at_stake", "Money at stake", it.at_stake)
        if n:
            numbers.append(n)
        elif isinstance(it.at_stake, Unknown):
            unknowns.append(it.at_stake)
    dates = {}
    for x in it.numbers:
        if isinstance(x.value, DateValue):  # a date is data to quote, not a figure to cite
            dates[x.label] = x.value.date
            continue
        n = _as_number(it.key, x.id, x.label, x.value)
        if n:
            numbers.append(n)
        elif isinstance(x.value, Unknown):
            unknowns.append(x.value)
    for field, name in (("lines_in_scope", "Open lines under the notice"), ("lines_already_late", "Of those, lines already past their promise date at the data date")):
        if getattr(it, field, None) is not None:  # a count a buyer reads must be a tool's count
            numbers.append(Number(id=f"item:{it.key}:{field}", name=name, value=Decimal(getattr(it, field)), unit="lines",
                                  provenance=Provenance(method="computed", source="action list", row=it.key, rule="counted from the item's own PO lines", by="attention.service")))
    if it.days_left is not None:
        numbers.append(Number(id=f"item:{it.key}:days_left", name="Days left to act", value=Decimal(it.days_left), unit="days",
                              provenance=Provenance(method="computed", source="action list", row=it.key, rule=f"the act-by date minus the data date, {AS_OF.isoformat()}", by="attention.service")))
    return numbers, unknowns, dates


def make_tools(ctx: RunContext, svc):
    @tool(
        "get_item",
        "Read one Action list item: its title, owner, finding, the next action, the date to act by, and the numbers "
        "and open questions code has already computed for it (duty exposure, days left, what is unknown and who owns "
        "it). Use it for any item that is not a supply shortage. Cite its numbers by id. To find an item you have no key for, use list_items. An item key starts with its kind and a colon (for example 'disruption:…', 'deadline:…', 'tariff:…', 'trust:…', 'unknown:…'); a bare supplier or part id is not a key.",
        {"item_key": str},
        annotations=READ,
    )
    async def get_item(args):
        try:
            it = svc.get_item(args["item_key"])
        except KeyError:
            return refuse(f"no item {args['item_key']}: list_items shows the keys that exist")
        numbers, unknowns, dates = read_item(it)
        data = {"key": it.key, "group": it.group, "title": it.title, "owner": it.owner, "finding": it.finding, "next_action": it.next_action,
                "act_by": it.act_by, "dates": dates, "date_ids": {**({f"item:{it.key}:act_by": it.act_by} if it.act_by else {}), **{f"item:{it.key}:{x.id}": x.value.date for x in it.numbers if isinstance(x.value, DateValue)}}, "refs": [{"type": r.type, "id": r.id, "label": r.label} for r in it.refs]}
        short = getattr(it, "robots_short", None) or []
        if short:      # robots short per product and per month, each month on its own: a model must not merge the months
            data["robots_short"] = [{"product": r.product.label or r.product.id, "month": r.month, "robots": r.robots, "short_parts": [p.id for p in r.short_parts]} for r in short]
            for r in short:
                numbers.append(Number(id=f"item:{it.key}:robots_short:{r.product.id}:{r.month}", name=f"{r.product.label or r.product.id} robots short in {r.month}, before stock on hand", value=Decimal(r.robots), unit="robots",
                                      provenance=Provenance(method="computed", source="demand_forecast", row=r.month, rule="the month's planned robots scaled by the share the short parts stop; never added across months", by="attention.service")))
        if getattr(it, "po_lines", None):  # the lines the item is about (e.g. the past-due lines), compact; their numbers are in `numbers`
            data["po_lines"] = [{"po_line": l.ref.id, "part": l.part.id, "supplier": l.supplier.id, "buyer": l.buyer, "promise": l.promise_date, "days_past_due": l.days_past_due} for l in it.po_lines[:25]]
            data["po_line_ids"] = [l.ref.id for l in it.po_lines]      # every line the item is about, uncut: the ids an answer may name
            late = [l for l in it.po_lines if (l.days_past_due or 0) > 0]
            data["past_due_line_ids"] = [l.ref.id for l in late]
            numbers.append(Number(id=f"item:{it.key}:po_line_count", name="PO lines the item is about", value=Decimal(len(it.po_lines)), unit="lines",
                                  provenance=Provenance(method="computed", source="po_lines", row=it.key, rule="the open lines the item names", by="attention.service")))
            numbers.append(Number(id=f"item:{it.key}:past_due_line_count", name="Of them, lines past the promised date", value=Decimal(len(late)), unit="lines",
                                  provenance=Provenance(method="computed", source="po_lines", row=it.key, rule=f"lines promised before the data date, {AS_OF.isoformat()}", by="attention.service")))
            for l in late:      # one number per past-due line, so each id an answer names is one the tool returned
                numbers.append(Number(id=f"item:{it.key}:past_due:{l.ref.id}", name=f"{l.ref.id}: days past due", value=Decimal(l.days_past_due), unit="days",
                                      provenance=Provenance(method="computed", source="po_lines", row=l.ref.id, rule=f"the data date, {AS_OF.isoformat()}, minus the promised date", by="attention.service")))
        return reply(ctx, f"Item {it.title}: {len(numbers)} computed numbers, {len(unknowns)} open questions", data, numbers, unknowns, capped="po_line_ids" not in data)      # an item about lines names every one: the ids are the answer, not cut

    @tool(
        "list_items",
        "The Action list: every item that will cost money if nobody acts, ranked inside each group (the fire, deadlines, "
        "tariff, the unanswerable), with its key, title, owner, date to act by and what the item refers to. Use it to "
        "find the item a question is about, then read it with get_item.",
        {"type": "object", "properties": {"owner": {"type": "string", "description": "only this buyer's items"}}},
        annotations=READ,
    )
    async def list_items(args):
        items = svc.list_items(args.get("owner"))
        data = [{"key": i.key, "group": i.group, "severity": i.severity, "title": i.title, "owner": i.owner, "act_by": i.act_by, "days_left": i.days_left,
                 "refs": [f"{r.type} {r.id}" for r in i.refs][:6]} for i in items]
        return reply(ctx, f"{len(data)} items on the Action list", data)

    @tool(
        "requests_for",
        "The requests to suppliers the approval ledger holds for an item, a supplier, or the contact either writes to: each one's state (proposed = waiting for approval, approved, executed = sent, rejected), "
        "recipient, subject, the buyer who signs it, when it was proposed, approved and sent, and why it was rejected. Read it before saying what has or has not gone out to a supplier. "
        "It reads only: approving and sending are a person's. Give an item_key, a supplier_id, or both.",
        {"type": "object", "properties": {"item_key": {"type": "string"}, "supplier_id": {"type": "string", "description": "the supplier id as find_suppliers returns it"}}},
        annotations=READ,
    )
    async def requests_for(args):
        if not args.get("item_key") and not args.get("supplier_id"):
            return refuse("give an item_key or a supplier_id")
        rows = svc.requests_for(args.get("item_key"), args.get("supplier_id"))
        sent = [r for r in rows if r["state"] == "executed" or r["sent_at"]]
        return reply(ctx, f"{len(rows)} requests on record" + (f", {len(sent)} sent" if rows else ": nothing has been staged, approved or sent"), rows)

    return [get_item, list_items, requests_for]
