"""Budget rates: the tender / BOQ rate per project and material (the estimate purchases are compared with)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class BudgetRate(Base):
    __tablename__ = "budget_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(String)
    plant: Mapped[str | None] = mapped_column(String)
    material: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    rate: Mapped[float] = mapped_column(Float)
    rate_raw: Mapped[str] = mapped_column(String)
    basis: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
