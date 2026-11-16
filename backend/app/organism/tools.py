"""The specialists' tools: thin wrappers over the domain services, each figure returned as a Number with a stable id (`pr:<PR>/<line>:qty`,
`po:<PO>/<line>:open_value`, `item:<key>:at_stake`) so an answer cites it and the verifier checks the answer against it. Read-only, except the
clerk's drafting tools, which stage proposals in the ledger (nothing is sent)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import routes as route_table, service as attention
from app.domain.fmt import dmy, en_in, inr, md
from app.domain.indices import service as indices
from app.domain.lookahead.service import items as lookahead_items
from app.domain.orders import service as orders
from app.domain.phases.ladder import ladder
from app.domain.prs import service as prs
from app.domain.quotes import service as quotes
from app.domain.receipts.service import delivery
from app.domain.requirements import service as req

from .schemas import Number


def num(id_: str, name: str, value: float | int | Decimal | None, unit: str) -> Number | None:
    if value is None:
        return None
    say = inr(float(value)) if unit == "INR" else (f"{en_in(float(value))} {unit}".strip() if unit not in ("days", "%") else f"{value:g} {unit}")
    return Number(id=id_, name=name, value=Decimal(str(round(float(value), 4))), unit=unit, say=say)


def _out(numbers: list[Number | None], **rest: Any) -> dict:
    return {"numbers": [n for n in numbers if n is not None], **rest}


# ---- the case ----------------------------------------------------------------------------------------------------------------------------------
def get_item(session: Session, key: str) -> dict:
    d = attention.item_detail(session, key)
    if d is None:
        return {"error": f"no case {key}"}
    nums = [num(f"item:{key}:at_stake", f"{d.at_stake_label} ({d.at_stake_rule})", float(d.at_stake.amount), "INR") if d.at_stake is not None and hasattr(d.at_stake, "amount") else None]
    nums += [Number(id=n.id, name=n.label, value=Decimal(str(n.value.amount if hasattr(n.value, "amount") else n.value.value)), unit="INR" if hasattr(n.value, "amount") else n.value.uom,
                    say=inr(float(n.value.amount)) if hasattr(n.value, "amount") else None) for n in d.numbers if hasattr(n.value, "amount") or hasattr(n.value, "uom")]
    return _out(nums, title=d.title, kind=d.kind, finding=d.finding, act_by=d.act_by, waiting_on=d.waiting_on, owner=d.owner,
                facts=[{"key": f.key, "fact": f.fact, "meaning": f.meaning} for f in d.findings], unknowns=[u.model_dump() for u in d.unknowns][:10],
                deadlines=[x.model_dump() for x in d.deadlines])


def list_items(session: Session, owner: str | None = None) -> dict:
    return {"items": [{"key": i.key, "title": i.title, "tab": i.tab, "owner": i.owner, "act_by": i.act_by} for i in attention.what_needs_attention(session, owner)]}


# ---- the site requirement planner ------------------------------------------------------------------------------------------------------------
def open_prs(session: Session, project: str | None = None, material: str | None = None) -> dict:
    rows = prs.list_lines(session, status="open", project=lookups.resolve_project(session, project) if project else None, material=material)
    return _out([num(f"pr:{r.ref.id}:qty", f"PR {r.ref.id} quantity", r.qty, r.uom) for r in rows[:40]],
                rows=[{"pr_line": r.ref.id, "text": r.text, "qty": r.qty, "uom": r.uom, "project": r.project.label if r.project else None, "needed_by": r.needed_by,
                       "age_days": r.age_days, "cs": r.cs} for r in rows[:40]], count=len(rows))


def pr_ladder(session: Session, pr_line: str) -> dict:
    L = ladder(session, pr_line_id=pr_line)
    if L is None:
        return {"error": f"no PR line {pr_line}"}
    return _out([num(f"ladder:{pr_line}:days_waiting", "days waiting now", L.days_waiting, "days")] + [num(f"ladder:{pr_line}:held:{k}", f"days held by {k}", v, "days") for k, v in L.held.items()],
                waiting_on=L.waiting_on, rungs=[{"rung": r.label, "date": r.date, "state": r.state, "held_by": r.held_by, "days": r.days, "source": r.source} for r in L.rungs])


def open_pos(session: Session, vendor: str | None = None, project: str | None = None, material: str | None = None) -> dict:
    rows = orders.list_lines(session, status="open", vendor=vendor, project=lookups.resolve_project(session, project) if project else None, material=material)
    return _out([num(f"po:{r.ref.id}:open_value", f"PO {r.ref.id} open value", float(r.open_value.amount), "INR") for r in rows[:40]]
                + [num(f"po:{r.ref.id}:open_qty", f"PO {r.ref.id} open quantity", r.open_qty, r.uom) for r in rows[:40]],
                rows=[{"po_line": r.ref.id, "text": r.text, "vendor": r.vendor.label, "open_qty": r.open_qty, "uom": r.uom, "due": r.delivery_date,
                       "revised": [x.date for x in r.revised], "validity_end": r.validity_end} for r in rows[:40]], count=len(rows))


def po_ladder(session: Session, po_line: str) -> dict:
    L = ladder(session, po_line_id=po_line)
    if L is None:
        return {"error": f"no PO line {po_line}"}
    return _out([num(f"ladder:{po_line}:days_waiting", "days waiting now", L.days_waiting, "days")] + [num(f"ladder:{po_line}:held:{k}", f"days held by {k}", v, "days") for k, v in L.held.items()],
                waiting_on=L.waiting_on, rungs=[{"rung": r.label, "date": r.date, "state": r.state, "held_by": r.held_by, "days": r.days, "source": r.source} for r in L.rungs])


def requirement_for(session: Session, project: str, material: str) -> dict:
    pid = lookups.resolve_project(session, project)
    if pid is None:
        return {"error": f"no project {project}"}
    s = req.supply_by_month(session, pid, material.split(","), req.months_ahead())
    nums = []
    for m in s.months:
        nums += [num(f"req:{pid}:{material}:{m.month}:required", f"required {m.month}", m.required, s.uom or ""), num(f"req:{pid}:{material}:{m.month}:on_order", f"on order {m.month}", m.on_order, s.uom or ""),
                 num(f"req:{pid}:{material}:{m.month}:gap", f"gap {m.month} (up to)", m.gap, s.uom or "")]
    return _out(nums, months=[m.model_dump() for m in s.months], note=s.note)


def site_impact(session: Session, key: str) -> dict:
    d = attention.item_detail(session, key)
    return {"fronts": [s.model_dump() for s in (d.site_impact if d else [])], "note": "up to: site stock is not in the data"}


def workfront_readiness(session: Session, project: str) -> dict:
    pid = lookups.resolve_project(session, project)
    return {"fronts": [f.model_dump() for f in req.readiness(session, pid)] if pid else []}


# ---- the sourcing analyst ----------------------------------------------------------------------------------------------------------------------
def compare_quotes(session: Session, cs: str | None = None, key: str | None = None) -> dict:
    v = quotes.cs(session, cs) if cs else None
    if v is None and key:
        d = attention.item_detail(session, key)
        v = d.cs if d else None
        if v is None and d is not None:      # quotes in hand by mail: the case's own figures
            return _out([Number(id=n.id, name=n.label, value=Decimal(str(n.value.amount)), unit="INR", say=inr(float(n.value.amount))) for n in d.numbers if hasattr(n.value, "amount")],
                        quotes=[f.fact for f in d.findings])
    if v is None:
        return {"error": "no comparative statement"}
    nums = [num(f"cs:{v.cs}:{q.vendor_name}:rate", f"{q.vendor_name} rate", float(q.rate.amount), "INR") for q in v.quotes if q.rate]
    nums += [num(f"cs:{v.cs}:last_po", "last PO rate", float(v.last_po_rate.amount), "INR") if v.last_po_rate else None,
             num(f"cs:{v.cs}:budget", "budget rate", float(v.budget_rate.amount), "INR") if v.budget_rate else None]
    return _out(nums, quotes=[{"vendor": q.vendor_name, "rate": float(q.rate.amount) if q.rate else None, "validity": q.validity, "remarks": q.remarks, "l1": q.l1} for q in v.quotes],
                l1_vs_last_pct=v.l1_vs_last_pct, l1_vs_budget_pct=v.l1_vs_budget_pct, status=v.status)


def rate_history(session: Session, material: str) -> dict:
    from app.domain.materials.service import detail  # noqa: PLC0415

    d = detail(session, material)
    if d is None:
        return {"error": f"no material {material}"}
    return _out([num(f"rate:{material}:{s.project.id}", f"{s.project.label} last rate", s.last_rate, "INR") for s in d.by_site] + [num(f"rate:{material}:median", "median of sites", d.median, "INR")],
                sites=[{"project": s.project.label, "rate": s.last_rate, "date": s.last_date, "vendor": s.vendor, "budget": s.budget} for s in d.by_site])


def vendor_record(session: Session, vendor: str) -> dict:
    from app.domain.suppliers.service import profile  # noqa: PLC0415

    v = profile(session, vendor)
    if v is None:
        return {"error": f"no vendor {vendor}"}
    d = v.delivery
    return _out([num(f"vendor:{v.ref.id}:on_time_pct", "on-time share", d.on_time_pct, "%"), num(f"vendor:{v.ref.id}:open_value", "open PO value", float(v.open_value.amount), "INR"),
                 num(f"vendor:{v.ref.id}:streak", "late receipts in a row", d.streak, "")],
                name=v.name, codes=v.codes, msme=v.msme, library=v.verticals, streak=d.line, msme_due=len(v.msme_due), contact=v.contact.name)


# ---- the price and PV analyst ------------------------------------------------------------------------------------------------------------------
def pv_cost(session: Session, po: str, current_month: str | None = None, qty: float | None = None) -> dict:
    l = next((x for x in orders.lines_of_po(session, po) if x.pv_clause), None)
    if l is None:
        return {"error": f"PO {po} has no price-variation clause: its price is firm"}
    month = current_month or indices.latest_month(session, l.pv_index)
    r = indices.pv(session, qty=qty or l.qty_base, rate=l.rate_base, share=l.pv_variable_share, index=l.pv_index, base_month=l.pv_base_month, current_month=month)
    return _out([num(f"pv:{po}:computed", "PV on the PO's clause", r.pv, "INR")], formula=r.formula, base_month=r.base_month, current_month=r.current_month)


def index_series(session: Session, index: str, months: int = 12) -> dict:
    s = indices.series(session).get(index, {})
    keys = sorted(s)[-months:]
    return _out([num(f"index:{index}:{k}", f"{index} {k}", s[k], "") for k in keys] + [num(f"index:{index}:monthly_change_pct", "average monthly change over 6 months",
                                                                                         (indices.monthly_change(session, index) or 0) * 100, "%")])


def lookahead(session: Session, project: str | None = None) -> dict:
    rows = [x for x in lookahead_items(session) if not project or x.project == lookups.resolve_project(session, project)]
    return _out([num(f"la:{x.id}:delay_cost", f"{x.item}: a month's delay", x.delay_cost, "INR") for x in rows] + [num(f"la:{x.id}:value", f"{x.item} value", x.value, "INR") for x in rows],
                items=[{"item": x.item, "project": x.project_name, "order_by": x.order_by, "basis": x.price_basis, "ordered": bool(x.ordered), "status": x.status} for x in rows])


# ---- the inbox analyst -------------------------------------------------------------------------------------------------------------------------
def inbox_overview(session: Session) -> dict:
    from app.domain.inbox.service import list_messages  # noqa: PLC0415

    return {"messages": [{"id": m.ref.id, "from": m.from_, "class": m.sender_class, "trust": m.trust, "kind": m.kind, "means": m.summary} for m in list_messages(session)]}


def read_message(session: Session, message_id: str) -> dict:
    from app.domain.inbox.service import detail  # noqa: PLC0415

    d = detail(session, message_id)
    if d is None:
        return {"error": f"no message {message_id}"}
    return _out([num(f"msg:{message_id}:claimed", "amount the message asks for", float(d.claimed.amount), "INR") if d.claimed else None],
                sender=d.summary.from_, sender_class=d.summary.sender_class, trust=d.summary.trust, flags=d.summary.trust_flags, kind=d.summary.kind, means=d.summary.summary,
                dates=[x.model_dump() for x in d.dates], moves=[x.model_dump() for x in d.moves], body=None if d.summary.trust == "blocked" else d.body)


def find_vendors(session: Session, text: str) -> dict:
    t = text.lower()
    return {"vendors": [{"id": i, "name": lookups.vendor_name(session, i), "codes": [r.record_id for r in lookups.records_of(session).get(i, [])]}
                        for i in lookups.identities(session) if t in lookups.vendor_name(session, i).lower() or any(t in r.name.lower() or t == r.record_id for r in lookups.records_of(session).get(i, []))]}


# ---- the routes (for the clerk and Lookout) ----------------------------------------------------------------------------------------------------
def routes_of(session: Session, key: str, owner: str | None = None) -> list[route_table.Route]:
    return route_table.routes(session, key, owner)


def say_dates(d: str | None) -> str:
    return dmy(d) if d else ""


__all__ = ["get_item", "list_items", "open_prs", "pr_ladder", "open_pos", "po_ladder", "requirement_for", "site_impact", "workfront_readiness", "compare_quotes",
           "rate_history", "vendor_record", "pv_cost", "index_series", "lookahead", "inbox_overview", "read_message", "find_vendors", "routes_of", "md"]
