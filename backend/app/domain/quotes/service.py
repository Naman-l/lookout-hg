"""Quotes and comparative statements: the CS tracker's rows and the quotes that exist only in mail (each citing its line), with L1 compared to
the last PO rate for the material at that plant and the budget rate for the project."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.budget.model import BudgetRate
from app.domain.cache import memo
from app.domain.orders.service import last_rate
from app.domain.quotes.model import ComparativeStatement, Quote
from app.domain.quotes.schema import CsView, QuoteView
from app.domain.suppliers.service import library_verticals
from app.domain.values import money, prov, ref


def view(session: Session, q: Quote) -> QuoteView:
    recs = lookups.records_of(session).get(q.identity_id or "", [])
    src = prov("extracted", f"message:{q.message_id}", row=q.line_ref, raw=q.rate_raw, by="quotes.service") if q.source == "mail" else \
        prov("stated", "quotes", row=str(q.src_row), raw=q.rate_raw, by="quotes.service")
    return QuoteView(
        ref=ref("quote", q.id, f"{q.vendor_name} · {q.cs_no or 'mail'}"), source=q.source,
        vendor=ref("supplier", q.identity_id, lookups.vendor_name(session, q.identity_id)) if q.identity_id else None, vendor_name=q.vendor_name,
        in_library=bool(q.identity_id and library_verticals(session, q.identity_id)), msme=any(r.msme for r in recs) if recs else None, quote_date=q.quote_date,
        qty=q.qty, uom=q.uom, rate=money(q.rate, src) if q.rate is not None else None, validity=q.validity, price_basis=q.price_basis, pv_formula=q.pv_formula,
        l1=bool(q.l1), message=ref("message", q.message_id) if q.message_id else None, line=q.line_ref, remarks=q.remarks)


@memo
def _by_cs(session: Session) -> dict[str, list[Quote]]:
    out: dict[str, list[Quote]] = {}
    for q in session.scalars(select(Quote).where(Quote.cs_no.is_not(None))):
        out.setdefault(q.cs_no, []).append(q)
    return out


@memo
def budget_rates(session: Session) -> dict[tuple[str, str], BudgetRate]:
    return {(b.project_id, b.material): b for b in session.scalars(select(BudgetRate))}


def budget_rate(session: Session, project_id: str | None, material: str | None) -> BudgetRate | None:
    return budget_rates(session).get((project_id or "", material or ""))


def compare(session: Session, quotes: list[Quote], project_id: str | None, material: str | None, plant: str | None = None) -> dict:
    """L1 among the priced quotes, the last PO rate at the plant (else the project), the budget rate, and how far L1 sits from each."""
    priced = [q for q in quotes if q.rate is not None]
    l1 = min(priced, key=lambda q: (q.rate, q.id)) if priced else None
    plants = [plant] if plant else lookups.plants_of(session).get(project_id or "", [])
    hit = max((h for h in (last_rate(session, material, plant=p) for p in plants) if h), key=lambda h: (h[1].doc_date, h[1].id), default=None) if material and plants else None
    b = budget_rate(session, project_id, material)
    pct = lambda a, base: round(100 * (a - base) / base, 1) if a is not None and base else None  # noqa: E731
    return dict(l1=l1, last=hit, budget=b, l1_vs_last=pct(l1.rate if l1 else None, hit[0] if hit else None), l1_vs_budget=pct(l1.rate if l1 else None, b.rate if b else None))


def cs(session: Session, cs_no: str) -> CsView | None:
    s = session.get(ComparativeStatement, cs_no)
    if s is None:
        return None
    qs = sorted(_by_cs(session).get(cs_no, []), key=lambda q: (q.rate is None, q.rate or 0, q.id))
    c = compare(session, qs, s.project_id, s.material)
    m = lookups.materials(session).get(s.material or "")
    l1v = view(session, c["l1"]) if c["l1"] else None
    qty = c["l1"].qty if c["l1"] else None
    return CsView(
        cs=s.cs_no, kind=s.kind, project=ref("project", s.project_id, lookups.project_name(session, s.project_id)) if s.project_id else None,
        material=ref("material", s.material, m.description if m else None) if s.material else None,
        pr_lines=[ref("pr_line", x) for x in (s.pr_line_ids or "").split(",") if x], rfq_sent=s.rfq_sent, first_quote=s.first_quote, vendors_asked=s.vendors_asked,
        quotes_in=s.quotes_in, status=s.status, approved_on=s.approved_on, approved_by=s.approved_by, quotes=[view(session, q) for q in qs], l1=l1v,
        last_po_rate=money(c["last"][0], prov("stated", "po_lines", row=c["last"][1].id, rule="the newest PO line's rate for this material at the plant",
                                              by="quotes.service")) if c["last"] else None,
        last_po_line=ref("po_line", c["last"][1].id) if c["last"] else None,
        budget_rate=money(c["budget"].rate, prov("stated", "budget_rates", row=str(c["budget"].src_row), raw=c["budget"].rate_raw, by="quotes.service")) if c["budget"] else None,
        l1_vs_last_pct=c["l1_vs_last"], l1_vs_budget_pct=c["l1_vs_budget"],
        value_at_l1=money(c["l1"].rate * qty, prov("computed", "quotes", rule="L1 rate x CS quantity", by="quotes.service")) if c["l1"] and qty else None)


def mail_quotes(session: Session, message_id: str | None = None) -> list[Quote]:
    q = select(Quote).where(Quote.source == "mail")
    if message_id:
        q = q.where(Quote.message_id == message_id)
    return list(session.scalars(q.order_by(Quote.id)))


def quotes_for_material(session: Session, material: str) -> list[QuoteView]:
    return [view(session, q) for q in session.scalars(select(Quote).where(Quote.material == material).order_by(Quote.quote_date.desc()))]


def list_cs(session: Session, status: str | None = None) -> list[ComparativeStatement]:
    q = select(ComparativeStatement)
    if status:
        q = q.where(ComparativeStatement.status == status)
    return list(session.scalars(q.order_by(ComparativeStatement.cs_no)))
