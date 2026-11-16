"""The 3-month material requirement (the roads and railway sheets): one line per project, sheet row and month, quantity x rate."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class RequirementLine(Base):
    __tablename__ = "requirement_lines"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sheet: Mapped[str] = mapped_column(String)  # roads | railway
    file: Mapped[str] = mapped_column(String)
    built_on: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    column_as_printed: Mapped[str] = mapped_column(String)
    row_as_printed: Mapped[str] = mapped_column(String)  # the material row as the sheet writes it
    material_codes: Mapped[str] = mapped_column(Text)  # comma list (answers.yaml)
    unit: Mapped[str | None] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    qty_raw: Mapped[str] = mapped_column(String)
    rate: Mapped[float | None] = mapped_column(Float)
    rate_raw: Mapped[str | None] = mapped_column(String)
    amount: Mapped[float | None] = mapped_column(Float)  # INR, qty x rate
    amount_printed: Mapped[float | None] = mapped_column(Float)  # INR, the sheet's own (rounded) Cr figure
    src_row: Mapped[int] = mapped_column(Integer)
    src_col: Mapped[int] = mapped_column(Integer)


class SheetTotal(Base):
    """A total a sheet prints, beside the same total recomputed from the cells read: the gate checks they agree."""

    __tablename__ = "sheet_totals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    file: Mapped[str] = mapped_column(String)
    what: Mapped[str] = mapped_column(String)
    printed: Mapped[float | None] = mapped_column(Float)
    computed: Mapped[float] = mapped_column(Float)
    tolerance: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
