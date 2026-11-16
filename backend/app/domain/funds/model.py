"""The monthly fund requirement (MIS sheets in ₹ Cr, heads x projects), as long-form lines in rupees, and its comparison with the material
requirement for the same project, head and month."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class FundLine(Base):
    __tablename__ = "fund_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)  # YYYY-MM
    built_on: Mapped[str] = mapped_column(String)
    head: Mapped[str] = mapped_column(String)
    column_as_printed: Mapped[str] = mapped_column(String)
    project_ids: Mapped[str | None] = mapped_column(String)  # comma list; None for a column no project resolves to
    band: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)  # INR
    amount_raw: Mapped[str] = mapped_column(String)
    unit_raw: Mapped[str] = mapped_column(String)  # cr | lakh | rupee
    src_row: Mapped[int] = mapped_column(Integer)
    src_col: Mapped[int] = mapped_column(Integer)
    flags: Mapped[str] = mapped_column(Text)


class FundCheck(Base):
    """One project (or fund column), head and month: what the material requirement prices and what the fund sheet asks, side by side."""

    __tablename__ = "fund_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    month: Mapped[str] = mapped_column(String)
    column_as_printed: Mapped[str] = mapped_column(String)
    project_ids: Mapped[str | None] = mapped_column(String)
    head: Mapped[str] = mapped_column(String)
    requirement: Mapped[float | None] = mapped_column(Float)  # INR; None when the requirement sheets carry no column for it
    fund: Mapped[float] = mapped_column(Float)
    difference: Mapped[float | None] = mapped_column(Float)
    disagrees: Mapped[int] = mapped_column(Integer)
    fund_line_ids: Mapped[str] = mapped_column(Text)
    requirement_line_ids: Mapped[str | None] = mapped_column(Text)
