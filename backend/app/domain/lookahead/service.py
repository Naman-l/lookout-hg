"""The long-lead look-ahead: items not yet ordered, when they must be ordered to arrive when the site needs them, and what each month's wait costs
on a PV-linked item while its index rises (item value x the variable share x the index's average monthly change over six months)."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.indices import service as indices
from app.domain.lookahead.model import LookAheadItem
from app.domain.orders.service import all_lines


class LookAheadView(BaseModel):
    id: int
    project: str | None
    project_name: str
    scope: str | None
    item: str
    material: str | None
    qty: float
    uom: str
    value: float
    price_basis: str
    lead: str
    need_by: str | None
    order_by: str | None
    ordered: list[str]  # PO lines on file for this material on this project
    index: str | None
    share: float | None
    monthly_change: float | None
    delay_cost: float | None  # a month's wait, PV-linked items only
    since_lookahead: float | None  # the index's rise since the order-by month (what waiting has cost so far, on the item's value x share)
    status: str | None
    src_row: int


@memo
def items(session: Session) -> list[LookAheadView]:
    lines = all_lines(session).values()
    out = []
    for i in session.scalars(select(LookAheadItem).order_by(LookAheadItem.id)):
        ordered = [l.id for l in lines if i.material and l.material == i.material and l.project_id == i.project_id]
        share = indices.variable_share(session, i.pv_index) if i.price_basis == "PV" else None
        ch = indices.monthly_change(session, i.pv_index) if i.pv_index else None
        since = indices.change_since(session, i.pv_index, i.order_by[:7]) if i.pv_index and i.order_by and i.order_by[:7] <= AS_OF.isoformat()[:7] else None
        out.append(LookAheadView(
            id=i.id, project=i.project_id, project_name=lookups.project_name(session, i.project_id) or i.project_as_printed, scope=i.scope, item=i.item,
            material=i.material, qty=i.qty, uom=i.uom, value=i.amount, price_basis=i.price_basis, lead=i.lead_raw, need_by=i.need_by, order_by=i.order_by,
            ordered=ordered, index=i.pv_index, share=share, monthly_change=ch,
            delay_cost=i.amount * share * ch if share and ch and ch > 0 else None,
            since_lookahead=i.amount * share * since if share and since and since > 0 else None, status=i.status, src_row=i.src_row))
    return out
