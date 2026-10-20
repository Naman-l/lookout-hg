"""Orders as supply: open lines, past due, timelines. Past due is computed against AS_OF, never stored."""

from __future__ import annotations

import re

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.fmt import days as days_text
from app.domain.inbox.model import Message, MessageEvent
from app.domain.orders.model import PoLine
from app.domain.common import Money
from app.domain.orders.schema import PoLine as PoLineOut, PoLineView, RevisedSplit, SupplyLine
from app.domain.suppliers.model import SupplierIdentity
from app.domain.values import prov, qty, ref, usd

OPEN = ("OPEN", "PARTIAL")


def _flags(line: PoLine) -> list[str]:
    return line.flags.split(",") if line.flags else []


def _events(session: Session) -> dict[str, list[MessageEvent]]:
    by_line: dict[str, list[MessageEvent]] = {}
    for e in session.scalars(select(MessageEvent).where(MessageEvent.ref_type == "po_line")
                             .order_by(MessageEvent.message_id, MessageEvent.id)):
        by_line.setdefault(e.ref_id, []).append(e)
    return by_line


def _revised(events: list[MessageEvent]) -> str | None:
    """Latest revised promise from the newest message that revised this line (all of its split dates have arrived by the last)."""
    rev = [e for e in events if e.kind == "promise_revision" and e.date_to]
    if not rev:
        return None
    newest = max(e.message_id for e in rev)
    return max(e.date_to for e in rev if e.message_id == newest)


def current_date(s: SupplyLine) -> str | None:
    """The date the line is now expected: the supplier's revision when there is one, else the ERP promise."""
    return s.revised_promise or s.promise


def revised_before_due(s: SupplyLine) -> bool:
    """The supplier gave a dated revision before the line fell due, and that date is still ahead: it is the line's current best date, and the ERP
    date passing is shown beside it, not read as lateness."""
    return bool(s.revised_promise and s.revised_on and s.promise and s.revised_on <= s.promise and s.revised_promise >= AS_OF.isoformat())


def _revised_on(events: list[MessageEvent], dates: dict[str, str]) -> str | None:
    """The date of the message that gave the revised promise."""
    rev = [e for e in events if e.kind == "promise_revision" and e.date_to]
    return dates.get(max(e.message_id for e in rev)) if rev else None


@memo
def _msg_dates(session: Session) -> dict[str, str]:
    return {m.id: m.date for m in session.scalars(select(Message))}


def _splits(events: list[MessageEvent]) -> list[RevisedSplit]:
    """What arrives on which date, when the newest revising message splits the line (a single date gives no split)."""
    rev = [e for e in events if e.kind == "promise_revision" and e.date_to]
    if not rev:
        return []
    newest = max(e.message_id for e in rev)
    parts = [e for e in rev if e.message_id == newest and e.qty]
    return [RevisedSplit(date=e.date_to, qty=e.qty) for e in sorted(parts, key=lambda e: e.date_to)] if len(parts) > 1 else []


def _days_past_due(promise: str | None, as_of: date) -> int | None:
    if not promise:
        return None
    d = (as_of - date.fromisoformat(promise)).days
    return d if d > 0 else None


def _open_value(line: PoLine) -> Money:
    """What is still to arrive, in dollars at finance's rate for the order month. With no rate the value stays in the order's own currency and `usd` is None:
    it is never a zero and never an unconverted amount added to a dollar total."""
    if line.open_usd is not None:
        return usd(line.open_usd, prov("computed", "po_lines", row=line.id, rule="open quantity times the order price, at finance's rate for the order month", by="orders.open_supply"))
    amount = Decimal(str(round((line.qty - (line.qty_received or 0)) * line.unit_price, 6)))
    return Money(amount=amount, currency=line.currency, provenance=prov("computed", "po_lines", row=line.id, by="orders.open_supply",
                                                                       rule="open quantity times the order price in the order's own currency: no exchange rate for its month"))


def _open_value_own(line: PoLine) -> Money:
    """What is still to arrive in the order's own currency: open quantity times the order price, as the supplier invoices it."""
    amount = Decimal(str(round((line.qty - (line.qty_received or 0)) * line.unit_price, 6)))
    return Money(amount=amount, currency=line.currency, provenance=prov("computed", "po_lines", row=line.id, by="orders.open_supply",
                                                                      rule="open quantity times the order price in the order's own currency"))


def _supply(line: PoLine, events: list[MessageEvent], names: dict[str, str], as_of: date, dates: dict[str, str]) -> SupplyLine:
    fm = next((e for e in events if e.kind == "force_majeure"), None)
    src = prov("computed", "po_lines", row=line.id, rule="ordered minus received, in the part's unit",
               by="orders.open_supply")
    return SupplyLine(
        po_line=ref("po_line", line.id), part=ref("part", line.part_number), record=ref("supplier_record", line.record_id),
        supplier=ref("supplier", line.identity_id, names.get(line.identity_id)), status=line.status,
        qty=qty(line.open_qty_ea or 0, {"FT": "M", "M": "M", "PK": "PK"}.get(line.uom, "EA"), src),
        open_value=_open_value(line), open_value_own=_open_value_own(line),
        promise=line.promised_date, revised_promise=_revised(events), revised_on=_revised_on(events, dates), revised_splits=_splits(events),
        days_past_due=_days_past_due(line.promised_date, as_of),
        disrupted_by=ref("message", fm.message_id) if fm else None,
        stale="stale_open" in _flags(line), flags=_flags(line))


@memo
def _all_open_supply(session: Session, as_of: date) -> list[SupplyLine]:
    """Every open and partial line as supply, oldest promise first: read once per database, so a per-part question is a filter and not another set of queries."""
    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    ev, dates = _events(session), _msg_dates(session)
    lines = session.scalars(select(PoLine).where(PoLine.status.in_(OPEN)).order_by(PoLine.promised_date, PoLine.id)).all()
    bodies = {m.id: (m.body or "").lower() for m in session.scalars(select(Message))}
    out = []
    for l in lines:
        events = ev.get(l.id, [])
        s = _supply(l, events, names, as_of, dates)
        rev = [e for e in events if e.kind == "promise_revision" and e.date_to]
        by = max(e.message_id for e in rev) if rev else None
        later = bool(s.revised_promise and s.promise and s.revised_promise > s.promise)
        kind = "force majeure" if s.disrupted_by else ("allocation" if re.search(r"allocat", bodies.get(by, "")) else "slip") if later else None
        out.append(s.model_copy(update={"revised_by": ref("message", by) if by else None, "notice_kind": kind}))
    return out


def open_supply(session: Session, part: str | None = None, *, as_of: date = AS_OF) -> list[SupplyLine]:
    """Open and partial lines for `part` (or every part), oldest promise first. Stale lines are included but marked
    `stale`: callers decide; the shortage and net-exposure rules leave them out."""
    everything = _all_open_supply(session, as_of)
    return everything if part is None else [s for s in everything if s.part.id == part]


@memo
def past_due(session: Session, *, as_of: date = AS_OF, buyer: str | None = None, include_stale: bool = False) -> list[SupplyLine]:
    """Open lines whose promise date is before `as_of` (strictly). The ERP date decides; a supplier's revised date is shown
    beside it. Stale lines are listed separately (they are an unknown, not a delay) unless `include_stale`."""
    q = select(PoLine).where(PoLine.status.in_(OPEN), PoLine.promised_date < as_of.isoformat())
    if buyer:
        q = q.where(PoLine.buyer_id == buyer)
    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    ev, dates = _events(session), _msg_dates(session)
    out = [_supply(l, ev.get(l.id, []), names, as_of, dates) for l in session.scalars(q.order_by(PoLine.promised_date))]
    return out if include_stale else [s for s in out if not s.stale]


def _stale_unknown(l: PoLine, s: SupplyLine, owner: str):
    from app.domain.values import unknown

    return unknown("whether this order is still open", f"ordered {l.order_date}, promised {l.promised_date}, {days_text(s.days_past_due)} past due: it may have been delivered or cancelled and never closed",
                   owner.split()[0], f"Was {l.id} ({l.part_number}) delivered, cancelled, or is it really still open?", [s.po_line, s.part])


@memo
def open_orders(session: Session, buyer: str | None = None, *, as_of: date = AS_OF, include_stale: bool = True) -> list[PoLineOut]:
    """The open PO report: open and partial lines, oldest promise first, optionally one buyer's (first name or full name). Stale lines (ordered over a year
    ago, still open) come last, marked `stale` with their Unknown, with no past-due days: they are not counted as open or late anywhere."""
    from app.domain.parts.service import buyer_name

    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    ev, dates = _events(session), _msg_dates(session)
    q = select(PoLine).where(PoLine.status.in_(OPEN))
    out = []
    for l in session.scalars(q.order_by(PoLine.promised_date, PoLine.id)):
        bn = buyer_name(session, l.buyer_id)
        if buyer and buyer not in (l.buyer_id, bn):
            continue
        s = _supply(l, ev.get(l.id, []), names, as_of, dates)
        if s.stale and not include_stale:
            continue
        factor = (l.unit_price / l.unit_usd_each / l.fx_rate) if (l.unit_usd_each and l.fx_rate) else 1.0
        price = None
        if l.unit_usd_each is not None:
            price = Money(amount=Decimal(str(round(l.unit_price / factor, 6))), currency=l.currency, usd=Decimal(str(round(l.unit_usd_each, 6))),
                          rate=Decimal(str(l.fx_rate)), rate_month=l.fx_month,
                          provenance=prov("inferred" if l.currency_method == "inferred" else "stated", "po_lines", row=l.id, raw=l.unit_price_raw + " " + l.currency_raw,
                                          rule="currency taken from the supplier record (the line has none)" if l.currency_method == "inferred" else None))
        out.append(PoLineOut(ref=s.po_line, part=s.part, supplier=s.supplier, qty=s.qty, unit_price=price, promise_date=l.promised_date,
                             revised_date=s.revised_promise, days_past_due=None if s.stale else s.days_past_due, status=l.status, disrupted_by=s.disrupted_by, buyer=bn,
                             stale=s.stale, unknown=_stale_unknown(l, s, bn) if s.stale else None))
    return sorted(out, key=lambda x: x.stale)


def line_view(session: Session, po_line_id: str, *, as_of: date = AS_OF) -> PoLineView | None:
    """One PO line with the source row beside the clean one, for the PO line page. Works for closed and cancelled lines too."""
    from app.domain.orders.schema import PoLineView as View
    from app.domain.parts.service import buyer_name
    from sqlalchemy import text

    l = session.get(PoLine, po_line_id)
    if l is None:
        return None
    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    ev = _events(session).get(l.id, [])
    raw = session.connection().execute(text("select * from raw_purchase_orders where src_row = :r"), {"r": l.src_row}).mappings().one()
    factor = (l.unit_price / l.unit_usd_each / l.fx_rate) if (l.unit_usd_each and l.fx_rate) else None
    me = ref("po_line", l.id)
    price = Money(amount=Decimal(str(round(l.unit_price / (factor or 1.0), 6))), currency=l.currency, usd=Decimal(str(round(l.unit_usd_each, 6))) if l.unit_usd_each is not None else None,
                  rate=Decimal(str(l.fx_rate)), rate_month=l.fx_month,
                  provenance=prov("inferred" if l.currency_method == "inferred" else "stated", "po_lines", row=l.id, raw=f"{l.unit_price_raw} {l.currency_raw}".strip(),
                                  rule="currency taken from the supplier record: the line has none" if l.currency_method == "inferred" else None))
    value = usd(l.line_usd or 0, prov("computed", "po_lines", row=l.id, rule="qty x price x order-month FX", inputs=[me]))
    open_ = qty(l.open_qty_ea, "EA", prov("computed", "po_lines", row=l.id, rule="(qty - received) x unit conversion")) if l.open_qty_ea is not None else None
    ordered = qty(l.qty_ea, "EA", prov("computed", "po_lines", row=l.id, rule="qty x unit conversion", raw=f"{l.qty_raw} {l.uom_raw}")) if l.qty_ea is not None else None
    return View(po_line=me, part=ref("part", l.part_number), supplier=ref("supplier", l.identity_id, names.get(l.identity_id)), record=ref("supplier_record", l.record_id),
                buyer=buyer_name(session, l.buyer_id), status=l.status, qty_ordered=ordered, qty_open=open_, unit_price=price, line_value=value, promise=l.promised_date,
                revised_promise=_revised(ev), days_past_due=_days_past_due(l.promised_date, as_of) if l.status in OPEN else None,
                flags=_flags(l), raw={k: (v if v != "" else None) for k, v in raw.items() if k != "src_row"})
