"""Consigned material: the company's own material sitting at a contract manufacturer, built into one of the company's parts there."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Consignment(Base):
    __tablename__ = "consignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_part: Mapped[str] = mapped_column(ForeignKey("parts.part_number"))
    holder_identity: Mapped[str] = mapped_column(ForeignKey("supplier_identities.id"))
    into_part: Mapped[str] = mapped_column(ForeignKey("parts.part_number"))
    evidence: Mapped[str] = mapped_column(Text)  # the message that says so
    method: Mapped[str] = mapped_column(String)  # stated: a person's answer, bootstrapped from that evidence
