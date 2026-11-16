"""Payments: LCs and bank guarantees from the LC/BG tracker (an LC still to open, a guarantee near expiry while the advance it secures is not
recovered), and the vendor ledger (invoices and payments) that makes the Invoiced and Paid rungs real."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.orders.service import lines_of_po
from app.domain.payments.model import LcBg, VendorLedgerItem


class GuaranteeView(BaseModel):
    id: int
    kind: str
    number: str | None
    po: str | None
    vendor_code: str | None
    vendor_name: str | None
    amount: float
    to_open_by: str | None
    issued_on: str | None
    expiry: str | None
    status: str | None
    remarks: str | None
    open_share: float | None  # the PO's open value over its value (1.0: nothing received yet)
    unrecovered: float | None  # an advance guarantee: the advance not yet recovered against receipts (amount x open share)
    days_left: int | None  # to the date that matters: to-open-by for an LC not opened, expiry for a guarantee
    src_row: int


@memo
def guarantees(session: Session) -> list[GuaranteeView]:
    out = []
    for g in session.scalars(select(LcBg).order_by(LcBg.id)):
        lines = lines_of_po(session, g.po_no) if g.po_no else []
        value = sum(l.value for l in lines)
        share = sum(l.open_value for l in lines) / value if value else None
        when = g.to_open_by if g.kind == "LC" and not g.issued_on else g.expiry
        out.append(GuaranteeView(id=g.id, kind=g.kind, number=g.number, po=g.po_no, vendor_code=g.record_id, vendor_name=g.vendor_name, amount=g.amount,
                                 to_open_by=g.to_open_by, issued_on=g.issued_on, expiry=g.expiry, status=g.status, remarks=g.remarks, open_share=share,
                                 unrecovered=g.amount * share if g.kind == "ABG" and share is not None else None,
                                 days_left=(date.fromisoformat(when) - AS_OF).days if when else None, src_row=g.src_row))
    return out


@memo
def ledger_by_po(session: Session) -> dict[str, list[VendorLedgerItem]]:
    out: dict[str, list[VendorLedgerItem]] = {}
    for it in session.scalars(select(VendorLedgerItem).order_by(VendorLedgerItem.doc_date)):
        if it.po_no:
            out.setdefault(it.po_no, []).append(it)
    return out


def invoiced_paid(session: Session, po_no: str) -> dict:
    """First invoice, first payment, invoiced and paid totals on a PO (FBL1N: RE invoices are credits to the vendor, KZ payments debits)."""
    items = ledger_by_po(session).get(po_no, [])
    inv = [i for i in items if i.doc_type == "RE"]
    pay = [i for i in items if i.doc_type == "KZ"]
    adv = [i for i in items if i.doc_type == "KA"]
    return dict(first_invoice=inv[0].doc_date if inv else None, first_invoice_row=inv[0].src_row if inv else None, last_payment=pay[-1].doc_date if pay else None,
                last_payment_row=pay[-1].src_row if pay else None, invoiced=sum(-i.amount for i in inv), paid=sum(i.amount for i in pay),
                advance=sum(abs(i.amount) for i in adv), open_invoices=sum(1 for i in inv if not i.clearing_doc))
