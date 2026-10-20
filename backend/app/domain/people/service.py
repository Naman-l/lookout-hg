"""The people: buyers from the buyers table, with what they buy and what is open on their desk. Nothing here names a person."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.orders.model import PoLine
from app.domain.parts.model import Buyer, Part
from app.domain.people.schema import Person
from app.domain.values import prov, ref, usd


@memo
def list_people(session: Session) -> list[Person]:
    """Every buyer in the buyers table, largest open value first. Open means OPEN or PARTIAL and not flagged stale_open (probably closed in reality)."""
    cats: dict[str, Counter] = {}
    for b_id, cat in session.execute(select(Part.buyer_id, Part.category).where(Part.buyer_id.is_not(None))):
        cats.setdefault(b_id, Counter())[cat or "uncategorised"] += 1
    lines: dict[str, list[PoLine]] = {}
    for l in session.scalars(select(PoLine).where(PoLine.status.in_(("OPEN", "PARTIAL")))):
        if "stale_open" not in (l.flags or ""):
            lines.setdefault(l.buyer_id, []).append(l)
    out = []
    for b in session.scalars(select(Buyer).order_by(Buyer.id)):
        mine = lines.get(b.id, [])
        value = sum(float(l.open_usd or 0.0) for l in mine)
        out.append(Person(
            id=b.id, name=b.name, initials=b.initials, categories=[c for c, _ in cats.get(b.id, Counter()).most_common()],
            parts=sum(cats.get(b.id, Counter()).values()), open_lines=len(mine),
            open_value=usd(value, prov("computed", "po_lines", rule="open value of the open order lines on this buyer's desk, in dollars at the order month's rate",
                                       inputs=[ref("po_line", l.id) for l in mine], by="people.list_people")),
            past_due_lines=sum(1 for l in mine if l.promised_date and l.promised_date < AS_OF.isoformat())))
    return sorted(out, key=lambda p: -float(p.open_value.usd))
