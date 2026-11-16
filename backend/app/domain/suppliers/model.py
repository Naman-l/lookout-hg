"""Vendors: an identity (the real company) and its SAP vendor records (one or more codes, never merged), and the approved-vendor library,
linked to the SAP records where a code, a GSTIN or the name ties them."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class SupplierIdentity(Base):
    """One real company. `id` is the code of its first record; a renamed company keeps its first code as its identity."""

    __tablename__ = "supplier_identities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)  # the newest record's name
    n_records: Mapped[int] = mapped_column(Integer)


class SupplierRecord(Base):
    """One row of the SAP vendor master, cleaned. Every changed field keeps its raw value beside it."""

    __tablename__ = "supplier_records"

    record_id: Mapped[str] = mapped_column(String, primary_key=True)  # the SAP vendor code
    identity_id: Mapped[str] = mapped_column(ForeignKey("supplier_identities.id"))
    identity_method: Mapped[str] = mapped_column(String)  # stated | answer
    identity_evidence: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String)
    gstin: Mapped[str | None] = mapped_column(String)
    pan: Mapped[str | None] = mapped_column(String)
    msme: Mapped[int] = mapped_column(Integer)
    msme_raw: Mapped[str | None] = mapped_column(String)
    udyam: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    region: Mapped[str | None] = mapped_column(String)
    bank_masked: Mapped[str | None] = mapped_column(String)
    contact_name: Mapped[str | None] = mapped_column(String)
    contact_email: Mapped[str | None] = mapped_column(String)
    email_domain: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    blocked: Mapped[int] = mapped_column(Integer)
    created_on: Mapped[str | None] = mapped_column(String)
    created_on_raw: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)


class VendorLibraryRow(Base):
    """A row of the approved-vendor library (an Excel kept outside SAP), linked to a SAP record where the data ties them."""

    __tablename__ = "vendor_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vertical: Mapped[str] = mapped_column(String)
    sub_vertical: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    gstin: Mapped[str | None] = mapped_column(String)
    approved_on: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_records.record_id"))
    link_method: Mapped[str] = mapped_column(String)  # sap_code | gstin | name | none
    sap_code_raw: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
