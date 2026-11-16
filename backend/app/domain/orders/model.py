"""Purchase orders and work orders (SAP ME2N), received and open quantities netted from MB51."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class PoLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<PO>/<item>"
    po_no: Mapped[str] = mapped_column(String)
    item: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[str] = mapped_column(String)  # ZNB standard PO | ZWO work order | ZIMP import PO
    record_id: Mapped[str] = mapped_column(ForeignKey("supplier_records.record_id"))
    identity_id: Mapped[str] = mapped_column(ForeignKey("supplier_identities.id"))
    material: Mapped[str | None] = mapped_column(ForeignKey("materials.code"))
    short_text: Mapped[str | None] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    qty_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    uom_raw: Mapped[str] = mapped_column(String)
    qty_base: Mapped[float] = mapped_column(Float)
    base_uom: Mapped[str] = mapped_column(String)
    net_price: Mapped[float] = mapped_column(Float)  # per price unit, as SAP holds it
    net_price_raw: Mapped[str] = mapped_column(String)
    price_unit: Mapped[int] = mapped_column(Integer)
    price_unit_raw: Mapped[str] = mapped_column(String)
    rate_base: Mapped[float] = mapped_column(Float)  # INR per base unit
    currency: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)  # INR
    doc_date: Mapped[str] = mapped_column(String)
    doc_date_raw: Mapped[str] = mapped_column(String)
    delivery_date: Mapped[str | None] = mapped_column(String)
    delivery_date_raw: Mapped[str | None] = mapped_column(String)
    plant: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    purch_group: Mapped[str] = mapped_column(String)
    buyer_id: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(String)
    pr_no: Mapped[str | None] = mapped_column(String)
    pr_item: Mapped[int | None] = mapped_column(Integer)
    pr_line_id: Mapped[str | None] = mapped_column(String)
    validity_end: Mapped[str | None] = mapped_column(String)
    validity_end_raw: Mapped[str | None] = mapped_column(String)
    pv_clause: Mapped[int] = mapped_column(Integer)
    pv_index: Mapped[str | None] = mapped_column(String)  # the index the clause names
    pv_base_month: Mapped[str | None] = mapped_column(String)
    pv_variable_share: Mapped[float | None] = mapped_column(Float)
    pv_raw: Mapped[str | None] = mapped_column(String)
    payment_terms: Mapped[str | None] = mapped_column(String)
    received_base: Mapped[float] = mapped_column(Float)  # net of reversals and returns
    open_base: Mapped[float] = mapped_column(Float)
    open_value: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)  # open | received
    flags: Mapped[str] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)
