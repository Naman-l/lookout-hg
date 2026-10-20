"""Parts: the item master, categories and the buyers who own them."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Buyer(Base):
    __tablename__ = "buyers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # first name: Ana, Ben, Cy, Di, Eve
    name: Mapped[str] = mapped_column(String)
    initials: Mapped[str] = mapped_column(String)


class Part(Base):
    __tablename__ = "parts"

    part_number: Mapped[str] = mapped_column(String, primary_key=True)
    mpn: Mapped[str | None] = mapped_column(String)
    manufacturer: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # finished | subassembly | purchased
    category: Mapped[str] = mapped_column(String)
    category_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    coo: Mapped[str | None] = mapped_column(String)  # ISO alpha-2; None = unknown
    coo_raw: Mapped[str | None] = mapped_column(String)
    coo_method: Mapped[str | None] = mapped_column(String)  # stated (in the item master) | answered (a person said so on the Import screen)
    hts: Mapped[str | None] = mapped_column(String)  # digits only, 6 or 10; None = unknown
    hts_raw: Mapped[str | None] = mapped_column(String)
    hts_method: Mapped[str] = mapped_column(String)  # stated | flagged (a letter-O repaired) | unknown
    preferred_record_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_records.record_id"))
    preferred_identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))
    planned_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # Active | Obsolete
    buyer_id: Mapped[str | None] = mapped_column(ForeignKey("buyers.id"))
    buyer_method: Mapped[str | None] = mapped_column(String)  # inferred (last PO buyer / category default)
    src_row: Mapped[int] = mapped_column(Integer)


class PartLink(Base):
    """Two part numbers that look like one physical part. Linked, never merged."""

    __tablename__ = "part_links"

    part_a: Mapped[str] = mapped_column(ForeignKey("parts.part_number"), primary_key=True)
    part_b: Mapped[str] = mapped_column(ForeignKey("parts.part_number"), primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # same_mpn
    evidence: Mapped[str] = mapped_column(Text)
