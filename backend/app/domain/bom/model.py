"""Bill of materials: one row per parent-and-child pair. Explosion and where-used are derived."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class BomLine(Base):
    __tablename__ = "bom_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_part: Mapped[str] = mapped_column(String)
    child_part: Mapped[str] = mapped_column(String)  # may be absent from the item master (orphan, flagged)
    qty_per: Mapped[float] = mapped_column(Float)
    qty_per_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    uom_raw: Mapped[str] = mapped_column(String)
    level: Mapped[int] = mapped_column(Integer)
    find_no: Mapped[str | None] = mapped_column(String)
    flags: Mapped[str | None] = mapped_column(Text)  # comma list: orphan_child, unit_converted, obsolete_child, second_placement
    src_row: Mapped[int] = mapped_column(Integer)
