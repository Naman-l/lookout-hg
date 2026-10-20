from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef, Money, Quantity, Unknown


class RevisedSplit(BaseModel):
    date: str
    qty: float


class SupplyLine(BaseModel):
    """An open PO line seen as supply: what is still to arrive, when it was promised, and whether it can."""

    po_line: EntityRef
    part: EntityRef
    record: EntityRef  # the ERP record the line was placed on
    supplier: EntityRef  # the company
    status: str
    qty: Quantity  # still to arrive, in the part's unit
    open_value: Money
    open_value_own: Money | None = None  # the same, in the currency the order is priced in (what the supplier invoices)
    promise: str | None
    revised_promise: str | None  # from a supplier message; the ERP date is not changed (the last date when the line is split)
    revised_on: str | None = None  # the date of the message that revised the promise
    revised_splits: list[RevisedSplit] = []  # when the supplier splits the line: what arrives on which date
    days_past_due: int | None
    disrupted_by: EntityRef | None  # the force-majeure message, if any
    revised_by: EntityRef | None = None  # the message that gave the revised promise, if any
    notice_kind: Literal["force majeure", "allocation", "slip"] | None = None  # what kind of notice disturbs the line: force majeure, an allocation, or a supplier's later date
    stale: bool  # ordered over a year ago and still open: probably not really open
    flags: list[str]


class PoLineView(BaseModel):
    po_line: EntityRef
    part: EntityRef
    supplier: EntityRef
    record: EntityRef
    buyer: str | None
    status: str
    qty_ordered: Quantity | None
    qty_open: Quantity | None
    unit_price: Money
    line_value: Money
    promise: str | None
    revised_promise: str | None
    days_past_due: int | None
    flags: list[str]
    raw: dict[str, str | None]  # the source row exactly as it was


class PoLine(BaseModel):
    """The contract's PO line (GET /api/orders): one row of the open PO report."""

    ref: EntityRef
    part: EntityRef
    supplier: EntityRef
    qty: Quantity
    unit_price: Money | None = None
    promise_date: str | None = None
    revised_date: str | None = None
    days_past_due: int | None = None
    status: str
    disrupted_by: EntityRef | None = None
    buyer: str
    stale: bool = False  # ordered over a year ago and still open: may not really be open; no past-due days, not counted as open
    unknown: Unknown | None = None  # for a stale line: the question, with its owner
