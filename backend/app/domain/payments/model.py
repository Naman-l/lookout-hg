"""Payments: LCs and bank guarantees (the LC/BG tracker), the vendor ledger (SAP FBL1N: invoices, payments, advances), and the October payment
projection (the MIS sheet)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class LcBg(Base):
    __tablename__ = "lc_bg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # LC | ABG | PBG
    number: Mapped[str | None] = mapped_column(String)
    po_no: Mapped[str | None] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String)
    vendor_name: Mapped[str | None] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    amount_raw: Mapped[str] = mapped_column(String)
    to_open_by: Mapped[str | None] = mapped_column(String)
    issued_on: Mapped[str | None] = mapped_column(String)
    expiry: Mapped[str | None] = mapped_column(String)
    bank: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    remarks: Mapped[str | None] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)


class VendorLedgerItem(Base):
    __tablename__ = "vendor_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[str] = mapped_column(String)
    doc_no: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)  # RE invoice | KZ payment | KA advance
    reference: Mapped[str | None] = mapped_column(String)
    po_no: Mapped[str | None] = mapped_column(String)
    doc_date: Mapped[str] = mapped_column(String)
    net_due: Mapped[str | None] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)  # signed as exported (an invoice is a credit to the vendor: negative)
    amount_raw: Mapped[str] = mapped_column(String)
    clearing_doc: Mapped[str | None] = mapped_column(String)
    clearing_date: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)


class PaymentProjection(Base):
    __tablename__ = "payment_projection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_as_printed: Mapped[str] = mapped_column(String)
    project_ids: Mapped[str | None] = mapped_column(String)
    party: Mapped[str] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String)
    item: Mapped[str | None] = mapped_column(String)
    rtgs: Mapped[float | None] = mapped_column(Float)
    rtgs_raw: Mapped[str | None] = mapped_column(String)
    lc: Mapped[float | None] = mapped_column(Float)
    lc_raw: Mapped[str | None] = mapped_column(String)
    terms_raw: Mapped[str | None] = mapped_column(Text)
    terms_kind: Mapped[str | None] = mapped_column(String)  # advance | lc | before_dispatch | pv | other
    advance_pct: Mapped[float | None] = mapped_column(Float)
    against_abg: Mapped[int] = mapped_column(Integer)
    lc_by: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
