"""The stage ladder and build readiness. Derived on demand from the records; nothing here is stored or guessed.

A rung is `done` or `expected` only when a record says so (the PO line, a supplier message, the forecast) and it points at that record. Every rung
the data cannot show (acknowledgement, work at the supplier, ship, transit, customs entry, inspection, stock, kit) is `unknown` with the person to
ask; a received date is never used to infer that the goods cleared customs or passed inspection.
"""

from __future__ import annotations

import calendar
from datetime import date
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.bom.service import explode_bom, requirements_per_robot
from app.domain.cache import memo
from app.domain.common.company import company_name
from app.domain.common import AS_OF
from app.domain.demand.model import DemandForecast, Product
from app.domain.demand import service as demand
from app.domain.demand.service import requirements
from app.domain.fmt import count, days as days_text, md, month as month_name
from app.domain.inbox.model import Message
from app.domain.orders import service as orders
from app.domain.orders.model import PoLine
from app.domain.parts.model import Part
from app.domain.phases.schema import Ask, BuildReadiness, BuildSummary, Ladder, LinePromise, Qty, ReadyGroup, ReadyPart, Rung
from app.domain.quotes.model import Offer
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord
from app.domain.ownership import buyer_of_part
from app.domain.values import prov, ref, unknown

LABELS = {
    "need": "Needed", "quote": "Quoted", "ordered": "Ordered", "promised": "Promised", "acknowledged": "Acknowledged", "at_supplier": "Being made",
    "shipped": "Shipped", "in_transit": "In transit", "customs": "Through customs", "received": "Received", "inspected": "Inspected",
    "stocked": "In stock", "kitted": "Kitted", "closed": "Closed",
}
KEYS = tuple(LABELS)


def _owner(session: Session, part: Part | None, line: PoLine | None = None) -> str:
    return buyer_of_part(session, part.part_number if part else None, line.buyer_id if line else None)


def _unknown_rung(key: str, what: str, why: str, owner: str, question: str, refs, detail: str | None = None) -> Rung:
    return Rung(key=key, label=LABELS[key], state="unknown", detail=detail or f"Unknown: {why}", unknown=unknown(what, why, owner, question, refs))


def _middle(session: Session, part: Part | None, line: PoLine | None, subject, supplier: str, po: str, domestic: bool, received: str | None) -> list[Rung]:
    """The rungs the data cannot show. Said once, the same way for every order, with who to ask."""
    note = f" (the goods arrived {md(received)}; that does not tell us this)" if received else ""
    refs = [subject]
    out = [
        _unknown_rung("acknowledged", "whether the supplier acknowledged the order", "the ERP has no acknowledgement field and the inbox holds no acknowledgement for this order",
                      "supplier", f"Has {supplier} acknowledged {po} and confirmed the date?", refs),
        _unknown_rung("at_supplier", "how far the supplier has got making it", "there is no production status in the data, only supplier notices", "supplier",
                      f"Where is {po} in production at {supplier}?", refs),
        _unknown_rung("shipped", "whether it has shipped", "no ship notice, packing list or tracking number is in the data", "supplier", f"Has {supplier} shipped {po}? Ask for the packing list.", refs),
        _unknown_rung("in_transit", "where it is in transit", "no carrier or forwarder data is in the data", "supplier", f"Which carrier and what ETA for {po}?", refs, f"Unknown: no carrier or forwarder data{note}"),
    ]
    if domestic:
        out.append(Rung(key="customs", label=LABELS["customs"], state="na", detail="A US supplier: no import entry"))
    else:
        out.append(_unknown_rung("customs", "whether it has cleared customs", "no entry, ISF or customs status is in the data", "broker",
                                 f"Has the customs broker cleared the shipment for {po}?", refs, f"Unknown: no customs data{note}"))
    return out


def _tail(session: Session, part: Part | None, line: PoLine | None, subject, po: str, on_hand: tuple[float, str, str] | None = None) -> list[Rung]:
    buyer = _owner(session, part, line)
    out = [_unknown_rung("inspected", "whether it passed incoming inspection", "no receiving or inspection records are in the data", buyer, f"Did {po} pass incoming inspection?", [subject])]
    if on_hand:
        q, by, when = on_hand
        out.append(Rung(key="stocked", label=LABELS["stocked"], state="done", date=when, detail=f"{q:g} on hand at the count on {md(when)} (counted by {by})", source=ref("part", part.part_number) if part else None))
    else:
        out.append(_unknown_rung("stocked", "what is in stock", "no stock count is in the data", buyer, f"How many of {part.part_number if part else 'this part'} are on the shelf?", [subject]))
    out.append(_unknown_rung("kitted", "whether it has been kitted for a build", "no kit or work-order data is in the data", buyer, "Has it been kitted for the build?", [subject]))
    return out


def _counts(rungs: list[Rung]) -> dict[str, int]:
    c = {"done": 0, "expected": 0, "late": 0, "disrupted": 0, "unknown": 0, "na": 0}
    for r in rungs:
        c[r.state] += 1
    return c


def _verdict(rungs: list[Rung]) -> str:
    c = _counts(rungs)
    bits = [f"{c['done']} shown by the records", f"{c['expected']} expected"]
    bits += [f"{c[k]} {w}" for k, w in (("late", "late"), ("disrupted", "disrupted")) if c[k]]
    bits.append(f"{c['unknown']} unknown (no data)")
    if c["na"]:
        bits.append(f"{c['na']} not applicable")
    return ", ".join(bits)


def _stock(session: Session) -> dict[str, tuple[float, str, str]]:
    """{part: (on hand, counted by, counted on)} from the latest uploaded count; empty when no count was ever loaded."""
    try:
        from app.domain.stock.model import StockCount
    except ImportError:
        return {}
    try:
        return {s.part_number: (s.qty_on_hand, s.counted_by or "", s.counted_on) for s in session.scalars(select(StockCount))}
    except Exception:  # noqa: BLE001  (a database built before the count existed has no such table)
        return {}


def _need_rung(session: Session, part: str) -> Rung:
    reqs = requirements(session, part)
    if not reqs:
        return Rung(key="need", label=LABELS["need"], state="na", detail="Not in any planned build in the forecast")
    first = reqs[0]
    total = float(sum(r.qty.value for r in reqs))
    by = ", ".join(f"{n} robots of {p}" for p, n in first.by_product.items())
    return Rung(key="need", label=LABELS["need"], state="done", date=first.month + "-01", detail=f"{float(first.qty.value):g} {first.qty.uom} needed in {month_name(first.month)} ({by}); {total:g} over the next {len(reqs)} months",
                source=ref("part", part))


def _quote_rung(session: Session, part: str, identity: str | None, before: str | None, supplier: str) -> Rung:
    q = select(Offer).where(Offer.part_number == part, Offer.superseded_by.is_(None), Offer.trust != "blocked")
    if identity:
        q = q.where(Offer.identity_id == identity)
    dates = {m.id: m.date for m in session.scalars(select(Message))}
    found = sorted(((dates[o.message_id], o) for o in session.scalars(q)), key=lambda t: t[0])
    owner = "supplier"
    prior = [(d, o) for d, o in found if before is None or d <= before]
    if prior:
        d, o = prior[-1]
        return Rung(key="quote", label=LABELS["quote"], state="done", date=d, detail=f"{o.supplier_name} quoted {o.price_raw} {o.currency}" + (f" ({o.quote_no})" if o.quote_no else ""), source=ref("message", o.message_id))
    later = f"; a later quote from {found[0][1].supplier_name} is in the inbox ({md(found[0][0])})" if found else ""
    return _unknown_rung("quote", "the quote this order was placed on", "the inbox holds only the last two months of mail" + later, owner, f"Which quote did {supplier} give for {part}?", [ref("part", part)],
                         "Unknown: no quote for this order in the inbox" + later)


def line_phases(session: Session, po_line_id: str) -> Ladder | None:
    line = session.get(PoLine, po_line_id)
    if line is None:
        return None
    part = session.get(Part, line.part_number)
    me = ref("po_line", line.id)
    ident = session.get(SupplierIdentity, line.identity_id)
    rec = session.get(SupplierRecord, line.record_id)
    supplier = ident.name if ident else line.identity_id
    sup = next((s for s in orders.open_supply(session, line.part_number) if s.po_line.id == line.id), None)
    open_ = sup is not None
    need = _need_rung(session, line.part_number) if open_ else Rung(key="need", label=LABELS["need"], state="na", detail="A closed order")
    rungs = [need, _quote_rung(session, line.part_number, line.identity_id, line.order_date, supplier)]
    rungs.append(Rung(key="ordered", label=LABELS["ordered"], state="done", date=line.order_date, detail=f"{line.qty_raw} {line.uom_raw} ordered from {supplier}", source=me))
    cancelled = line.status == "CANCELLED"
    flags = (line.flags or "").split(",")
    # promised
    if cancelled:
        rungs.append(Rung(key="promised", label=LABELS["promised"], state="na", detail="Cancelled"))
    elif open_ and sup.stale:
        rungs.append(_unknown_rung("promised", "whether this order is still open", f"ordered {md(line.order_date, True)}, promised {md(line.promised_date, True)}: it may have been delivered or cancelled and never closed",
                                   _owner(session, part, line), f"Was {line.id} delivered, cancelled, or really still open?", [me]))
    elif open_ and not line.promised_date:
        rungs.append(_unknown_rung("promised", "the delivery date", "the order has no promise date in the ERP", "supplier", f"What delivery date will {supplier} commit to for {line.id}?", [me]))
    elif open_:
        arrives = orders.current_date(sup)
        flag = "disrupted" if sup.disrupted_by else ("slipped" if sup.revised_promise and sup.revised_promise > sup.promise else ("past_due" if sup.days_past_due else None))
        if sup.disrupted_by:
            det = f"Promised {md(sup.promise)}; named on the supplier's force-majeure notice"
        elif flag == "slipped":
            det = (f"PO date {md(sup.promise)} passed; {supplier}'s notice of {md(sup.revised_on)} revised it to {md(sup.revised_promise)}" if sup.days_past_due
                   else f"The ERP says {md(sup.promise)}; the supplier now says {md(sup.revised_promise)}")
        elif flag == "past_due":
            det = f"Promised {md(sup.promise)}, {days_text(sup.days_past_due)} past due"
        else:
            det = f"Promised {md(sup.promise)}"
        pstate = "disrupted" if flag == "disrupted" else ("late" if (sup.days_past_due or arrives < AS_OF.isoformat()) else "expected")
        rungs.append(Rung(key="promised", label=LABELS["promised"], state=pstate, date=arrives, detail=det, source=sup.disrupted_by or me, flag=flag))
    elif line.promised_date and line.received_date and "received_before_ordered" not in flags:
        late = (date.fromisoformat(line.received_date) - date.fromisoformat(line.promised_date)).days
        how = "on the day" if late == 0 else (f"{abs(late)} days early" if late < 0 else f"{late} days late")
        rungs.append(Rung(key="promised", label=LABELS["promised"], state="done", date=line.promised_date, detail=f"Promised {md(line.promised_date)}, arrived {how}", source=me))
    else:
        rungs.append(Rung(key="promised", label=LABELS["promised"], state="done" if line.promised_date else "na", date=line.promised_date, detail=f"Promised {md(line.promised_date)}" if line.promised_date else "No promise date was recorded", source=me))
    domestic = bool(rec and rec.country == "US")
    middle = _middle(session, part, line, me, supplier, line.po_number, domestic, None if "received_before_ordered" in flags else line.received_date)
    if open_ and sup.disrupted_by:
        for i, r in enumerate(middle):
            if r.key == "at_supplier":
                middle[i] = r.model_copy(update={"flag": "disrupted", "source": sup.disrupted_by, "detail": "Unknown: the supplier's plant is under a force-majeure notice; no production status is in the data"})
    rungs += middle
    # received
    got = line.qty_received or 0
    if cancelled:
        rungs.append(Rung(key="received", label=LABELS["received"], state="na", detail="Cancelled"))
    elif open_:
        ps = next(r for r in rungs if r.key == "promised")
        rstate = ps.state if ps.state in ("late", "disrupted", "expected") else "unknown"
        text = f"{line.qty_received_raw} of {line.qty_raw} {line.uom_raw} received, last on {md(line.received_date)}; the rest has not arrived" if got > 0 else "Nothing received yet"
        if rstate == "unknown":
            rungs.append(_unknown_rung("received", "when the rest arrives", "there is no usable promise date", "supplier", f"When will {supplier} deliver {line.id}?", [me], f"Unknown: {text}"))
        else:
            rungs.append(Rung(key="received", label=LABELS["received"], state=rstate, date=ps.date, detail=text, source=ps.source, flag=ps.flag))
    elif "received_before_ordered" in flags:
        rungs.append(_unknown_rung("received", "when this line arrived", f"its received date ({md(line.received_date, True)}) is before its order date ({md(line.order_date, True)})", "ERP admin",
                                   f"When did {line.id} actually arrive? The ERP's received date is before the order.", [me], "Unknown: the received date in the ERP precedes the order"))
    elif line.received_date:
        rungs.append(Rung(key="received", label=LABELS["received"], state="done", date=line.received_date, detail=f"{line.qty_received_raw} of {line.qty_raw} {line.uom_raw} received", source=me))
    else:
        rungs.append(Rung(key="received", label=LABELS["received"], state="na", detail="Nothing was received"))
    rungs += _tail(session, part, line, me, line.po_number, _stock(session).get(line.part_number))
    # closed
    if open_:
        rungs.append(Rung(key="closed", label=LABELS["closed"], state="expected", detail="Closes when the rest arrives", source=me))
    elif cancelled:
        rungs.append(Rung(key="closed", label=LABELS["closed"], state="done", date=line.received_date or line.order_date, detail="Cancelled", source=me))
    elif "return" in flags:
        rungs.append(Rung(key="closed", label=LABELS["closed"], state="done", date=line.received_date, detail="Returned to the supplier", source=me))
    elif "short_closed" in flags:
        rungs.append(Rung(key="closed", label=LABELS["closed"], state="done", date=line.received_date, detail=f"Closed short: {line.qty_received_raw} of {line.qty_raw} {line.uom_raw} received", source=me))
    else:
        rungs.append(Rung(key="closed", label=LABELS["closed"], state="done", date=None if "received_before_ordered" in flags else line.received_date, detail="Received in full and closed", source=me))
    order = {k: i for i, k in enumerate(KEYS)}
    rungs.sort(key=lambda r: order[r.key])
    cur = orders.current_date(sup) if open_ else None
    return Ladder(subject=me, kind="po_line", rungs=rungs, counts=_counts(rungs), verdict=_verdict(rungs), qty=sup.qty if open_ else None,
                  promised=LinePromise(date=cur, erp_date=sup.promise if sup.promise != cur else None) if cur else None)


ORDER = ("disrupted", "late", "unknown", "expected", "done", "na")   # which state speaks for a part when its open lines disagree


def _roll(key: str, lines: list[Ladder]) -> Rung | None:
    """The part's rung for the current open supply: the worst state among its open lines, the earliest date in that state, the line it comes from."""
    rs = [next(r for r in l.rungs if r.key == key) for l in lines]
    if not rs:
        return None
    worst = min(rs, key=lambda r: ORDER.index(r.state))
    same = [r for r in rs if r.state == worst.state]
    dated = sorted(r.date for r in same if r.date)
    n = f"{len(same)} of {len(rs)} open lines: " if len(rs) > 1 else ""
    out = worst.model_copy(update={"date": dated[0] if dated else None, "detail": n + worst.detail})
    return out


def _last_time(allp: list[PoLine]) -> str:
    recv = [l for l in allp if l.received_date and "received_before_ordered" not in (l.flags or "")]
    if not recv:
        return "nothing has been received in the PO history"
    r = max(recv, key=lambda l: l.received_date)
    return f"last time: {r.qty_received_raw} {r.uom_raw} received {md(r.received_date, True)} ({r.po_number})"


@memo
def part_phases(session: Session, part_number: str) -> Ladder | None:
    """The part against its current need and open supply. Each rung comes from the ladders of the open order lines; what happened on closed orders is history,
    said in the detail ("last time: ...") and never shown as done."""
    part = session.get(Part, part_number)
    if part is None:
        return None
    me = ref("part", part_number, part.description)
    allp = list(session.scalars(select(PoLine).where(PoLine.part_number == part_number).order_by(PoLine.order_date, PoLine.id)))
    supply = orders.open_supply(session, part_number)
    lines = [x for x in (line_phases(session, s.po_line.id) for s in supply) if x]
    live = [l for l, s in zip(lines, supply) if not s.stale]
    rungs = [_need_rung(session, part_number)]
    offers = list(session.scalars(select(Offer).where(Offer.part_number == part_number, Offer.superseded_by.is_(None), Offer.trust != "blocked")))
    dates = {m.id: m.date for m in session.scalars(select(Message))}
    if offers:
        o = max(offers, key=lambda x: dates[x.message_id])
        rungs.append(Rung(key="quote", label=LABELS["quote"], state="done", date=dates[o.message_id], detail=f"{count(len(offers), "live quote")} in the inbox; latest {o.supplier_name}, {o.price_raw} {o.currency}", source=ref("message", o.message_id)))
    else:
        rungs.append(_unknown_rung("quote", "a current quote", "no quote for this part is in the inbox", "supplier", f"Is there a current quote for {part_number}?", [me]))
    history = _last_time(allp)
    if allp and supply:
        last = max(allp, key=lambda l: l.order_date)
        rungs.append(Rung(key="ordered", label=LABELS["ordered"], state="done", date=last.order_date, detail=f"{count(len(supply), "open line")}; latest ordered {md(last.order_date, True)} ({last.po_number})", source=ref("po_line", last.id)))
    elif allp:
        rungs.append(Rung(key="ordered", label=LABELS["ordered"], state="na", detail=f"No open order; last ordered {md(allp[-1].order_date, True)} ({allp[-1].po_number})"))
    else:
        rungs.append(Rung(key="ordered", label=LABELS["ordered"], state="na", detail="Never ordered in the two years of PO history (built in house or not yet bought)"))
    if not supply:
        rungs.append(Rung(key="promised", label=LABELS["promised"], state="na", detail="No open order"))
    else:
        rungs.append(_roll("promised", lines))
    ident = session.get(SupplierIdentity, part.preferred_identity_id) if part.preferred_identity_id else None
    sname = ident.name if ident else "the supplier"
    mid = _middle(session, part, None, me, sname, part_number, False, None)
    for i, r in enumerate(mid):
        if r.key == "at_supplier" and any(next(x for x in l.rungs if x.key == "at_supplier").flag == "disrupted" for l in live):
            hit = next(next(x for x in l.rungs if x.key == "at_supplier") for l in live if next(x for x in l.rungs if x.key == "at_supplier").flag == "disrupted")
            mid[i] = r.model_copy(update={"flag": "disrupted", "source": hit.source, "detail": hit.detail})
    rungs += mid
    if supply:
        got = _roll("received", lines)
        rungs.append(got.model_copy(update={"detail": f"{got.detail}; {history}"}))
    else:
        rungs.append(Rung(key="received", label=LABELS["received"], state="na", detail=f"Nothing to receive; {history}"))
    rungs += _tail(session, part, None, me, part_number, _stock(session).get(part_number))
    rungs.append(Rung(key="closed", label=LABELS["closed"], state="na", detail="Closing belongs to each order line"))
    order = {k: i for i, k in enumerate(KEYS)}
    rungs.sort(key=lambda r: order[r.key])
    return Ladder(subject=me, kind="part", rungs=rungs, counts=_counts(rungs), verdict=_verdict(rungs), lines=lines)


# ---- build readiness ----

def _resolve_product(session: Session, product: str) -> Product | None:
    p = session.get(Product, product.upper())
    if p:
        return p
    key = product.strip().lower().replace("-", " ").replace("_", " ")
    return next((x for x in session.scalars(select(Product)) if x.name.lower() == key), None)


def _month_end(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def _state(need: float, lines, month_end: str, on_hand: float) -> tuple[str, str, str | None, object]:
    """(state, detail, arrives, cause) for a bought part against one month's need."""
    short = max(0.0, need - on_hand)
    if on_hand and short == 0:
        return "in_stock", f"{on_hand:g} on hand at the last count covers the {need:g} needed", None, None
    stock_note = f" ({on_hand:g} on hand counted; {short:g} still to find)" if on_hand else ""
    if not lines:
        if on_hand:
            return "short_after_stock", f"No open order, and the count leaves {short:g} short" , None, None
        return "no_order", "No open order. With no stock data this is unknown, not covered", None, None
    d = next((l for l in lines if l.disrupted_by), None)
    if d:
        return "disrupted", f"Under the supplier's force-majeure notice{stock_note}", orders.current_date(d), d.disrupted_by
    late = [l for l in lines if l.days_past_due and not orders.revised_before_due(l)]
    if late:
        return "past_due", f"{count(len(late), "order")} late on the supplier's latest date, the oldest {days_text(max(l.days_past_due for l in late))}{stock_note}", min(l.promise for l in late), None
    if any(not l.promise for l in lines):
        return "undated", f"An open order has no promise date{stock_note}", None, None
    when = sorted((orders.current_date(l), float(l.qty.value)) for l in lines)
    moved = [l for l in lines if orders.revised_before_due(l)]
    note = ""
    if moved:
        l0 = moved[0]
        note = f" ({l0.supplier.label}'s notice of {md(l0.revised_on)} revised {count(len(moved), "line")}; the PO date {md(l0.promise)} passed)"
    stock_note += note
    in_time = sum(q for dt, q in when if dt <= month_end)
    if in_time >= short:
        last = max(dt for dt, _ in when if dt <= month_end)
        return "covered", f"Dated open supply of {in_time:g} lands by {md(last)}, before the end of the month{stock_note}", last, None
    run = 0.0
    for dt, q in when:
        run += q
        if run >= short:
            return "after_build", f"Dated open supply covers it only on {md(dt)}, after the month ends{stock_note}", dt, None
    return "short", f"Open orders total {sum(q for _, q in when):g} against {short:g} needed{stock_note}", None, None


@memo
def build_readiness(session: Session, product: str, month: str) -> BuildReadiness | None:
    prod = _resolve_product(session, product)
    f = session.scalar(select(DemandForecast).where(DemandForecast.product_part == prod.part_number, DemandForecast.month == month)) if prod else None
    if prod is None or f is None:
        return None
    units = f.units
    me = ref("product", prod.part_number, prod.name)
    per = requirements_per_robot(session)[prod.part_number]
    rows = explode_bom(session, prod.part_number)
    assemblies = {r.path[-2] for r in rows if len(r.path) > 2}
    parts = {p.part_number: p for p in session.scalars(select(Part))}
    by_part: dict[str, list] = defaultdict(list)
    for s in orders.open_supply(session):
        by_part[s.part.id].append(s)
    stock = _stock(session)
    end = _month_end(month)
    states: dict[str, ReadyPart] = {}
    for pn, perrobot in per.items():
        p = parts.get(pn)
        need_v = Decimal(perrobot) * units
        uom = p.uom if p else "EA"
        need = Qty(value=need_v, uom=uom)
        label = p.description if p else None
        if pn in assemblies:
            states[pn] = ReadyPart(part=ref("part", pn, label), state="in_house", detail=f"{company_name(session)} builds this; its parts are counted below", need=need)
            continue
        live = [s for s in by_part.get(pn, []) if not s.stale]
        oh = stock[pn][0] if pn in stock else 0.0
        st, det, arrives, cause = _state(float(need_v), live, end, oh)
        gap = demand.month_gaps(session, pn).get(month) if demand.notice_affects(session, pn) and not oh else None
        if gap is not None:      # a part a notice moved: the same cumulative supply-against-need as the shortage view, not a second count
            under_notice = any(l.disrupted_by for l in live)
            if gap.gap_now > 0.5 and st in ("covered", "past_due", "undated"):
                st, arrives, cause = ("disrupted" if under_notice else "after_build"), None, (next((l.disrupted_by for l in live if l.disrupted_by), None))
                det = f"Dated open supply does not cover the {gap.cum_need:g} needed through the month: {gap.gap_now:g} lands after it"
            elif gap.gap_now <= 0.5 and st in ("disrupted", "after_build"):
                st, arrives, cause = "covered", None, None
                det = f"Dated open supply covers the {gap.cum_need:g} needed through the month" + (" (the lines under the notice count from after the supplier's restart estimate)" if under_notice else "")
        owner = _owner(session, p)
        ask = None
        if st == "no_order":
            ask = Ask(owner=owner, question=f"Do we have {pn} on the shelf, or is an order missing?")
        elif st == "undated":
            ask = Ask(owner="supplier", question=f"What date will the supplier commit to for {pn}?")
        total = sum(float(s.qty.value) for s in live)
        states[pn] = ReadyPart(part=ref("part", pn, label), state=st, detail=det, need=need, open_qty=Qty(value=Decimal(str(total)), uom=uom) if live else None,
                               po_lines=[s.po_line.id for s in live], arrives=arrives, supplier=live[0].supplier if live else None, cause=cause,
                               on_hand=Qty(value=Decimal(str(oh)), uom=uom) if pn in stock else None, ask=ask)
    groups: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        g = r.path[1] if len(r.path) > 2 else prod.part_number
        if r.part.id not in groups[g]:
            groups[g].append(r.part.id)
    out = []
    order_ = [prod.part_number] + [g for g in groups if g != prod.part_number]
    for g in order_:
        if g not in groups:
            continue
        members = [states[x] for x in groups[g]]
        c: dict[str, int] = defaultdict(int)
        for m in members:
            c[m.state] += 1
        gp = parts.get(g)
        out.append(ReadyGroup(assembly=ref("part" if g != prod.part_number else "product", g, gp.description if gp else prod.name), parts=members, counts=dict(c)))
    counts: dict[str, int] = defaultdict(int)
    for s in states.values():
        counts[s.state] += 1
    counts = dict(counts)
    src = prov("computed", "demand_forecast", row=f"{prod.part_number}/{month}", rule="robots planned times the parts each one needs", inputs=[me], by="phases.build_readiness")
    return BuildReadiness(product=me, month=month, units=units, verdict=_verdict_line(prod.name, month, units, counts, bool(stock), company_name(session)), need_source=src, counts=counts, groups=out,
                          stock_counted=sum(1 for pn in states if pn in stock),
                          stock_note="Stock counted for %d of these parts." % sum(1 for pn in states if pn in stock) if stock else "No stock count is loaded: parts with no open order are unknown, not covered.")


def _verdict_line(name: str, month: str, units: int, c: dict[str, int], counted: bool, company: str = "the company") -> str:
    n_parts = sum(v for k, v in c.items() if k != "in_house")
    bits = []
    phrases = [("in_stock", "{} are covered by the stock count"), ("covered", "{} have dated supply landing in the month"), ("after_build", "{} arrive after the month ends"),
               ("past_due", "{} are late on the supplier's latest date"), ("disrupted", "{} are under a supplier's force-majeure notice"), ("short", "{} are short on their open orders"),
               ("undated", "{} have an order with no promise date"), ("short_after_stock", "{} are short after the count"),
               ("no_order", "{} have no open order" + ("" if counted else " (unknown without stock data)"))]
    for k, t in phrases:
        if c.get(k):
            bits.append(t.format(c[k]))
    tail = f"; {c['in_house']} assemblies {company} builds are counted through their parts" if c.get("in_house") else ""
    return f"{name}, {month_name(month)}: {units} robots need {n_parts} bought parts. " + "; ".join(bits) + tail + "."


SUMMARY_STATES = ("covered", "after_build", "past_due", "disrupted", "no_order", "in_house")


@memo
def builds(session: Session) -> list[BuildSummary]:
    """One row per product that has a forecast: its next build month on or after the data date's month, with the readiness counts and verdict."""
    this = AS_OF.isoformat()[:7]
    out = []
    for prod in session.scalars(select(Product).order_by(Product.part_number)):
        months = sorted(m for m in session.scalars(select(DemandForecast.month).where(DemandForecast.product_part == prod.part_number)) if m >= this)
        b = build_readiness(session, prod.part_number, months[0]) if months else None
        if b:
            out.append(BuildSummary(product=b.product, month=b.month, units=b.units, counts={**{k: 0 for k in SUMMARY_STATES}, **b.counts}, verdict=b.verdict))
    return out
