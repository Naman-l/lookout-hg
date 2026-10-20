"""What a slip in consigned material reaches: its open orders and their dates now, and the products that contain the part built from it."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.bom.service import where_used
from app.domain.consignments.model import Consignment as Row
from app.domain.consignments.schema import Consignment, MaterialLine, ProductReached
from app.domain.orders import service as orders
from app.domain.values import ref


def list_consignments(session: Session) -> list[Consignment]:
    out = []
    for r in session.scalars(select(Row).order_by(Row.id)):
        lines = []
        for s in orders.open_supply(session, r.material_part):
            now = orders.current_date(s)
            later = (date.fromisoformat(now) - date.fromisoformat(s.promise)).days if now and s.promise else None
            lines.append(MaterialLine(po_line=naming.labelled(session, [s.po_line])[0], promised=s.promise, now=now, days_later=later))
        slips = [l.days_later for l in lines if l.days_later and l.days_later > 0]
        mk = lambda t, i: naming.labelled(session, [ref(t, i)])[0]      # noqa: E731
        out.append(Consignment(id=r.id, material=mk("part", r.material_part), holder=mk("supplier", r.holder_identity), into=mk("part", r.into_part), evidence=r.evidence,
                               method=r.method, material_lines=lines, slip_days=max(slips) if slips else None,
                               reaches=[ProductReached(product=w.product, qty_per_robot=w.qty_per_robot) for w in where_used(session, r.into_part)]))
    return out
