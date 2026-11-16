"""PR lines (ME5A) as a buyer reads them: status, age, turnaround to the PO (a PR keyed in the day of its PO is left out of turnaround, it measures
nothing), the RFQ and CS behind it, and the plain-word flags the recipe set."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF, EntityRef, Money
from app.domain.orders.service import all_lines as po_lines
from app.domain.prs.model import PrLine
from app.domain.quotes.model import Quote
from app.domain.values import money, prov, ref

FLAG_WORDS = {"same_day_po": "PR keyed in the day of its PO", "rfq_before_pr": "RFQ sent before the PR was raised", "no_project": "PR with no project"}


class PrLineView(BaseModel):
    ref: EntityRef
    pr: str
    item: int
    material: EntityRef | None
    text: str
    qty: float
    uom: str
    value: Money | None  # qty x the last PO rate for the material at that plant (else none: the PR carries no price)
    plant: str
    project: EntityRef | None
    purch_group: str
    buyer: str | None
    requisitioner: str | None
    created: str
    released: str | None
    needed_by: str | None
    status: str  # open | converted | deleted | closed
    po_line: EntityRef | None
    po_date: str | None
    turnaround_days: int | None  # PR release (else creation) to the PO's date; None when the PR was keyed in the PO's day or is not converted
    age_days: int | None  # an open PR: days since release (else creation)
    cs: str | None
    rfq_sent: str | None
    quotes_in: int
    changed_on: str | None
    flags: list[str]


@memo
def all_lines(session: Session) -> dict[str, PrLine]:
    return {l.id: l for l in session.scalars(select(PrLine).order_by(PrLine.pr_no, PrLine.item))}


@memo
def _quotes_by_pr_line(session: Session) -> dict[str, list[Quote]]:
    out: dict[str, list[Quote]] = {}
    for q in session.scalars(select(Quote).where(Quote.pr_line_id.is_not(None))):
        out.setdefault(q.pr_line_id, []).append(q)
    return out


def price_of(session: Session, l: PrLine) -> float | None:
    """A PR carries no price: its value is its quantity at the last PO rate for that material at that plant (else anywhere), else unknown."""
    from app.domain.orders.service import last_rate  # noqa: PLC0415

    if not l.material:
        return None
    hit = last_rate(session, l.material, plant=l.plant) or last_rate(session, l.material)
    return hit[0] if hit else None


def view(session: Session, l: PrLine) -> PrLineView:
    po = po_lines(session).get(l.po_line_id or "")
    start = l.released or l.created
    same_day = "same_day_po" in (l.flags or "")
    tat = (date.fromisoformat(po.doc_date) - date.fromisoformat(start)).days if po and not same_day else None
    qs = _quotes_by_pr_line(session).get(l.id, [])
    rate = price_of(session, l)
    m = lookups.materials(session).get(l.material or "")
    qty = l.qty_base if l.qty_base is not None else l.qty
    return PrLineView(
        ref=ref("pr_line", l.id, l.short_text), pr=l.pr_no, item=l.item, material=ref("material", l.material, m.description if m else None) if l.material else None,
        text=l.short_text or "", qty=qty, uom=(m.base_uom if m and l.qty_base is not None else l.uom),
        value=money(qty * rate, prov("computed", "pr_lines", row=str(l.src_row), rule="PR quantity x the last PO rate for the material at the plant (a PR has no price)",
                                     by="prs.service")) if rate else None,
        plant=l.plant, project=ref("project", l.project_id, lookups.project_name(session, l.project_id)) if l.project_id else None, purch_group=l.purch_group,
        buyer=lookups.member_name(session, l.buyer_id) or None, requisitioner=l.requisitioner, created=l.created, released=l.released, needed_by=l.needed_by,
        status=l.status, po_line=ref("po_line", po.id, po.short_text) if po else None, po_date=po.doc_date if po else None, turnaround_days=tat,
        age_days=(AS_OF - date.fromisoformat(start)).days if l.status == "open" else None,
        cs=next((q.cs_no for q in qs if q.cs_no), None), rfq_sent=min((q.rfq_sent for q in qs if q.rfq_sent), default=None),
        quotes_in=len({q.record_id for q in qs if q.rate}), changed_on=l.changed_on,
        flags=[FLAG_WORDS.get(f, f.replace("_", " ")) for f in (l.flags or "").split(",") if f])


def list_lines(session: Session, *, status: str | None = None, buyer: str | None = None, project: str | None = None, material: str | None = None) -> list[PrLineView]:
    return [view(session, l) for l in all_lines(session).values()
            if not ((status and l.status != status) or (buyer and l.buyer_id != buyer) or (project and l.project_id != project) or (material and l.material != material))]


def lines_of_pr(session: Session, pr_no: str) -> list[PrLine]:
    return [l for l in all_lines(session).values() if l.pr_no == pr_no]
