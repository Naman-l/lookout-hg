"""The item master, buyers and the plain-words helpers every other service uses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import Unknown
from app.domain.orders import service as orders
from app.domain.parts.model import Buyer, Part as PartRow
from app.domain.parts.schema import Part, PartDetail, Shortage, SupplyState
from app.domain.suppliers.model import SupplierIdentity
from app.domain.ownership import buyer_of_part
from app.domain.values import prov, qty, ref, unknown, usd


def buyer_name(session: Session, buyer_id: str | None) -> str:
    """'Ana' -> 'Ana Lopez'. An unknown buyer is IT (the ERP admin): someone still owns the question."""
    b = session.get(Buyer, buyer_id) if buyer_id else None
    return b.name if b else "IT (ERP admin)"


@memo
def list_parts(session: Session) -> list[Part]:
    from app.domain.bom.service import robots_by_part

    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    robots = robots_by_part(session)
    supply: dict[str, float] = {}
    for s in orders.open_supply(session):
        if not s.stale:
            supply[s.part.id] = supply.get(s.part.id, 0.0) + float(s.qty.value)
    out = []
    for p in session.scalars(select(PartRow).order_by(PartRow.part_number)):
        me = ref("part", p.part_number, p.description)
        owner = buyer_of_part(session, p.part_number)  # the id the Unknown carries: 'unknown · ask <buyer>'
        coo: str | Unknown = p.coo or unknown(f"country of origin of {p.part_number}", "the duty follows origin, not the supplier's country", owner,
                                              f"Where is {p.part_number} made?", [me])
        hts: str | Unknown = p.hts or unknown(f"HTS code of {p.part_number}", "the duty depends on the tariff code", owner, f"What is the HTS code of {p.part_number}?", [me])
        out.append(Part(ref=me, description=p.description, category=p.category, coo=coo, hts=hts,
                        preferred_supplier=ref("supplier", p.preferred_identity_id, names.get(p.preferred_identity_id)) if p.preferred_identity_id else None,
                        open_supply=qty(supply.get(p.part_number, 0.0), p.uom, prov("computed", "po_lines", rule="open order lines, not counting orders open over a year")),
                        robots=robots.get(p.part_number, [])))
    return out


def _shortage(session: Session, part: str) -> Shortage | None:
    from app.domain.demand.service import shortage

    t = shortage(session, part)
    b = next((b for b in t.buckets if b.month == t.first_short_month and b.short is not None), None)
    if b is None:
        return None
    covered = qty(max(b.requirements.value - b.short.value, 0), b.requirements.uom, prov("computed", "demand_forecast", row=b.month, rule="needed minus what is short", inputs=[ref("part", part)], by="parts.part_detail"))
    return Shortage(month=b.month, requirement=b.requirements, covered=covered, short=b.short)


def _supply_state(session: Session, part: str) -> SupplyState | None:
    from app.domain.phases.service import part_phases

    lad = part_phases(session, part)
    r = next((r for r in lad.rungs if r.key == "promised"), None) if lad else None
    if r is None or r.state == "na":
        return None
    return SupplyState(state=r.state, date=r.date, detail=r.detail, source=r.source)


def _closed_leads(session: Session, part_number: str | None = None) -> list[tuple[str, str, int, int | None]]:
    """(part, line, actual days order to receipt, planned days) for every closed PO line with both dates."""
    from datetime import date

    from app.domain.orders.model import PoLine

    q = select(PoLine.part_number, PoLine.id, PoLine.order_date, PoLine.received_date, PartRow.planned_lead_time_days).join(PartRow, PartRow.part_number == PoLine.part_number).where(
        PoLine.status == "CLOSED", PoLine.received_date.is_not(None), PoLine.order_date.is_not(None))
    if part_number:
        q = q.where(PoLine.part_number == part_number)
    return [(p, i, (date.fromisoformat(r[:10]) - date.fromisoformat(o[:10])).days, plt) for p, i, o, r, plt in session.execute(q) if o and r]


def lead_time_actual(session: Session, part_number: str):
    """The part's measured lead time beside the planned one; None when no closed line has both dates."""
    from statistics import median

    from app.domain.parts.schema import LeadTimeActual

    rows = _closed_leads(session, part_number)
    if not rows:
        return None
    plt = rows[0][3]
    return LeadTimeActual(planned_days=plt, median_days=round(median(a for _, _, a, _ in rows)), receipts=len(rows), later=sum(1 for _, _, a, _ in rows if plt and a > plt),
                          lines=[ref("po_line", i) for _, i, _, _ in rows])


def lead_time_bias(session: Session) -> dict:
    """Across every closed line with a planned lead time: how many took longer than planned, and the median overrun in days (the planning-parameter finding)."""
    from statistics import median

    rows = [(a, p) for _, _, a, p in _closed_leads(session) if p]
    return {"lines": len(rows), "later": sum(1 for a, p in rows if a > p), "median_overrun_days": median(a - p for a, p in rows) if rows else None, "median_actual_days": median(a for a, _ in rows) if rows else None}


def part_detail(session: Session, part_number: str) -> PartDetail | None:
    """The part page: the item master row with its raw values, where it is used, the tariff and origin status, the reference price, possible duplicates."""
    from sqlalchemy import or_, text

    from app.domain.bom.service import where_used
    from app.domain.orders.model import ReferencePrice
    from app.domain.parts.model import PartLink
    from app.domain.tariffs import service as tariffs

    row = session.get(PartRow, part_number)
    if row is None:
        return None
    base = next(p for p in list_parts(session) if p.ref.id == part_number)
    me = ref("part", part_number, row.description)
    raw = session.connection().execute(text("select * from raw_parts where src_row = :r"), {"r": row.src_row}).mappings().one()
    lead = (qty(row.planned_lead_time_days, "days", prov("stated", "parts", row=part_number, raw=str(row.planned_lead_time_days)))
            if row.planned_lead_time_days else unknown("planned lead time", "no lead time is on file, so a reorder date cannot be computed", buyer_of_part(session, part_number), f"What is the planned lead time of {part_number}?", [me]))
    rp = session.get(ReferencePrice, part_number)
    price = usd(rp.usd_each, prov("computed", "po_lines", row=rp.po_line_id, rule="latest clean PO line, USD each", inputs=[ref("po_line", rp.po_line_id)]), places=6) if rp else None
    links = session.scalars(select(PartLink).where(or_(PartLink.part_a == part_number, PartLink.part_b == part_number)))
    linked = [ref("part", l.part_b if l.part_a == part_number else l.part_a) for l in links]
    exposure = tariffs.exposure_for_part(session, part_number)
    return PartDetail(shortage=_shortage(session, part_number), supply_state=_supply_state(session, part_number), lead_time_actual=lead_time_actual(session, part_number), part=base, kind=row.kind, mpn=row.mpn, manufacturer=row.manufacturer, uom=row.uom, status=row.status, buyer=buyer_name(session, row.buyer_id) if row.buyer_id else None,
                      buyer_method=row.buyer_method, planned_lead_time=lead, raw={k: (v if v != "" else None) for k, v in raw.items() if k != "src_row"},
                      where_used=where_used(session, part_number), tariff=tariffs.tariff_rule_for(session, part_number), origin=tariffs.coo_status(session, part_number),
                      reference_price=price, open_lines=sum(1 for s in orders.open_supply(session, part_number) if not s.stale), linked_parts=linked,
                      exposure=exposure if exposure.status != "not_applicable" else None)
