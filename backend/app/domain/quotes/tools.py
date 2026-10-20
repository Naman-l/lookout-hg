"""Agent tool over the quotes service: the quote comparison (bid tab) with landed cost, one column per offer."""

from __future__ import annotations

from decimal import Decimal


from claude_agent_sdk import tool

from ...organism import company
from ...organism.context import RunContext
from ...organism.schemas import Number
from ...organism.toolkit import READ, date_words, money_number, plain_number, plural, reply


def _key(col) -> str:
    o = col.landed.offer
    return "current" if col.is_current else (o.quote_no or f"offer{o.offer_id}")


def _terms(o, L) -> dict:
    """The conditions beside the price as named fields. Every value is text (a date in ISO beside its words): a figure said about an offer is a price with an id, or one of these."""
    lt = o.lead_time
    r = L.duty_rule
    return {
        "incoterm": o.incoterm_term, "incoterm_place": o.incoterm_place,
        "lead_time": None if lt is None else {"text": str(lt.value), "days": None if o.lead_time_days is None else f"{o.lead_time_days} days", "basis": lt.condition},
        "valid_until": o.valid_until, "valid_until_words": date_words(o.valid_until) if o.valid_until else None,
        "moq": None if o.moq is None else f"{o.moq:,} pieces",
        "tooling_usd": None if o.tooling_usd is None else f"USD {o.tooling_usd:,.2f}",
        "surcharge": None if o.surcharge_pct is None else {"pct": f"{o.surcharge_pct:g}%", "included": "already in the quoted price" if o.surcharge_included else "added to the quoted price"},
        "prepayment": o.prepayment, "payment_terms": o.payment_terms,
        "origin": {"iso": o.origin, "claim": o.origin_claim, "site": o.site, "available_from": o.available_from, "available_from_words": date_words(o.available_from) if o.available_from else None},
        "duty_rule": None if r is None else {"tranche": str(r.tranche), "rate": f"{r.rate:.0%}", "effective_date": r.effective_date, "effective_words": date_words(r.effective_date),
                                             "in_transit_relief": "none" if r.entered_before is None else f"exempt if exported before {r.exported_before} and entered before {r.entered_before}"},
    }


def origin_alternatives(columns: list[dict]) -> list[dict]:
    """Offers for the same part whose origin differs from the incumbent's (or, with no incumbent, from the first offer's): another country, a new site,
    each with the date it can start where the document gives one, and the id of its price."""
    base = next((c for c in columns if c["current"]), columns[0] if columns else None)
    return [{"supplier": c["supplier"], "quote_no": c["quote_no"], "origin_claim": c["origin_claim"], "origin_iso": c["origin"], "available_from": c["terms"]["origin"]["available_from"],
             "available_from_words": c["terms"]["origin"]["available_from_words"], "price_id": c["price_id"]}
            for c in columns if not c["current"] and base is not None and (c["origin"], c["origin_claim"]) != (base["origin"], base["origin_claim"])]


def make_tools(ctx: RunContext, svc):
    co = company.names(ctx.db_path)[1]  # the company's short name, from the recipe

    @tool(
        "compare_offers",
        "The quote comparison (bid tab) for one part: every supplier offer plus the current supplier's last PO, each "
        "as a landed cost per piece (price, surcharge, known duty, tooling per unit). Each column carries what is NOT "
        "known: duty that depends on an origin ruling, freight, and conditions kept with their value (a lead time that "
        "starts after sample approval, a validity date, the Incoterm, the origin the supplier claims). Code did the "
        "arithmetic and the unit normalisation (a price per 1,000 is already per piece); never recompute. Use it for "
        f"every part where {co} might buy from someone else.",
        {"type": "object", "properties": {"part_number": {"type": "string"}, "qty": {"type": "integer", "description": "order quantity to compare at, if known"}}, "required": ["part_number"]},
        annotations=READ,
    )
    async def compare_offers(args):
        part = args["part_number"]
        tab = svc.compare_offers(part, args.get("qty"))
        numbers: list[Number] = []
        columns, unknowns = [], []
        keys = [_key(c) for c in tab.columns]
        for col, k0 in zip(tab.columns, keys):
            L, o = col.landed, col.landed.offer
            k = f"{k0}/{o.site or o.origin or o.offer_id}" if keys.count(k0) > 1 else k0      # two offers on one quote number (two sites) never share an id
            name = o.supplier_name.split(" Co.")[0].split(",")[0].split(" (")[0]
            same = (not col.is_current) and any(c.is_current and c.landed.offer.supplier == o.supplier and o.supplier is not None for c in tab.columns)
            who = f"Last paid ({co}'s last PO)" if col.is_current else (f"{name}'s new quote" if same else name)
            numbers.append(money_number(f"quote:{part}:{k}:price", f"{who}: price per piece for {part}", L.unit_price_usd))
            if L.duty_usd is not None:
                numbers.append(money_number(f"quote:{part}:{k}:duty", f"{who}: known duty per piece", L.duty_usd))
            if L.surcharge_usd is not None:
                numbers.append(money_number(f"quote:{part}:{k}:surcharge", f"{who}: surcharge per piece", L.surcharge_usd))
            if col.is_current:      # the last price paid and that price with the new duty are two figures, never one
                numbers.append(money_number(f"quote:{part}:{k}:total", f"{who}: that price with the new duty, per piece (not what was paid)" if L.with_new_duty_usd is not None else f"{who}: price per piece (no duty applies)", L.total_known_usd))
            else:
                numbers.append(money_number(f"quote:{part}:{k}:total", f"{who}: landed cost per piece (known parts)", L.total_known_usd))
            landed = L.with_new_duty_usd if (col.is_current and L.with_new_duty_usd is not None) else (L.total_known_usd if not col.is_current else L.unit_price_usd)
            numbers.append(money_number(f"quote:{part}:{k}:landed_usd_each", f"{who}: landed cost per piece after the duty that applies (USD each)", landed))
            if L.total_if_china_usd is not None:
                numbers.append(money_number(f"quote:{part}:{k}:total_if_china", f"{who}: landed cost per piece if ruled China origin", L.total_if_china_usd))
            unknowns += L.unknowns
            columns.append({
                "key": k, "supplier": who, "current": col.is_current, "quote_no": o.quote_no, "qty_break": o.qty_break, "incoterm": o.incoterm, "origin": o.origin,
                "origin_claim": o.origin_claim, "origin_source": o.origin_source, "duty_status": L.duty_status,
                "lead_time": None if o.lead_time is None else {"value": str(o.lead_time.value), "condition": o.lead_time.condition},
                "valid_until": o.valid_until, "valid_until_words": date_words(o.valid_until) if o.valid_until else None, "days_left": o.days_left, "expired": o.expired,
                "moq": o.moq, "tooling_usd": o.tooling_usd, "payment_terms": o.payment_terms, "conditions": o.conditions, "trust": o.trust, "notes": L.notes,
                "terms": _terms(o, L), "price_id": f"quote:{part}:{k}:price",
                "last_paid_usd": str((L.last_paid_usd or L.unit_price_usd).usd) if col.is_current else None, "with_new_duty_usd": str(L.with_new_duty_usd.usd) if L.with_new_duty_usd else None,
            })
        last = next((c.landed.unit_price_usd for c in tab.columns if c.is_current and c.landed.unit_price_usd is not None and c.landed.unit_price_usd.usd), None)
        if last is not None:  # each quote's change against last paid, on one named basis (price per piece vs last paid price per piece): code's figure, never the model's arithmetic (BUYER Q5)
            for col, k0 in zip(tab.columns, keys):
                L, o = col.landed, col.landed.offer
                k = f"{k0}/{o.site or o.origin or o.offer_id}" if keys.count(k0) > 1 else k0
                if col.is_current or L.unit_price_usd is None or L.unit_price_usd.usd is None:
                    continue
                invoiced = Decimal(str(L.unit_price_usd.usd)) + (Decimal(str(L.surcharge_usd.usd)) if L.surcharge_usd is not None and L.surcharge_usd.usd is not None else 0)
                pct = (invoiced / Decimal(str(last.usd)) - 1) * 100
                numbers.append(plain_number(f"quote:{part}:{k}:vs_last_paid_pct", f"{o.quote_no or k}: as invoiced, price + any surcharge (USD {invoiced:.2f} each{f' at the {o.qty_break}-piece break' if o.qty_break else ''}) against last paid ({last.usd} USD), percent", pct.quantize(Decimal("0.1")), "%"))
                if invoiced != Decimal(str(L.unit_price_usd.usd)):  # with a surcharge, the price alone is a second, named basis: the case page's figure is on price alone
                    alone = (Decimal(str(L.unit_price_usd.usd)) / Decimal(str(last.usd)) - 1) * 100
                    numbers.append(plain_number(f"quote:{part}:{k}:vs_last_paid_price_pct", f"{o.quote_no or k}: on price alone (USD {Decimal(str(L.unit_price_usd.usd)):.2f} each, before the surcharge) against last paid ({last.usd} USD), percent", alone.quantize(Decimal("0.1")), "%"))
        qty = args.get("qty")
        if qty:  # an order of this quantity (a bridge order): its total as invoiced and the prepayment the quote would demand on it, by the quote's own rule (BUYER Q5)
            import re as _re  # noqa: PLC0415

            for col, k0 in zip(tab.columns, keys):
                L, o = col.landed, col.landed.offer
                k = f"{k0}/{o.site or o.origin or o.offer_id}" if keys.count(k0) > 1 else k0
                if col.is_current or L.unit_price_usd is None or L.unit_price_usd.usd is None:
                    continue
                inv = Decimal(str(L.unit_price_usd.usd)) + (Decimal(str(L.surcharge_usd.usd)) if L.surcharge_usd is not None and L.surcharge_usd.usd is not None else 0)
                order_usd = (inv * Decimal(qty)).quantize(Decimal("0.01"))
                numbers.append(plain_number(f"quote:{part}:{k}:order_{qty}_usd", f"{o.quote_no or k}: {qty} pieces as invoiced (USD {inv:.2f} each, price + any surcharge)", order_usd, "USD"))
                m = _re.search(r"(\d+(?:\.\d+)?)\s*%[^.]*?(?:above|over|exceeding)\s+([A-Z]{3})\s*([\d,]+)", getattr(o, "prepayment", None) or "")
                if m and getattr(o.price, "rate", None):
                    order_own = order_usd / Decimal(str(o.price.rate))  # the threshold is in the quote's currency
                    if m.group(2) == o.price.currency and order_own > Decimal(m.group(3).replace(",", "")):
                        pre = (order_usd * Decimal(m.group(1)) / 100).quantize(Decimal("0.01"))
                        numbers.append(plain_number(f"quote:{part}:{k}:order_{qty}_prepayment_usd", f"{o.quote_no or k}: the {m.group(1)}% prepayment the quote demands on {qty} pieces (above {m.group(2)} {m.group(3)}), USD: what an order on open terms avoids", pre, "USD"))
        numbers += [Number(id=f.id, name=f.name, value=f.amount, unit=f.unit, provenance=f.provenance) for f in getattr(tab, "figures", [])]      # every quoted figure with an id, at every break
        quoted = [c for c in columns if not c["current"]]
        alternatives = origin_alternatives(columns)
        return reply(ctx, f"Quote comparison for {part}: {plural(len(quoted), 'offer')} beside the current supplier",
                     {"part": part, "qty": tab.qty, "note": tab.note, "columns": columns, "origin_alternatives": alternatives}, numbers, unknowns)

    return [compare_offers]
