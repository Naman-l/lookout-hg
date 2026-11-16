"""Vendor shapes (the screens and the API say "vendor"; the platform's model names stay `Supplier*`)."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import EntityRef, Money
from app.domain.receipts.service import Delivery


class Contact(BaseModel):
    name: str | None
    email: str | None  # the only valid recipient for anything Lookout drafts to the vendor


class VendorCode(BaseModel):
    """One SAP vendor code of the company: a renamed company keeps both codes, linked, never merged."""

    code: str
    name: str
    gstin: str | None
    msme: bool
    udyam: str | None
    city: str | None
    region: str | None
    bank_masked: str | None
    blocked: bool
    created_on: str | None
    link: str  # stated (its own record) | answer (a person linked it, with evidence)
    evidence: str | None = None


class LibraryEntry(BaseModel):
    vertical: str
    sub_vertical: str | None
    category: str | None
    approved_on: str | None
    status: str
    link: str  # how the library row was tied to the SAP record: sap_code | gstin | name


class VendorRow(BaseModel):
    ref: EntityRef  # supplier:<identity>
    name: str
    codes: list[str]
    gstin: str | None
    msme: bool
    city: str | None
    region: str | None
    verticals: list[str]  # the library verticals it is approved in (none: not in the library)
    in_library: bool
    open_lines: int
    open_value: Money
    po_value: Money  # every PO line on file with it
    on_time_pct: int | None
    receipts: int
    streak: int
    renamed: bool  # carries two codes (a new legal entity)
    cases: list[EntityRef] = []  # Today items that name it


class MsmeDue(BaseModel):
    invoice: str
    po: str | None
    invoice_date: str
    due_by: str  # 45 days from the invoice (the MSMED Act's limit)
    amount: Money
    days_left: int


class VendorDetail(VendorRow):
    contact: Contact
    records: list[VendorCode]
    library: list[LibraryEntry]
    delivery: Delivery
    payment_terms: list[str]  # the terms on its open POs, as SAP's codes mean them
    msme_due: list[MsmeDue]  # unpaid invoices of an MSME vendor that fall due within 45 days of the data date
    guarantees: list[dict]  # its LCs and bank guarantees on file
    po_lines: list[EntityRef]
    quotes: list[EntityRef]
    messages: list[EntityRef]
