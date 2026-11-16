"""Vendors: one row per company (its SAP codes linked, never merged), with what the library approves it for, how it has delivered, what is open
with it, and, for an MSME vendor, the invoices that fall due under the 45-day rule."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.inbox.model import Message
from app.domain.orders.model import PoLine
from app.domain.payments.model import LcBg, VendorLedgerItem
from app.domain.quotes.model import Quote
from app.domain.receipts.service import delivery
from app.domain.suppliers.model import VendorLibraryRow
from app.domain.suppliers.schema import Contact, LibraryEntry, MsmeDue, VendorCode, VendorDetail, VendorRow
from app.domain.values import money, prov, ref


def contact_on_file(session: Session, identity_or_record: str | None) -> Contact:
    name, email = lookups.contact_on_file(session, identity_or_record)
    return Contact(name=name, email=email)


@memo
def _library(session: Session) -> dict[str, list[VendorLibraryRow]]:
    out: dict[str, list[VendorLibraryRow]] = {}
    recs = lookups.records(session)
    for row in session.scalars(select(VendorLibraryRow).where(VendorLibraryRow.record_id.is_not(None))):
        ident = recs[row.record_id].identity_id if row.record_id in recs else row.record_id
        out.setdefault(ident, []).append(row)
    return out


def library_verticals(session: Session, identity_id: str) -> list[str]:
    return sorted({r.vertical for r in _library(session).get(identity_id, []) if (r.status or "").lower().startswith("approved")})


@memo
def _lines_by_vendor(session: Session) -> dict[str, list[PoLine]]:
    out: dict[str, list[PoLine]] = {}
    for l in session.scalars(select(PoLine)):
        out.setdefault(l.identity_id, []).append(l)
    return out


def _row(session: Session, ident: str) -> VendorRow:
    recs = lookups.records_of(session).get(ident, [])
    newest = recs[-1] if recs else None
    lines = _lines_by_vendor(session).get(ident, [])
    open_ = [l for l in lines if l.status == "open"]
    d = delivery(session, ident)
    lib = _library(session).get(ident, [])
    return VendorRow(
        ref=ref("supplier", ident, lookups.vendor_name(session, ident)), name=lookups.vendor_name(session, ident), codes=[r.record_id for r in recs],
        gstin=newest.gstin if newest else None, msme=any(r.msme for r in recs), city=newest.city if newest else None, region=newest.region if newest else None,
        verticals=library_verticals(session, ident), in_library=bool(lib), open_lines=len(open_),
        open_value=money(sum(l.open_value for l in open_), prov("computed", "po_lines", rule="open value of its PO lines (ordered less received, net of reversals)",
                                                            inputs=[ref("po_line", l.id) for l in open_[:100]], by="suppliers.service")),
        po_value=money(sum(l.value for l in lines), prov("computed", "po_lines", rule="value of every PO line on file with it", by="suppliers.service")),
        on_time_pct=d.on_time_pct, receipts=d.n, streak=d.streak, renamed=len(recs) > 1)


@memo
def list_vendors(session: Session) -> list[VendorRow]:
    """Every company in the vendor master, the most open value first, then by name (a list to find a vendor in, not a ranking of vendors)."""
    rows = [_row(session, i) for i in lookups.identities(session)]
    return sorted(rows, key=lambda r: (-float(r.open_value.amount), r.name))


def msme_due(session: Session, ident: str) -> list[MsmeDue]:
    """Unpaid invoices of an MSME vendor whose 45-day limit falls within 45 days of the data date (or has passed)."""
    if not any(r.msme for r in lookups.records_of(session).get(ident, [])):
        return []
    limit = int(lookups.answers().get("msme_payment_days") or 45)
    codes = [r.record_id for r in lookups.records_of(session).get(ident, [])]
    out = []
    for it in session.scalars(select(VendorLedgerItem).where(VendorLedgerItem.record_id.in_(codes), VendorLedgerItem.doc_type == "RE",
                                                              VendorLedgerItem.clearing_doc.is_(None))):
        due = date.fromisoformat(it.doc_date) + timedelta(days=limit)
        left = (due - AS_OF).days
        if left <= limit:
            out.append(MsmeDue(invoice=it.reference or it.doc_no, po=it.po_no, invoice_date=it.doc_date, due_by=due.isoformat(), days_left=left,
                               amount=money(abs(it.amount), prov("stated", "vendor_ledger", row=str(it.src_row), raw=it.amount_raw, by="suppliers.service"))))
    return sorted(out, key=lambda m: m.due_by)


def profile(session: Session, ident_or_code: str) -> VendorDetail | None:
    ident = lookups.identity_of(session, ident_or_code) or (ident_or_code if ident_or_code in lookups.identities(session) else None)
    if ident is None:
        return None
    row = _row(session, ident)
    recs = lookups.records_of(session).get(ident, [])
    terms_map = lookups.answers().get("payment_terms") or {}
    lines = _lines_by_vendor(session).get(ident, [])
    codes = [r.record_id for r in recs]
    guarantees = [dict(kind=g.kind, number=g.number, po=g.po_no, amount=float(g.amount), to_open_by=g.to_open_by, issued_on=g.issued_on, expiry=g.expiry,
                       status=g.status, remarks=g.remarks) for g in session.scalars(select(LcBg).where(LcBg.record_id.in_(codes)))]
    quotes = list(session.scalars(select(Quote).where(Quote.identity_id == ident).order_by(Quote.quote_date.desc())))
    msgs = list(session.scalars(select(Message).where(Message.identity_id == ident).order_by(Message.date.desc())))
    return VendorDetail(
        **row.model_dump(), contact=contact_on_file(session, ident),
        records=[VendorCode(code=r.record_id, name=r.name, gstin=r.gstin, msme=bool(r.msme), udyam=r.udyam, city=r.city, region=r.region, bank_masked=r.bank_masked,
                            blocked=bool(r.blocked), created_on=r.created_on, link=r.identity_method, evidence=r.identity_evidence) for r in recs],
        library=[LibraryEntry(vertical=x.vertical, sub_vertical=x.sub_vertical, category=x.category, approved_on=x.approved_on, status=x.status, link=x.link_method)
                 for x in _library(session).get(ident, [])],
        delivery=delivery(session, ident),
        payment_terms=sorted({(terms_map.get(l.payment_terms) or {}).get("label", l.payment_terms or "") for l in lines if l.status == "open" and l.payment_terms}),
        msme_due=msme_due(session, ident), guarantees=guarantees,
        po_lines=[ref("po_line", l.id, l.short_text) for l in sorted(lines, key=lambda l: l.doc_date, reverse=True)],
        quotes=[ref("quote", q.id, f"{q.cs_no or 'mail'} · {q.vendor_name}") for q in quotes],
        messages=[ref("message", m.id, m.subject) for m in msgs])
