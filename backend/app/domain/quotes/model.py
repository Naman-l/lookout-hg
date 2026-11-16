"""Quotes and comparative statements: every vendor's quote from the RFQ/CS tracker and from mail (each mail quote citing its line), and one
comparative statement per CS number, built from them."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # tracker | mail
    cs_no: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    pr_no: Mapped[str | None] = mapped_column(String)
    pr_item: Mapped[int | None] = mapped_column(Integer)
    pr_line_id: Mapped[str | None] = mapped_column(String)
    material: Mapped[str | None] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String)
    identity_id: Mapped[str | None] = mapped_column(String)
    vendor_name: Mapped[str] = mapped_column(String)
    rfq_sent: Mapped[str | None] = mapped_column(String)
    quote_date: Mapped[str | None] = mapped_column(String)
    qty: Mapped[float | None] = mapped_column(Float)
    uom: Mapped[str | None] = mapped_column(String)
    rate: Mapped[float | None] = mapped_column(Float)  # INR per unit
    rate_raw: Mapped[str | None] = mapped_column(String)
    validity: Mapped[str | None] = mapped_column(String)
    price_basis: Mapped[str | None] = mapped_column(String)  # Firm | PV
    pv_formula: Mapped[str | None] = mapped_column(Text)
    l1: Mapped[int] = mapped_column(Integer)
    last_po_rate_printed: Mapped[float | None] = mapped_column(Float)
    budget_rate_printed: Mapped[float | None] = mapped_column(Float)
    cs_status: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String)
    approved_on: Mapped[str | None] = mapped_column(String)
    buyer_id: Mapped[str | None] = mapped_column(String)
    remarks: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String)
    line_ref: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int | None] = mapped_column(Integer)


class ComparativeStatement(Base):
    __tablename__ = "comparative_statements"

    cs_no: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # rate (a quarter's rate for bulk material) | item (a PR's items)
    project_id: Mapped[str | None] = mapped_column(String)
    material: Mapped[str | None] = mapped_column(String)
    pr_line_ids: Mapped[str | None] = mapped_column(Text)  # comma list
    rfq_sent: Mapped[str | None] = mapped_column(String)
    first_quote: Mapped[str | None] = mapped_column(String)
    vendors_asked: Mapped[int] = mapped_column(Integer)
    quotes_in: Mapped[int] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String)
    approved_on: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String)
    l1_record: Mapped[str | None] = mapped_column(String)
    l1_rate: Mapped[float | None] = mapped_column(Float)
