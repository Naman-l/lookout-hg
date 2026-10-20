"""Detectors: the four truths as code, and the trust shield. They read the records and raise items; they never write.

Truths, in the order the Action list ranks them: the fire (disruption), the deadlines, the tariff, the unanswerable (unknown).
Trust items sit right after the fire: a forged payment change is the most expensive thing in the inbox.

Item keys are frozen (QUALITY's cases bind to them):
  disruption:<supplier id>                 e.g. disruption:XX-0001
  trust:<message file stem>                e.g. trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident
  deadline:<supplier id>:<date>            e.g. deadline:XX-0001:2026-10-15
  tariff:<part number> | tariff:other      e.g. tariff:PN-12345
  unknown:<part number> | unknown:<po line id>   e.g. unknown:PN-12345, unknown:ORD-10711/1
"""

from __future__ import annotations

import math
import re

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common.company import company_name
from app.domain import naming
from app.domain.annotate import service as annotate
from app.domain.fmt import count, days as days_text, humanize, md, month as month_name, month_year, sentence
from app.domain.attention.schema import DatedRow, ProductExposure, RobotsShort, ActionItem, ActionItemDetail, DateValue, Number
from app.domain.bom.service import where_used
from app.domain.common import AS_OF, Money, Quantity, Unknown
from app.domain.demand import service as demand
from app.domain.demand.model import DemandForecast, Product
from app.domain.inbox import service as inbox
from app.domain.inbox.model import Message, MessageEvent
from app.domain.orders import service as orders
from app.domain.orders.model import PoLine, ReferencePrice
from app.domain.parts.model import Part
from app.domain.quotes.model import Offer
from app.domain.parts.service import buyer_name
from app.domain.suppliers import risk as supplier_risk
from app.domain.suppliers import service as suppliers
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord
from app.domain.tariffs import service as tariffs
from app.domain.tariffs.model import TariffRule
from app.domain.ownership import buyer_ids, buyer_of_part
from app.domain.values import prov, qty, ref, unknown, usd

GROUP_RANK = {"disruption": 0, "trust": 1, "deadline": 2, "tariff": 3, "unknown": 4}
TARIFF_ITEM_MIN = 25_000.0  # smaller parts roll into tariff:other
DEADLINE_WINDOW_DAYS = 45


def _days(d: str | None) -> int | None:
    return (date.fromisoformat(d) - AS_OF).days if d else None


def _money(m: Money | Quantity | Unknown | None) -> float:
    return float(m.usd) if isinstance(m, Money) and m.usd is not None else 0.0


def _fmt(x: float) -> str:
    """Money in prose, by the rule the money columns use: millions to two decimals ($1.54M), thousands from $10K whole ($104K), else whole dollars."""
    return f"${x / 1e6:.2f}M" if x >= 1e6 else f"${x / 1e3:.0f}K" if x >= 1e4 else f"${x:,.0f}"


def _short(session: Session, identity_id: str) -> str:
    """'Acme', 'Acme Extrusion': the name a buyer says (see naming.supplier_name)."""
    return naming.supplier_name(session, identity_id)


def _head(desc: str) -> str:
    return desc.split(",")[0].strip().lower()


def _and(words: list[str]) -> str:
    """['Alpha', 'Beta', 'Gamma'] -> 'Alpha, Beta and Gamma'."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _noun(session: Session, parts: list[str]) -> str:
    """What the short parts are, in a buyer's words: 'drive motors', 'power electronics'."""
    rows = [session.get(Part, p) for p in parts]
    cats = {r.category for r in rows}
    if len(cats) == 1 and next(iter(cats)) != "Motors":
        return next(iter(cats)).lower()
    r = rows[0]
    head = _head(r.description) + "s"
    return f"drive {head}" if "drive" in r.description.lower() else head


def _owner_of(session: Session, ids) -> str:
    counts: dict[str, int] = {}
    for l in session.scalars(select(PoLine).where(PoLine.id.in_(list(ids)))):
        counts[l.buyer_id] = counts.get(l.buyer_id, 0) + 1
    return buyer_name(session, max(counts, key=counts.get)) if counts else "IT (ERP admin)"


def _robots_hit(session: Session, parts, month: str, own: dict[str, float] | None = None) -> dict[str, int]:
    """{product name: robots short} for the builds of `month` that the short parts stop: the month's planned robots, scaled by the share of the month's need
    that is short (units short / units needed), the most any one short part stops. Never more than the robots planned that month.
    `own` gives a part's own shortage that month where the caller knows it (a slip: `demand.slip_impact(part).by_month`), so a gap that was there before is not counted."""
    hit: dict[str, int] = {}
    for part in parts:
        b = next((b for b in demand.shortage(session, part).buckets if b.month == month), None)
        need = float(b.requirements.value) if b else 0.0
        if own is not None and part in own:
            share = min(1.0, own[part] / need) if need else 0.0
        else:
            share = min(1.0, float(b.short.value) / need) if b and b.short is not None and need else 1.0 if b and b.short is None else 0.0
        mq = next((m for m in demand.requirements(session, part) if m.month == month), None)
        for name, n in (mq.by_product if mq else {}).items():
            hit[name] = max(hit.get(name, 0), min(n, math.ceil(n * share - 1e-9)))
    return {k: v for k, v in hit.items() if v}


def _robots_note(session: Session, parts, month: str | None, own: dict[str, float] | None = None) -> str | None:
    """'182 Alpha + 40 Beta robots in October, short of drive motors': the builds the short parts stop, as buyers count them, and which parts they are. Each product once,
    however many of the parts it uses; two items that stop the same robots for different parts say so."""
    if not month:
        return None
    parts = [parts] if isinstance(parts, str) else list(parts)
    fam = {p.name: p.family for p in session.scalars(select(Product))}
    robots = {fam.get(name, name): n for name, n in _robots_hit(session, parts, month, own).items()}
    if not robots:
        return None
    return " + ".join(f"{n} {name}" for name, n in robots.items()) + f" robots in {month_name(month)}, short of {_noun(session, parts)}"


def _robots_short_rows(session: Session, short_parts, month: str | None, own: dict[str, float] | None = None) -> list[RobotsShort]:
    """The robots the short parts stop that month, per product: shortage-limited (`_robots_hit`), not the month's whole plan."""
    if not month:
        return []
    hit = _robots_hit(session, short_parts, month, own)
    return [RobotsShort(product=e.product, month=month, robots=hit[e.product.label], short_parts=e.short_parts)
            for e in fire_products(session, short_parts, month) if e.short_parts and e.product.label in hit]


def _fire_months(shorts) -> dict[str, list[str]]:
    """{month: the parts short that month} under a force-majeure notice: every month whose shortage bucket asserts a shortage, in month order."""
    out: dict[str, list[str]] = {}
    for p, t in shorts.items():
        for b in t.buckets:
            if b.short is not None and float(b.short.value) > 0.5:
                out.setdefault(b.month, []).append(p)
    return dict(sorted(out.items()))


def _slip_months(impacts) -> dict[str, dict[str, float]]:
    """{month: {part: its own shortage that month}} for a slip: the months the new dates leave short that the promised dates covered (`slip_impact.months`),
    never a gap that was already there."""
    out: dict[str, dict[str, float]] = {}
    for p, imp in impacts.items():
        for m in imp.months:
            out.setdefault(m, {})[p] = imp.by_month[m]
    return dict(sorted(out.items()))


def fire_products(session: Session, short_parts, month: str | None) -> list[ProductExposure]:
    """Every product with the parts of it that are short in `month` and its forecast that month, fewest short parts first (then the larger build first)."""
    if not month:
        return []
    planned = {f.product_part: f.units for f in session.scalars(select(DemandForecast).where(DemandForecast.month == month))}
    uses: dict[str, list[str]] = {}
    for part in short_parts:
        for w in where_used(session, part):
            uses.setdefault(w.product.id, []).append(part)
    fam = {p.part_number: p.name for p in session.scalars(select(Product))}
    out = [ProductExposure(product=ref("product", pn, name), robots=planned.get(pn, 0), short_parts=[ref("part", x) for x in sorted(set(uses.get(pn, [])))])
           for pn, name in fam.items()]
    return sorted(out, key=lambda e: (len(e.short_parts), -e.robots, e.product.id))


def _effective_date(session: Session, part: str) -> str | None:
    """The date the tariff rule that matches this part takes effect, or None when the part is on no rule."""
    r = tariffs.tariff_rule_for(session, part).rule
    return r.effective_date if r else None


def _buyer_first(session: Session, part: str) -> str:
    """The first name of the buyer who owns a part (the buyer on most of its PO lines), for an Unknown's owner."""
    return buyer_of_part(session, part)


def _stock_questions(session: Session, parts, why: str) -> list[Unknown]:
    """One open question per buyer about what is on hand, each listing that buyer's parts: the person who can answer is the one who buys them."""
    mine: dict[str, list[str]] = {}
    for p in sorted(set(parts)):
        mine.setdefault(_buyer_first(session, p), []).append(p)
    return [unknown("on-hand stock", why, who, f"What stock of {', '.join(ps)} is on hand or on order outside the ERP?", [ref("part", p) for p in ps])
            for who, ps in sorted(mine.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def _by_owner(pairs, sep: str = " ") -> str:
    """'Ana PN-12345, PN-12345; Cy PN-12345': who has which of the things, in the order of the first one each owns."""
    groups: dict[str, list[str]] = {}
    for owner, what in pairs:
        groups.setdefault(owner.split()[0], []).append(what)
    return "; ".join(f"{o}{sep}{', '.join(w)}" for o, w in groups.items())


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _category(group: str, key: str, title: str) -> str | None:
    """Which of the procurement stages (discovery, RFQ, quote and risk, purchasing) an item belongs to, where it belongs to one. A fire or late orders are
    purchasing; a quote, a price rise, a duty, an unknown origin is quote and risk; a message that may be fraud belongs to none."""
    if group == "trust":
        return None
    if group == "disruption":
        return "Purchasing"
    if group == "deadline":
        return "Purchasing" if key == "deadline:chase" or "delivery dates" in title else "Quote & risk"
    return "Quote & risk"


def _item(session, key, group, severity, title, *, owner, at_stake=None, gross=None, act_by=None, next_action="", refs=None, note=None, category=None, fire=None) -> ActionItem:
    made = ActionItem(key=key, group=group, severity=severity, title=_cap(naming.namify(session, humanize(title))), at_stake=at_stake, at_stake_gross=gross, act_by=act_by,
                      at_stake_note=note, days_left=_days(act_by), owner=owner, next_action=sentence(naming.namify(session, humanize(next_action))) if next_action else "",
                      refs=naming.labelled(session, refs or []), category=category or _category(group, key, title), **(fire or {}))
    made.title_entities = annotate.annotate(session, made.title, held=group == "trust")      # a trust item is about a held message: its names are claims
    made.next_action_entities = annotate.annotate(session, made.next_action, held=group == "trust")
    return made


# --- the fire -------------------------------------------------------------------------------------------------------

def _fire_context(session: Session):
    by_id: dict[str, list[MessageEvent]] = {}
    for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "po_line")):
        by_id.setdefault(e.ref_id, []).append(e)
    lines = {l.id: l for l in session.scalars(select(PoLine).where(PoLine.id.in_(list(by_id))))}
    groups: dict[str, list[str]] = {}
    for lid, l in lines.items():
        groups.setdefault(l.identity_id, []).append(lid)
    return groups, by_id, lines


def _disruption(session: Session) -> list[tuple[ActionItem, dict]]:
    groups, by_id, lines = _fire_context(session)
    out = []
    names = {p.part_number: p.name for p in session.scalars(select(Product))}
    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    for ident, ids in sorted(groups.items()):
        parts = sorted({lines[i].part_number for i in ids})
        sh = {p: demand.shortage(session, p) for p in parts}
        shorts = {p: s for p, s in sh.items() if s.first_short_month}
        first = min((s.first_short_month for s in shorts.values()), default=None)
        robots = [fam[x] for x in sorted({w.product.id for p in shorts for w in where_used(session, p)})]
        stuck_value = sum(lines[i].open_usd or 0.0 for i in ids)
        who = _short(session, ident)
        contact = suppliers.contact_on_file(session, ident)
        primary = max(shorts, key=lambda p: float(next(b for b in shorts[p].buckets if b.month == first).requirements.value), default=None) if shorts else None
        kind_of = _noun(session, [primary]) if primary else "parts"
        short_months = _fire_months(shorts)      # every month the notice leaves short, each counted on its own
        title = (f"{who} fire: {_and(robots)} builds short of {kind_of} from {month_name(first)}" if first else f"{who} fire: {count(len(ids), "open PO line")} stuck")
        promised = session.scalar(select(func.min(MessageEvent.date_to)).where(MessageEvent.kind == "deadline", MessageEvent.ref_type == "supplier",
                                                                               MessageEvent.ref_id == ident, MessageEvent.detail.like("%revised delivery dates%")))
        act_by = promised or (f"{first}-01" if first else None)
        item = _item(session, f"disruption:{ident}", "disruption", "high", title, owner=_owner_of(session, ids),
                     at_stake=usd(stuck_value, prov("computed", "po_lines", rule="open value of the lines on the force-majeure notice",
                                                     inputs=[ref("po_line", i) for i in ids], by="attention.disruption")),
                     act_by=act_by, next_action=f"Ask {contact.name or who} for revised dates and what it can still ship before the {month_name(first)} builds" if first else "Ask the supplier for revised dates",
                     note="; ".join(n for m, ps in short_months.items() if (n := _robots_note(session, ps, m))) or None,
                     fire=dict(lines_in_scope=len(ids), lines_already_late=sum(1 for i in ids if lines[i].promised_date and lines[i].promised_date < AS_OF.isoformat()),
                               robots_short=[r for m, ps in short_months.items() for r in _robots_short_rows(session, ps, m)]),
                     refs=[ref("supplier", ident, who)] + [ref("part", p) for p in parts] + [ref("message", m) for m in sorted({e.message_id for es in by_id.values() for e in es})])
        out.append((item, dict(ident=ident, ids=ids, parts=parts, sh=sh, shorts=shorts, first=first, names=names, who=who, contact=contact, lines=lines, promised=promised)))
    return out


def _disruption_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    if ctx.get("incident"):
        return _incident_detail(session, item, ctx)
    if ctx.get("slip"):
        return _slip_detail(session, item, ctx)
    if ctx.get("risk"):
        return _risk_detail(session, item, ctx)
    if ctx.get("consignment"):
        return _consignment_detail(session, item, ctx)
    ids, parts, sh, shorts, first = ctx["ids"], ctx["parts"], ctx["sh"], ctx["shorts"], ctx["first"]
    numbers, evidence = [], list(item.refs)
    for p in parts:
        stuck = sum(float(s.qty.value) for s in orders.open_supply(session, p) if s.disrupted_by)
        numbers.append(Number(id=f"stuck_qty:{p}", label=f"{p} open quantity stuck at {ctx['who']}",
                              value=qty(stuck, "EA", prov("computed", "po_lines", rule="lines on the force-majeure notice", inputs=[ref("part", p)], by="orders.open_supply"))))
        t = shorts.get(p)
        if t:
            b = next(b for b in t.buckets if b.month == t.first_short_month)
            numbers.append(Number(id=f"requirement:{p}:{b.month}", label=f"{p} needed in {b.month}", value=b.requirements))
            numbers.append(Number(id=f"shortage:{p}:{b.month}:short", label=f"{p} short in {b.month}, before stock on hand", value=b.short))
    if first:
        numbers.append(Number(id="first_short_month", label="First month with a build short", value=DateValue(date=f"{first}-01", provenance=prov("computed", "demand_forecast", rule="first month where usable supply < requirement", by="demand.shortage"))))
    rec = session.scalar(select(MessageEvent.date_to).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "supplier", MessageEvent.ref_id == ctx["ident"]))
    if rec:
        numbers.append(Number(id="recovery_by", label=f"Supplier's own estimate: partial production resumes in {next((t.recovery_text for t in sh.values() if t.recovery_text), 'a few weeks')}, counted from the notice (latest {md(rec)})", value=DateValue(date=rec, provenance=prov("extracted", "message", rule="the supplier's own estimate, counted from the date of its notice"))))
    primary = max(shorts, key=lambda p: float(next(b for b in shorts[p].buckets if b.month == first).requirements.value), default=None) if shorts else None
    on_hand = _stock_questions(session, parts, "the data has no inventory, so the size of the shortage is 'up to' the requirement, not a definite number")
    revised = unknown("revised delivery dates", f"{ctx['who']} has not said when any of the {count(len(ids), "line")} can ship", "supplier",
                      f"What are the revised dates and what can still ship, per PO line? (promised by {md(item.act_by)})", [ref("po_line", i) for i in ids])
    robots = sorted({w.product.id for p in shorts for w in where_used(session, p)})
    notice = session.scalar(select(MessageEvent.detail).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "supplier", MessageEvent.ref_id == ctx["ident"]))
    notice = humanize(notice.split(";")[0]) if notice else "a force-majeure notice"
    finding = (f"{ctx['who']} has declared force majeure ({notice}) and cannot deliver {count(len(ids), "open PO line")} ({count(len(parts), "part")}). "
               + (f"The first build short is in {month_name(first)}: {_and([ctx['names'][r] for r in robots])} need {', '.join(parts)}, and none is on its way. " if first else "")
               + "On-hand stock is not in the data, so every shortage is 'up to'." + (f" Revised dates are due {md(ctx['promised'])}." if ctx.get("promised") else ""))
    open_lines = {l.ref.id: l for l in orders.open_orders(session)}
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=numbers, unknowns=[*on_hand, revised], evidence=evidence,
                            po_lines=[open_lines[i] for i in sorted(ids) if i in open_lines],
                            messages=[m for m in inbox.list_messages(session) if m.ref.id in {r.id for r in item.refs if r.type == "message"}],
                            time_phased=sh[primary] if primary else None)


def _slip_items(session: Session) -> list[tuple[ActionItem, dict]]:
    """Suppliers whose notice moved open supply past a month that needed it (allocation, lead-time extension): the same fire, a smaller one.
    One row per supplier with the builds it puts short, from `demand.slip_impact`."""
    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    by_sup: dict[str, dict] = {}
    for part in sorted({s.part.id for s in orders.open_supply(session) if not s.stale}):
        imp = demand.slip_impact(session, part)
        if not imp:
            continue
        sup = next(s.supplier.id for s in orders.open_supply(session, part) if s.po_line in imp.slipped_lines)
        g = by_sup.setdefault(sup, dict(impacts={}, lines=[]))
        g["impacts"][part] = imp
        g["lines"] += [l.id for l in imp.slipped_lines]
    out = []
    for ident, g in sorted(by_sup.items()):
        impacts = g["impacts"]
        all_slipped = [s for s in orders.open_supply(session) if s.supplier.id == ident and s.revised_promise and s.promise and s.revised_promise > s.promise and not s.stale]
        first = min(i.first_month for i in impacts.values())
        primary = max(impacts, key=lambda p: float(impacts[p].first_month_qty.value) if impacts[p].first_month == first else 0.0)
        robots = [fam[x] for x in sorted({w.product.id for p in impacts for w in where_used(session, p)})]
        who = _short(session, ident)
        kind_of = _noun(session, sorted(impacts))
        dates = sorted(s.revised_promise for s in all_slipped)
        value = sum(float(s.open_value.usd) for s in all_slipped if s.open_value.usd is not None)
        by_month = {m: [p for p, i in impacts.items() if i.first_month == m] for m in sorted({i.first_month for i in impacts.values()})}      # each part is short in its own first month: a robot that uses it is counted there
        slip_months = _slip_months(impacts)      # robots short in every month the new dates leave short, each counted on its own
        cutoff = session.scalar(select(func.min(MessageEvent.date_to)).where(MessageEvent.kind == "deadline", MessageEvent.ref_type == "supplier", MessageEvent.ref_id == ident,
                                                                              MessageEvent.detail.like("%longer lead time%")))       # the supplier's own date: orders after it take the longer lead time
        gv = usd(value, prov("computed", "po_lines", rule="open value of the lines the notice moves", inputs=[s.po_line for s in all_slipped], by="attention.slip"))
        per_month = "; ".join(f"{_and(sorted({fam[w.product.id] for p in ps for w in where_used(session, p)}))} short of {_noun(session, ps)} from {month_name(m)}" for m, ps in by_month.items())      # each month on its own
        item = _item(session, f"disruption:{ident}", "disruption", "high",
                     f"{who} notice: {count(len(all_slipped), "PO line")} slip to {md(dates[0])}-{md(dates[-1])}; {per_month}",
                     owner=_owner_of(session, [s.po_line.id for s in all_slipped]), at_stake=gv, act_by=cutoff or f"{first}-01",
                     next_action=f"Ask {suppliers.contact_on_file(session, ident).name or who} for an earlier allocation on {', '.join(sorted(impacts))}, or find stock elsewhere",
                     note="; ".join(n for m, own in slip_months.items() if (n := _robots_note(session, list(own), m, own))) or None,
                     fire=dict(lines_in_scope=len(all_slipped), lines_already_late=sum(1 for s in all_slipped if s.promise < AS_OF.isoformat()),
                               robots_short=[r for m, own in slip_months.items() for r in _robots_short_rows(session, list(own), m, own)]),
                     refs=[ref("supplier", ident, who)] + [ref("part", p) for p in sorted(impacts)] + [s.po_line for s in all_slipped])
        out.append((item, dict(slip=True, ident=ident, impacts=impacts, slipped=all_slipped, who=who, primary=primary, first=first, robots=robots, by_month=by_month)))
    return out


# News of an operational incident at a supplier: the topics (from the recipe's news vocabulary) that stop a plant shipping, and how an item says each.
INCIDENT_CAUSE = {"cyberattack": "cyberattack", "fire": "fire", "closure": "plant halt"}


def _incident_items(session: Session, skip: set[str]) -> list[tuple[ActionItem, dict]]:
    """A supplier with news of an operational incident (a cyberattack, a fire, a halt) AND open lines that are moved by its own schedule-change mail or already past due: one
    supply-disruption item, whether or not a shortage follows. Suppliers already carried by a force-majeure or notice item are skipped (it is the same fire)."""
    from app.domain.events.model import Event

    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    news = {}
    for e in session.scalars(select(Event).where(Event.kind == "news", Event.topic.in_(list(INCIDENT_CAUSE))).order_by(Event.date)):
        if e.identity_id and e.identity_id not in skip:
            news[e.identity_id] = e
    out = []
    today = AS_OF.isoformat()
    for ident, ev in sorted(news.items()):
        scope = [s for s in orders.open_supply(session) if s.supplier.id == ident and not s.stale and ((s.revised_promise and s.promise and s.revised_promise > s.promise) or (s.promise and s.promise < today))]
        if not scope:
            continue
        moved = [s for s in scope if s.revised_promise and s.promise and s.revised_promise > s.promise]
        late = [s for s in scope if s not in moved]
        who, cause = _short(session, ident), INCIDENT_CAUSE[ev.topic]
        parts = sorted({s.part.id for s in scope})
        robots = [fam[x] for x in sorted({w.product.id for p in parts for w in where_used(session, p)} & set(fam))]
        value = sum(float(s.open_value.usd) for s in scope if s.open_value.usd is not None)
        mail_ids = sorted({s.revised_by.id for s in moved if s.revised_by})
        ship = sorted(d for e in session.scalars(select(MessageEvent).where(MessageEvent.message_id.in_(mail_ids), MessageEvent.kind == "promise_revision")) if e.detail
                      for d in re.findall(r"ship[s]? (\d{4}-\d{2}-\d{2})", e.detail)) if mail_ids else []
        news_ref = ev.source_id
        new_dates = sorted(s.revised_promise for s in moved)
        head = f"{count(len(scope), "PO line")} late or moved" + (f" (new dates {md(new_dates[0])}-{md(new_dates[-1])})" if moved else "")
        item = _item(session, f"incident:{ident}", "disruption", "high", f"{who} {cause}: {head}; {_and(robots)} builds use these parts" if robots else f"{who} {cause}: {head}",
                     owner=_owner_of(session, [s.po_line.id for s in scope]),
                     at_stake=usd(value, prov("computed", "po_lines", rule="open value of the lines the supplier moved or has not delivered on time", inputs=[s.po_line for s in scope], by="attention.incident")),
                     act_by=(ship[0] if ship else (new_dates[0] if new_dates else today)),
                     next_action=f"Ask {suppliers.contact_on_file(session, ident).name or who} to confirm the new dates hold after the {cause}" + (f" (first shipment {md(ship[0])})" if ship else "") + ", and what ships on the late lines",
                     fire=dict(lines_in_scope=len(scope), lines_already_late=sum(1 for s in scope if s.promise < today)),
                     refs=[ref("supplier", ident, who)] + [ref("part", p) for p in parts] + [s.po_line for s in scope] + [ref("message", m) for m in mail_ids] + [ref("news", news_ref)])
        out.append((item, dict(incident=True, ident=ident, who=who, cause=cause, news=ev, moved=moved, late=late, scope=scope, ship=ship, parts=parts, robots=robots, mail_ids=mail_ids)))
    return out


def _incident_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    who, cause, moved, late, scope = ctx["who"], ctx["cause"], ctx["moved"], ctx["late"], ctx["scope"]
    numbers = []
    for s in sorted(moved, key=lambda s: s.promise):
        numbers.append(Number(id=f"slip:{s.po_line.id}", label=f"{s.po_line.id} {s.part.id}: promised {md(s.promise)}, now {md(s.revised_promise)}",
                              value=DateValue(date=s.revised_promise, provenance=prov("extracted", "message", row=s.po_line.id, raw=s.promise, inputs=[s.po_line]))))
    for s in sorted(late, key=lambda s: s.promise):
        numbers.append(Number(id=f"past_due:{s.po_line.id}", label=f"{s.po_line.id} {s.part.id}: promised {md(s.promise)}, not received, no new date",
                              value=DateValue(date=s.promise, provenance=prov("stated", "po_lines", row=s.po_line.id, inputs=[s.po_line]))))
    value = sum(float(s.open_value.usd) for s in scope if s.open_value.usd is not None)
    numbers.append(Number(id=f"incident:{ctx['ident']}:open_value", label=f"Open value of the {count(len(scope), 'line')} (USD)",
                          value=usd(value, prov("computed", "po_lines", rule="open value of the lines moved or past due", inputs=[s.po_line for s in scope], by="attention.incident"))))
    finding = (f"{who} reported a {cause} on {md(ctx['news'].date)}: {ctx['news'].detail or ctx['news'].title} "
               + (f"Its schedule-change mail moves {count(len(moved), 'PO line')} to {md(min(s.revised_promise for s in moved))} through {md(max(s.revised_promise for s in moved))}" + (f", the first shipment {md(ctx['ship'][0])}" if ctx['ship'] else "") + ". " if moved else "")
               + (f"{count(len(late), 'more line')} {'is' if len(late) == 1 else 'are'} past the promised date with no new one. " if late else "")
               + f"{_and(ctx['robots'])} builds use {', '.join(ctx['parts'])}. On-hand stock is not in the data, so whether a build is short is not known.")
    unknowns = _stock_questions(session, ctx["parts"], "the data has no inventory, so whether a build is short is unknown")
    open_lines = {l.ref.id: l for l in orders.open_orders(session)}
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=numbers, unknowns=unknowns, evidence=item.refs, po_lines=[open_lines[s.po_line.id] for s in scope if s.po_line.id in open_lines],
                            messages=[m for m in inbox.list_messages(session) if m.ref.id in set(ctx["mail_ids"])])


def _slip_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    impacts, slipped, who, primary = ctx["impacts"], ctx["slipped"], ctx["who"], ctx["primary"]
    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    numbers = []
    for p, imp in sorted(impacts.items()):
        numbers.append(Number(id=f"slip_short:{p}:{imp.first_month}", label=f"{p} short in {month_name(imp.first_month)} because of the new dates, before stock on hand", value=imp.first_month_qty))
        if imp.first_month_backlog.value > imp.first_month_qty.value:
            numbers.append(Number(id=f"slip_backlog:{p}:{imp.first_month}", label=f"{p} unmet need carried in from earlier months, cumulative to the end of {month_name(imp.first_month)}", value=imp.first_month_backlog))
    for s in sorted(slipped, key=lambda s: s.promise):
        numbers.append(Number(id=f"slip:{s.po_line.id}", label=f"{s.po_line.id} {s.part.id}: promised {md(s.promise)}, now {md(s.revised_promise)}",
                              value=DateValue(date=s.revised_promise, provenance=prov("extracted", "message", row=s.po_line.id, raw=s.promise, inputs=[s.po_line]))))
    # duty on lines that now arrive on or after the effective date
    claims = {e.ref_id: e for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "origin_claim"))}
    china_claim = [s for s in slipped if s.po_line.id in claims and "China" in claims[s.po_line.id].detail]
    unknowns = _stock_questions(session, impacts, "the data has no inventory, so a shortage here is 'up to' the requirement")
    note = ""
    for s in china_claim:
        d = tariffs.duty_for_line(session, s.po_line.id)
        if d.status == "unknown":
            unknowns.append(d.unknown)
        elif d.duty is not None and (eff := _effective_date(session, s.part.id)) and s.revised_promise >= eff:
            numbers.append(Number(id=f"duty_if_arrives_late:{s.po_line.id}", label=f"{s.part.id}: duty if it enters on or after {md(eff)} (made in China per the notice)", value=d.duty))
    if china_claim:
        note = (f" The notice says {', '.join(sorted({claims[s.po_line.id].detail.split(' (')[0] for s in china_claim}))} are made in {', '.join(sorted({claims[s.po_line.id].detail.split(' manufactured in ')[-1].split(' (')[0] for s in china_claim}))}: what arrives on or after the duty date "
                f"pays it unless it entered before; the parts' own origin is {'blank' if any(session.get(Part, s.part.id).coo is None for s in china_claim) else 'China'} in the item master.")
    finding = (f"{who} moved {count(len(slipped), "open PO line")} to {md(min(s.revised_promise for s in slipped))} through {md(max(s.revised_promise for s in slipped))}. "
               "The promised dates covered " + "; ".join(f"{', '.join(ps)} for the {month_name(m)} builds ({_and([fam[x] for x in sorted({w.product.id for p in ps for w in where_used(session, p)})])})" for m, ps in ctx["by_month"].items()) + "; the new ones do not." + note)
    open_lines = {l.ref.id: l for l in orders.open_orders(session)}
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=numbers, unknowns=unknowns, evidence=item.refs,
                            po_lines=[open_lines[s.po_line.id] for s in slipped if s.po_line.id in open_lines],
                            messages=[m for m in inbox.list_messages(session) if m.supplier and m.supplier.id == ctx["ident"] and m.kind in ("slip", "correction", "force majeure")],
                            time_phased=demand.shortage(session, primary))


def _buyer_on_lines_of(session: Session, identity_id: str) -> str | None:
    """The id of the buyer on most of a supplier's PO lines."""
    counts: dict[str, int] = {}
    for b in session.scalars(select(PoLine.buyer_id).where(PoLine.identity_id == identity_id)):
        counts[b] = counts.get(b, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _poss(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def _clauses(description: str | None) -> list[str]:
    return [c.strip() for c in (description or "").split(",") if c.strip()]


def _next_due(live) -> str | None:
    """The next date an open line is due (its revised promise, else its promise), on or after the data date; None when none is."""
    days = sorted(d for d in ((s.revised_promise or s.promise) for s in live) if d and d >= AS_OF.isoformat())
    return days[0] if days else None


def _consignment_items(session: Session) -> list[tuple[ActionItem, dict]]:
    """Material the company consigns to a contract manufacturer, built there into a part, that is late: the slip reaches every product that contains the built part,
    and the manufacturer's own lead time runs from receipt of the material (read from its quote). One row per consignment whose material has slipped."""
    from app.domain.consignments import service as consignments

    out = []
    names = {p.part_number: p.family for p in session.scalars(select(Product))}
    for c in consignments.list_consignments(session):
        late = [l for l in c.material_lines if l.days_later and l.days_later > 0]
        if not late or not c.slip_days:
            continue
        ids = {l.po_line.id for l in late}
        supply = [s for s in orders.open_supply(session, c.material.id) if s.po_line.id in ids]
        held_by = supply[0].supplier.id if supply else c.holder.id
        value = sum(float(s.open_value.usd) for s in supply if s.open_value.usd is not None)
        into, mat = session.get(Part, c.into.id), session.get(Part, c.material.id)
        built = next((x for x in _clauses(into.description)[1:2] if _clauses(into.description)[0].isupper()), _clauses(into.description)[0]).lower()
        board = _clauses(mat.description)[0]
        reached = sorted({names.get(r.product.id, r.product.id) for r in c.reaches})
        everyone = set(reached) == set(names.values())
        span = f"{round(c.slip_days / 7)} weeks" if c.slip_days >= 10 else count(c.slip_days, "day")
        slip_event = session.scalars(select(MessageEvent).where(MessageEvent.ref_type == "po_line", MessageEvent.ref_id.in_(ids), MessageEvent.kind == "promise_revision")).first()
        quote = re.search(r"message (\S+?):", c.evidence)
        offer = session.scalars(select(Offer).where(Offer.identity_id == c.holder.id, Offer.part_number == c.into.id, Offer.lead_time_condition.like("%consign%"))).first()
        buyers = list(dict.fromkeys(buyer_name(session, b) for b in (mat.buyer_id, into.buyer_id, _buyer_on_lines_of(session, c.holder.id)) if b))
        who, maker = _short(session, held_by), _short(session, c.holder.id)
        item = _item(session, f"consignment:{c.material.id}", "disruption", "high" if everyone else "medium",
                     f"{built.capitalize()}s for {'every robot' if everyone else _and(reached) + ' robots'} slip about {span}: consigned {board} late at {who}",
                     owner=" · ".join(buyers), act_by=min((l.now for l in late if l.now and l.now >= AS_OF.isoformat()), default=AS_OF.isoformat()), category="Purchasing",      # the day the material now arrives (M8), not the data date
                     at_stake=usd(value, prov("computed", "po_lines", rule="open value of the late lines of the consigned material", inputs=[s.po_line for s in supply], by="attention.consignment")) if supply else None,
                     note=f"{c.slip_days} days later than promised" + (f"; {_poss(maker)} {offer.lead_time} runs {offer.lead_time_condition}" if offer else ""),
                     next_action=f"Ask {suppliers.contact_on_file(session, held_by).name or who} for an earlier date on {', '.join(sorted(ids))}; ask {suppliers.contact_on_file(session, c.holder.id).name or maker} what the later receipt does to the {built}'s lead time",
                     refs=[ref("supplier", held_by, who), ref("supplier", c.holder.id, maker), ref("part", c.material.id), ref("part", c.into.id)] + [l.po_line for l in late]
                     + ([ref("message", slip_event.message_id)] if slip_event else []) + ([ref("message", quote.group(1))] if quote else []))
        out.append((item, dict(consignment=True, c=c, late=late, supply=supply, built=built, board=board, who=who, maker=maker, offer=offer, reached=reached, everyone=everyone, span=span)))
    return out


def _consignment_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    c, late, who, maker, built, board, offer = ctx["c"], ctx["late"], ctx["who"], ctx["maker"], ctx["built"], ctx["board"], ctx["offer"]
    finding = (f"{who} moved {count(len(late), 'open order')} for the {board} ({c.material.id}) from {md(late[0].promised)} to {md(late[0].now)}, {c.slip_days} days later. "
               f"The company consigns that board to {maker}, which builds it into the {built} ({c.into.id}) that goes into {'every robot' if ctx['everyone'] else _and(ctx['reached'])}. "
               + (f"{_poss(maker)} quote counts its {offer.lead_time} {offer.lead_time_condition}, so the {built} is about {ctx['span']} later too. " if offer else f"The {built} is built from the board, so it is later too. ")
               + "The records hold no stock of the board or the built part.")
    nums = [Number(id=f"consigned_slip_days:{c.material.id}", label=f"Days later than promised ({c.material.id})", value=qty(c.slip_days, "days", prov("computed", "po_lines", rule="the longest slip among the open orders of the consigned material", inputs=[l.po_line for l in late], by="attention.consignment")))]
    reach_month = late[0].now[:7] if late and late[0].now else None
    plan = {f.product_part: f.units for f in session.scalars(select(DemandForecast).where(DemandForecast.month == reach_month))} if reach_month else {}
    nums = [Number(id="tile:slip_days", label="Days later than promised", value=nums[0].value),
            Number(id="tile:pcb_due", label=f"The {board} is now due", value=DateValue(date=late[0].now, provenance=prov("extracted", "message", row=late[0].po_line.id, raw=late[0].promised, inputs=[late[0].po_line])))] \
           + [Number(id=f"tile:robots:{r.product.id}:{reach_month}", label=f"{r.product.label or r.product.id} planned in {month_name(reach_month)}", value=qty(plan.get(r.product.id, 0), "robots", prov("computed", "demand_forecast", row=f"{r.product.id}/{reach_month}", rule="robots planned that month; the built part goes into each", by="attention.consignment")))
              for r in c.reaches if reach_month and plan.get(r.product.id)] + nums
    nums += [Number(id=f"slip:{l.po_line.id}", label=f"{l.po_line.id}: promised {md(l.promised)}, now {md(l.now)}", value=DateValue(date=l.now, provenance=prov("extracted", "message", row=l.po_line.id, raw=l.promised, inputs=[l.po_line]))) for l in late]
    if item.at_stake is not None:
        nums.append(Number(id=f"consigned_open_value:{c.material.id}", label=f"Open value of the late {board} orders", value=item.at_stake))
    unknowns = [unknown("stock of the board or the built part", "the data has no inventory", buyer_of_part(session, c.material.id), f"Is there {board} or {built} on hand at {maker}, or in transit, that covers the weeks?", [ref("part", c.into.id)])]
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=unknowns, evidence=item.refs,
                            po_lines=[l for l in orders.open_orders(session) if l.ref.id in {x.po_line.id for x in late}],
                            messages=[m for m in inbox.list_messages(session) if m.ref.id in {r.id for r in item.refs if r.type == "message"}])


def _risk_items(session: Session) -> list[tuple[ActionItem, dict]]:
    """A supplier with a warning in its own quote or in the news (insolvency, prepayment demanded, terms cut, a price far above the last PO) that is also the
    only source of a part the plan needs. One row per supplier; the warnings are read from the records (`suppliers.risk`), never named here."""
    out = []
    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    for ident in sorted(i for i in session.scalars(select(SupplierIdentity.id))):
        flags = supplier_risk.risk_flags(session, ident)
        sole = supplier_risk.sole_source_parts(session, ident) if flags else []
        if not flags or not sole or not any(f.severity == "high" for f in flags):      # a mild warning alone stays on the supplier's page, not on Today
            continue
        kinds = {f.kind for f in flags}
        who = _short(session, ident)
        parts = {p: session.get(Part, p) for p in sole}
        first = sole[0]
        robots = sorted({fam[w.product.id] for p in sole for w in where_used(session, p)})
        late = next((f for f in flags if f.kind == "late_delivery"), None)
        share = supplier_risk.spend_share(session).get(ident, 0.0)
        head = ("in insolvency" if "insolvency" in kinds else "demands prepayment" if "prepayment" in kinds else "has cut its payment terms" if "terms_cut" in kinds
                else f"delivers late ({late.text.split(' of its ')[0].replace('On time on ', 'on time on ')} of {late.text.split(' of its ')[1].split(' closed')[0]} lines)" if late
                else "wants cash before it ships" if "cash_in_advance" in kinds else "quotes far above the last PO")
        what = f"{_and(robots)} {_head(parts[first].description)}" + (f" and {len(sole) - 1} more part{'s' if len(sole) > 2 else ''}" if len(sole) > 1 else "")
        lead = "don't prepay; " if kinds & {"insolvency", "prepayment"} else ""
        monthly = next((m for m in demand.requirements(session, first)), None)
        live = [s for s in orders.open_supply(session) if s.supplier.id == ident and not s.stale]
        value = sum(float(s.open_value.usd) for s in live if s.open_value.usd is not None)
        late = [s for s in live if s.days_past_due]
        offers = list(session.scalars(select(Offer).where(Offer.identity_id == ident, Offer.superseded_by.is_(None), Offer.trust != "blocked")))
        valid = sorted(o.validity_date for o in offers if o.validity_date and o.validity_date >= AS_OF.isoformat())
        buyers = list(dict.fromkeys(buyer_name(session, session.get(Part, p).buyer_id) for p in sole))
        contact = suppliers.contact_on_file(session, ident)
        item = _item(session, f"risk:{ident}", "disruption", "high" if ("insolvency" in kinds or share >= supplier_risk.thresholds(session)["top_spend_share"]) else "medium", f"{who} {head}: {lead}secure the {what}",
                     owner=" · ".join(buyers), act_by=valid[0] if valid else _next_due(live), category="Quote & risk",      # a quote's lapse, else the next open line's date (M8), never the data date
                     at_stake=usd(value, prov("computed", "po_lines", rule="open value of the supplier's live open orders", inputs=[s.po_line for s in live], by="attention.risk")) if live else None,
                     note=f"sole source of {_head(parts[first].description)} ({parts[first].part_number})" + (f": {monthly.qty.value:.0f} a month for the {_and(robots)} build" if monthly else "") + (f"; {share:.1%} of the last twelve months' spend" if share >= 0.01 else ""),
                     next_action=(f"Do not pay in advance on {who}'s quote; " if lead else "") + f"ask {contact.name or who} to ship the {count(len(live), 'open line')} on open terms, and ask a second source for {parts[first].part_number}",
                     refs=[ref("supplier", ident, who)] + [ref("part", p) for p in sole] + [r for f in flags for r in f.sources][:6])
        out.append((item, dict(risk=True, ident=ident, who=who, flags=flags, sole=sole, late=late, live=live, monthly=monthly, robots=robots, offers=offers)))
    return out


def _risk_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    who, flags, sole, late, live, monthly, robots = ctx["who"], ctx["flags"], ctx["sole"], ctx["late"], ctx["live"], ctx["monthly"], ctx["robots"]
    finding = (f"{who}: " + "; ".join(f.text for f in flags) + f". It is the only supplier of {', '.join(sole)}" + (f", which the {_and(robots)} build needs at {monthly.qty.value:.0f} a month" if monthly else "") + ". "
               + (f"{len(late)} of its {count(len(live), 'open line')} {'is' if len(late) == 1 else 'are'} already late, the oldest promised {md(min(s.promise for s in late))}. " if late else "")
               + "The records hold its own quote and the news; they do not say whether it can keep shipping.")
    nums = [Number(id="tile:lines_late", label=f"{who}'s open lines already late", value=qty(len(late), "lines", prov("computed", "po_lines", rule="open lines past their promise date", inputs=[s.po_line for s in late], by="attention.risk")))]
    pre = next((f for f in flags if f.kind == "prepayment"), None)
    pct = re.search(r"(\d+(?:\.\d+)?)%", pre.text) if pre else None
    if pct:
        nums.append(Number(id="tile:prepayment", label="Prepayment demanded", value=qty(float(pct.group(1)), "%", prov("extracted", "offers", rule=pre.evidence or pre.text, inputs=pre.sources, by="attention.risk"))))
    if item.at_stake is not None:
        nums.append(Number(id=f"risk_open_value:{ctx['ident']}", label=f"Open value with {who} (what an insolvency would stop)", value=item.at_stake))
    if monthly:
        nums.append(Number(id=f"risk_need:{sole[0]}", label=f"{sole[0]} needed a month", value=monthly.qty))
    unknowns = [unknown("whether the supplier can keep delivering", "the records hold its own quote and the news, not its position" + (" or the monitor's decision" if any(f.kind == "insolvency" for f in flags) else ""), buyer_of_part(session, sole[0]),
                        f"Will {who} ship the open lines on open terms" + (", and will the court-appointed monitor confirm it?" if any(f.kind == "insolvency" for f in flags) else "?"), [ref("supplier", ctx["ident"], who)])]
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=unknowns, evidence=item.refs, po_lines=[l for l in orders.open_orders(session) if l.supplier.id == ctx["ident"]],
                            messages=[m for m in inbox.list_messages(session) if m.supplier and m.supplier.id == ctx["ident"]])


# --- trust ----------------------------------------------------------------------------------------------------------

def _lookalike(session: Session, m: Message) -> str | None:
    """The supplier (identity id) whose contact domain the sender's domain imitates (close but not equal), by string similarity: a mechanism, not a name."""
    from difflib import SequenceMatcher

    best, who = 0.0, None
    for r in session.scalars(select(SupplierRecord)):
        d = r.email_domain
        if not d or not m.from_domain or d == m.from_domain:
            continue
        s = SequenceMatcher(None, d, m.from_domain).ratio()
        if s > best:
            best, who = s, r
    return who.identity_id if who is not None and best >= 0.85 else None


def _lookalike_of(session: Session, m: Message) -> str | None:
    """The short name of the supplier the sender imitates, or None."""
    sid = _lookalike(session, m)
    return _short(session, sid) if sid else None


def _trust_items(session: Session) -> list[tuple[ActionItem, dict]]:
    out = []
    for m in session.scalars(select(Message).where(Message.trust == "blocked").order_by(Message.date)):
        flags = (m.trust_flags or "").split(",")
        events = {e.kind: e for e in session.scalars(select(MessageEvent).where(MessageEvent.message_id == m.id))}
        owner = next((b for b in buyer_ids(session) if f"{b.lower()}." in (m.to_addrs or "").lower()), None)
        imitated = None
        if "bank_detail_change" in flags:
            ev = events.get("remittance_change")
            amount = float(ev.qty) if ev is not None and ev.qty else 0.0
            look = _lookalike(session, m)
            imitated = None if m.identity_id else look      # the supplier a look-alike sender pretends to be: its page shows the attempt
            who = _short(session, look) if look else None
            title = f"Payment change request from a look-alike of {who}: do not pay" if who else "Payment change request from a sender that is not on file: do not pay"
            nxt = "Do not pay or update the vendor master. Confirm bank details by phone with the contact on file; tell finance."
            claim = f"USD {amount:,.0f} to new bank details" if amount else "a payment to new bank details"
        else:
            offer = session.scalar(select(Offer).where(Offer.message_id == m.id, Offer.part_number.is_not(None)).order_by(Offer.id))
            part, lot, price = (offer.part_number, offer.qty_break or 0, offer.unit_price_each) if offer else (None, 0, 0.0)
            rp = session.get(ReferencePrice, part) if part else None
            ratio = price / rp.usd_each if rp and rp.usd_each else None
            amount = price * lot
            title = (f"Spot offer at {ratio:.1f}x the usual price, with an instruction aimed at AI systems: do not order" if ratio
                     else "Spot offer, with an instruction aimed at AI systems: do not order")
            cov = orders.open_supply(session, part) if part else []
            nxt = "Do not order. " + (f"An open PO already covers the part ({cov[0].po_line.id}, {cov[0].qty.value:.0f} EA)." if cov else "")
            part_buyer = buyer_of_part(session, part) if part else None
            if part_buyer and part_buyer != "unassigned" and part_buyer != owner:
                nxt += f" It came to {owner}'s inbox; {part_buyer} buys the part."
                owner = part_buyer
            claim = f"{lot:,} pieces at USD {price:,.2f} each" if offer else "a spot lot"
        item = _item(session, f"trust:{m.id}", "trust", "high", title, owner=buyer_name(session, owner), next_action=nxt,
                     at_stake=usd(amount, prov("extracted", f"message:{m.file}", rule=f"{claim}: the message's claim, not a payable", by="attention.trust")),
                     act_by=AS_OF.isoformat(), refs=[ref("message", m.id, m.subject)] + ([ref("supplier", m.identity_id)] if m.identity_id else [ref("supplier", imitated, _short(session, imitated))] if imitated else []))
        out.append((item, dict(message=m, flags=flags, claim=claim, events=events)))
    return out


def _trust_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    m: Message = ctx["message"]
    verdict = inbox.trust(session, m.id)
    why = "; ".join(f.words for f in verdict.flags)
    finding = f"Blocked before anyone read it: {why}. The message asks you to send {ctx['claim']}. Its text is shown as quoted data; no action can be drafted from it."
    nums = [Number(id=f"claim:{m.id}", label="Amount the message asks for (its claim, not a payable)", value=item.at_stake)]
    offer = session.scalar(select(Offer).where(Offer.message_id == m.id, Offer.part_number.is_not(None)).order_by(Offer.id))
    rp = session.get(ReferencePrice, offer.part_number) if offer else None
    if offer and rp and rp.usd_each:
        part, usual = offer.part_number, rp.usd_each
        nums.append(Number(id=f"usual_unit_price:{part}", label=f"Usual unit price for {part} (last order)",
                           value=usd(usual, prov("stated", "po_lines", row=rp.po_line_id, rule="latest clean PO line", inputs=[ref("po_line", rp.po_line_id)]), places=6)))
        nums.append(Number(id=f"offered_unit_price:{part}", label="Price the message offers, each", value=usd(offer.unit_price_each, prov("extracted", f"message:{m.file}", raw=offer.price_raw), places=6)))
        nums.append(Number(id=f"price_ratio:{part}", label="Offered price over the usual price", value=qty(round(offer.unit_price_each / usual, 1), "x", prov(
            "computed", "messages", rule="offered unit price / usual unit price", inputs=[ref("message", m.id), ref("po_line", rp.po_line_id)], by="attention.trust"))))
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=[], evidence=item.refs, messages=[s for s in inbox.list_messages(session) if s.ref.id == m.id])


# --- deadlines ------------------------------------------------------------------------------------------------------

def _rise_rates(detail: str) -> list[tuple[float, list[str]]]:
    """'+8.5% extruded profiles, +4.0% die-cast brackets from 2026-11-01' -> [(8.5, ['extru', 'profi']), (4.0, ['cast', 'brack'])]: each rise with the stems of the words that say what it applies to."""
    return [(float(pct), [w[:5] for w in re.findall(r"[a-z]{4,}", words.lower()) if w not in ("from", "effective")])
            for pct, words in re.findall(r"([+-]?\d+(?:\.\d+)?)%\s+([^,;]+?)(?=,|;|\sfrom\b|$)", detail or "")]


def _price_lock_cost(session: Session, ident: str, lock) -> Money:
    """What acting by the lock date saves: the rise on the need that is still to be ordered and delivered from the rise date to the lock's delivery-by date, each part at the rise that
    applies to it (the notice names the rises by what they apply to). Open orders are already placed at today's price: they carry no rise, and they cover the earliest need first
    (`demand.uncovered_between`). The window is whole months from the rise month through the delivery-by month, because the forecast is monthly; at the part's last clean price."""
    from app.domain.orders.model import ReferencePrice

    notice = session.scalars(select(MessageEvent).where(MessageEvent.message_id == lock.message_id, MessageEvent.kind == "price_change")).first()
    to = re.search(r"delivery by (\d{4}-\d{2}-\d{2})", lock.detail or "")
    rates = _rise_rates(notice.detail) if notice else []
    if not (notice and notice.date_from and to and rates):
        return unknown("what the price rise costs", "the notice does not give the rise, its start and the lock's delivery date in a form that can be priced", _owner_of(session, []), "What is the rise per part, and which deliveries does the lock cover?", [ref("supplier", ident)])
    start, end = notice.date_from, to.group(1)
    parts = sorted({l.part_number for l in session.scalars(select(PoLine).where(PoLine.identity_id == ident, PoLine.status != "CANCELLED")) if l.part_number})
    total, inputs = 0.0, []

    def rate_of(part: str) -> float:
        p = session.get(Part, part)
        for text in ((p.description or "").lower(), (p.category or "").lower()) if p else ():      # what the part is says more than the category it is filed under
            hit = next((pct for pct, stems in rates if any(st in text for st in stems)), None)
            if hit is not None:
                return hit / 100
        return 0.0

    for part in parts:
        r = rate_of(part)
        if not r:
            continue
        last_month = max((q.month for q in demand.requirements(session, part) if f"{q.month}-01" <= end), default=None)
        left = demand.uncovered_between(session, part, start[:7], last_month) if last_month else 0.0      # open orders netted against the earliest need first, whatever date they land
        rp = session.get(ReferencePrice, part)
        if rp and left:
            total += left * rp.usd_each * r
            inputs.append(ref("part", part))
    return usd(total, prov("computed", "po_lines", rule=f"the announced rise on the need in the months {start[:7]} to the lock's delivery-by month ({end[:7]}, whole months) that open orders do not cover, at the last price paid; open orders are netted against the earliest need first, overdue ones counted as available now", inputs=inputs[:50], by="attention.deadline"))


def _quote_stake(session: Session, identity_id: str, validity: str) -> dict:
    """What lapsing costs, or - where there is no alternative price - the spend the quote covers (a different thing, labelled so).

    For each quoted part: the lowest quoted unit price against the next-best price (the last clean PO price, or another live offer), times the
    12-month requirement. If any part would cost more without the quote, the stake is that extra cost (rule `lapse_cost`). Otherwise the stake is
    the planned spend the quote covers (rule `spend_covered`); the row says "covers", never "at stake"."""
    from app.domain.quotes.model import Offer
    from app.domain.quotes.service import _fx
    from app.domain.orders.model import ReferencePrice

    mine = list(session.scalars(select(Offer).where(Offer.identity_id == identity_id, Offer.validity_date == validity, Offer.superseded_by.is_(None), Offer.trust != "blocked")))
    quoted: dict[str, float] = {}
    for o in mine:
        if o.part_number:
            quoted[o.part_number] = min(quoted.get(o.part_number, 1e18), o.unit_price_each * _fx(session, o.currency)[0])
    lapse = spend = 0.0
    inputs = []
    for part, price in quoted.items():
        need = sum(float(r.qty.value) for r in demand.requirements(session, part))
        if not need:
            continue
        alts = [x.unit_price_each * _fx(session, x.currency)[0] for x in session.scalars(select(Offer).where(
            Offer.part_number == part, Offer.superseded_by.is_(None), Offer.trust != "blocked")) if (x.identity_id, x.validity_date) != (identity_id, validity)]
        rp = session.get(ReferencePrice, part)
        if rp:
            alts.append(rp.usd_each)
        spend += price * need
        if alts:
            lapse += max(0.0, min(alts) - price) * need
        inputs.append(ref("part", part))
    if lapse > 0:
        return dict(kind="lapse_cost", amount=lapse, spend=spend, money=usd(lapse, prov("computed", "offers", rule="lapse_cost: (next-best price - quoted price) x the 12-month requirement, per quoted part",
                                                                                           inputs=inputs, by="attention.deadline")))
    if spend > 0:
        return dict(kind="spend_covered", amount=spend, spend=spend,
                    money=unknown("what lapsing costs", "no other price for these parts is on file, so a re-quote cannot be compared; the quote prices planned buys but the stake is the difference, which is not known",
                                  _buyer_first(session, next(iter(quoted), "")), "What would a new quote for these parts cost, if this one lapsed?", [ref("part", p) for p in list(quoted)[:8]]))
    return dict(kind="unknown", amount=0.0, spend=0.0, money=unknown("what lapsing costs", "none of the quoted parts has forecast demand", _buyer_first(session, next(iter(quoted), "")), f"Which of the quoted parts will {company_name(session)} buy?", [ref("supplier", identity_id)]))


def _validity_deadlines(session: Session) -> tuple[list[tuple[ActionItem, dict]], list[tuple[ActionItem, dict]]]:
    """Quotes that lapse within the window, from the offers (emails and PDFs alike). The first is its own item (the fire's supplier);
    the rest roll up into one `deadline:quotes` item. Returns (visible, children): each quote is also resolvable on its own key."""
    from app.domain.quotes.model import Offer

    singles, seen = [], set()
    for o in session.scalars(select(Offer).where(Offer.validity_date.is_not(None), Offer.identity_id.is_not(None), Offer.trust != "blocked").order_by(Offer.validity_date)):
        left = _days(o.validity_date)
        key = f"deadline:{o.identity_id}:{o.validity_date}"
        if left is None or left < 0 or left > DEADLINE_WINDOW_DAYS or key in seen:
            continue
        seen.add(key)
        who = _short(session, o.identity_id)
        parts = sorted({x.part_number for x in session.scalars(select(Offer).where(Offer.identity_id == o.identity_id, Offer.validity_date == o.validity_date)) if x.part_number})
        owner = _owner_of(session, [l.id for l in session.scalars(select(PoLine).where(PoLine.identity_id == o.identity_id).limit(200))])
        st = _quote_stake(session, o.identity_id, o.validity_date)
        stake = st["money"]
        cost = f"lapsing costs {_fmt(st['amount'])}" if st["kind"] == "lapse_cost" else f"quoted on {_fmt(st['amount'])} of planned buys; cost of lapsing unknown" if st["kind"] == "spend_covered" else "cost of lapsing unknown"
        sev = "high" if left <= 7 else "medium" if left <= 21 else "low"
        item = _item(session, key, "deadline", sev, f"{who}'s {_noun(session, parts)} quote expires {md(o.validity_date)}: {len(parts)} part{'s' if len(parts) != 1 else ''}, {cost}", owner=owner, at_stake=stake,
                     act_by=o.validity_date, next_action="Decide what to order on this quote, or ask for an extension",
                     refs=[ref("supplier", o.identity_id, who), ref("message", o.message_id)] + ([ref("quote", o.quote_no, f"{who} quote {o.quote_no}")] if o.quote_no else [])
                          + [ref("part", p) for p in parts[:8]])
        singles.append((item, dict(offer=o, parts=parts, stake=st)))
    on_fire = set(_fire_context(session)[0])
    lead = [x for x in singles if x[0].key.split(":")[1] in on_fire]   # a supplier that already has a disruption row keeps its own row
    rest = [x for x in singles if x not in lead]
    if len(rest) < 2:
        return singles, singles
    lapse_total = sum(c["stake"]["amount"] for _, c in rest if c["stake"]["kind"] == "lapse_cost")
    spend_total = sum(c["stake"]["spend"] for _, c in rest)
    kind, stake = ("lapse_cost", lapse_total) if lapse_total > 0 else ("spend_covered", spend_total)
    pv = prov("computed", "offers", rule=("lapse_cost: sum of what each quote's lapse would add" if kind == "lapse_cost" else "spend_covered: sum of the planned spend the quotes cover; no cheaper alternative exists"),
              inputs=[r for i, _ in rest for r in i.refs if r.type == "supplier"], by="attention.deadline")
    cost = f"lapsing costs {_fmt(stake)}" if kind == "lapse_cost" else f"quoted on {_fmt(stake)} of planned buys; cost of lapsing unknown"
    first = min(i.act_by for i, _ in rest)
    quote_owners = []
    for i, c in sorted(rest, key=lambda x: x[0].act_by):
        pb = session.scalar(select(Part.buyer_id).where(Part.part_number == c["offer"].part_number))
        quote_owners.append((buyer_name(session, pb) if pb else i.owner, f"{_short(session, c['offer'].identity_id)} by {md(c['offer'].validity_date)}"))
    names = ", ".join(f"{_short(session, c['offer'].identity_id)} {md(c['offer'].validity_date)}" for _, c in rest)
    roll = _item(session, "deadline:quotes", "deadline", "medium" if (_days(first) or 99) <= 21 else "low", f"{len(rest)} more quotes expire by {md(max(i.act_by for i, _ in rest))} ({names}): {cost}",
                 owner=" · ".join(dict.fromkeys(o for o, _ in quote_owners)),
                 at_stake=usd(stake, pv) if stake and kind == "lapse_cost" else unknown("what lapsing costs", "no other price for the quoted parts is on file, so a re-quote cannot be compared", quote_owners[0][0], "What would new quotes cost if these lapsed?", []),
                 act_by=first, next_action=f"{_by_owner(quote_owners, ": ")}. Each decides what to order, or asks for an extension",
                 refs=[r for i, _ in rest for r in i.refs if r.type == "supplier"])
    return lead + [(roll, dict(rest=rest))], singles


def _closure_item(session: Session, e, closure, key: str, who: str, due: str, owner_name: str):
    """A supplier's closure as a dated row: the day to act is its last shipment before the closure (when it gave one), else the first closed day. The stake is the open value
    of its lines that cannot leave later than that or fall inside the closure; lines already under a force-majeure notice are the fire's, not this row's."""
    a, b = closure.date_from, closure.date_to
    last = e.date_to if e.kind == "deadline" else None
    held = re.search(r"ship (\w+ \d+)$", closure.detail or "")
    mine = [s for s in orders.open_supply(session) if s.supplier.id == e.ref_id and not s.stale and not s.disrupted_by and s.promise and s.promise <= b]
    value = sum(float(s.open_value.usd) for s in mine if s.open_value.usd is not None)
    late = [s for s in mine if s.days_past_due]
    contact = suppliers.contact_on_file(session, e.ref_id).name or who
    sev = "high" if (_days(due) or 99) <= 7 else "medium"
    title = f"{who} closed {md(a)} to {md(b)}" + (f": its last shipment before it is {md(last)}" if last else "")
    stake = usd(value, prov("computed", "po_lines", rule=f"open value of the supplier's lines due by the end of the closure ({md(b)}), past due ones included", inputs=[s.po_line for s in mine], by="attention.closure")) if value else None
    item = _item(session, key, "deadline", sev, title, owner=owner_name, at_stake=stake, act_by=due, category="Purchasing",
                 note=f"{count(len(mine), 'open line')} due by {md(b)}" + (f", {len(late)} already late" if late else "") if mine else None,
                 next_action=(f"Ask {contact} to ship what is late and what is needed before {md(b)} by {md(last)}" if last else f"Ask {contact} what is due in the closure and what can ship before {md(a)}")
                 + (f"; anything scheduled in the closure ships {held.group(1)}" if held else ""),
                 refs=[ref("supplier", e.ref_id, who), ref("message", e.message_id)] + [s.po_line for s in mine[:6]])
    return item, dict(event=e, closure=closure, lines=mine, late=late)


def _deadlines(session: Session) -> list[tuple[ActionItem, dict]]:
    out, seen = [], set()
    last_ship = {e.message_id for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "deadline", MessageEvent.detail.like("last shipment%")))}
    for e in session.scalars(select(MessageEvent).where(MessageEvent.kind.in_(("deadline", "closure"))).order_by(MessageEvent.date_to)):
        if not e.date_to or e.ref_type != "supplier" or not e.ref_id or "longer lead time" in (e.detail or ""):      # a lead-time cut-off is the slip row's date, not a row of its own
            continue
        if e.kind == "closure" and e.message_id in last_ship:      # its last shipment date is the row; the closure is that row's window
            continue
        closure = None
        if e.detail.startswith("last shipment"):
            closure = session.scalars(select(MessageEvent).where(MessageEvent.message_id == e.message_id, MessageEvent.kind == "closure")).first()
        elif e.kind == "closure":
            closure = e
        due = e.date_to if e.kind == "deadline" else e.date_from
        forwarding = "forward only until" in e.detail
        left = _days(due)
        if left is None or left < 0 or left > (120 if forwarding else DEADLINE_WINDOW_DAYS):
            continue
        key = f"deadline:{e.ref_id}:{due}"
        if key in seen:
            continue
        seen.add(key)
        who = _short(session, e.ref_id)
        owner_name = _owner_of(session, [l.id for l in session.scalars(select(PoLine).where(PoLine.identity_id == e.ref_id).limit(200))])
        if closure is not None:
            item, ctx = _closure_item(session, e, closure, key, who, due, owner_name)
            out.append((item, ctx))
            continue
        if forwarding:
            old = re.search(r"the old (\S+) addresses", e.detail)
            new = re.search(r"[\w.+-]+@[\w.-]+", session.scalar(select(Message.body).where(Message.id == e.message_id)) or "")
            item = _item(session, key, "deadline", "low" if left > 30 else "medium", f"{who}: the old {old.group(1) if old else ''} addresses forward only until {md(due)}",
                         owner=owner_name, at_stake=None, act_by=due, category="Quote & risk",
                         next_action=f"Send orders to {new.group(0) if new else 'the new address'} from now on, and update the contact on every open order and quote before {md(due)}",
                         refs=[ref("supplier", e.ref_id, who), ref("message", e.message_id)])
            out.append((item, dict(event=e)))
            continue
        if "revised delivery dates" in e.detail:
            stake = unknown("the revised delivery dates", f"{who} has promised new dates for its stuck lines by this day; until then no build can be re-planned", "supplier",
                            "What are the revised dates and what can still ship, per PO line?", [ref("supplier", e.ref_id)])
            title = f"{who} promised revised delivery dates by {md(e.date_to)}: chase if they do not come"
            nxt = f"If nothing arrives by {md(e.date_to)}, call {suppliers.contact_on_file(session, e.ref_id).name or who} and ask what it can still ship"
        else:
            rise = session.scalar(select(MessageEvent.date_from).where(MessageEvent.message_id == e.message_id, MessageEvent.kind == "price_change"))
            covers = re.search(r"delivery by (\d{4}-\d{2}-\d{2})", e.detail or "")
            stake, title = _price_lock_cost(session, e.ref_id, e), f"{who} price rise{f' from {md(rise)}' if rise else ''}: orders acknowledged by {md(e.date_to)} keep today's price" + (f" on deliveries to {md(covers.group(1))}" if covers else "")
            nxt = f"Place and get acknowledged the orders you need before {md(e.date_to)}; the old price holds for the delivery date in the notice"
        sev = "high" if left <= 7 else "medium" if left <= 21 else "low"
        item = _item(session, key, "deadline", sev, title, owner=owner_name, at_stake=stake, act_by=e.date_to, next_action=nxt,
                     refs=[ref("supplier", e.ref_id, who), ref("message", e.message_id)])
        if "revised delivery dates" in e.detail:  # a promise by a date: nothing to chase before it
            item = item.model_copy(update={"waits_until": e.date_to})
        out.append((item, dict(event=e)))
    return out


# --- the chase ------------------------------------------------------------------------------------------------------

RISKY = ("past_due", "after_build", "short", "disrupted", "undated", "short_after_stock")


def _word_on(session: Session) -> tuple[set[str], set[str]]:
    """(PO lines, PO numbers) that any supplier message or notice mentions outside quoted text."""
    from sqlalchemy import text

    lines = {r[0] for r in session.execute(text("select ref_id from message_refs where ref_type = 'po_line' and quoted = 0"))}
    lines |= {r[0] for r in session.execute(text("select ref_id from message_events where ref_type = 'po_line'"))}
    pos = {r[0] for r in session.execute(text("select ref_id from message_refs where ref_type = 'po' and quoted = 0"))}
    return lines, pos


def _chase(session: Session) -> list[tuple[ActionItem, dict]]:
    """One row for the open lines past due that nobody has said a word about: no revision, no notice, no message. Lines that are stale, under a
    force-majeure notice or revised by the supplier have their own rows or states. Ranked by whether the line feeds a build that is not covered, then by value."""
    from app.domain.phases import service as phases

    said_lines, said_pos = _word_on(session)
    # a supplier that has told us when it can and cannot ship (a closure or a force-majeure notice) has not gone silent
    spoke = set(session.scalars(select(MessageEvent.ref_id).where(MessageEvent.kind.in_(("closure", "force_majeure")), MessageEvent.ref_type == "supplier")))
    rows = [s for s in orders.past_due(session) if not s.disrupted_by and not s.revised_promise and s.po_line.id not in said_lines
            and session.get(PoLine, s.po_line.id).po_number not in said_pos and s.supplier.id not in spoke]
    if not rows:
        return []
    risk: dict[str, str] = {}
    for b in phases.builds(session):
        full = phases.build_readiness(session, b.product.id, b.month)
        for g in full.groups:
            for p in g.parts:
                if p.state in RISKY:
                    risk.setdefault(p.part.id, f"{b.product.label} {month_name(b.month)}")
    rows.sort(key=lambda s: (s.part.id not in risk, -float(s.open_value.usd or 0), s.po_line.id))
    lines = {l.id: l for l in session.scalars(select(PoLine).where(PoLine.id.in_([s.po_line.id for s in rows])))}
    owner_of = {s.po_line.id: buyer_name(session, lines[s.po_line.id].buyer_id) for s in rows}
    total = sum(float(s.open_value.usd) for s in rows if s.open_value.usd is not None)
    by_value: dict[str, float] = {}
    for s in rows:
        by_value[owner_of[s.po_line.id]] = by_value.get(owner_of[s.po_line.id], 0.0) + float(s.open_value.usd or 0)
    top = max(rows, key=lambda s: float(s.open_value.usd or 0))
    first = rows[0]
    pv = prov("computed", "po_lines", rule="open value of the lines past due that no supplier message mentions", inputs=[s.po_line for s in rows], by="attention.chase")
    sup = lambda s: _short(session, lines[s.po_line.id].identity_id)  # noqa: E731
    item = _item(session, "deadline:chase", "deadline", "medium",
                 f"{count(len(rows), "line")} past due with no word from the supplier: {_fmt(total)} open; largest {sup(top)} {_fmt(float(top.open_value.usd))} ({owner_of[top.po_line.id].split()[0]})",
                 owner=" · ".join(sorted(by_value, key=by_value.get, reverse=True)), at_stake=usd(total, pv), act_by=None,
                 next_action=f"Chase the largest first: ask {sup(first)} for a ship date on {first.po_line.id}", refs=[ref("part", pid) for pid in list(dict.fromkeys(s.part.id for s in rows))[:3]])
    return [(item, dict(chase=rows, owners=owner_of, risk=risk, top=top, parts=list(dict.fromkeys(s.part.id for s in rows))))]


def _deadline_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    if "chase" in ctx:
        rows = ctx["chase"]
        nums = [Number(id=f"chase:{s.po_line.id}", value=s.open_value,
                       label=f"{s.po_line.id} {s.part.id}: {_short(session, session.get(PoLine, s.po_line.id).identity_id)}, {days_text(s.days_past_due)} past due, {ctx['owners'][s.po_line.id].split()[0]}"
                             + (f", feeds {ctx['risk'][s.part.id]}" if s.part.id in ctx["risk"] else "") + ", no message mentions it") for s in rows]
        ids = {s.po_line.id for s in rows}
        top = ctx["top"]
        head = [Number(id="chase:count", label="Lines past due with no word from the supplier", value=qty(len(rows), "lines", prov("computed", "po_lines", rule="open lines past due that no message mentions", inputs=[s.po_line for s in rows], by="attention.chase"))),
                Number(id="chase:open_total", label="Open value of those lines", value=item.at_stake),
                Number(id="chase:largest", label=f"Largest line: {top.po_line.id}, {_short(session, session.get(PoLine, top.po_line.id).identity_id)}", value=top.open_value)]
        nums = head + nums
        return ActionItemDetail(**item.model_dump(), finding=f"{count(len(rows), "open line")} are past due and no supplier message, notice or revision mentions them. Lines that feed a build that is not covered come first, then by value.",
                                numbers=nums, unknowns=[], evidence=[ref("part", pid) for pid in ctx["parts"]], po_lines=[l for l in orders.open_orders(session, None) if l.ref.id in ids])
    if "rest" in ctx:
        nums = [Number(id=f"act_by:{i.key}", label=i.title, value=DateValue(date=i.act_by, provenance=prov("extracted", "offers", row=i.key))) for i, _ in ctx["rest"]]
        return ActionItemDetail(**item.model_dump(), finding=f"{len(ctx['rest'])} quotes lapse between {md(item.act_by)} and {md(max(i.act_by for i, _ in ctx['rest']))}. Each can be re-quoted higher after it lapses.",
                                numbers=nums, unknowns=[], evidence=item.refs)
    if "offer" in ctx:
        o = ctx["offer"]
        nums = [Number(id="act_by", label="Quote valid until", value=DateValue(date=o.validity_date, provenance=prov("extracted", f"message:{o.message_id}", row=o.line_ref))),
                Number(id=f"{ctx['stake']['kind']}:{o.quote_no}", label="What lapsing costs (next-best price - quoted price) x the 12-month requirement" if ctx["stake"]["kind"] == "lapse_cost"
                       else "Planned buys the quoted prices lapse on (lowest quoted price x the 12-month requirement): not a loss", value=item.at_stake),
                Number(id=f"spend_covered:{o.quote_no}", label="Planned buys priced by the quote", value=usd(ctx["stake"]["spend"], prov("computed", "offers", rule="spend_covered: lowest quoted unit price x the 12-month requirement")))]
        risk_said, alternatives = _supplier_risk_context(session, o.identity_id, list(ctx["parts"]))
        return ActionItemDetail(**item.model_dump(), finding=f"{_short(session, o.identity_id)}'s {_noun(session, ctx['parts'])} quote prices {count(len(ctx['parts']), 'part')} and lapses {md(o.validity_date)}, {item.days_left} days after {md(AS_OF.isoformat())}: the quoted prices lapse with it, and it can be re-quoted higher." + risk_said,
                                numbers=nums, unknowns=([item.at_stake] if isinstance(item.at_stake, Unknown) else []) + alternatives, evidence=item.refs, messages=[m for m in inbox.list_messages(session) if m.ref.id == o.message_id])
    if "closure" in ctx:
        e, c, lines, late = ctx["event"], ctx["closure"], ctx["lines"], ctx["late"]
        who = _short(session, e.ref_id)
        nums = [Number(id="act_by", label="Act by" + (" (its last shipment before the closure)" if e.kind == "deadline" else " (the first closed day)"), value=DateValue(date=item.act_by, provenance=prov("extracted", f"message:{e.message_id}", row=e.line_ref or c.line_ref))),
                Number(id="closed_from", label="Closed from", value=DateValue(date=c.date_from, provenance=prov("extracted", f"message:{c.message_id}", row=c.line_ref))),
                Number(id="closed_to", label="Closed through", value=DateValue(date=c.date_to, provenance=prov("extracted", f"message:{c.message_id}", row=c.line_ref)))]
        if item.at_stake is not None:
            nums.append(Number(id=f"closure_open_value:{e.ref_id}", label=f"Open value of {who}'s lines due by {md(c.date_to)}", value=item.at_stake))
        finding = (f"{who} is closed {md(c.date_from)} to {md(c.date_to)} ({c.detail.split('; ', 1)[1] if '; ' in c.detail else 'no dates for shipments are given'}). "
                   + (f"{count(len(lines), 'open line')} fall due by {md(c.date_to)}" + (f", {len(late)} of them already late" if late else "") + ". " if lines else "No open line falls due in the closure. ")
                   + f"{item.days_left} days left at {AS_OF}.")
        open_lines = {l.ref.id: l for l in orders.open_orders(session)}
        return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=[], evidence=item.refs, po_lines=[open_lines[s.po_line.id] for s in lines if s.po_line.id in open_lines],
                                messages=[m for m in inbox.list_messages(session) if m.ref.id == e.message_id])
    e: MessageEvent = ctx["event"]
    finding = f"{e.detail.capitalize()} (message of {session.get(Message, e.message_id).date}). {item.days_left} days left at {AS_OF}."
    stock: list[Unknown] = []
    nums = [Number(id="act_by", label="Act by", value=DateValue(date=e.date_to, provenance=prov("extracted", f"message:{e.message_id}", row=e.line_ref)))]
    for pc in session.scalars(select(MessageEvent).where(MessageEvent.message_id == e.message_id, MessageEvent.kind == "price_change")):      # each announced rise, per what it applies to, as a percentage with the line it came from
        for pct, words in re.findall(r"([+-]?\d+(?:\.\d+)?)%\s+([^,;]+?)(?=,|;|\sfrom\b|$)", pc.detail or ""):
            slug = re.sub(r"[^a-z0-9]+", "_", words.lower()).strip("_")
            nums.append(Number(id=f"price_increase_pct:{slug}", label=f"Announced price rise on {words.strip()}", value=qty(float(pct), "%", prov("extracted", f"message:{e.message_id}", row=pc.line_ref, raw=f"{pct}% {words.strip()}"))))
    if "keep today's price" in (e.detail or ""):      # a price lock: how much to place before it depends on what is already on the shelf
        ours = sorted({p for p, in session.execute(select(PoLine.part_number).where(PoLine.identity_id == e.ref_id)).all() if demand.requirements(session, p)})[:8]
        stock = _stock_questions(session, ours, "the data has no inventory, so how much to place before the price rises cannot be sized") if ours else []
        rise_from = session.scalar(select(MessageEvent.date_from).where(MessageEvent.message_id == e.message_id, MessageEvent.kind == "price_change"))
        if rise_from and e.date_to and e.date_to < rise_from:      # the lock closes before the rise starts: the notice does not say what an order in between pays
            who = _short(session, e.ref_id)
            stock.append(unknown("which price an order placed between the lock date and the rise date pays",
                                 f"the notice protects orders placed and acknowledged by {md(e.date_to)}, but the rise starts {md(rise_from)}; it does not say what an order placed in between pays, so the real deadline is unknown",
                                 _buyer_first(session, ours[0]) if ours else _owner_of(session, []),
                                 f"Orders placed {md(e.date_to)} to {md(rise_from)}: the current price or the new one? Ask {suppliers.contact_on_file(session, e.ref_id).name or who}.", [ref("supplier", e.ref_id, who)]))
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums,
                            unknowns=([item.at_stake] if isinstance(item.at_stake, Unknown) else []) + stock, evidence=item.refs,
                            messages=[m for m in inbox.list_messages(session) if m.ref.id == e.message_id])


# --- the tariff -----------------------------------------------------------------------------------------------------

def _cond(e) -> float:
    """The duty on a part's open orders that is owed only if they ship late (in transit), 0 when none."""
    return float(e.conditional.usd) if e.conditional else 0.0


def _tariff_items(session: Session, exposures=None) -> tuple[list[tuple[ActionItem, dict]], list[tuple[ActionItem, dict]]]:
    """One row for the whole tariff (tranche 1: 25% from Nov 1), with the per-part breakdown in its detail. Each part with a duty is also
    resolvable on its own key (`tariff:<part>`), which is what the Tariff analyst works one at a time."""
    every = [e for e in (exposures or tariffs.all_exposures(session)) if e.status == "china_listed"]
    exps = [e for e in every if float(e.net.usd) > 0 or e.conditional]   # parts with a duty owed, or owed if their orders ship late, get their own item
    contact = {r.tranche: r.exclusion_contact_by for r in session.scalars(select(TariffRule))}
    desc = {p.part_number: p.description for p in session.scalars(select(Part))}
    children = []
    for e in sorted(exps, key=lambda e: -(float(e.net.usd) + _cond(e))):
        net, pid = float(e.net.usd), e.part.id
        cond = _cond(e)
        figure = (f"{_fmt(net)} owed" + (f", {_fmt(cond)} more if open orders ship late" if cond else "")) if net else f"{_fmt(cond)} owed only if open orders ship late"
        sup = session.get(Part, pid).preferred_identity_id
        who = session.get(SupplierIdentity, sup).name if sup else "the supplier"
        item = _item(session, f"tariff:{pid}", "tariff", "high" if net + cond >= 100_000 else "medium" if net + cond >= TARIFF_ITEM_MIN else "low",
                     f"{pid}: new duty from {md(e.effective_date)}, {figure}",
                     owner=buyer_name(session, session.get(Part, pid).buyer_id), at_stake=e.net if net else e.conditional, gross=e.gross, act_by=contact.get(e.tariff.rule.tranche),
                     next_action=f"Confirm origin and code with {who}; compare pulling in before {md(e.effective_date)}, re-sourcing, or proof of origin",
                     refs=[ref("part", pid, desc[pid]), ref("tariff_rule", str(e.tariff.rule.id))] + ([ref("supplier", sup)] if sup else []))
        children.append((item, dict(exposure=e)))
    t1 = [e for e in exps if e.tariff.rule.tranche == 1]
    if not t1:
        return [], children
    r1 = next(r for r in session.scalars(select(TariffRule)) if r.tranche == 1)
    net = sum(float(e.net.usd) for e in t1)
    cond_total = sum(_cond(e) for e in t1)
    gross = sum(float(e.gross.usd) for e in every if e.tariff.rule.tranche == 1)
    pv = prov("computed", "po_lines", rule="sum of tranche-1 parts' duty owed / gross duty: " + tariffs.rule_sentences(r1)["owed"], inputs=[e.part for e in every if e.tariff.rule.tranche == 1], by="attention.tariff")
    top = sorted(t1, key=lambda e: -float(e.net.usd))
    owners: dict[str, float] = {}
    for e in t1:
        o = buyer_name(session, session.get(Part, e.part.id).buyer_id)
        owners[o] = owners.get(o, 0.0) + float(e.net.usd)
    ranked = sorted(owners, key=owners.get, reverse=True)
    mine = {o: [e.part.id for e in top if buyer_name(session, session.get(Part, e.part.id).buyer_id) == o][:2] for o in ranked}
    share = {o: round(100 * owners[o] / net) for o in ranked}
    who = "; ".join(f"{o.split()[0]}: {', '.join(mine[o])} ({share[o]}% of the net)" for o in ranked)
    item = _item(session, "tariff:all", "tariff", "high", f"New {r1.rate:.0%} duty on China-origin parts from {md(r1.effective_date)}: {_fmt(net)} owed" + (f", {_fmt(cond_total)} more if open orders ship late" if cond_total else ""), owner=" · ".join(ranked), at_stake=usd(net, pv), gross=usd(gross, pv),
                 act_by=contact.get(1), next_action=f"{who}. Each: confirm origin, then compare pulling in before {md(r1.effective_date)}, re-sourcing, or proof of origin",
                 refs=[e.part for e in top[:12]])
    return [(item, dict(rollup=True, exposures=exps, every=every))], children


def _supplier_risk_context(session: Session, ident: str, parts: list[str]) -> tuple[str, list[Unknown]]:
    """For a quote from a supplier with a serious warning that is the only source of a quoted part: the warning in words (with what it was read from) and, per such part, the
    open question of who else could supply it, owned by the part's buyer."""
    flags = [f for f in supplier_risk.risk_flags(session, ident) if f.severity == "high"]
    sole = [p for p in supplier_risk.sole_source_parts(session, ident) if p in parts]
    if not flags or not sole:
        return "", []
    who = _short(session, ident)
    said = " Risk on the supplier: " + "; ".join(f.text + (f" ({f.evidence})" if f.kind == "insolvency" and f.evidence else "") for f in flags) + "."
    asks = [unknown(f"alternative source for {p}", f"{who} is the only company that has supplied {p}, and {flags[0].text[:1].lower() + flags[0].text[1:]}", _buyer_first(session, p),
                    f"Which other supplier can quote {p}, and by when?", [ref("part", p), ref("supplier", ident, who)]) for p in sole]
    return said, asks


def _named_unknowns_for_part(session: Session, e) -> list[Unknown]:
    """What a buyer must still ask about a duty-listed part, named with its owner: whether goods left in time (the notice's in-transit clause applies to lines whose ship
    date is the unknown, or that wait on a supplier's restart) and the origin papers of a new source that claims another origin than the part's own."""
    out: list[Unknown] = []
    pn, rule = e.part.id, e.tariff.rule
    owner = _buyer_first(session, pn)
    lines = [l for l in e.open_lines if l.bucket == "conditional"]      # only a line whose outcome rests on the clause: owed lines (a supplier that cannot ship before the date) and exempt ones are settled
    if rule.exported_before and lines:
        out.append(unknown("in-transit status", f"the notice exempts goods exported before {md(rule.exported_before)} and entered before {md(rule.entered_before)}; whether any of these {count(len(lines), 'line')} left in time is not in the data",
                           owner, f"Did any of {', '.join(l.po_line.id for l in lines[:4])} ship before {md(rule.exported_before)}?", [l.po_line for l in lines[:6]]))
    part = session.get(Part, pn)
    for o in session.scalars(select(Offer).where(Offer.part_number == pn, Offer.superseded_by.is_(None), Offer.trust != "blocked")):
        if o.origin_claim and part.coo == "CN" and not o.origin_claim.lower().startswith("china"):
            out.append(unknown(f"origin documentation for {o.supplier_name}'s quote", f"{o.supplier_name} claims {o.origin_claim} origin" + (f" ({o.conditions.strip().rstrip('.')})" if o.conditions else "")
                               + "; the broker decides by substantial transformation and the papers are not in the data",
                               owner, f"Can {o.supplier_name} show where {pn} is made and where its parts come from, so the broker can rule on its origin?", [ref("part", pn), ref("message", o.message_id)]))
            break
    return out


def _fire_owed_numbers(session: Session, t1, rule) -> list[Number]:
    """The same figure as a number the agent can cite (plan-13 item 8): the duty owed on a burned supplier's open orders, which cannot ship before the duty date."""
    by_notice: dict[str, list] = {}
    for e in t1:
        for l in e.open_lines:
            if l.under_force_majeure and l.bucket == "owed":
                by_notice.setdefault(l.under_force_majeure.id, []).append((e, l))
    out = []
    for mid, rows in sorted(by_notice.items()):
        m = session.get(Message, mid)
        if not (m and m.identity_id and tariffs.restart_window(session, m.identity_id)):
            continue
        out.append(Number(id=f"duty_owed_fire:{m.identity_id}", label=f"Owed on {_short(session, m.identity_id)}'s {count(len(rows), 'open order')} under force majeure: they cannot ship before {md(rule.effective_date)}",
                          value=usd(sum(float(l.open_value.usd) * e.rate for e, l in rows), prov("computed", "po_lines", rule="25% of the open value of the supplier's lines under the notice, whose restart is after the duty date",
                                                                                                 inputs=[l.po_line for _, l in rows], by="attention.tariff"))))
    return out


def _owner_share_numbers(session: Session, t1, rule) -> list[Number]:
    """Each buyer's share of the duty owed, split into what cannot be avoided (a burned supplier's open orders, which cannot ship before the duty date)
    and what still depends on ship dates or origin proof (BUYER Q6: 'how much of my duty share can I still avoid?'). Code figures the agent cites."""
    share: dict[str, float] = {}
    fixed: dict[str, float] = {}
    for e in t1:
        o = buyer_name(session, session.get(Part, e.part.id).buyer_id)
        share[o] = share.get(o, 0.0) + float(e.net.usd)
        for l in e.open_lines:
            if l.under_force_majeure and l.bucket == "owed":
                m = session.get(Message, l.under_force_majeure.id)
                if m and m.identity_id and tariffs.restart_window(session, m.identity_id):
                    fixed[o] = fixed.get(o, 0.0) + float(l.open_value.usd) * e.rate
    out = []
    for o in sorted(share, key=share.get, reverse=True):
        first = o.split()[0]
        pv = prov("computed", "po_lines", rule=f"sum of the duty owed on {first}'s parts (the parts' buyer)", inputs=[e.part for e in t1], by="attention.tariff")
        out.append(Number(id=f"duty_share:{first}", label=f"{first}'s share of the duty owed", value=usd(share[o], pv)))
        if fixed.get(o):
            out.append(Number(id=f"duty_share_fixed:{first}", label=f"Of {first}'s share, owed on lines under force majeure that cannot ship before {md(rule.effective_date)}", value=usd(fixed[o], pv)))
            out.append(Number(id=f"duty_share_open:{first}", label=f"Of {first}'s share, what still depends on ship dates or origin proof", value=usd(share[o] - fixed[o], pv)))
    return out


def _fire_in_owed(session: Session, t1, rule) -> str:
    """The part of the owed that is a burned supplier's open orders: its notice puts the restart after the duty date, so nothing ships before it. Read from the notice, named."""
    by_notice: dict[str, list] = {}
    for e in t1:
        for l in e.open_lines:
            if l.under_force_majeure and l.bucket == "owed":
                by_notice.setdefault(l.under_force_majeure.id, []).append((e, l))
    out = []
    for mid, rows in by_notice.items():
        m = session.get(Message, mid)
        rw = tariffs.restart_window(session, m.identity_id) if m and m.identity_id else None
        if not rw:
            continue
        duty = sum(float(l.open_value.usd) * e.rate for e, l in rows)
        who = _short(session, m.identity_id)
        out.append(f"{_fmt(duty)} of the owed is {who}'s {count(len(rows), 'open order')} under force majeure: its notice of {md(rw[2])} puts the earliest restart on {md(rw[0])}, so the supplier cannot ship before {md(rule.effective_date)}. ")
    return "".join(out)


def _tariff_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    if ctx.get("rollup"):
        exps = ctx["exposures"]
        t1 = sorted([e for e in exps if e.tariff.rule.tranche == 1], key=lambda e: -float(e.net.usd))
        t2 = [e for e in exps if e.tariff.rule.tranche == 2]
        nums = [Number(id=f"duty_net:{e.part.id}", label=f"{e.part.id}", value=e.net) for e in t1]
        rates = {r.tranche: r for r in session.scalars(select(TariffRule))}
        r1, r2 = rates[1], rates.get(2)
        t2_label = f"Tranche 2 ({r2.rate:.0%} from {md(r2.effective_date)})" if r2 else "Tranche 2"
        nums += [Number(id=f"rate:t{t}", label=f"Duty rate, tranche {t} (from {md(r.effective_date)})", value=qty(round(r.rate * 100, 4), "%", prov("stated", "tariff_rules", row=str(r.id), raw=f"{r.rate:.0%}", rule="the advisory's rate")))
                 for t, r in sorted(rates.items())]
        cond1 = sum(_cond(e) for e in t1)
        ifc_total = sum(float(x.net.usd) for x in tariffs.all_exposures(session) if x.status == "unknown_origin")
        tiles = [Number(id="tile:owed", label="Owed", value=item.at_stake),
                 Number(id="tile:if_late", label="Owed only if the open orders ship late", value=usd(cond1, prov("computed", "po_lines", rule=tariffs.rule_sentences(r1)["conditional"], inputs=[e.part for e in t1 if e.conditional], by="attention.tariff"))),
                 Number(id="tile:if_china", label="Owed if the parts with no recorded origin are China-origin", value=usd(ifc_total, prov("computed", "po_lines", rule=tariffs.rule_sentences(r1)["if_china"], inputs=[x.part for x in tariffs.all_exposures(session) if x.status == "unknown_origin"], by="attention.tariff")))]
        if item.act_by:
            tiles.append(Number(id="tile:act_by", label="Act by (the broker's cut-off to discuss exclusions)", value=DateValue(date=item.act_by, provenance=prov("extracted", "tariff_rules", rule="the advisory's exclusion-request cut-off"))))
        nums = tiles + _fire_owed_numbers(session, t1, r1) + _owner_share_numbers(session, t1, r1) + nums
        if cond1:
            nums.append(Number(id="duty_conditional:tranche1", label="Tranche 1 owed only if the open orders ship late", value=usd(cond1, prov(
                "computed", "po_lines", rule=tariffs.rule_sentences(r1)["conditional"], inputs=[e.part for e in t1 if e.conditional], by="attention.tariff"))))
        nums += [Number(id="duty_gross:tranche1", label="Tranche 1 gross (every open line and the full 12-month forecast)", value=item.at_stake_gross),
                 Number(id="duty_net:tranche2", label=f"{t2_label}, owed", value=usd(sum(float(e.net.usd) for e in t2), prov("computed", "po_lines", rule="sum of tranche-2 parts' net duty", inputs=[e.part for e in t2]))),
                 Number(id="duty_gross:tranche2", label="Tranche 2, gross", value=usd(sum(float(e.gross.usd) for e in ctx["every"] if e.tariff.rule.tranche == 2), prov("computed", "po_lines", rule="sum of tranche-2 parts' gross duty", inputs=[e.part for e in t2])))]
        passed = sum(float(e.pass_through.usd) for e in exps if e.pass_through)
        sent = tariffs.rule_sentences(r1)
        owed1, cond1, gross1 = float(item.at_stake.usd), sum(_cond(e) for e in t1), float(item.at_stake_gross.usd)
        ifc = sum(float(x.net.usd) for x in tariffs.all_exposures(session) if x.status == "unknown_origin")      # parts of unknown origin, under either tranche
        finding = (f"The broker's advisory {r1.advisory_no or ''} (issued {md(r1.issued)}) puts {r1.rate:.0%} on China-origin goods entered from {md(r1.effective_date)}"
                   + (f" and {r2.rate:.0%} from {md(r2.effective_date)}" if r2 else "") + f". Its row for the first tranche reads: \"{r1.source_line}\". "
                   f"Owed {_fmt(owed1)}: {sent['owed']} " + (f"Conditional {_fmt(cond1)}: {sent['conditional']} " if cond1 else "") + (f"If China {_fmt(ifc)}: {sent['if_china']} " if ifc else "")
                   + _fire_in_owed(session, t1, r1) + f"Gross {_fmt(gross1)} counts every open line and the whole 12-month need: the ceiling, not the figure to act on. "
                   f"The largest owed are {', '.join(e.part.id for e in t1[:5])}. " + (f"{t2_label} adds {_fmt(sum(float(e.net.usd) for e in t2))} owed. " if r2 and t2 else "")
                   + (f"Another {_fmt(passed)} is paid by DDP suppliers and will appear in their prices. " if passed else "") + "Open a part for its origin, code and the lines behind each figure.")
        unknowns = []
        if cond1 and r1.exported_before:
            held = [e for e in t1 if e.conditional]
            unknowns.append(unknown("whether the conditional orders ship before the duty date", f"the ship date decides whether a conditional order owes the duty, and no ship date is in the data",
                                    buyer_of_part(session, held[0].part.id), f"Will the open orders due in the window or with no date ship before {md(r1.exported_before)}?", [e.part for e in held[:6]]))
        open_lines = {l.ref.id: l for l in orders.open_orders(session)}
        lines = [open_lines[l.po_line.id] for e in t1[:4] for l in e.open_lines if l.po_line.id in open_lines]
        return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=unknowns, evidence=item.refs, po_lines=lines)
    e = ctx["exposure"]
    open_lines = {l.ref.id: l for l in orders.open_orders(session)}
    lines = [open_lines[l.po_line.id] for l in e.open_lines if l.po_line.id in open_lines]
    n = [Number(id=f"rate:t{e.tariff.rule.tranche}", label=f"Duty rate, tranche {e.tariff.rule.tranche} (from {md(e.effective_date)})",
                value=qty(round(e.rate * 100, 4), "%", prov("stated", "tariff_rules", row=str(e.tariff.rule.id), raw=f"{e.rate:.0%}", rule="the advisory's rate", inputs=[ref("tariff_rule", str(e.tariff.rule.id))]))),
         Number(id=f"duty_net:{e.part.id}", label="New duty owed (what to act on)", value=e.net),
         Number(id=f"duty_gross:{e.part.id}", label="New duty, gross (every open line and the full 12-month forecast)", value=e.gross)]
    if e.reference_price:
        n.append(Number(id=f"reference_price:{e.part.id}", label="Price used for demand with no order yet (latest clean PO line)", value=e.reference_price))
    n.append(Number(id=f"uncovered_qty:{e.part.id}", label="12-month requirement not covered by open supply",
                    value=qty(e.uncovered_qty, "EA", prov("computed", "demand_forecast", rule="12-month need (robots planned times the parts each one needs) minus what is already on order", by="attention.tariff", inputs=[e.part]))))
    rule, sent = e.tariff.rule, e.rule_sentences
    why = "; ".join(f"{l.po_line.id}: {l.why.split('. ')[0]}" for l in e.open_lines[:6])
    finding = (f"{e.part.id} is of China origin on tariff code {session.get(Part, e.part.id).hts}. The advisory row that covers it reads: \"{rule.source_line}\" ({rule.advisory_no or 'advisory'}, issued {md(rule.issued)}). "
               f"Owed {_fmt(float(e.net.usd))}: {sent['owed']} " + (f"Conditional {_fmt(_cond(e))}: {sent['conditional']} " if _cond(e) else "") + f"Gross {_fmt(float(e.gross.usd))}. Lines: {why}."
               + (" Duty on DDP lines is paid by the supplier and passed through in the price." if e.pass_through else ""))
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=n, unknowns=_named_unknowns_for_part(session, e), evidence=item.refs, po_lines=lines)


# --- the unanswerable -----------------------------------------------------------------------------------------------

def _unknown_children(session: Session, exposures=None) -> list[tuple[ActionItem, dict]]:
    out = []
    exps = exposures or tariffs.all_exposures(session)
    contact = min((r.exclusion_contact_by for r in session.scalars(select(TariffRule)) if r.exclusion_contact_by), default=None)
    for e in exps:
        if e.status not in ("unknown_origin", "unknown_hts"):
            continue
        p = session.get(Part, e.part.id)
        if e.status == "unknown_hts" and p.coo != "CN":
            continue  # a blank code matters only where the part could owe the China duty
        owner = buyer_name(session, p.buyer_id)
        what = "country of origin" if e.status == "unknown_origin" else "HTS code"
        title = f"{p.part_number}: {what} unknown" + (f" ({_fmt(float(e.net.usd))} if China)" if e.net is not None and e.status == "unknown_origin" else "")
        item = _item(session, f"unknown:{p.part_number}", "unknown", "medium" if (e.net is not None and float(e.net.usd) >= 50_000) else "low", title, owner=owner, at_stake=e.unknown,
                     act_by=contact, next_action=f"Ask {session.get(SupplierIdentity, p.preferred_identity_id).name if p.preferred_identity_id else 'the supplier'} for a certificate of origin" if e.status == "unknown_origin"
                     else "Ask the supplier or the customs broker for the HTS classification", refs=[ref("part", p.part_number, p.description)])
        out.append((item, dict(exposure=e, part=p)))
    for s in orders.past_due(session, include_stale=True):
        if not s.stale:
            continue
        l = session.get(PoLine, s.po_line.id)
        owner = buyer_name(session, l.buyer_id)
        u = unknown("whether this order is still open", f"ordered {md(l.order_date, True)}, promised {md(l.promised_date, True)}, {days_text(s.days_past_due)} past due: it may have been delivered or cancelled and never closed", owner.split()[0],
                    f"Was {l.id} ({l.part_number}) delivered, cancelled, or is it really still open?", [s.po_line, s.part])
        item = _item(session, f"unknown:{l.id}", "unknown", "low", f"{l.id}: open since {month_year(l.order_date)}, {days_text(s.days_past_due)} past due: probably not really open",
                     owner=owner, at_stake=u, next_action="Confirm with the supplier or receiving, then close or cancel it in the ERP", refs=[s.po_line, s.part, s.supplier], category="Purchasing")
        out.append((item, dict(line=l, supply=s)))
    for s in orders.open_supply(session):
        if s.stale or s.promise is not None or s.disrupted_by:
            continue
        l = session.get(PoLine, s.po_line.id)
        owner = buyer_name(session, l.buyer_id)
        value = float(s.open_value.usd) if s.open_value.usd is not None else 0.0
        u = unknown("the promised date", f"{l.id} is open ({_fmt(value)}) and the ERP holds no promise date: it can never be late by date and no build can count on it",
                    owner.split()[0], f"What date has {_short(session, l.identity_id)} promised for {l.id} ({l.part_number})?", [s.po_line, s.part])
        item = _item(session, f"unknown:{l.id}", "unknown", "medium" if value >= 50_000 else "low", f"{l.id}: {_fmt(value)} open with no promised date",
                     owner=owner, at_stake=u, next_action="Ask the supplier for a promise date and enter it in the ERP", refs=[s.po_line, s.part, s.supplier], category="Purchasing")
        out.append((item, dict(line=l, supply=s, undated=True, money=value)))
    return out


def _unknown_items(session: Session, exposures=None) -> tuple[list[tuple[ActionItem, dict]], list[tuple[ActionItem, dict]]]:
    """Three rows (origin, tariff code, old orders), one per kind of gap, each listing its parts; every part or line is also resolvable on its own key."""
    kids = _unknown_children(session, exposures)
    kinds = {"origin": [k for k in kids if "country of origin" in k[0].title], "hts": [k for k in kids if "HTS code unknown" in k[0].title],
             "stale-orders": [k for k in kids if "line" in k[1] and not k[1].get("undated")],
             "undated": [k for k in kids if k[1].get("undated")]}
    labels = {"origin": ("country of origin unknown", "parts on the tariff list with no origin: the duty can neither be charged nor ruled out"),
              "hts": ("tariff code unknown", "China-origin parts with no tariff code: the duty cannot be computed"),
              "stale-orders": ("old orders probably not really open", "old orders still open; left out of supply and of the net duty"),
              "undated": ("open orders with no promised date", "open orders the ERP holds no promise date for: they can never be late by date and no build can count on them")}
    out = []
    for kind, members in kinds.items():
        if not members:
            continue
        owners: dict[str, int] = {}
        for it, _ in members:
            owners[it.owner] = owners.get(it.owner, 0) + 1
        owner = max(owners, key=owners.get)
        names = sorted(owners)
        lead, why = labels[kind]
        stake = unknown(lead, why, owner.split()[0], {"origin": "Where are these parts made? Ask each supplier for a certificate of origin.", "hts": "What is the HTS classification of each?",
                                                          "stale-orders": "Was each delivered, cancelled, or is it really still open?",
                                                          "undated": "What date has each supplier promised?"}[kind], [r for it, _ in members for r in it.refs][:12])
        money = sum(float(c["exposure"].net.usd) for _, c in members if "exposure" in c and c["exposure"].net is not None and c["exposure"].status == "unknown_origin")
        if kind == "undated":
            money = sum(c["money"] for _, c in members)
        title = (f"{len(members)} {lead}" if kind in ("stale-orders", "undated") else f"{count(len(members), "part")}: {lead}") + (f" ({_fmt(money)} {'open' if kind == 'undated' else 'if China'})" if money else "")
        item = _item(session, f"unknown:{kind}", "unknown", "medium" if money >= 50_000 else "low", title, owner=" · ".join(names), at_stake=stake,
                     act_by=min((it.act_by for it, _ in members if it.act_by), default=None), next_action={"origin": "Ask each supplier for a certificate of origin: ", "hts": "Ask the supplier or the customs broker for the HTS classification: ",
                                                                                         "stale-orders": "Confirm with the suppliers or receiving, then close or cancel in the ERP: ",
                                                                                         "undated": "Ask each supplier for a promise date and enter it in the ERP: "}[kind] + _by_owner([(it.owner, it.key.split(":", 1)[1]) for it, _ in members]),
                     refs=[r for it, _ in members for r in it.refs][:16], category="Purchasing" if kind in ("stale-orders", "undated") else "Quote & risk")
        out.append((item, dict(members=members, kind=kind, money=money)))
    return out, kids


def _unknown_detail(session: Session, item: ActionItem, ctx: dict) -> ActionItemDetail:
    if "members" in ctx:
        members = ctx["members"]
        nums = [Number(id=f"duty_if_china_net:{c['part'].part_number}", label=f"{it.title.split(':')[0]}: duty if the origin is China, net (not known: do not treat as a cost)", value=c["exposure"].net)
                for it, c in members if "exposure" in c and c["exposure"].net is not None and c["exposure"].status == "unknown_origin"]
        unk = [it.at_stake for it, _ in members if isinstance(it.at_stake, Unknown)]
        noun = "orders" if ctx["kind"] in ("stale-orders", "undated") else "parts"
        tiles = [Number(id="tile:count", label=f"How many {noun}", value=qty(len(members), noun, prov("computed", "po_lines" if noun == "orders" else "parts", rule="the members of this row", inputs=[r for r in item.refs[:50]], by="attention.unknown")))]
        if nums:
            tiles.append(Number(id="tile:if_china", label="Duty if every one of them is China-origin (not known: do not treat as a cost)", value=usd(sum(float(n.value.usd) for n in nums), prov("computed", "po_lines", rule="sum of each part's net duty if its origin is China", inputs=[r for r in item.refs[:50]], by="attention.unknown"))))
        if item.act_by:
            tiles.append(Number(id="tile:act_by", label="Act by", value=DateValue(date=item.act_by, provenance=prov("extracted", "tariff_rules", rule="the broker's cut-off to discuss exclusion requests"))))
        nums = tiles + nums
        finding = f"{len(members)} {'orders' if ctx['kind'] in ('stale-orders', 'undated') else 'parts'}: {item.at_stake.what}. {item.at_stake.why_it_blocks}. Shown as unknown, never as a cost; each has an owner."
        return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=unk, evidence=item.refs)
    if "line" in ctx:
        l, s = ctx["line"], ctx["supply"]
        if ctx.get("undated"):
            return ActionItemDetail(**item.model_dump(), finding=f"{l.id} ({l.part_number}) is open, {_fmt(ctx['money'])} of it, and the ERP holds no promise date. It can never show as late and no build can count on it: someone has to ask the supplier.",
                                    numbers=[Number(id=f"open_value:{l.id}", label="Open value", value=s.open_value)], unknowns=[item.at_stake], evidence=item.refs,
                                    po_lines=[x for x in orders.open_orders(session) if x.ref.id == l.id])
        return ActionItemDetail(**item.model_dump(), finding=f"{l.id} has been open since {md(l.order_date, True)} with nothing received. Treated as an unknown, not as supply: it is left out of open supply and of the net tariff figure.",
                                numbers=[Number(id=f"open_value:{l.id}", label="Value if it were really open", value=s.open_value)], unknowns=[item.at_stake], evidence=item.refs,
                                po_lines=[x for x in orders.open_orders(session) if x.ref.id == l.id])
    e, p = ctx["exposure"], ctx["part"]
    nums = []
    if e.status == "unknown_origin" and e.net is not None:
        nums = [Number(id=f"duty_if_china_net:{p.part_number}", label="New duty if the origin is China, net (not known: do not treat as a cost)", value=e.net),
                Number(id=f"duty_if_china_gross:{p.part_number}", label="New duty if the origin is China, gross (not known)", value=e.gross)]
    finding = (f"{p.part_number} is on tariff code {p.hts} ({e.rate:.0%} from {md(e.effective_date)}) but its country of origin is blank, so whether the duty applies cannot be computed. "
               f"Shown as unknown, never as a cost; the figures below hold only if the origin is China." if e.status == "unknown_origin"
               else f"{p.part_number} is of China origin but has no tariff code, so the duty cannot be computed. Ask for the classification.")
    open_lines = {l.ref.id: l for l in orders.open_orders(session)}
    return ActionItemDetail(**item.model_dump(), finding=finding, numbers=nums, unknowns=[e.unknown] if e.unknown else [], evidence=item.refs,
                            po_lines=[open_lines[l.po_line.id] for l in e.open_lines if l.po_line.id in open_lines])


# --- Today's words, robots and the viewer's slice --------------------------------------------------------------------

def _code(name: str) -> str:
    """'Alpha A1' -> 'A1': the short name a buyer uses for a robot."""
    return name.split()[-1]


def _robots_by_part(session: Session) -> dict[str, list[str]]:
    from app.domain.bom.service import robots_by_part

    return robots_by_part(session)


def _parts_named(session: Session, it: ActionItem, ctx: dict) -> list[str]:
    """The parts an item is about: its part refs, the parts on its PO lines, and the parts its detector worked from. A deadline that names no part stands for the
    named supplier's open lines. A held message names no part it can be trusted on, and aged orders are left out of supply, so neither touches a build."""
    if it.group == "trust" or it.key == "unknown:stale-orders":
        return []
    parts = [r.id for r in it.refs if r.type == "part"]
    lines = [r.id for r in it.refs if r.type == "po_line"]
    for k in ("parts", "sole"):
        parts += [p for p in ctx.get(k) or [] if isinstance(p, str)]
    parts += [e.part.id for e in ctx.get("exposures") or []]
    for k in ("slipped", "scope", "chase"):
        parts += [s.part.id for s in ctx.get(k) or []]
    for m, _ in (ctx.get("members") or []) + (ctx.get("rest") or []):
        parts += [r.id for r in m.refs if r.type == "part"]
        lines += [r.id for r in m.refs if r.type == "po_line"]
    if lines:
        parts += list(session.scalars(select(PoLine.part_number).where(PoLine.id.in_(lines))))
    if not parts and it.group == "deadline":
        sup = next((r.id for r in it.refs if r.type == "supplier"), None)
        parts = [s.part.id for s in orders.open_supply(session) if sup and s.supplier.id == sup and not s.stale]
    return list(dict.fromkeys(parts))


def _robots_of(session: Session, parts: list[str]) -> list:
    by_part = _robots_by_part(session)
    names = {p.part_number: p.name for p in session.scalars(select(Product))}
    ids = sorted({pid for p in parts for pid in by_part.get(p, [])})
    return [ref("product", pid, names.get(pid)) for pid in ids]


def _short_line(rows: list[RobotsShort]) -> str:
    """'182 T2 + 40 P5 short in Oct · 24 H1 in Nov': each month on its own, never summed."""
    out = []
    for n, m in enumerate(sorted({r.month for r in rows})):
        here = sorted((r for r in rows if r.month == m), key=lambda r: -r.robots)
        out.append(" + ".join(f"{r.robots} {_code(r.product.label or r.product.id)}" for r in here) + (" short in " if n == 0 else " in ") + month_name(m)[:3])
    return " · ".join(out)


def _codes_for(session: Session, families: list[str]) -> str:
    """['Beta', 'Alpha'] -> 'B1 and A1' (each family's short robot name); every robot -> 'all three' (or 'both', 'all 4')"""
    code = {p.family: _code(p.name) for p in session.scalars(select(Product))}
    return {2: "both", 3: "all three"}.get(len(code), f"all {len(code)}") if len(set(families)) == len(code) else _and([code.get(f, f) for f in families])


def _retitle(session: Session, it: ActionItem, title: str | None, summary: str | None) -> ActionItem:
    update: dict = {"summary": summary}
    if title and title != it.title:
        t = _cap(naming.namify(session, humanize(title)))
        update.update(title=t, title_entities=annotate.annotate(session, t, held=it.group == "trust"))
    return it.model_copy(update=update)


def _reword(session: Session, it: ActionItem, ctx: dict) -> ActionItem:
    """A row in a buyer's words (F45 Today): a short title and one line of facts under it. The detectors' own text (next action, the note, the detail) is unchanged."""
    k = it.key
    if k.startswith("disruption:") and ctx.get("slip"):
        dates = sorted(s.revised_promise for s in ctx["slipped"])
        first = ctx["first"]
        return _retitle(session, it, f"{ctx['who']} notice: {count(len(ctx['slipped']), 'PO line')} slip to {md(dates[0])} – {md(dates[-1])}; "
                        f"{_noun(session, ctx['by_month'][first])} short from {month_name(first)}", _short_line(it.robots_short))
    if k.startswith("disruption:"):
        return _retitle(session, it, it.title.replace(" builds short of ", " short of "),
                        " · ".join(x for x in (_short_line(it.robots_short), count(it.lines_in_scope, "line") if it.lines_in_scope else "") if x) or None)
    if k.startswith("incident:"):
        new = sorted(s.revised_promise for s in ctx["moved"])
        shift = sorted((date.fromisoformat(s.revised_promise) - date.fromisoformat(s.promise)).days for s in ctx["moved"])
        facts = ([f"{count(len(shift), 'line')} pushed out +{shift[0]}" + (f"–{shift[-1]}" if shift[-1] != shift[0] else "") + " d"] if shift else []) + ([f"{len(ctx['late'])} past due"] if ctx["late"] else [])
        return _retitle(session, it, f"{ctx['who']} {ctx['cause']}: {count(len(ctx['scope']), 'PO line')} late or moved" + (f" (new dates {md(new[0])} – {md(new[-1])})" if new else ""),
                        " · ".join(facts) or None)
    if k.startswith("consignment:"):
        return _retitle(session, it, None, (it.at_stake_note or "").split(";")[0].strip() or None)
    if k.startswith("risk:"):
        head, _, rest = it.title.partition(": ")
        lead = "don't prepay; " if rest.startswith("don't prepay; ") else ""
        first = session.get(Part, ctx["sole"][0])
        what = (f"{ctx['robots'][0]} " if len(ctx["robots"]) == 1 else "") + _head(first.description)
        m = re.search(r"(\d[\d,]*) a month for the", it.at_stake_note or "")
        fams = [r.label.split()[0] for r in _robots_of(session, [first.part_number]) if r.label]      # the robots this part goes into (BOM), not every robot the supplier serves
        return _retitle(session, it, f"{head}: {lead}secure the {what}",
                        f"sole source of {first.part_number}" + (f", {m.group(1)} a month for {_codes_for(session, fams)}" if m and fams else ""))
    if k.startswith("trust:"):
        msg = ctx["message"]
        if "bank_detail_change" in ctx["flags"]:
            who = _lookalike_of(session, msg)
            return _retitle(session, it, f"Bank-detail change from a look-alike {who} domain: do not pay" if who else None, "call back the contact on file")
        offer = session.scalar(select(Offer).where(Offer.message_id == msg.id, Offer.part_number.is_not(None)).order_by(Offer.id))
        return _retitle(session, it, None, " · ".join(x for x in (_short(session, msg.identity_id) if msg.identity_id else "", offer.part_number if offer else "") if x) or None)
    if k == "deadline:chase":
        top, owners = ctx["top"], ctx["owners"]
        who = _short(session, session.get(PoLine, top.po_line.id).identity_id)
        return _retitle(session, it, f"{count(len(ctx['chase']), 'past-due line')}, no updated promise", f"largest {who} {_fmt(float(top.open_value.usd))} ({owners[top.po_line.id].split()[0]})")
    if k == "deadline:quotes":
        rest = sorted(ctx["rest"], key=lambda x: x[0].act_by)
        spend = sum(c["stake"]["spend"] for _, c in rest)
        return _retitle(session, it, f"{len(rest)} quotes expiring: " + ", ".join(f"{_short(session, c['offer'].identity_id)} {md(c['offer'].validity_date)}" for _, c in rest),
                        f"{_fmt(spend)} of forecast demand on these quotes" if spend else None)
    if k.startswith("deadline:") and "event" in ctx:
        e = ctx["event"]
        if "forward only until" in (e.detail or ""):
            name, sep, rest = _short(session, e.ref_id).partition(" (formerly ")
            return _retitle(session, it, f"{name.split()[0] if sep else name}{sep}{rest}: old addresses forward only until {md(it.act_by)}", "update the supplier contact")
        m = re.match(r"(.+) price rise( from [^:]+)?: orders acknowledged by (.+?) keep today's price(?: on deliveries to (.+))?$", it.title)
        if m:
            return _retitle(session, it, f"{m.group(1)} price rise{m.group(2) or ''}: acknowledge orders by {m.group(3)} to keep today's price",
                            f"on deliveries to {m.group(4)}" if m.group(4) else None)
        return _retitle(session, it, None, it.at_stake_note)
    if k.startswith("deadline:"):
        return _retitle(session, it, None, it.at_stake_note)
    if k == "tariff:all":
        cond = sum(_cond(e) for e in ctx["exposures"] if e.tariff.rule.tranche == 1)
        return _retitle(session, it, it.title.split(":")[0], f"+{_fmt(cond)} if open orders ship late" if cond else None)
    if k.startswith("unknown:"):
        n, money, kind = len(ctx["members"]), ctx["money"], ctx["kind"]
        if kind == "origin":
            return _retitle(session, it, f"{count(n, 'part')} missing country of origin (COO)", f"+{_fmt(money)} duty if China" if money else None)
        if kind == "hts":
            return _retitle(session, it, f"{count(n, 'part')} missing HTS code", None)
        if kind == "undated":
            return _retitle(session, it, f"{count(n, 'open order')} with no promised date", f"{_fmt(money)} open" if money else None)
        pos: dict[str, list[str]] = {}
        for _, c in ctx["members"]:
            pos.setdefault(_short(session, c["line"].identity_id), []).append(c["line"].po_number)
        return _retitle(session, it, f"{count(n, 'aged open PO')}: confirm received or cancelled, then close",
                        " · ".join(f"{', '.join(dict.fromkeys(v))} ({who})" for who, v in pos.items()))
    return it


def _with_robots(session: Session, it: ActionItem, ctx: dict) -> ActionItem:
    return it.model_copy(update={"robots": _robots_of(session, _parts_named(session, it, ctx))})


def _chase_slice(session: Session, it: ActionItem, ctx: dict, owner: str) -> ActionItem | None:
    """The viewer's own past-due lines of the team's chase row: the same key, her lines, her money, the robots they feed, and how many the team has."""
    mine = sorted((s for s in ctx["chase"] if ctx["owners"][s.po_line.id] == owner), key=lambda s: -(s.days_past_due or 0))
    if not mine:
        return None
    sup = lambda s: _short(session, session.get(PoLine, s.po_line.id).identity_id)  # noqa: E731
    facts = [f"{sup(s)} {s.part.id}" + (f" {s.days_past_due} d late" if n == 0 and s.days_past_due else "") for n, s in enumerate(mine)]
    total = sum(float(s.open_value.usd or 0) for s in mine)
    notes: dict[str, str] = {}
    by_part = _robots_by_part(session)
    for s in mine:
        for pid in by_part.get(s.part.id, []):
            notes.setdefault(pid, f"{s.part.id} {s.days_past_due} d late" if s.days_past_due else s.part.id)
    pv = prov("computed", "po_lines", rule="open value of the viewer's past-due lines that no supplier message mentions", inputs=[s.po_line for s in mine], by="attention.chase")
    sliced = it.model_copy(update={"owner": owner, "at_stake": usd(total, pv), "robots": _robots_of(session, [s.part.id for s in mine]), "robot_notes": notes})
    shown = facts[:2] + ([f"{len(facts) - 2} more"] if len(facts) > 2 else [])      # one line: the oldest with its age, one more, then a count
    return _retitle(session, sliced, f"{count(len(mine), 'past-due line')}, no updated promise", " · ".join(shown + [f"{len(ctx['chase'])} across the team"]))


def _kind_of(session: Session, parts: list[str]) -> str:
    """The parts' category as a buyer says it: 'PCB (bare)' -> 'bare PCB'; several categories -> what the first part is."""
    cats = list(dict.fromkeys(session.get(Part, p).category for p in parts))
    m = re.fullmatch(r"(.+) \((.+)\)", cats[0]) if len(cats) == 1 else None
    return f"{m.group(2)} {m.group(1)}" if m else cats[0] if len(cats) == 1 else _head(session.get(Part, parts[0]).description)


def _quote_slices(session: Session, ctx: dict, owner: str, visible: list) -> list[ActionItem]:
    """The viewer's own quotes from the team's quotes row, each on its own key (its own stage): who, and what lapsing touches."""
    out = []
    for i, c in sorted(ctx["rest"], key=lambda x: x[0].act_by):
        pb = session.scalar(select(Part.buyer_id).where(Part.part_number == c["offer"].part_number))
        if (buyer_name(session, pb) if pb else i.owner) != owner:
            continue
        ident = c["offer"].identity_id
        who = _short(session, ident)
        risk = next((r for r, _ in visible if r.key == f"risk:{ident}"), None)
        why = risk.title.split(":")[0].split(" (")[0].replace(who, "supplier", 1) if risk else ""
        facts = " · ".join(x for x in ((f"{_fmt(c['stake']['spend'])} of forecast demand" if c["stake"]["spend"] else f"{count(len(c['parts']), 'part')} ({_kind_of(session, c['parts'])})"), why) if x)
        sliced = _retitle(session, i.model_copy(update={"owner": owner}), f"{who} quote expiring", facts or None)
        out.append(_with_robots(session, sliced, dict(parts=c["parts"])))
    return out


# --- public -------------------------------------------------------------------------------------------------------

DETAIL = {"disruption": _disruption_detail, "trust": _trust_detail, "deadline": _deadline_detail, "tariff": _tariff_detail, "unknown": _unknown_detail}


@memo
def _build(session: Session):
    exps = tariffs.all_exposures(session)
    tvis, tkids = _tariff_items(session, exps)
    uvis, ukids = _unknown_items(session, exps)
    dvis, dkids = _validity_deadlines(session)

    def sort_key(pair):
        it, ctx = pair
        m = ctx.get("money", 0.0) if it.group == "unknown" else _money(it.at_stake)
        days = it.days_left if it.days_left is not None else 9999
        risk_row = int(it.key.startswith("risk:"))      # a supplier's risk is not a live disruption: its open dollars are exposure, not a loss, so it follows the fire, the slips and the late consigned board
        return (GROUP_RANK[it.group], days, -m, it.key) if it.group == "deadline" else (GROUP_RANK[it.group], risk_row, -m, days, it.key)

    fires, slips = _disruption(session), _slip_items(session)
    # A slip on a supplier that already has an open disruption case (its reply re-dated the fire's lines) is that case moving on, not a second
    # case: one key per cause, so the slip folds into the fire (LOOKOUT QA #66; pre-existing since b9e08cd).
    on_fire = {c["ident"] for _, c in fires if "ident" in c}
    slips = [(it, c) for it, c in slips if c.get("ident") not in on_fire]
    carried = {c["ident"] for _, c in fires + slips if "ident" in c}
    visible = sorted(fires + slips + _incident_items(session, carried) + _consignment_items(session) + _risk_items(session) + _trust_items(session) + _deadlines(session) + _chase(session) + dvis + tvis + uvis, key=sort_key)
    # One row per cause: a supplier's other deadlines (its closure, its promised dates, a quote that lapses) while it has a force-majeure disruption are steps of that problem, shown
    # under it as dated rows; each stays resolvable by its own key.
    fire_ids = {c["ident"] for _, c in fires if "ident" in c and not c.get("slip")}
    folded = {}
    for it, c in visible:
        parts = it.key.split(":")
        if it.group == "deadline" and len(parts) == 3 and parts[0] == "deadline" and parts[1] in fire_ids:
            folded.setdefault(parts[1], []).append((it, c))
    if folded:
        gone = {it.key for rows in folded.values() for it, _ in rows}
        visible = [(it.model_copy(update={"dated": [DatedRow(key=d.key, title=d.title, act_by=d.act_by, days_left=d.days_left, at_stake=d.at_stake) for d, _ in sorted(folded[c["ident"]], key=lambda r: r[0].act_by or "")]}), c)
                   if (it.group == "disruption" and c.get("ident") in folded and "ids" in c and not c.get("slip")) else (it, c) for it, c in visible if it.key not in gone]
    shown = {i.key for i, _ in visible}
    children = {i.key: (i, c) for i, c in tkids + ukids + dkids if i.key not in shown}
    for rows in folded.values():
        children.update({it.key: (it, c) for it, c in rows})
    # Today's words and the robots each item touches (F45): every row, and every item reachable on its own key.
    visible = [(_with_robots(session, _reword(session, it, c), c), c) for it, c in visible]
    children = {k: (_with_robots(session, it, c), c) for k, (it, c) in children.items()}
    return visible, children


def what_needs_attention(session: Session, owner: str | None = None) -> list[ActionItem]:
    """The Action list as a buyer reads it, ranked: the fire, trust, deadlines (soonest first), the tariff as one row, the unknowns as
    one row per kind; inside each group, money at stake then days left. Each part, order or quote behind a row is still reachable
    by its own key (`all_keys`, `item_detail`)."""
    visible = _build(session)[0]
    if not owner:
        return [i for i, _ in visible]
    out = []
    for i, c in visible:
        if owner.lower() not in i.owner.lower():
            continue
        who = next((n for n in i.owner.split(" · ") if n.lower() == owner.lower()), None)
        if who and i.key == "deadline:chase":      # a team row the viewer has lines in: the viewer's own slice of it (B3)
            mine = _chase_slice(session, i, c, who)
            out += [mine] if mine else []
        elif who and i.key == "deadline:quotes":
            out += _quote_slices(session, c, who, visible)
        elif who and i.key == "unknown:stale-orders":
            mine = [(m, x) for m, x in c["members"] if m.owner == who]
            out += [_reword(session, i.model_copy(update={"owner": who}), {**c, "members": mine})] if mine else []
        else:
            out.append(i)
    return out


def cases_by_part(session: Session) -> dict[str, list[str]]:
    """{part: the keys of Today's rows that hold it}, in Today's order: a row holds a part when its refs name the part, or name one of the part's PO lines,
    or its money at stake is counted from them. The duty rows and the customs-data unknowns (origin, HTS) are left out: they change a part's cost, not whether it
    arrives for a build."""
    line_part = dict(session.execute(select(PoLine.id, PoLine.part_number)).all())
    out: dict[str, list[str]] = {}
    for it in what_needs_attention(session):
        if it.group == "tariff" or it.key in ("unknown:origin", "unknown:hts"):
            continue
        lines = {r.id for r in it.refs if r.type == "po_line"} | {r.id for r in (getattr(getattr(it.at_stake, "provenance", None), "inputs", None) or []) if r.type == "po_line"}
        parts = {r.id for r in it.refs if r.type == "part"} | {line_part[l] for l in lines if l in line_part}
        for p in sorted(parts):
            out.setdefault(p, []).append(it.key)
    return out


def all_items(session: Session) -> list[ActionItem]:
    """Every item the list can name: the rows on Today and the ones folded under them or behind them (a supplier's dated steps, a part's unknown), each by its own key."""
    visible, children = _build(session)
    return [i for i, _ in visible] + [i for i, _ in children.values()]


def all_keys(session: Session) -> list[str]:
    """Every key `item_detail` resolves: the rows of the list and the parts, orders and quotes rolled up into them."""
    visible, children = _build(session)
    return [i.key for i, _ in visible] + sorted(children)


def _say(session: Session, d: ActionItemDetail) -> ActionItemDetail:
    """The prose of a detail in a buyer's dates and a buyer's names (the id after the name); the data fields keep ISO and ids."""
    say = lambda t: naming.namify(session, humanize(t))      # noqa: E731
    d.finding = sentence(say(d.finding))
    d.finding_entities = annotate.annotate(session, d.finding, held=d.group == "trust")
    d.unknowns = [u.model_copy(update={"question": say(u.question), "why_it_blocks": say(u.why_it_blocks)}) for u in d.unknowns]
    d.numbers = [n.model_copy(update={"label": say(n.label)}) for n in d.numbers]
    d.evidence = naming.labelled(session, d.evidence)
    return d


def item_context(session: Session, key: str) -> tuple[ActionItem, dict] | None:
    """An item and the working context its detector kept (the records it was built from), for the modules that go further than the detail does."""
    visible, children = _build(session)
    return next(((i, c) for i, c in visible if i.key == key), children.get(key))


def item_detail(session: Session, key: str) -> ActionItemDetail | None:
    visible, children = _build(session)
    for item, ctx in visible:
        if item.key == key:
            return _say(session, DETAIL[item.group](session, item, ctx))
    if key in children:
        item, ctx = children[key]
        return _say(session, DETAIL[item.group](session, item, ctx))
    return None
