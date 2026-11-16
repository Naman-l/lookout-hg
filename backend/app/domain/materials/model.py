"""Materials: the SAP material master, with the group a sheet row or a fund head maps to and the index its price moves with."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Material(Base):
    __tablename__ = "materials"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String)
    group: Mapped[str] = mapped_column(String)  # SAP material group
    category: Mapped[str] = mapped_column(String)  # the coarser category a buyer reads (answers.yaml)
    base_uom: Mapped[str] = mapped_column(String)
    alt_uom: Mapped[str | None] = mapped_column(String)
    alt_per_base: Mapped[float | None] = mapped_column(Float)  # alternate units in one base unit (20 bags in a tonne)
    lead_days: Mapped[int | None] = mapped_column(Integer)  # planned delivery time
    pv_index: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
