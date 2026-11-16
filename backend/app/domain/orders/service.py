"""PO lines (ME2N, netted against MB51): one view every screen, detector and tool shares, with the dates a vendor's mail has moved."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.inbox.model import MessageEvent
from app.domain.orders.model import PoLine
from app.domain.orders.schema import PoLineView, PvClause, RevisedSplit
from app.domain.values import money, prov, ref

FLAG_WORDS = {"no_pr": "PO with no PR", "not_in_library": "vendor not in the approved library", "same_day_po": "PR keyed in the day of the PO",
              "price_per_1000": "price per 1,000 in SAP", "bags": "ordered in bags"}


@memo
def revisions(session: Session) -> dict[str, list[RevisedSplit]]:
    """{po line: the dates a vendor's message moved it to, oldest message first}."""
    out: dict[str, list[RevisedSplit]] = {}
    for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "promise_revision", MessageEvent.ref_type == "po_line").order_by(MessageEvent.id)):
        out.setdefault(e.ref_id, []).append(RevisedSplit(date=e.date_to, qty=e.qty, message=e.message_id, line=e.line_ref))
    return out


def view(session: Session, l: PoLine) -> PoLineView:
    terms = (lookups.answers().get("payment_terms") or {}).get(l.payment_terms or "", {})
    doc_types = lookups.answers().get("doc_types") or {}
    m = lookups.materials(session).get(l.material or "")
    src = prov("stated", "po_lines", row=str(l.src_row), by="orders.service")
    past = (AS_OF - date.fromisoformat(l.delivery_date)).days if l.status == "open" and l.delivery_date and l.delivery_date < AS_OF.isoformat() else None
    return PoLineView(
        ref=ref("po_line", l.id, l.short_text), po=l.po_no, item=l.item, doc_type=doc_types.get(l.doc_type, l.doc_type),
        vendor=ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id)), vendor_code=l.record_id,
        material=ref("material", l.material, m.description if m else l.short_text) if l.material else None, text=l.short_text or "",
        qty=l.qty_base, uom=l.base_uom, rate=money(l.rate_base, prov("computed", "po_lines", row=str(l.src_row), raw=f"{l.net_price_raw} per {l.price_unit_raw} {l.uom_raw}",
                                                                      rule="net price / price unit, in the base unit", by="orders.service")),
        value=money(l.value, src), received=l.received_base, open_qty=l.open_base,
        open_value=money(l.open_value, prov("computed", "po_lines", row=str(l.src_row), rule="open quantity x rate (ordered less net received)", by="orders.service")),
        doc_date=l.doc_date, delivery_date=l.delivery_date, days_past_due=past, revised=revisions(session).get(l.id, []), validity_end=l.validity_end,
        project=ref("project", l.project_id, lookups.project_name(session, l.project_id)) if l.project_id else None, plant=l.plant, purch_group=l.purch_group,
        buyer=lookups.member_name(session, l.buyer_id) or None, pr_line=ref("pr_line", l.pr_line_id) if l.pr_line_id else None,
        pv=PvClause(index=l.pv_index, base_month=l.pv_base_month, variable_share=l.pv_variable_share, raw=l.pv_raw) if l.pv_clause else None,
        payment_terms=terms.get("label") or l.payment_terms, status=l.status,
        flags=[FLAG_WORDS.get(f, f.replace("_", " ")) for f in (l.flags or "").split(",") if f])


@memo
def all_lines(session: Session) -> dict[str, PoLine]:
    return {l.id: l for l in session.scalars(select(PoLine).order_by(PoLine.po_no, PoLine.item))}


def line(session: Session, po_line_id: str) -> PoLine | None:
    return all_lines(session).get(po_line_id)


def lines_of_po(session: Session, po_no: str) -> list[PoLine]:
    return [l for l in all_lines(session).values() if l.po_no == po_no]


def list_lines(session: Session, *, status: str | None = None, buyer: str | None = None, project: str | None = None, vendor: str | None = None,
               material: str | None = None) -> list[PoLineView]:
    out = []
    for l in all_lines(session).values():
        if (status and l.status != status) or (buyer and l.buyer_id != buyer) or (project and l.project_id != project) or (material and l.material != material):
            continue
        if vendor and vendor not in (l.identity_id, l.record_id):
            continue
        out.append(view(session, l))
    return out


def last_rate(session: Session, material: str, plant: str | None = None, project: str | None = None, before: str | None = None) -> tuple[float, PoLine] | None:
    """The rate on the newest PO line for this material (at this plant or project, where given), dated before `before` (the data date by default)."""
    cut = before or AS_OF.isoformat()
    best = None
    for l in all_lines(session).values():
        if l.material != material or l.doc_date > cut or (plant and l.plant != plant) or (project and l.project_id != project):
            continue
        if best is None or (l.doc_date, l.id) > (best.doc_date, best.id):
            best = l
    return (best.rate_base, best) if best else None
