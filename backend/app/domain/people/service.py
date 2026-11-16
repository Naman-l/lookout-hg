"""The people: the SCM team from the buyers table, with their role, purchasing groups and what is open on their desk. Nothing here names a person."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.orders.model import PoLine
from app.domain.people.model import Buyer
from app.domain.people.schema import Person
from app.domain.prs.model import PrLine
from app.domain.values import money, prov, ref


@memo
def list_people(session: Session) -> list[Person]:
    """Every member of the team, in the order the team table lists them (no ranking). Open: PO lines not yet fully received, PR lines not yet converted."""
    po = list(session.scalars(select(PoLine).where(PoLine.status == "open")))
    pr = list(session.scalars(select(PrLine).where(PrLine.status == "open")))
    out = []
    for b in session.scalars(select(Buyer)):
        groups = set((b.purchasing_groups or "").split(","))
        mine = [l for l in po if l.purch_group in groups]
        value = sum(float(l.open_value or 0.0) for l in mine)
        out.append(Person(
            id=b.id, name=b.name, initials=b.initials, role=b.role, purchasing_groups=sorted(g for g in groups if g),
            verticals=[v for v in (b.verticals or "").split(",") if v], categories=[b.role], open_lines=len(mine),
            open_prs=sum(1 for l in pr if l.purch_group in groups),
            open_value=money(value, prov("computed", "po_lines", rule="open value of the PO lines on this member's purchasing groups, not yet fully received",
                                         inputs=[ref("po_line", l.id) for l in mine[:200]], by="people.list_people")),
            past_due_lines=sum(1 for l in mine if l.delivery_date and l.delivery_date < AS_OF.isoformat())))
    return out
