"""The delegation of authority: who signs a document of a kind and value, and who countersigns above a threshold."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class DoaRule(Base):
    __tablename__ = "doa_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[str] = mapped_column(String)
    from_inr: Mapped[float] = mapped_column(Float)
    to_inr: Mapped[float | None] = mapped_column(Float)
    approver: Mapped[str] = mapped_column(String)
    countersign: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
