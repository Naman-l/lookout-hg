"""Commodity indices by month (IEEMA, LME, steel, cement, diesel): what a price-variation clause moves with."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class IndexValue(Base):
    __tablename__ = "commodity_index"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<index>:<YYYY-MM>"
    month: Mapped[str] = mapped_column(String)
    index: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
