"""Demand: the products the company builds and the monthly build plan."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Product(Base):
    """A finished robot: the root of a BOM."""

    __tablename__ = "products"

    part_number: Mapped[str] = mapped_column(ForeignKey("parts.part_number"), primary_key=True)
    name: Mapped[str] = mapped_column(String)  # as the forecast spells it: "Alpha A1"
    family: Mapped[str] = mapped_column(String)  # Alpha | Beta | Gamma


class DemandForecast(Base):
    __tablename__ = "demand_forecast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_part: Mapped[str] = mapped_column(ForeignKey("products.part_number"))
    product_raw: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)  # YYYY-MM
    units: Mapped[int] = mapped_column(Integer)
    src_row: Mapped[int] = mapped_column(Integer)
