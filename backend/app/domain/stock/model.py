"""What the stores hold, from a count a person gave. The ERP export has no on-hand data, so a part with no count is unknown, never zero."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class StockCount(Base):
    __tablename__ = "stock_counts"

    part_number: Mapped[str] = mapped_column(ForeignKey("parts.part_number"), primary_key=True)
    qty_on_hand: Mapped[float] = mapped_column(Float)  # in the part's own unit
    uom: Mapped[str] = mapped_column(String)
    qty_raw: Mapped[str] = mapped_column(String)  # as the person wrote it
    counted_on: Mapped[str] = mapped_column(String)
    counted_by: Mapped[str] = mapped_column(String)
