"""Goods receipts (SAP MB51): 101 receipts, 102 reversals and 122 returns, each signed as SAP exports it, netted per PO line."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<material document>/<item>"
    mat_doc: Mapped[str] = mapped_column(String)
    item: Mapped[int] = mapped_column(Integer)
    movement: Mapped[str] = mapped_column(String)  # 101 | 102 | 122
    posting_date: Mapped[str] = mapped_column(String)
    posting_date_raw: Mapped[str] = mapped_column(String)
    material: Mapped[str | None] = mapped_column(ForeignKey("materials.code"))
    plant: Mapped[str] = mapped_column(String)
    plant_name: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    qty: Mapped[float] = mapped_column(Float)  # signed, as exported
    qty_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    qty_base: Mapped[float] = mapped_column(Float)  # signed, in the material's base unit
    amount: Mapped[float] = mapped_column(Float)  # signed INR
    amount_raw: Mapped[str] = mapped_column(String)
    po_no: Mapped[str | None] = mapped_column(String)
    po_item: Mapped[int | None] = mapped_column(Integer)
    po_line_id: Mapped[str | None] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String)
    reference: Mapped[str | None] = mapped_column(String)
    flags: Mapped[str] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)
