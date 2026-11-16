"""PO line shapes: a line of a purchase order or work order as the records hold it, with what is still open and any date the vendor has moved."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import EntityRef, Money


class RevisedSplit(BaseModel):
    date: str
    qty: float | None = None
    message: str  # the message that moved it
    line: str | None = None  # the line of the message it was read from


class PvClause(BaseModel):
    index: str | None
    base_month: str | None
    variable_share: float | None
    raw: str | None


class PoLineView(BaseModel):
    ref: EntityRef  # po_line:<PO>/<item>
    po: str
    item: int
    doc_type: str  # Purchase order | Work order | Import purchase order
    vendor: EntityRef
    vendor_code: str
    material: EntityRef | None
    text: str
    qty: float
    uom: str
    rate: Money  # per unit of `uom`, the price unit applied
    value: Money
    received: float
    open_qty: float
    open_value: Money
    doc_date: str
    delivery_date: str | None
    days_past_due: int | None
    revised: list[RevisedSplit] = []  # dates the vendor has moved it to (the ERP date is not changed)
    validity_end: str | None
    project: EntityRef | None
    plant: str
    purch_group: str
    buyer: str | None  # the member's full name
    pr_line: EntityRef | None
    pv: PvClause | None
    payment_terms: str | None
    status: str  # open | received
    flags: list[str]  # plain words: "PO with no PR", "vendor not in the approved library"
