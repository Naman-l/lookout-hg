"""Offers, landed cost and the bid tab. Code does every sum; what is not known stays an Unknown beside the total."""

from __future__ import annotations

import collections
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF, Conditional, Money
from app.domain.demand import service as demand
from app.domain.orders.model import FxRate, PoLine, ReferencePrice
from app.domain.parts.model import Part
from app.domain.quotes.model import Offer
from app.domain.quotes.schema import BidColumn, BidTab, DutyRule, LandedCost, OfferView, QuoteFigure
from app.domain.suppliers.model import SupplierIdentity
from app.domain.tariffs import service as tariffs
from app.domain.ownership import buyer_of_part
from app.domain.values import prov, ref, unknown, usd


def _fx(session: Session, currency: str) -> tuple[float, str]:
    if currency == "USD":
        return 1.0, AS_OF.strftime("%Y-%m")
    month = session.scalar(select(func.max(FxRate.month)).where(FxRate.currency == currency))
    return session.scalar(select(FxRate.usd_per_unit).where(FxRate.currency == currency, FxRate.month == month)), month


def _view(session: Session, o: Offer) -> OfferView:
    rate, month = _fx(session, o.currency)
    me = ref("message", o.message_id)
    price = Money(amount=Decimal(str(o.price)), currency=o.currency, usd=Decimal(str(round(o.price * rate, 6))), rate=Decimal(str(rate)), rate_month=month,
                  provenance=prov("extracted", f"message:{o.message_id}", row=o.line_ref, raw=o.price_raw, inputs=[me]))
    each = usd(o.unit_price_each * rate, places=6, provenance=prov("computed", "offers", row=str(o.id), raw=o.price_raw, rule="quoted price / 1,000 if per 1,000, x FX at the latest month",
                                              inputs=[me], by="quotes.offers_for_part"))
    left = (date.fromisoformat(o.validity_date) - AS_OF).days if o.validity_date else None
    lead = Conditional(value=o.lead_time, condition=o.lead_time_condition, provenance=prov("extracted", f"message:{o.message_id}", row=o.line_ref)) if o.lead_time and o.lead_time_condition else None
    if o.lead_time and not o.lead_time_condition:
        lead = Conditional(value=o.lead_time, condition="from the order", provenance=prov("extracted", f"message:{o.message_id}", row=o.line_ref))
    sup = session.get(SupplierIdentity, o.identity_id) if o.identity_id else None
    part = session.get(Part, o.part_number) if o.part_number else None
    origin, origin_source = o.origin_iso, ("the quote" if o.origin_iso else None)
    if origin is None and o.origin_claim is None and part is not None and part.coo:
        origin, origin_source = part.coo, "stated in the part master"
    return OfferView(offer_id=o.id, supplier=ref("supplier", sup.id, sup.name) if sup else None, supplier_name=o.supplier_name, message=me, quote_no=o.quote_no,
                     part=ref("part", o.part_number or ""), qty_break=o.qty_break, price=price, price_basis=o.price_basis, unit_price_usd=each, incoterm=(o.incoterm or "") + (f" {o.incoterm_place}" if o.incoterm_place else "") or None,
                     origin_claim=o.origin_claim, origin=origin, origin_source=origin_source, lead_time=lead, valid_until=o.validity_date, days_left=left, expired=left is not None and left < 0,
                     moq=o.moq, tooling_usd=o.tooling_usd, payment_terms=o.payment_terms, conditions=o.conditions, trust=o.trust,
                     incoterm_term=o.incoterm, incoterm_place=o.incoterm_place, lead_time_days=o.lead_time_days, surcharge_pct=o.surcharge_pct,
                     surcharge_included=None if o.surcharge_pct is None else bool(o.surcharge_included), prepayment=o.prepayment, available_from=o.available_from,
                     site=_site(o.origin_claim), line_ref=o.line_ref)


def _site(origin_claim: str | None) -> str | None:
    """'China (Dongguan)' -> 'Dongguan'; 'Malaysia (Georgetown assembly; cells from the Huizhou plant)' -> 'Georgetown': the first place in the parenthesis, without the word that says what is done there."""
    m = re.search(r"\(([^)]+)\)", origin_claim or "")
    if not m:
        return None
    first = re.sub(r"\s+(assembly|plant|site|factory|works)$", "", m.group(1).split(";")[0].strip(), flags=re.I)
    return first or None


def offers_in_message(session: Session, message_id: str) -> list[OfferView]:
    """Every live offer the quote in this message holds (a price a later message corrected is left out), in the order they sit in the document."""
    q = select(Offer).where(Offer.message_id == message_id, Offer.superseded_by.is_(None)).order_by(Offer.id)
    return [_view(session, o) for o in session.scalars(q)]


@memo
def offers_for_part(session: Session, part: str, include_blocked: bool = False) -> list[OfferView]:
    """The live offers for a part: corrections applied (a superseded price is not offered), blocked senders left out unless asked."""
    q = select(Offer).where(Offer.part_number == part, Offer.superseded_by.is_(None)).order_by(Offer.supplier_name, Offer.origin_iso, Offer.qty_break, Offer.id)
    return [_view(session, o) for o in session.scalars(q) if include_blocked or o.trust != "blocked"]


def _figures(session: Session, part: str, offers: list[OfferView], rp) -> list[QuoteFigure]:
    """Every figure a quote states or implies, as a number with an id the answer can cite: each price as quoted (in the quote's own currency) at every break, the order total with
    the surcharge, the prepayment it demands (and in dollars), the change on the last PO in the supplier's own currency, and, for a quote that covers other parts, their prices and the
    next twelve months' new duty on the quote's China lines. Code does the arithmetic; the provenance names the quote's line or the rule."""
    import re

    out: list[QuoteFigure] = []
    last = session.get(PoLine, rp.po_line_id) if rp else None
    for v in offers:
        twins = [x for x in offers if x.quote_no == v.quote_no and x.qty_break == v.qty_break and x.offer_id != v.offer_id]      # two offers on one quote number and break (two sites) must not share an id
        base = f"quote:{part}:{v.quote_no or f'offer{v.offer_id}'}" + (f"/{v.site or v.origin or v.offer_id}" if twins else "") + (f"@{v.qty_break}" if v.qty_break else "")
        cur = v.price.currency
        each = v.price.amount / (1000 if v.price_basis == "per_1000" else 1)
        msg = [v.message] if v.message and v.message.id else []
        out.append(QuoteFigure(id=f"{base}:price_quoted", name=f"{v.supplier_name}: price per piece as quoted ({cur})", amount=each, unit=cur, provenance=v.price.provenance))
        net = None
        if v.qty_break:
            net = each * v.qty_break
            p_net = prov("computed", "offers", row=str(v.offer_id), rule=f"{v.qty_break} pieces x the quoted price per piece", inputs=msg, by="quotes.compare_offers")
            out.append(QuoteFigure(id=f"{base}:order_net", name=f"{v.supplier_name}: {v.qty_break} pieces at the quoted price ({cur}, before any surcharge)", amount=net, unit=cur, provenance=p_net))
            total = net
            if v.surcharge_pct and not v.surcharge_included:
                total = (net * (1 + Decimal(str(v.surcharge_pct)) / 100)).quantize(Decimal("0.01"))
                p_tot = prov("computed", "offers", row=str(v.offer_id), rule=f"{v.qty_break} pieces x the quoted price, plus the {v.surcharge_pct:g}% material surcharge the quote adds on net value", inputs=msg, by="quotes.compare_offers")
                out.append(QuoteFigure(id=f"{base}:order_total", name=f"{v.supplier_name}: {v.qty_break}-piece order with the surcharge ({cur})", amount=total, unit=cur, provenance=p_tot))
            m = re.search(r"(\d+(?:\.\d+)?)\s*%[^.]*?(?:above|over|exceeding)\s+[A-Z]{3}\s*([\d,]+)", v.prepayment or "")
            if m and total > Decimal(m.group(2).replace(",", "")):
                pre = (total * Decimal(m.group(1)) / 100).quantize(Decimal("0.01"))
                p_pre = prov("computed", "offers", row=str(v.offer_id), rule=f"{m.group(1)}% of the {v.qty_break}-piece order ({cur} {total:,.2f}), because it is above the {cur} {m.group(2)} the quote sets", inputs=msg, by="quotes.compare_offers")
                out.append(QuoteFigure(id=f"{base}:prepayment", name=f"{v.supplier_name}: prepayment demanded on the {v.qty_break}-piece order ({cur})", amount=pre, unit=cur, provenance=p_pre))
                if cur != "USD" and v.price.rate:
                    out.append(QuoteFigure(id=f"{base}:prepayment_usd", name=f"{v.supplier_name}: that prepayment in dollars at finance's {v.price.rate_month} rate", amount=(pre * Decimal(str(v.price.rate))).quantize(Decimal("0.01")), unit="USD",
                                           provenance=prov("computed", "offers", row=str(v.offer_id), rule=f"the prepayment x finance's rate {v.price.rate} for {v.price.rate_month}", inputs=msg, by="quotes.compare_offers")))
        if last is not None and last.currency == cur and last.unit_price and v.price_basis == "each":
            pct = ((each / Decimal(str(last.unit_price)) - 1) * 100).quantize(Decimal("0.1"))
            out.append(QuoteFigure(id=f"{base}:vs_last_po_pct", name=f"{v.supplier_name}: change against the last PO price ({cur} {last.unit_price:g}, {last.id}), before any surcharge", amount=pct, unit="%",
                                   provenance=prov("computed", "offers", row=str(v.offer_id), rule=f"quoted price / the last PO line's price in the same currency - 1 ({last.id})", inputs=msg + [ref("po_line", last.id)], by="quotes.compare_offers")))
    # a quote with several parts: the others' prices, and the new duty over the next twelve months on its China lines
    quotes_here = {v.quote_no for v in offers if v.quote_no}
    if quotes_here:
        total_duty: dict[str, Decimal] = {}
        quote_offers = list(session.scalars(select(Offer).where(Offer.quote_no.in_(quotes_here), Offer.superseded_by.is_(None), Offer.trust != "blocked").order_by(Offer.id)))
        sites_of, breaks_of = collections.defaultdict(set), collections.defaultdict(set)
        for x in quote_offers:
            sites_of[(x.part_number, x.quote_no)].add(_site(x.origin_claim) or x.origin_iso or "")
            breaks_of[(x.part_number, x.quote_no)].add(x.qty_break)
        for o in quote_offers:
            lc = landed_cost(session, o.id)
            g = (o.part_number, o.quote_no)      # a part quoted from two sites, or at two breaks, on one quote number gets one id per site and per break
            sfx = (f"/{re.sub(r'[^A-Za-z0-9]+', '_', _site(o.origin_claim) or o.origin_iso or str(o.id)).strip('_')}" if len(sites_of[g]) > 1 else "") + (f"@{o.qty_break}" if len(breaks_of[g]) > 1 else "")
            if o.part_number != part:
                out.append(QuoteFigure(id=f"quote:{o.part_number}:{o.quote_no}{sfx}:price", name=f"{o.supplier_name}: price per piece for {o.part_number} (USD)", amount=lc.unit_price_usd.usd, unit="USD", provenance=lc.unit_price_usd.provenance))
            if lc.duty_usd is not None and lc.duty_status in ("owed", "at_cost_on_top") and o.part_number:
                need = Decimal(o.annual_qty) if o.annual_qty else sum((r.qty.value for r in demand.requirements(session, o.part_number)), Decimal(0))      # the quote's own estimate of a year's use, else the plan's
                duty = (lc.duty_usd.usd * need).quantize(Decimal("0.01"))
                total_duty[o.quote_no] = total_duty.get(o.quote_no, Decimal(0)) + duty
                out.append(QuoteFigure(id=f"quote:{o.part_number}:{o.quote_no}{sfx}:duty_next_12_months", name=f"{o.part_number}: the new duty on a year's use (the quote's estimated quantity) at this price (USD)", amount=duty, unit="USD",
                                       provenance=prov("computed", "offers", row=str(o.id), rule="the quote's estimated annual quantity (else twelve months of planned need) x the price x the duty rate its origin brings", inputs=[ref("part", o.part_number)], by="quotes.compare_offers")))
        for qn, d in total_duty.items():
            out.append(QuoteFigure(id=f"quote:{qn}:duty_next_12_months", name=f"Quote {qn}: the new duty on the next twelve months' need across its China lines (USD)", amount=d, unit="USD",
                                   provenance=prov("computed", "offers", rule="the sum of the quote's lines' twelve-month duty", by="quotes.compare_offers")))
    return out


def _duty_rule(session: Session, part: str | None) -> DutyRule | None:
    """The tariff rule a part falls under (its tranche, rate, date and in-transit window), or None when it is not on the list."""
    ts = tariffs.tariff_rule_for(session, part) if part else None
    if ts is None or ts.status != "listed":
        return None
    r = ts.rule
    return DutyRule(tranche=r.tranche, rate=r.rate, effective_date=r.effective_date, exported_before=r.exported_before, entered_before=r.entered_before)


def landed_cost(session: Session, offer_id: int, *, annual_qty: float | None = None) -> LandedCost:
    """Unit cost to the company: price, material surcharge, new duty by tariff rule and origin, tooling spread over a year's need.

    Customs value is the price paid excluding international freight. A DDP price does not include a later China duty (BCX invoices it
    'at cost'), so it is added and marked `at_cost_on_top`. Freight and insurance are not in the data: an Unknown for any term that is
    not delivered. An origin the supplier cannot settle (Vietnam with Chinese magnets, a Georgetown pack) gives no duty, only the figure
    that applies if it is ruled China."""
    o = session.get(Offer, offer_id)
    v = _view(session, o)
    price = float(v.unit_price_usd.usd)
    inputs = [ref("message", o.message_id), ref("part", o.part_number or "")]
    surcharge = 0.0 if o.surcharge_included else price * (o.surcharge_pct or 0) / 100   # a surcharge the quote says is already in its price is not added again
    notes, unknowns = [], []
    status, duty, duty_cn = "none", None, None
    ts = tariffs.tariff_rule_for(session, o.part_number) if o.part_number else None
    rate = ts.rule.rate if ts and ts.status == "listed" else None
    p = session.get(Part, o.part_number) if o.part_number else None
    owner = buyer_of_part(session, o.part_number)
    if ts is None or ts.status != "listed":
        status = "no_rule"
        notes.append("the part is not on the new China duty list" if ts and ts.status in ("not_listed", "excluded") else "no tariff code on the part")
    elif o.origin_iso == "CN":
        status = "at_cost_on_top" if (o.incoterm or "") == "DDP" else "owed"
        duty = price * rate
        notes.append(f"China origin on a listed code: {rate:.0%} of the customs value" + (" (the supplier invoices it at cost on top of the DDP price)" if status == "at_cost_on_top" else ""))
    elif o.origin_iso is None and o.origin_claim is None and p is not None and p.coo:
        # the quote states no origin: the item master's stated origin applies
        if p.coo == "CN":
            status = "at_cost_on_top" if (o.incoterm or "") == "DDP" else "owed"
            duty = price * rate
        notes.append(f"the quote states no origin; the item master says {p.coo}" + (f": {rate:.0%} duty" if p.coo == "CN" else ": no new China duty"))
    elif o.origin_iso is None:
        status = "unknown_origin"
        duty_cn = price * rate
        unknowns.append(unknown("origin ruling", f"{o.supplier_name} claims '{o.origin_claim}'; whether that is not China origin is a customs-broker call, not the supplier's",
                                "broker", "Does the origin documentation support non-China origin for this part?", [ref("part", o.part_number or "")]))
    else:
        notes.append(f"{o.origin_iso} origin: no new China duty")
    if (o.incoterm or "") not in ("DDP",):
        unknowns.append(unknown("freight and insurance", "international freight and insurance are not in the data; they are not part of the customs value but are part of the landed cost",
                                owner, f"What is the freight and insurance for {o.incoterm or 'this term'}?", [ref("part", o.part_number or "")]))
    tooling_pu = None
    if o.tooling_usd:
        need = annual_qty or sum(float(r.qty.value) for r in demand.requirements(session, o.part_number)) if o.part_number else 0
        if need:
            tooling_pu = o.tooling_usd / need
            notes.append(f"tooling USD {o.tooling_usd:,.0f} spread over {need:,.0f} pieces a year")
        else:
            unknowns.append(unknown("tooling per piece", "tooling is one-time and the annual volume of this part is not in the forecast", owner, "How many will be bought a year?"))
    pv = prov("computed", "offers", row=str(o.id), rule="price + surcharge + duty (rate x customs value) + tooling per piece", inputs=inputs, by="quotes.landed_cost")
    known = price + surcharge + (duty or 0.0) + (tooling_pu or 0.0)
    if o.payment_terms and ("deposit" in o.payment_terms or "advance" in o.payment_terms):
        notes.append(f"payment: {o.payment_terms}")
    if o.conditions and "prepayment" in o.conditions.lower():
        notes.append("prepayment applies above EUR 25,000 net")
    u6 = lambda x: usd(x, pv, places=6)  # noqa: E731  (per-piece amounts keep six places)
    return LandedCost(offer=v, unit_price_usd=v.unit_price_usd, surcharge_usd=u6(surcharge) if surcharge else None, duty_status=status,
                      duty_usd=u6(duty) if duty is not None else None, duty_if_china_usd=u6(duty_cn) if duty_cn is not None else None,
                      tooling_per_unit_usd=u6(tooling_pu) if tooling_pu else None, total_known_usd=u6(known),
                      total_if_china_usd=u6(known + duty_cn) if duty_cn is not None else None, unknowns=unknowns, notes=notes,
                      duty_rule=_duty_rule(session, o.part_number))


def compare_offers(session: Session, part: str, qty: int | None = None) -> BidTab:
    """The bid tab: one column per supplier and origin (the best break at or below `qty`), plus the last PO line as the current price.
    Cheapest known total first; a column whose origin is unsettled shows its total and the figure if it is ruled China."""
    offers = offers_for_part(session, part)
    best: dict[tuple, OfferView] = {}
    for v in offers:
        key = (v.supplier_name, v.origin, v.origin_claim)
        if qty is not None and v.qty_break and v.qty_break > qty:
            continue
        cur = best.get(key)
        if cur is None or (v.qty_break or 0) >= (cur.qty_break or 0):
            best[key] = v
    cols = [BidColumn(label=f"{v.supplier_name}" + (f" ({v.origin_claim.split(' (')[0].split(';')[0]})" if v.origin_claim else ""),
                      landed=landed_cost(session, v.offer_id, annual_qty=None)) for v in best.values()]
    rp = session.get(ReferencePrice, part)
    if rp:
        line = session.get(PoLine, rp.po_line_id)
        fake = Offer(id=-1, message_id="", source="po", supplier_name=session.get(SupplierIdentity, line.identity_id).name, part_number=part, price_raw=str(line.unit_price),
                     price=rp.usd_each, currency="USD", price_basis="each", unit_price_each=rp.usd_each, incoterm=None, origin_iso=(session.get(Part, part).coo), trust="ok")
        cols.append(BidColumn(label=f"Current: {fake.supplier_name} (last PO {line.order_date})", is_current=True, landed=_current_column(session, line, rp)))
    cols.sort(key=lambda c: float(c.landed.total_known_usd.usd))
    return BidTab(part=ref("part", part), qty=qty, columns=cols, figures=_figures(session, part, offers, rp),
                  note="Totals are per piece and cover price, surcharge, known duty and tooling; freight and insurance are not in the data. A column with an unsettled origin shows what it would cost if ruled China.")


def _current_column(session: Session, line: PoLine, rp: ReferencePrice) -> LandedCost:
    """The incumbent: the last clean PO line, with the duty its origin would bring."""
    p = session.get(Part, line.part_number)
    ts = tariffs.tariff_rule_for(session, line.part_number)
    rate = ts.rule.rate if ts.status == "listed" else None
    ddp = tariffs._importer(session, line.record_id) == "supplier"
    price = rp.usd_each
    duty = price * rate if (rate and p.coo == "CN") else None
    status = "none" if duty is None else ("at_cost_on_top" if ddp else "owed")
    pv = prov("computed", "po_lines", row=line.id, rule="last clean PO line + duty by tariff rule", inputs=[ref("po_line", line.id)], by="quotes.compare_offers")
    offer = OfferView(offer_id=-1, supplier=ref("supplier", line.identity_id), supplier_name=session.get(SupplierIdentity, line.identity_id).name, message=ref("message", ""), quote_no=None,
                      part=ref("part", line.part_number), qty_break=None, price=usd(price, pv), price_basis="each", unit_price_usd=usd(price, pv), incoterm=None,
                      origin_claim=p.coo, origin=p.coo, lead_time=None, valid_until=None, days_left=None, expired=False, moq=None, tooling_usd=None, payment_terms=None,
                      conditions=f"last paid on {line.id}", trust="ok")
    return LandedCost(offer=offer, unit_price_usd=usd(price, pv), surcharge_usd=None, duty_status=status, duty_usd=usd(duty, pv) if duty else None, duty_if_china_usd=None,
                      tooling_per_unit_usd=None, total_known_usd=usd(price + (duty or 0.0), pv), total_if_china_usd=None, unknowns=[],
                      last_paid_usd=usd(price, prov("computed", "po_lines", row=line.id, rule="the last clean PO line's price, in dollars, with no duty", inputs=[ref("po_line", line.id)], by="quotes.compare_offers")),
                      with_new_duty_usd=usd(price + duty, pv) if duty else None,
                      notes=[f"origin {p.coo or 'unknown'}" + (f", {rate:.0%} duty" if duty else "")], duty_rule=_duty_rule(session, line.part_number))
