"""Suppliers: an identity (the real company) and its ERP records (one or more ids, never merged)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class SupplierIdentity(Base):
    """One real company. `id` is the record id of its canonical (newest-system, oldest) record."""

    __tablename__ = "supplier_identities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)
    n_records: Mapped[int] = mapped_column(Integer)


class SupplierRecord(Base):
    """One row of the ERP supplier master, cleaned. Every changed field keeps its raw value beside it."""

    __tablename__ = "supplier_records"

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("supplier_identities.id"))
    identity_method: Mapped[str] = mapped_column(String)  # stated | inferred
    identity_evidence: Mapped[str | None] = mapped_column(Text)
    system: Mapped[str] = mapped_column(String)  # legacy (V-) | new (SUP-)
    name: Mapped[str] = mapped_column(String)  # as entered
    country: Mapped[str | None] = mapped_column(String)  # ISO 3166 alpha-2
    country_raw: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    tier: Mapped[int | None] = mapped_column(Integer)  # None = blank in the ERP (unknown)
    payment_terms_raw: Mapped[str | None] = mapped_column(String)
    payment_terms: Mapped[str | None] = mapped_column(String)  # canonical label, e.g. "Net 60"
    net_days: Mapped[int | None] = mapped_column(Integer)
    prepay_pct: Mapped[int | None] = mapped_column(Integer)  # share paid before shipment
    currency: Mapped[str | None] = mapped_column(String)
    incoterms_raw: Mapped[str | None] = mapped_column(String)
    incoterm: Mapped[str | None] = mapped_column(String)  # FOB | FCA | EXW | DDP | DAP | CIF
    incoterm_place: Mapped[str | None] = mapped_column(String)
    contact_name: Mapped[str | None] = mapped_column(String)
    contact_email: Mapped[str | None] = mapped_column(String)
    email_domain: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # Active | Inactive | On hold
    created_date: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
