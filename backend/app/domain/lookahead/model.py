"""The long-lead look-ahead: items not yet ordered, with lead times, price basis (PV or firm) and the date the site needs them."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class LookAheadItem(Base):
    __tablename__ = "lookahead_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block: Mapped[str] = mapped_column(String)  # immediate | q4
    project_as_printed: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    scope: Mapped[str | None] = mapped_column(String)  # SS | TL, from the printed name
    item: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)
    rate_raw: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)  # qty x rate (the printed amount is checked against it)
    price_basis: Mapped[str] = mapped_column(String)  # PV | Firm
    lead_min_months: Mapped[int] = mapped_column(Integer)
    lead_max_months: Mapped[int] = mapped_column(Integer)
    lead_raw: Mapped[str] = mapped_column(String)
    need_by: Mapped[str | None] = mapped_column(String)  # YYYY-MM
    order_by: Mapped[str | None] = mapped_column(String)  # need-by minus the longest lead time (YYYY-MM-DD, first of the month)
    material: Mapped[str | None] = mapped_column(String)  # the material master code this item is (answers.yaml)
    pv_index: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)
