"""Supplier risk: what a supplier wrote in its quotes and what was reported about it, read as warnings, never as a score.

A flag is raised from the records only: the conditions and terms of a supplier's live offers (a blocked message's offers are never read), the events
matched to it, and the last price paid. The words are looked for, not a name: insolvency or administration, prepayment demanded, payment terms cut, a
quote far above the last PO. A flag becomes an Action-list item only when the supplier is the sole source of a part the plan needs."""

from __future__ import annotations

import json
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.events.model import Event
from app.domain.common import AS_OF
from app.domain.orders.model import PoLine, ReferencePrice
from app.domain.quotes.model import Offer
from app.domain.quotes.service import _fx
from app.domain.suppliers.model import SupplierRecord
from app.domain.suppliers.schema import RiskFlag
from app.domain.values import ref

INSOLVENCY = re.compile(r"insolven|administration|receivership|bankrupt|chapter 11|protective[- ]shield|schutzschirm|liquidat|creditor protection", re.I)
PREPAYMENT = re.compile(r"(\d+(?:\.\d+)?)\s*%[^.]*?(?:above|over|exceeding|from)\s+([A-Z]{3}|\$)\s*([\d,]+)", re.I)
TERMS_CUT = re.compile(r"net\s*(\d+)\s*\(was\s*(\d+)\)", re.I)
PRICE_JUMP = 0.10      # a quote this far above the last price paid is a warning of its own
BIG_JUMP = 0.25        # and this far, a serious one


NEWS_RISK = re.compile(r"\b(bill|ban|banned|bar|sanction|sanctions|export control|embargo|investigation|lawsuit|recall|strike|cyber|ransomware|fire|flood|earthquake|typhoon|explosion|bankrupt|insolven)\w*", re.I)
RISK_TOPICS = ("cyberattack", "insolvency", "fire", "recall", "shortage", "layoffs")      # the news topics the recipe's vocabulary tags as a risk to supply
DEFAULTS = {"on_time_below": 0.5, "min_closed_lines": 10, "top_spend_share": 0.10}


@memo
def thresholds(session: Session) -> dict:
    """The detector's thresholds, from the recipe's answers (`supplier_risk:`), carried in build_meta; the defaults only when a build carries none."""
    from sqlalchemy import text as _text

    try:
        row = session.execute(_text("select value from build_meta where key = 'supplier_risk'")).first()
        return {**DEFAULTS, **(json.loads(row[0]) if row and row[0] else {})}
    except Exception:  # noqa: BLE001
        return dict(DEFAULTS)


@memo
def spend_share(session: Session) -> dict[str, float]:
    """{supplier: its share of the last twelve months' spend}, from the clean dollar value of the order lines."""
    cutoff = (AS_OF - timedelta(days=365)).isoformat()
    spend: dict[str, float] = {}
    for ident, usd in session.execute(select(PoLine.identity_id, PoLine.line_usd).where(PoLine.order_date >= cutoff, PoLine.line_usd.is_not(None))):
        spend[ident] = spend.get(ident, 0.0) + float(usd)
    total = sum(spend.values()) or 1.0
    return {k: v / total for k, v in spend.items()}


def _live_offers(session: Session, identity_id: str) -> list[Offer]:
    return list(session.scalars(select(Offer).where(Offer.identity_id == identity_id, Offer.superseded_by.is_(None), Offer.trust != "blocked").order_by(Offer.id)))


@memo
def risk_flags(session: Session, identity_id: str) -> list[RiskFlag]:
    """Every warning the records carry for one supplier, most serious first: insolvency, prepayment demanded, payment terms cut, a quote far above the last PO."""
    flags: list[RiskFlag] = []
    offers = _live_offers(session, identity_id)
    said = [(o, m.group(0)) for o in offers if o.conditions and (m := INSOLVENCY.search(o.conditions))]
    reported = list(session.scalars(select(Event).where(Event.identity_id == identity_id, Event.kind == "news", Event.topic == "insolvency")))
    if said or reported:
        sources = [ref("message", o.message_id) for o, _ in said[:1]] + [ref("news", e.source_id) for e in reported[:2]]
        quoted = ""
        if said:      # the sentence of the quote that says it
            c = said[0][0].conditions
            k = INSOLVENCY.search(c).start()
            quoted = c[c.rfind(".", 0, k) + 1:(c.find(".", k) if c.find(".", k) >= 0 else len(c))].strip()
        words = " / ".join(x for x in (quoted, reported[0].title if reported else "") if x)      # what the quote says and what was reported, each in its own words
        flags.append(RiskFlag(kind="insolvency", severity="high", sources=sources,
                              text="In an insolvency procedure" + (f" (reported {reported[0].date})" if reported else "") + (": its own quote says so" if said else ""), evidence=words))
    for o in offers:
        m = PREPAYMENT.search(" ".join(filter(None, [o.prepayment, o.conditions])))
        if o.prepayment and m:
            order = o.qty_break * o.price
            threshold = float(m.group(3).replace(",", ""))
            applies = order > threshold
            flags.append(RiskFlag(kind="prepayment", severity="high" if applies else "medium", sources=[ref("message", o.message_id)],
                                  text=f"Demands {m.group(1)}% prepayment on orders above {m.group(2)} {m.group(3)}" + (f"; {o.qty_break} pieces is {o.currency} {order:,.0f}, so it applies" if applies else ""),
                                  evidence=o.prepayment))
            break
        if o.prepayment:
            flags.append(RiskFlag(kind="prepayment", severity="medium", sources=[ref("message", o.message_id)], text=f"Demands prepayment: {o.prepayment}", evidence=o.prepayment))
            break
    for o in offers:
        if o.payment_terms and (m := TERMS_CUT.search(o.payment_terms)) and int(m.group(1)) < int(m.group(2)):
            flags.append(RiskFlag(kind="terms_cut", severity="medium", sources=[ref("message", o.message_id)], text=f"Cut its payment terms from {m.group(2)} to {m.group(1)} days", evidence=o.payment_terms))
            break
    cheapest: dict[str, tuple[float, Offer]] = {}      # a part's lowest quoted price, in dollars, is the one to compare with the last PO
    for o in offers:
        if o.part_number:
            now = o.unit_price_each * _fx(session, o.currency)[0]
            if o.part_number not in cheapest or now < cheapest[o.part_number][0]:
                cheapest[o.part_number] = (now, o)
    for part, (now, o) in sorted(cheapest.items()):
        last = session.get(ReferencePrice, part)
        if last and last.usd_each and now / last.usd_each - 1 >= PRICE_JUMP:
            jump = now / last.usd_each - 1
            breaks = sorted({(x.qty_break or 0, x.unit_price_each * _fx(session, x.currency)[0]) for x in offers if x.part_number == part and x.message_id == o.message_id})
            said = ", ".join(f"{(p / last.usd_each - 1) * 100:+.1f}% at {q} pcs (${p:,.2f})" if q else f"{(p / last.usd_each - 1) * 100:+.1f}% (${p:,.2f})" for q, p in breaks)
            flags.append(RiskFlag(kind="price_jump", severity="high" if jump >= BIG_JUMP else "medium", sources=[ref("message", o.message_id)],  # every break with its basis named, so the case page and Ask agree (BUYER/SIDEQ)
                                  text=f"Quotes {part} above the last PO, price only, before any surcharge: {said}, against ${last.usd_each:,.2f}", evidence=o.price_raw))
            break
    # how it delivers, how it wants to be paid, what it leaves undated, what the news says: read from the lines, the vendor record and the events
    from app.domain.suppliers.service import delivery_performance

    cfg = thresholds(session)
    d = delivery_performance(session).get(identity_id)
    if d and d.n >= cfg["min_closed_lines"] and d.on_time_pct < cfg["on_time_below"]:
        flags.append(RiskFlag(kind="late_delivery", severity="high", sources=[],
                              text=f"On time on {d.on_time_pct:.0%} of its {d.n} closed lines; the {d.late} late ones average {d.avg_days_late:g} days late", evidence=f"{d.on_time} of {d.n} received on or before the promise"))
    rec = session.scalars(select(SupplierRecord).where(SupplierRecord.identity_id == identity_id, SupplierRecord.prepay_pct >= 100)).first()
    if rec:
        flags.append(RiskFlag(kind="cash_in_advance", severity="high" if spend_share(session).get(identity_id, 0) >= cfg["top_spend_share"] else "medium", sources=[ref("supplier_record", rec.record_id)],
                              text=f"Paid in advance: {rec.payment_terms_raw or rec.payment_terms}", evidence=rec.payment_terms_raw))
    undated = list(session.scalars(select(PoLine).where(PoLine.identity_id == identity_id, PoLine.status.in_(("OPEN", "PARTIAL")), PoLine.promised_date.is_(None))))
    if undated:
        worth = sum(float(l.open_usd or 0) for l in undated)
        flags.append(RiskFlag(kind="undated_open", severity="medium", sources=[ref("po_line", l.id) for l in undated[:3]],
                              text=f"{len(undated)} open line{'s' if len(undated) != 1 else ''} with no promised date (${worth:,.0f})", evidence=None))
    for e in session.scalars(select(Event).where(Event.identity_id == identity_id, Event.kind == "news").order_by(Event.date)):
        if e.topic in RISK_TOPICS and e.topic != "insolvency" or (e.topic in ("other", None) and NEWS_RISK.search(e.title or "")):
            flags.append(RiskFlag(kind="news_risk", severity="medium", sources=[ref("news", e.source_id)], text=f"Reported {e.date}: {e.title}", evidence=e.title))
    return flags


@memo
def sole_source_parts(session: Session, identity_id: str) -> list[str]:
    """Parts the plan needs (a requirement in the forecast) that this supplier alone has supplied: no other company is on any PO line for them."""
    from app.domain.demand import service as demand

    suppliers: dict[str, set[str]] = {}
    for part, ident in session.execute(select(PoLine.part_number, PoLine.identity_id)).all():
        suppliers.setdefault(part, set()).add(ident)
    return sorted(p for p, who in suppliers.items() if who == {identity_id} and demand.requirements(session, p))
