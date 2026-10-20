"""Tariff rules parsed from the customs broker's advisory."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class TariffRule(Base):
    __tablename__ = "tariff_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tranche: Mapped[int] = mapped_column(Integer)
    hts_prefix: Mapped[str] = mapped_column(String)  # digits only, e.g. 850440
    hts_prefix_raw: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    rate: Mapped[float] = mapped_column(Float)  # 0.25
    effective_date: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String)  # CN: duty follows origin, not export country
    exclusion_contact_by: Mapped[str | None] = mapped_column(String)  # the broker's date to discuss exclusion requests
    in_transit: Mapped[str | None] = mapped_column(Text)  # the notice's in-transit provision for this tranche, in words
    exported_before: Mapped[str | None] = mapped_column(String)  # goods exported before this date ...
    entered_before: Mapped[str | None] = mapped_column(String)
    source_line: Mapped[str | None] = mapped_column(Text)  # the row of the advisory this rule was read from, as written
    advisory_no: Mapped[str | None] = mapped_column(String)
    issued: Mapped[str | None] = mapped_column(String)  # ... and entered before this one owe nothing; None: no in-transit relief


class TariffExclusion(Base):
    __tablename__ = "tariff_exclusions"

    hts_prefix: Mapped[str] = mapped_column(String, primary_key=True)
    hts_prefix_raw: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
