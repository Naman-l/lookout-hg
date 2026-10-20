"""Demand = forecast x BOM explosion, and the time-phased view against open supply."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.bom.service import requirements_per_robot, where_used
from app.domain.demand.model import DemandForecast, Product
from app.domain.common import AS_OF
from app.domain.demand.schema import ForecastMonth, ForecastRow, MonthBucket, MonthQty, SlipImpact, TimePhased
from app.domain.inbox.model import Message, MessageEvent
from app.domain.orders import service as orders
from app.domain.parts.model import Part
from app.domain.ownership import buyer_of_part
from app.domain.values import prov, qty, ref, unknown


def _buyer(session: Session, part: str) -> str:
    """The first name of the buyer who owns the part: the one who can say what is on the shelf."""
    return buyer_of_part(session, part)


@memo
def _forecast_by_month(session: Session) -> tuple[dict[str, dict[str, int]], dict[str, str], dict[str, str]]:
    """{month: {product part: robots}}, {product part: name} and {part: unit}: read once per database, since every part's requirement needs all three."""
    by_month: dict[str, dict[str, int]] = {}
    for f in session.scalars(select(DemandForecast).order_by(DemandForecast.month)):
        by_month.setdefault(f.month, {})[f.product_part] = f.units
    return by_month, {p.part_number: p.name for p in session.scalars(select(Product))}, {p.part_number: p.uom for p in session.scalars(select(Part))}


@memo
def requirements(session: Session, part: str, months: int = 12) -> list[MonthQty]:
    """Units of `part` needed each month: sum over products of (robots forecast x quantity per robot)."""
    per_robot = requirements_per_robot(session)
    by_month, names, uoms = _forecast_by_month(session)
    uom = uoms.get(part, "EA")
    out: list[MonthQty] = []
    for month in sorted(by_month)[:months]:
        total, used = Decimal(0), {}
        for product_part, robots in by_month[month].items():
            q = per_robot.get(product_part, {}).get(part)
            if q:
                total += q * robots
                used[names[product_part]] = robots
        if total:
            out.append(MonthQty(month=month, by_product=used, qty=qty(total, uom, prov(
                "computed", "demand_forecast", row=month, rule="robots planned times the parts each one needs",
                inputs=[ref("part", part)], by="demand.requirements"))))
    return out


class MonthGap(NamedTuple):
    cum_need: float  # requirement from the first month through this one
    gap_now: float  # of it, not covered by dated supply landing by the end of the month, at the dates now in force
    gap_before: float  # the same at the dates the POs promised, before any notice


def uncovered_between(session: Session, part: str, first_month: str, last_month: str) -> float:
    """Need in the months first..last that the open orders do NOT cover, with dated supply used up by the earliest need first (an order that lands after the need it was meant for
    covers the backlog before it covers a later month). Same dated supply as `month_gaps` (revised dates, overdue counted as available now, stale lines nothing), kept for every month
    including those past the last order: after FIFO the units left over are the latest ones, so the answer is the uncovered total at `last_month`, at most the need in the window."""
    reqs = requirements(session, part)
    months = [r.month for r in reqs]
    if not reqs or last_month not in months:
        return 0.0
    due = AS_OF.isoformat()
    supply = [s for s in orders.open_supply(session, part) if not s.stale]
    ids = {s.supplier.id for s in supply if s.disrupted_by}
    ev = _fm_event(session, ids) if ids else None
    back = _month_after(ev.date_to) if ev and ev.date_to else None
    landed = 0.0
    for s in supply:
        for d, q in ([(back, float(s.qty.value))] if s.disrupted_by else [(sp.date, sp.qty) for sp in s.revised_splits] if s.revised_splits else [(orders.current_date(s), float(s.qty.value))]):
            if d and (d[:7] if d >= due else months[0]) <= last_month:
                landed += q
    cum_need = sum(float(r.qty.value) for r in reqs if r.month <= last_month)
    window_need = sum(float(r.qty.value) for r in reqs if first_month <= r.month <= last_month)
    return min(max(0.0, cum_need - landed), window_need)


def _fm_event(session: Session, ids):
    return session.scalars(select(MessageEvent).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "supplier", MessageEvent.ref_id.in_(ids))
                           .order_by(MessageEvent.date_to.desc())).first()


def _month_after(date_text: str) -> str:
    y, m = int(date_text[:4]), int(date_text[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}-01"


@memo
def month_gaps(session: Session, part: str) -> dict[str, MonthGap]:
    """The one supply-against-need calculation, for the months up to the last that an open order lands in: cumulative requirement against cumulative dated supply, month by month, at the dates now in force and at the
    dates the POs promised. Dated supply counts from the month it lands (revised splits and dates where a notice gave them); a line past due at the data date
    lands in the first month; a line under force majeure lands the month after the supplier's own restart estimate (never, when it gave none); stale lines count
    for nothing. Shortage, the slip's impact and build readiness all read this, so they cannot disagree."""
    reqs = requirements(session, part)
    if not reqs:
        return {}
    supply = [s for s in orders.open_supply(session, part) if not s.stale]
    months = [r.month for r in reqs]
    due = AS_OF.isoformat()
    ids = {s.supplier.id for s in supply if s.disrupted_by}
    ev = _fm_event(session, ids) if ids else None
    back = _month_after(ev.date_to) if ev and ev.date_to else None

    def cum(pieces_of):
        out = {m: 0.0 for m in months}
        for s in supply:
            for d, q in pieces_of(s):
                if not d:
                    continue
                key = d[:7] if d >= due else months[0]
                for m in months:
                    if m >= key:
                        out[m] += q
        return out

    now = cum(lambda s: [(back, float(s.qty.value))] if s.disrupted_by else [(sp.date, sp.qty) for sp in s.revised_splits] if s.revised_splits else [(orders.current_date(s), float(s.qty.value))])
    before = cum(lambda s: [(s.promise, float(s.qty.value))])
    landing = [d[:7] if d >= due else months[0] for s in supply for d in ([back] if s.disrupted_by else [s.promise] + [sp.date for sp in s.revised_splits] + [orders.current_date(s)]) if d]
    last = max(landing, default=None)                 # past the last month any open order lands, the need is not yet ordered: that is an ordering question, not a gap in dated supply
    out, run = {}, 0.0
    for r in reqs:
        run += float(r.qty.value)
        if last and r.month <= last:
            out[r.month] = MonthGap(run, max(0.0, run - now[r.month]), max(0.0, run - before[r.month]))
    return out


@memo
def notice_affects(session: Session, part: str) -> bool:
    """A supplier's notice is behind a line of this part: it is under force majeure, or its date was revised later. Only then does the data say a shortage."""
    return any(s.disrupted_by or (s.revised_promise and s.promise and s.revised_promise > s.promise) for s in orders.open_supply(session, part) if not s.stale)


@memo
def slip_impact(session: Session, part: str) -> SlipImpact | None:
    """What a supplier's revised dates do to the builds: compare cumulative receipts at the ERP promise dates with the revised dates against the
    cumulative requirement. A month counts only if the promised dates covered it and the revised ones do not (a gap that was already there is
    not the slip's doing). Lines past due at the data date are assumed to land in the first month at their promise; stale lines are left out."""
    reqs = requirements(session, part)
    supply = [s for s in orders.open_supply(session, part) if not s.stale]
    slipped = [s for s in supply if s.revised_promise and s.promise and s.revised_promise > s.promise]
    if not reqs or not slipped:
        return None
    months = [r.month for r in reqs]
    gaps = month_gaps(session, part)
    diff = {m: gaps[m].gap_now - gaps[m].gap_before if m in gaps else 0.0 for m in months}
    hit = [m for m in months if diff[m] > 0.5]
    if not hit:
        return None
    uom = reqs[0].qty.uom
    own = {m: min(diff[m], float(r.qty.value)) for m, r in zip(months, reqs)}      # a month is short by at most what it needs; the rest is backlog
    src = lambda rule: prov("computed", "po_lines", rule=rule, inputs=[s.po_line for s in slipped], by="demand.slip_impact")  # noqa: E731
    return SlipImpact(part=ref("part", part), slipped_lines=[s.po_line for s in slipped], months=hit, first_month=hit[0], by_month={m: round(own[m], 3) for m in hit},
                      backlog_by_month={m: round(diff[m], 3) for m in hit},
                      first_month_qty=qty(own[hit[0]], uom, src("the month's own requirement not covered at the revised dates, beyond what the promised dates left uncovered; at most the month's requirement")),
                      first_month_backlog=qty(diff[hit[0]], uom, src("cumulative requirement not covered at the revised dates minus the same at the promised dates")))


def _per_unit(session: Session, part: str) -> str:
    names = {p.part_number: p.name for p in session.scalars(select(Product))}
    return ", ".join(f"{w.qty_per_robot.normalize():f} per {names.get(w.product.id, w.product.id)}".replace(".0 ", " ")
                     for w in where_used(session, part)) or "not in any BOM"


@memo
def shortage(session: Session, part: str) -> TimePhased:
    """Requirements against open supply by month (the MRP-style view).

    Supply under force majeure counts as arriving nowhere until the supplier's own recovery estimate; a shortage is asserted
    only for those months. On-hand stock is not in the data, so no balance is ever shown: on_hand is an Unknown with an owner."""
    reqs = requirements(session, part)
    supply = [s for s in orders.open_supply(session, part) if not s.stale]
    uom = reqs[0].qty.uom if reqs else "EA"
    recovery, recovery_text, recovery_line, recovery_source = None, None, None, None
    ids = {s.supplier.id for s in supply if s.disrupted_by}
    if ids:
        ev = session.scalars(select(MessageEvent).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "supplier", MessageEvent.ref_id.in_(ids)).order_by(MessageEvent.date_to.desc())).first()
        if ev:
            recovery = ev.date_to
            m = re.search(r"resumes in (\d+ to \d+ weeks)", ev.detail)
            recovery_text = m.group(1) if m else None
            body = session.scalar(select(Message.body).where(Message.id == ev.message_id)) or ""
            n = int(ev.line_ref[1:]) if ev.line_ref and ev.line_ref[1:].isdigit() else 0
            recovery_line = body.splitlines()[n - 1].strip() if n else None
            recovery_source = ref("message", ev.message_id) if n else None
    first_month = reqs[0].month if reqs else None
    due = AS_OF.isoformat()
    past_due = Decimal(0)
    receipts: dict[str, Decimal] = {}
    stuck: dict[str, Decimal] = {}
    for s in supply:
        when = orders.current_date(s)
        key = when[:7] if when and when >= due else (first_month or "no date")
        if s.promise and s.promise < due and not s.revised_promise:
            past_due += s.qty.value
            if not s.disrupted_by:  # late but not stopped: assumed to land in the first month; a stopped line is only counted as past due
                receipts[key] = receipts.get(key, Decimal(0)) + s.qty.value  # late but not stopped: assumed to land in the first month
            continue
        receipts[key] = receipts.get(key, Decimal(0)) + s.qty.value
        if s.disrupted_by:
            stuck[key] = stuck.get(key, Decimal(0)) + s.qty.value
    src = lambda what: prov("computed", "po_lines", rule=f"{what}", by="demand.shortage")  # noqa: E731
    buckets, first_short = [], None
    gaps = month_gaps(session, part)
    affected = notice_affects(session, part)         # only a part a notice moved is asserted short: with no stock data every other part would look short
    for r in reqs:
        rec, stk = receipts.get(r.month, Decimal(0)), stuck.get(r.month, Decimal(0))
        g = gaps.get(r.month)
        now = g.gap_now if g and affected else 0.0
        short_q = backlog = before = None
        if now > 0.5:
            short_q = qty(min(float(r.qty.value), now), uom, src("the month's own requirement not covered by dated supply at the dates now in force (at most the month's requirement)"))
            backlog = qty(now, uom, src("cumulative requirement not covered by dated supply at the dates now in force: it accumulates exactly the months raised"))
            first_short = first_short or r.month
        if g and affected and g.gap_before > 0.5:
            before = qty(min(float(r.qty.value), g.gap_before), uom, src("of the shortage, what the promised dates did not cover either: no notice caused it"))
        buckets.append(MonthBucket(month=r.month, requirements=r.qty, short=short_q, backlog=backlog, uncovered_before=before,
                                   scheduled_receipts=qty(rec, uom, src("open supply by promise month")),
                                   under_disruption=qty(stk, uom, src("open supply on lines the supplier cannot deliver"))))
    impact = slip_impact(session, part)
    last = gaps[max(gaps)] if gaps and affected else None
    unmet = qty(last.gap_now, uom, src("cumulative requirement still not covered once every open order has landed")) if last and last.gap_now > 0.5 else None
    return TimePhased(
        unmet_after_all_open_orders=unmet,
        part=ref("part", part), per_unit=_per_unit(session, part), past_due_receipts=qty(past_due, uom, src(f"open lines promised before {AS_OF.isoformat()}")),
        buckets=buckets, first_short_month=first_short, disrupted=bool(ids) or impact is not None, recovery_by=recovery, recovery_text=recovery_text, recovery_line=recovery_line, recovery_source=recovery_source,
        on_hand=unknown("on-hand stock", "the data has no inventory, safety stock or MRP output, so a projected balance cannot be stated",
                        _buyer(session, part), "What is on hand and on order outside the ERP for this part?", [ref("part", part)]))


@memo
def forecast(session: Session) -> list[ForecastRow]:
    """Robots to build per month, by product, as the S&OP forecast gives them."""
    names = {p.part_number: p.name for p in session.scalars(select(Product).order_by(Product.part_number))}
    rows = []
    for part, name in names.items():
        months = [ForecastMonth(month=f.month, units=f.units) for f in
                  session.scalars(select(DemandForecast).where(DemandForecast.product_part == part).order_by(DemandForecast.month))]
        rows.append(ForecastRow(product=name, months=months))
    return rows


@memo
def products(session: Session):
    from app.domain.demand.schema import ProductOut

    return [ProductOut(part_number=p.part_number, name=p.name, family=p.family) for p in session.scalars(select(Product).order_by(Product.part_number))]
