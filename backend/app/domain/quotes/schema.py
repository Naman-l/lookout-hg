"""Quotes and comparative statements (CS): every vendor's price for a PR line or a quarter's bulk rate, beside the last PO rate at that site and
the budget (BOQ / tender) rate."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import EntityRef, Money


class QuoteView(BaseModel):
    ref: EntityRef  # quote:<id>
    source: str  # tracker | mail
    vendor: EntityRef | None  # supplier:<identity>; None for a sender not in the vendor master
    vendor_name: str
    in_library: bool
    msme: bool | None
    quote_date: str | None
    qty: float | None
    uom: str | None
    rate: Money | None  # None: asked, no price yet
    validity: str | None
    price_basis: str | None  # Firm | PV
    pv_formula: str | None
    l1: bool
    message: EntityRef | None  # a quote that exists only in mail, with the line it was read from
    line: str | None
    remarks: str | None


class CsView(BaseModel):
    """One comparative statement: the vendors asked, the quotes in, L1 against the last PO rate at that site and the budget rate."""

    cs: str
    kind: str  # item | rate
    project: EntityRef | None
    material: EntityRef | None
    pr_lines: list[EntityRef]
    rfq_sent: str | None
    first_quote: str | None
    vendors_asked: int
    quotes_in: int
    status: str | None
    approved_on: str | None
    approved_by: str | None
    quotes: list[QuoteView]
    l1: QuoteView | None
    last_po_rate: Money | None
    last_po_line: EntityRef | None
    budget_rate: Money | None
    l1_vs_last_pct: float | None
    l1_vs_budget_pct: float | None
    value_at_l1: Money | None  # L1 x the CS quantity
