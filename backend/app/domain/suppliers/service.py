"""Suppliers as companies: one identity, its ERP records, its open exposure and its contact on file."""

from __future__ import annotations

from app.domain import naming
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.suppliers.risk import risk_flags
from app.domain.inbox.model import Message
from app.domain.news.model import NewsItem
from app.domain.orders import service as orders
from app.domain.orders.model import PoLine
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord
from app.domain.suppliers.schema import Contact, DeliveryPerformance, LateStreak, Supplier, SupplierDetail
from app.domain.values import prov, ref, usd

STATUS = {"Active": "active", "On hold": "hold", "Inactive": "inactive"}


def open_summary(open_n: int, stale_n: int) -> str:
    """The header over a list of order rows: the rows are the open ones and the old ones that may not really be open, and the header says both."""
    return f"{open_n} open" + (f" · {stale_n} may not really be open" if stale_n else "")


def contact_on_file(session: Session, identity_id: str) -> Contact:
    """The contact of the identity's canonical record. A message's sender address is never a recipient."""
    r = session.get(SupplierRecord, identity_id)
    return Contact(name=r.contact_name if r else None, email=r.contact_email if r else None)


STREAK_MIN = 3  # late receipts in a row before the record shows the streak (in the recipe's data the runs that matter are 5 to 10 long; a pair is noise)


@memo
def delivery_performance(session: Session) -> dict[str, DeliveryPerformance]:
    """{supplier id: how it delivered}, from closed lines that have a promise and a receipt date: on time is received on or before the promise.
    Beside the all-time share: the latest 10 receipts, and the current late streak with this year's late share against last year's (the all-time
    share hides a supplier getting worse: 70% on time over all time while its last 9 receipts were late)."""
    from datetime import date as _date

    from app.domain.common import AS_OF

    seen: dict[str, list[tuple[str, int]]] = {}
    rows = session.execute(select(PoLine.identity_id, PoLine.promised_date, PoLine.received_date, PoLine.id).where(
        PoLine.status == "CLOSED", PoLine.promised_date.is_not(None), PoLine.received_date.is_not(None)).order_by(PoLine.received_date, PoLine.id))
    for ident, promised, received, _ in rows:
        seen.setdefault(ident, []).append((received[:10], (_date.fromisoformat(received[:10]) - _date.fromisoformat(promised[:10])).days))
    year = AS_OF.year
    out: dict[str, DeliveryPerformance] = {}
    for i, rs in seen.items():
        ds = [d for _, d in rs]
        run = []
        for r in reversed(rs):
            if r[1] <= 0:
                break
            run.append(r)
        this = [d for rec, d in rs if int(rec[:4]) == year]
        last = [d for rec, d in rs if int(rec[:4]) == year - 1]
        pct = lambda xs: round(sum(1 for d in xs if d > 0) / len(xs), 3) if xs else None  # noqa: E731
        streak = None
        if len(run) >= STREAK_MIN:
            share = f" · {round(100 * pct(this))}% late in {year}" + (f" ({round(100 * pct(last))}% in {year - 1})" if last else "") if this else ""
            streak = LateStreak(late_in_row=len(run), first=run[-1][0], last=run[0][0], min_days_late=min(d for _, d in run), max_days_late=max(d for _, d in run),
                                year=year, late_this_year=sum(1 for d in this if d > 0), n_this_year=len(this), late_pct_this_year=pct(this) or 0.0,
                                late_last_year=sum(1 for d in last if d > 0), n_last_year=len(last), late_pct_last_year=pct(last),
                                line=f"Last {len(run)} receipts late{share}")
        tail = ds[-10:]
        out[i] = DeliveryPerformance(n=len(ds), on_time=sum(1 for d in ds if d <= 0), on_time_pct=round(sum(1 for d in ds if d <= 0) / len(ds), 3), late=sum(1 for d in ds if d > 0),
                                     avg_days_late=round(sum(d for d in ds if d > 0) / sum(1 for d in ds if d > 0), 1) if any(d > 0 for d in ds) else None,
                                     last10_on_time=sum(1 for d in tail if d <= 0), last10_n=len(tail), streak=streak)
    return out


def _quoted_terms(session: Session, identity_id: str) -> str | None:
    """Payment terms a quote on file says changed ("Net 30 (was 45)"): they replace the supplier master's, while the quote is valid (BUYER 02).
    A quote that only states its own terms changes nothing on the account."""
    from app.domain.common import AS_OF  # noqa: PLC0415
    from app.domain.quotes.model import Offer  # noqa: PLC0415

    rows = session.scalars(select(Offer).where(Offer.identity_id == identity_id, Offer.trust == "ok", Offer.superseded_by.is_(None),
                                               Offer.payment_terms.like("%(was %"))).all()
    valid = sorted((o for o in rows if not o.validity_date or o.validity_date >= AS_OF.isoformat()), key=lambda o: o.validity_date or "", reverse=True)
    return valid[0].payment_terms if valid else None


def _row(session: Session, i: SupplierIdentity, recs: list[SupplierRecord], open_value: float, past_due: int) -> Supplier:
    canon = next(r for r in recs if r.record_id == i.id)
    place = f" {canon.incoterm_place}" if canon.incoterm_place and canon.incoterm_place != "Origin" else (" Origin" if canon.incoterm_place else "")
    return Supplier(
        ref=ref("supplier", i.id, i.name), short=naming.supplier_name(session, i.id), country=canon.country or "", terms=_quoted_terms(session, i.id) or canon.payment_terms or canon.payment_terms_raw or "",
        incoterms=f"{canon.incoterm}{place}" if canon.incoterm else "", status=STATUS[canon.status], records=len(recs),
        open_value=usd(open_value, prov("computed", "po_lines", rule="open value over every record of the company")),
        past_due_lines=past_due, risk=risk_flags(session, i.id), delivery=delivery_performance(session).get(i.id))


@memo
def list_suppliers(session: Session) -> list[Supplier]:
    recs: dict[str, list[SupplierRecord]] = {}
    for r in session.scalars(select(SupplierRecord)):
        recs.setdefault(r.identity_id, []).append(r)
    val: dict[str, float] = {}
    for l in session.scalars(select(PoLine).where(PoLine.status.in_(orders.OPEN))):
        if "stale_open" not in (l.flags or ""):
            val[l.identity_id] = val.get(l.identity_id, 0.0) + (l.open_usd or 0.0)
    late: dict[str, int] = {}
    for s in orders.past_due(session):
        late[s.supplier.id] = late.get(s.supplier.id, 0) + 1
    return [_row(session, i, recs[i.id], val.get(i.id, 0.0), late.get(i.id, 0))
            for i in session.scalars(select(SupplierIdentity).order_by(SupplierIdentity.name))]


def profile(session: Session, identity_id: str) -> SupplierDetail | None:
    row = next((s for s in list_suppliers(session) if s.ref.id == identity_id), None)
    if row is None:
        return None
    recs = list(session.scalars(select(SupplierRecord).where(SupplierRecord.identity_id == identity_id)))
    canon = next(r for r in recs if r.record_id == identity_id)
    all_open = [s for s in orders.open_supply(session) if s.supplier.id == identity_id]
    open_lines = [s for s in all_open if not s.stale]
    return SupplierDetail(
        **row.model_dump(), contact=contact_on_file(session, identity_id), tier=canon.tier, record_ids=sorted(r.record_id for r in recs), open_lines=len(open_lines), stale_lines=len(all_open) - len(open_lines),
        open_summary=open_summary(len(open_lines), len(all_open) - len(open_lines)),
        messages=[ref("message", m) for m in session.scalars(select(Message.id).where(Message.identity_id == identity_id).order_by(Message.date))],
        news=[ref("news", n) for n in session.scalars(select(NewsItem.id).where(NewsItem.identity_id == identity_id).order_by(NewsItem.date))])


def delivery_ranking(session: Session, limit: int = 10) -> list[dict]:
    """Suppliers ranked by how often they delivered late, from closed lines with a promise and a receipt: the on-time share (lowest first, more lines first among equals),
    the closed lines it rests on, the open lines already past due and their value, and the parts the company buys from it most often."""
    parts: dict[str, dict[str, int]] = {}
    for ident, part in session.execute(select(PoLine.identity_id, PoLine.part_number)):
        parts.setdefault(ident, {}).setdefault(part, 0)
        parts[ident][part] += 1
    perf = delivery_performance(session)
    rows = []
    for sup in list_suppliers(session):
        d = perf.get(sup.ref.id)
        if d is None:
            continue
        top = sorted(parts.get(sup.ref.id, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        rows.append({"supplier": sup.ref.id, "name": sup.ref.label or sup.ref.id, "closed_lines": d.n, "on_time": d.on_time, "on_time_pct": round(d.on_time_pct * 100), "late": d.late,
                     "avg_days_late": d.avg_days_late, "past_due_open_lines": sup.past_due_lines, "open_value_usd": round(sup.open_value.usd or 0), "top_parts": [p for p, _ in top]})
    rows.sort(key=lambda r: (r["on_time_pct"], -r["closed_lines"], r["supplier"]))
    return rows[:limit]
