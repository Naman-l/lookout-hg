"""The ways through a supplier's disruption, as data: what each needs, the first date the data supports, what it costs where that can be computed,
and the one unknown that decides it. Four options, each built from the records, none from prose:

allocation     the supplier's other capacity: its own promise to name revised dates is the first date the data gives
air_freight    ship what survived before the duty window closes: the duty that is owed only if the goods ship late is the effect the data can price
resequence     move builds in the plan: every product with the parts of it that are short and its forecast, laid out in part-number order (no ranking)
second_source  another supplier's quote for a short part: its landed cost against what is paid today, its lead time with the event it waits on
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.attention import service
from app.domain.attention.schema import DateValue, FireOption, Need
from app.domain.common import AS_OF
from app.domain.demand import service as demand
from app.domain.inbox.model import MessageEvent
from app.domain.orders.model import ReferencePrice
from app.domain.parts.model import Part
from app.domain.ownership import buyer_of_part
from app.domain.quotes import service as quotes
from app.domain.tariffs import service as tariffs
from app.domain.values import prov, ref, unknown, usd


def _allocation(session: Session, ctx: dict, buyer: str) -> FireOption:
    who, ident = ctx["who"], ctx["ident"]
    promised = session.scalar(select(MessageEvent).where(MessageEvent.kind == "deadline", MessageEvent.ref_type == "supplier", MessageEvent.ref_id == ident,
                                                         MessageEvent.detail.like("%revised delivery dates%")))
    supplier = ref("supplier", ident, who)
    return FireOption(
        kind="allocation", label=f"Ask {who} to keep the original dates or allocate" if ctx.get("notice") == "slip" else f"Allocation from {who}'s other capacity", refs=[supplier],
        needs=[Need(what="the supplier's written commitment of quantity and dates from capacity that is not under the notice", owner="supplier", ref=supplier)],
        earliest=DateValue(date=promised.date_to, provenance=prov("extracted", f"message:{promised.message_id}", row=str(promised.id), rule="the date the supplier promised to name revised delivery dates", inputs=[ref("message", promised.message_id)])) if promised else None,
        earliest_basis="the supplier's own promise to name revised dates" if promised else "the supplier has not given a date",
        cost_unknowns=[unknown("the price and freight of the supplier's other capacity", "the data holds no price for goods from another plant of the same supplier", buyer,
                               f"What would {who} charge for goods from its other capacity, and how do they ship?", [supplier])],
        decided_by=unknown("how much the supplier can allocate from other capacity, and by when", "the notice does not say; revised dates are promised, not given", "supplier",
                           f"How much of the stuck quantity can {who} ship from capacity that is not under the notice, and by what date?", [supplier]))


def _air_freight(session: Session, ctx: dict, buyer: str) -> FireOption:
    who, ids = ctx["who"], set(ctx["ids"])
    conditional, inputs, rule_date = 0.0, [], None
    for part in ctx["parts"]:
        e = tariffs.exposure_for_part(session, part)
        for l in e.open_lines:
            if l.po_line.id in ids and (l.bucket == "conditional" or l.under_force_majeure) and l.open_value.usd is not None and e.rate:      # owed because the plant cannot restart in time, or conditional on a ship date
                conditional += float(l.open_value.usd) * e.rate
                inputs.append(l.po_line)
                rule_date = e.tariff.rule.exported_before or rule_date
    supplier = ref("supplier", ctx["ident"], who)
    if ctx.get("notice") == "slip":  # nothing burned: the delayed lines themselves are flown, if the supplier can ship them earlier
        return FireOption(
            kind="air_freight", label="Air-ship the delayed lines", refs=[supplier],
            needs=[Need(what="the supplier ships the delayed lines earlier than its new dates", owner="supplier", ref=supplier), Need(what="an air-freight quote and a carrier", owner=buyer)],
            earliest=None, earliest_basis="no ship date earlier than the supplier's new dates is in the data",
            duty_effect=usd(conditional, prov("computed", "po_lines", rule=f"duty owed on these lines unless they ship before {rule_date}" if rule_date else "duty owed unless shipped in time",
                                              inputs=inputs, by="attention.options")) if conditional else None,
            cost_unknowns=[unknown("air freight", "freight is not in the data for any order", buyer, f"What would it cost to air-ship {who}'s delayed lines?", [supplier])],
            decided_by=unknown("whether the supplier can ship the delayed lines earlier", "the notice gives only the new dates", "supplier",
                               f"Can {who} ship the delayed lines earlier than its new dates, by air?", [supplier]))
    return FireOption(
        kind="air_freight", label="Air-freight what survived", refs=[supplier],
        needs=[Need(what="finished goods or stock that survived the incident", owner="supplier", ref=supplier), Need(what="an air-freight quote and a carrier", owner=buyer)],
        earliest=None, earliest_basis="no stock or shipping date for surviving goods is in the data",
        duty_effect=usd(conditional, prov("computed", "po_lines", rule=f"duty owed on these lines unless goods that survived ship before {rule_date}: the supplier's notice puts a restart from production after it" if rule_date else "duty owed unless shipped in time",
                                          inputs=inputs, by="attention.options")) if conditional else None,
        cost_unknowns=[unknown("air freight", "freight is not in the data for any order", buyer, f"What would it cost to air-freight what {who} still has, and how much is there?", [supplier])],
        decided_by=unknown("what the supplier still has on hand, undamaged", "no stock or finished-goods file exists for the supplier's plant", "supplier",
                           f"What finished goods and stock does {who} have that the fire did not damage, and when can they ship?", [supplier]))


def _resequence(session: Session, item_first: str | None, shorts: dict) -> FireOption:
    first = item_first
    short_parts = [p for p, t in shorts.items() if t.first_short_month == first]
    products = sorted(service.fire_products(session, short_parts, first), key=lambda e: e.product.id)      # laid out, not ranked
    return FireOption(
        kind="resequence", label="Re-sequence the builds", products=products,
        needs=[Need(what="planning agrees to move builds in the plan", owner="planning")],
        earliest=DateValue(date=f"{first}-01", provenance=prov("computed", "demand_forecast", rule="the first month a short part stops a build")) if first else None,
        earliest_basis="the first month with a short part",
        decided_by=unknown("which builds can move without breaking a customer date", "customer dates and finished-goods stock are not in the data", "planning",
                           "Which products can be built first without missing a customer date?", [p.product for p in products]))


def _second_source(session: Session, ctx: dict, buyer: str) -> FireOption:
    best = None
    for part, t in ctx["shorts"].items():
        bucket = next((b for b in t.buckets if b.month == t.first_short_month), None)
        short = float(bucket.short.value) if bucket and bucket.short else 0.0
        for o in quotes.offers_for_part(session, part):
            if o.supplier is not None and o.supplier.id == ctx["ident"]:
                continue
            if o.qty_break and short and o.qty_break > short and best is not None:
                continue
            landed = quotes.landed_cost(session, o.offer_id)
            if best is None or float(landed.total_known_usd.usd) < float(best[1].total_known_usd.usd):
                best = (part, landed, short)
    if best is None:
        return FireOption(kind="second_source", label="A second source", needs=[Need(what="a qualified alternative supplier with a quote", owner=buyer)],
                          earliest_basis="no quote from another supplier is in the inbox",
                          decided_by=unknown("whether any other supplier can make the part", "no alternative quote is on file", buyer, "Which other suppliers could make the short parts?", []))
    part, landed, short = best
    offer = landed.offer
    rp = session.get(ReferencePrice, part)
    delta = None
    if rp is not None and short:
        delta = usd((float(landed.total_known_usd.usd) - float(rp.usd_each)) * short,
                    prov("computed", "offers", rule="(the quote's landed unit cost now, without any duty that is not yet known, minus the last price paid) times the first month's shortage",
                         inputs=[offer.message, ref("part", part), ref("po_line", rp.po_line_id)], by="attention.options"))
    needs = [Need(what=offer.lead_time.condition, owner="supplier", ref=offer.supplier)] if offer.lead_time and offer.lead_time.condition else []
    needs += [Need(what="qualify the new source and settle the origin of its goods", owner=buyer, ref=offer.message)]
    if offer.moq:
        needs.append(Need(what=f"an order of at least {offer.moq} pieces", owner=buyer, ref=offer.message))
    days = None
    if offer.lead_time and isinstance(offer.lead_time.value, str):
        digits = "".join(c for c in offer.lead_time.value.split()[0] if c.isdigit())
        days = int(digits) if digits else None
    floor = DateValue(date=(AS_OF + timedelta(days=days)).isoformat(), provenance=prov("computed", "offers", rule="the data date plus the quote's lead time; the real date waits on the condition",
                                                                                      inputs=[offer.message])) if days is not None and offer.lead_time and offer.lead_time.condition else None
    return FireOption(
        kind="second_source", label=f"{offer.supplier_name} for {naming.part_name(session.get(Part, part).description)}",
        refs=[offer.message, ref("part", part)] + ([offer.supplier] if offer.supplier else []), needs=needs, moq=offer.moq,
        earliest=None, earliest_basis=f"{offer.lead_time.value} {offer.lead_time.condition}" if offer.lead_time and offer.lead_time.condition else None,
        not_before=floor, cost_delta=delta, cost_basis=f"{int(short)} pieces short in the first short month, against the last price paid, before any duty (the bid tab compares landed with the duty)" if short else None,
        cost_unknowns=list(landed.unknowns),
        decided_by=unknown("whether the new source is qualified and its goods are not China-origin", "the quote waits on approval and its origin is a customs-broker question", buyer,
                           f"Can {offer.supplier_name} be qualified in time, and what origin will the goods be ruled?", [offer.message]))


def order_before(session: Session, ident: str | None, who: str, buyer: str) -> FireOption | None:
    """Order before the lead-time cutoff: when the supplier's own notice moves its lead time for orders placed after a date, and some of the need until
    an order placed after that date could land is on no open order, the uncovered need is ordered by the cutoff at the old lead time. None otherwise."""
    from app.domain.attention.notices import lead_time_change  # noqa: PLC0415
    from app.domain.orders.model import PoLine  # noqa: PLC0415

    lt = lead_time_change(session, ident)
    if lt is None:
        return None
    lands = lt.order_by + timedelta(days=1) + timedelta(weeks=lt.new_weeks)     # the first order after the cutoff, at the new lead time
    through = lands.isoformat()[:7]
    uncovered = []
    for part in sorted({p for (p,) in session.execute(select(PoLine.part_number).where(PoLine.identity_id == ident)) if p}):
        months = [b for b in demand.shortage(session, part).buckets if b.month <= through]
        need = sum(float(b.requirements.value) for b in months)
        on_order = sum(float(b.scheduled_receipts.value) for b in months)
        if need > on_order:
            uncovered.append((part, round(need - on_order)))
    if not uncovered:
        return None
    message, supplier = ref("message", lt.message_id), ref("supplier", ident, who)
    month = date_label(through)
    return FireOption(
        kind="order_before", label="Order before the lead-time cutoff", refs=[message, supplier] + [ref("part", p) for p, _ in uncovered],
        needs=[Need(what=f"orders for the need through {month} that no open order covers: " + ", ".join(f"{q:,} {p}" for p, q in uncovered), owner=buyer, ref=message)],
        earliest=DateValue(date=lt.order_by.isoformat(), provenance=prov("extracted", f"message:{lt.message_id}", rule=f"the last day an order keeps the {lt.old_weeks}-week lead time, per the supplier's notice",
                                                                          inputs=[message])),
        earliest_basis=f"orders placed {lt.when} {lt.cutoff_text} wait {lt.new_weeks} weeks instead of {lt.old_weeks}; one placed after it lands {service.md(lands.isoformat())} at the earliest",
        cost_basis=f"{sum(q for _, q in uncovered):,} pieces needed through {month} are on no open order (forecast minus open orders, by month)",
        decided_by=unknown("whether the supplier confirms orders placed by the cutoff at the old lead time", "the notice changes the lead time; it does not say what it confirms for new orders", "supplier",
                           f"Will {who} confirm orders we place by {service.md(lt.order_by.isoformat())} at {lt.old_weeks} weeks?", [supplier]))


def date_label(month: str) -> str:
    """'2027-01' -> 'Jan 2027'."""
    from datetime import date as _d  # noqa: PLC0415

    return _d(int(month[:4]), int(month[5:7]), 1).strftime("%b %Y")


def _as_fire(session: Session, ctx: dict) -> dict | None:
    """The fire's working context built from another disruption kind's: its supplier, the PO lines and parts it touches, and the parts that go short (and the first month)."""
    if ctx.get("slip"):
        ids, parts = [s.po_line.id for s in ctx["slipped"]], sorted(ctx["impacts"])
    elif ctx.get("incident"):
        ids, parts = [s.po_line.id for s in ctx["scope"]], list(ctx["parts"])
    elif ctx.get("risk"):
        ids, parts = [l.id for l in ctx.get("live", []) if hasattr(l, "id")], sorted(ctx["sole"])
    else:
        return None
    if not parts:
        return None
    sh = {p: demand.shortage(session, p) for p in parts}
    shorts = {p: t for p, t in sh.items() if t.first_short_month}
    first = min((t.first_short_month for t in shorts.values()), default=None)
    notice = next(k for k in ("slip", "incident", "risk") if ctx.get(k))
    return dict(who=ctx["who"], ident=ctx["ident"], ids=ids, parts=parts, sh=sh, shorts=shorts, first=first, notice=notice)


def case_kind(session: Session, key: str) -> str | None:
    """What kind of case an item is, from its detector's own context: fire, slip, incident, risk, consignment (disruptions); closure, price_lock (a supplier's dated deadline); None otherwise."""
    hit = service.item_context(session, key)
    if hit is None:
        return None
    item, ctx = hit
    if item.group == "disruption":
        return next((k for k in ("slip", "incident", "risk", "consignment") if ctx.get(k)), "fire" if "ids" in ctx else None)
    if item.group == "deadline" and ctx.get("event") is not None:
        return "closure" if ctx.get("closure") else "price_lock" if "price" in (ctx["event"].detail or "") else None
    return None


def fire_options(session: Session, key: str) -> list[FireOption] | None:
    """The four ways through the disruption behind `key` (a `disruption:<supplier>` item with a force-majeure notice), or None for any other item."""
    hit = service.item_context(session, key)
    if hit is None or hit[0].group != "disruption":
        return None
    item, ctx = hit
    if "ids" not in ctx or ctx.get("slip"):
        ctx = _as_fire(session, ctx)      # a notice, a supplier at risk or an incident: the same four ways, from the parts it puts at risk
        if ctx is None:
            return None
    part = ctx["parts"][0] if ctx["parts"] else None
    buyer = buyer_of_part(session, part) if part else item.owner.split(" · ")[0]
    out = [_allocation(session, ctx, buyer), _air_freight(session, ctx, buyer), _resequence(session, ctx["first"], ctx["shorts"]), _second_source(session, ctx, buyer)]
    ob = order_before(session, ctx["ident"], ctx["who"], buyer)
    return out + [ob] if ob else out
