"""The options of each kind of case, as a code table (plan-13 agent spec, top 1): the kinds, the labels a buyer reads, the button and where each
leads are fixed by code, so the wording matches the buyer's words and the list never changes between runs. Lookout writes only which
one it recommends (rule B); the verifier checks that.

leads_to: request (an email to the supplier's contact on file, the clerk drafts it), note (a note to a person inside the company; a PO change or an order is a note
"to enter in the ERP", since the app writes no orders), record (the buyer's decision, written down with a reason).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.attention import service
from app.domain.attention.options import case_kind
from app.domain.suppliers import service as suppliers
from app.domain.values import EntityRef

LeadsTo = Literal["request", "note", "record"]


class OptionKind(BaseModel):
    kind: str
    label: str
    leads_to: LeadsTo
    to: str = ""  # who it goes to, resolved for the item: the supplier's contact, the item's owner, or a function ("planning", "Accounts Payable")
    button: str = ""
    erp: bool = False  # a PO change or an order: the note says it is to enter in the ERP
    changes: str = ""  # what choosing it changes, honest and from code: a known effect, or when it will be known; never a model estimate
    also_start: bool = False  # a dated route whose date falls on or before the item's act-by: started beside whichever one the buyer chooses (BUYER D2)
    by: str | None = None  # that date (YYYY-MM-DD), where the route has one
    refs: list[EntityRef] = []  # the records the option is built on, where code linked one (the quote an alternate origin comes from)
    also_why: str = ""  # why code offers it as an also-start, from the records ("order by <date>, on or before the act-by", "sole source of <part> · on time on <n>% of <m> lines")


# (kind, label, leads_to, to): "{who}" is the supplier's name; to = "supplier" (its contact on file), "owner" (the item's owner) or a function's name.
_T = tuple[str, str, LeadsTo, str]
OPTION_KINDS: dict[str, list[_T]] = {      # labels: content-spec §4/§5 noun phrases, at most 6 words (ui-ai-contract v2)
    "fire": [
        ("allocation", "Allocation request · {who}", "request", "supplier"),
        ("second_source", "Alternate source", "note", "owner"),
        ("air_freight", "Air-freight surviving stock", "request", "supplier"),   # the same email as allocation: it already asks what survived (one thread per contact)
        ("resequence", "Re-sequence builds", "note", "planning"),
        ("wait", "Wait for revised dates", "record", ""),
    ],
    "slip": [
        ("allocation", "Allocation request · {who}", "request", "supplier"),
        ("air_freight", "Air freight, delayed lines", "request", "supplier"),
        ("second_source", "Alternate source", "note", "owner"),
        ("resequence", "Re-sequence builds", "note", "planning"),
        ("accept", "Accept the new dates", "note", "owner"),
        ("order_before", "Order before the lead-time cutoff", "note", "owner"),
    ],
    "incident": [
        ("confirm_dates_hold", "Confirm the new dates hold · {who}", "request", "supplier"),
        ("accept", "Accept the new dates", "note", "owner"),
        ("second_source", "Alternate quote", "note", "owner"),
    ],
    "risk": [   # generic for every supplier at risk (BUYER-EXPERT's caveat): the records hold no position for any of them
        ("open_terms", "Firm dates, normal terms · {who}", "request", "supplier"),
        ("bridge", "Bridge quantity, no prepayment", "request", "supplier"),
        ("second_source", "Alternate source", "note", "owner"),
        ("recheck", "Re-check on a date", "record", ""),
    ],
    "consignment": [   # two parties: the material's supplier and the contract manufacturer that builds with it
        ("earlier_date", "Earlier date or partial · {who}", "request", "supplier"),
        ("cm_partial", "Partial-start request · {maker}", "request", "maker"),
        ("direct_air", "Direct air to {maker}", "note", "owner"),
        ("cm_stock", "Consigned stock check · {maker}", "request", "maker"),
    ],
    "closure": [
        ("pull_in", "Ship before the closure · {who}", "request", "supplier"),
        ("accept", "Accept the new ship date", "note", "owner"),
    ],
    "price_lock": [
        ("buy_ahead", "Buy ahead at today's price", "request", "supplier"),   # the acknowledgement the clerk drafts: the open lines at today's price by the date
        ("accept", "Accept the new price", "record", ""),
        ("extend", "Extension request · {who}", "request", "supplier"),
    ],
    "deadline:quotes": [
        ("bridge", "Bridge quantity, no prepayment", "request", "supplier"),
        ("extend", "Extension request", "request", "supplier"),
        ("lapse", "Let the quote lapse", "record", ""),
        ("accept", "Accept as quoted", "record", ""),
    ],
    "deadline:chase": [
        ("ship_date", "Expedite: ask for a ship date", "request", "supplier"),
        ("accept_date", "Accept the new date", "note", "owner"),
        ("reorder", "Cancel and re-source", "note", "owner"),
    ],
    "tariff:all": [   # a roll-up: no clerk runs on it, so nothing here is an email; the owner acts on each part's case
        ("ship_before", "Ship before the duty starts", "note", "owner"),
        ("switch_origin", "Alternate origin", "note", "owner"),
        ("prove_origin", "Proof of origin", "note", "owner"),
        ("broker_exclusion", "Broker exclusion request", "note", "owner"),
        ("accept", "Accept and budget the duty", "record", ""),
    ],
    "unknown:origin": [
        ("ask_origin", "Certificate of origin request", "request", "supplier"),
        ("enter_answer", "Enter the answer in Import", "record", ""),
    ],
    "unknown:hts": [
        ("ask_broker", "Ask the customs broker", "note", "owner"),
        ("enter_answer", "Enter the answer in Import", "record", ""),
    ],
    "unknown:stale-orders": [   # never an email to the supplier: Receiving knows, and a request to a disrupted supplier would ride into that case's email
        ("ask_receiving", "Ask Receiving", "note", "owner"),
        ("close", "Close the PO", "note", "owner"),
        ("cancel", "Cancel the PO", "note", "owner"),
    ],
}
_ERP = {("slip", "accept"), ("slip", "order_before"), ("closure", "accept"), ("incident", "accept"), ("price_lock", "buy_ahead"), ("deadline:chase", "accept_date"), ("deadline:chase", "reorder"),
        ("unknown:stale-orders", "close"), ("unknown:stale-orders", "cancel")}   # a PO change or an order: a note to enter in the ERP


CHANGES = {   # (kind of case, option) -> what choosing it changes; {who}, {promised}, {part}, {month} are filled from the case
    ("fire", "allocation"): "known by {promised} ({who}'s quantity)", ("fire", "second_source"): "October unchanged; the quoted part only",
    ("fire", "air_freight"): "only if stock survived", ("fire", "resequence"): "builds reordered; the parts stay short",
    ("fire", "wait"): "shortfall unchanged until the reply", ("fire", "alternate_on_file"): "{month} unchanged; {part} only",
    ("slip", "allocation"): "known after the supplier's reply", ("slip", "air_freight"): "earlier only if the supplier ships early",
    ("slip", "second_source"): "only after qualification", ("slip", "resequence"): "builds reordered; the parts stay short",
    ("slip", "accept"): "PO lines take the new dates", ("slip", "order_before"): "new orders keep today's lead time",
    ("incident", "confirm_dates_hold"): "dates confirmed or re-dated", ("incident", "accept"): "PO lines take the new dates",
    ("incident", "second_source"): "only after qualification",
    ("risk", "open_terms"): "open lines keep coming, no prepayment", ("risk", "bridge"): "covers the need while the quote holds",
    ("risk", "second_source"): "only after qualification", ("risk", "recheck"): "nothing changes until the date",
    ("consignment", "earlier_date"): "an earlier material date moves the build", ("consignment", "cm_partial"): "the build starts on partial receipt",
    ("consignment", "direct_air"): "material reaches the maker sooner", ("consignment", "cm_stock"): "known after the maker's answer",
    ("closure", "pull_in"): "late lines ship before the closure", ("closure", "accept"): "PO lines take the new date",
    ("price_lock", "buy_ahead"): "open lines keep today's price", ("price_lock", "accept"): "the new price applies",
    ("price_lock", "extend"): "known after the supplier's reply",
    ("deadline:quotes", "bridge"): "covers the need at the quoted price", ("deadline:quotes", "extend"): "known after the reply",
    ("deadline:quotes", "lapse"): "the quote ends", ("deadline:quotes", "accept"): "the quoted terms apply",
    ("deadline:chase", "ship_date"): "known after the reply", ("deadline:chase", "accept_date"): "the PO line takes the new date",
    ("deadline:chase", "reorder"): "the line is cancelled; a new order",
    ("tariff:all", "ship_before"): "no duty on what enters in time", ("tariff:all", "switch_origin"): "no duty if the new origin holds",
    ("tariff:all", "prove_origin"): "duty set by the proven origin", ("tariff:all", "broker_exclusion"): "known after the broker's answer",
    ("tariff:all", "accept"): "the duty is budgeted",
    ("unknown:origin", "ask_origin"): "duty set by the certificate", ("unknown:origin", "enter_answer"): "the part's duty is recomputed",
    ("unknown:hts", "ask_broker"): "known after the broker's answer", ("unknown:hts", "enter_answer"): "the part's duty is recomputed",
    ("unknown:stale-orders", "ask_receiving"): "known after Receiving's answer", ("unknown:stale-orders", "close"): "left out of supply",
    ("unknown:stale-orders", "cancel"): "left out of supply and duty",
}


def _alternates_on_file(session: Session, ident: str, parts: list[str]) -> list[tuple[str, str]]:
    """(supplier id, part) for each part the notice hits that another supplier has already delivered on a PO line: a second source on file, not a quote."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.domain.orders.model import PoLine  # noqa: PLC0415

    rows = session.execute(select(PoLine.identity_id, PoLine.part_number).where(PoLine.part_number.in_(parts), PoLine.identity_id != ident).distinct()).all()
    return sorted({(sid, part) for sid, part in rows if sid})


ON_TIME_FLOOR = 0.60   # BUYER D4: below this on-time share a second source is started beside any route


def _second_source_why(session: Session, ident: str | None, parts: list[str]) -> str:
    """Why a second source is started beside the chosen route (BUYER D4), or "": the supplier is the only source on file (PO lines and quotes) of a part
    the case hits, or it delivers on time on less than 60% of its closed lines."""
    from sqlalchemy import or_, select  # noqa: PLC0415

    from app.domain.orders.model import PoLine  # noqa: PLC0415
    from app.domain.quotes.model import Offer  # noqa: PLC0415

    if not ident:
        return ""
    sole = [p for p in parts if not session.scalar(select(PoLine.id).where(PoLine.part_number == p, PoLine.identity_id != ident).limit(1))
            and not session.scalar(select(Offer.id).where(Offer.part_number == p, or_(Offer.identity_id != ident, Offer.identity_id.is_(None))).limit(1))]
    perf = suppliers.delivery_performance(session).get(ident)
    why = []
    if sole:
        why.append(f"sole source of {', '.join(sole[:3])}{f' (+{len(sole) - 3})' if len(sole) > 3 else ''}")
    if perf and perf.n and perf.on_time_pct < ON_TIME_FLOOR:
        why.append(f"on time on {round(perf.on_time_pct * 100)}% of {perf.n} lines")
    return " · ".join(why)


def _china(o) -> bool:
    """The offer's goods are China-origin, or claimed so: a settled ISO origin, else the country its claim names first."""
    return o.origin == "CN" or (o.origin is None and (o.origin_claim or "China").split(";")[0].split("(")[0].strip().lower() in ("china", "cn", "prc"))


def alternate_origins(session: Session) -> list[dict]:
    """BUYER T2: for each part with duty owed, the cheapest offer on file whose origin is not China, when it lands cheaper than the cheapest China-origin
    column with the duty (compare_offers' totals); largest duty first. Each: part, owed, offer view, landed, with_duty."""
    from app.domain.quotes import service as quotes  # noqa: PLC0415
    from app.domain.tariffs import service as tariffs  # noqa: PLC0415

    out = []
    for e in tariffs.all_exposures(session):
        owed = float(getattr(e.owed, "usd", 0) or 0) + float(getattr(e.conditional, "usd", 0) or 0)
        if e.status != "china_listed" or not owed:
            continue
        cols = quotes.compare_offers(session, e.part.id).columns
        alt = [c for c in cols if not c.is_current and not _china(c.landed.offer)]
        cn = [c for c in cols if _china(c.landed.offer)]
        if not alt or not cn:
            continue
        a, c = min(alt, key=lambda x: float(x.landed.total_known_usd.usd)), min(cn, key=lambda x: float(x.landed.total_known_usd.usd))
        if float(a.landed.total_known_usd.usd) < float(c.landed.total_known_usd.usd):
            out.append(dict(part=e.part.id, owed=owed, offer=a.landed.offer, landed=float(a.landed.total_known_usd.usd), with_duty=float(c.landed.total_known_usd.usd)))
    return sorted(out, key=lambda x: -x["owed"])


def _fixed_duty(session: Session, key: str, owner: str | None) -> str:
    """The duty that no route avoids, from the case's own figures: the viewer's fixed share (duty_share_fixed:<buyer>), else the team's duty owed on
    lines that cannot ship in time (duty_owed_fire:*); worded with the date its label gives. "" when there is none."""
    import re  # noqa: PLC0415

    detail = service.item_detail(session, key)
    if detail is None:
        return ""
    nums = detail.numbers or []
    mine = [n for n in nums if owner and n.id == f"duty_share_fixed:{owner.split()[0]}"]
    picked = mine or ([] if owner and any(n.id.startswith("duty_share_fixed:") for n in nums) else [n for n in nums if n.id.startswith("duty_owed_fire:")])
    total = sum(float(getattr(n.value, "usd", 0) or 0) for n in picked)
    if total <= 0:
        return ""
    when = next((m.group(1) for n in picked if (m := re.search(r"cannot ship before ([A-Z][a-z]{2} \d{1,2})", n.label or ""))), None)
    money = f"${total / 1000:,.0f}K" if total >= 10_000 else f"${total:,.2f}"
    return f"{money} is owed on lines that cannot ship before {when}" if when else f"{money} is owed on lines that cannot ship in time"


def frame_kind(session: Session, key: str) -> str:
    """The kind of case whose table applies: fire, slip, risk, price_lock (from the detector), else the item key itself (deadline:chase, tariff:all, …)."""
    return case_kind(session, key) or key


def _owns(session: Session, owner: str, part: str) -> bool:
    from app.domain.ownership import buyer_of_part  # noqa: PLC0415

    b = buyer_of_part(session, part)
    return owner.lower() in (b.lower(), service.buyer_name(session, b).lower(), service.buyer_name(session, b).split()[0].lower())


def option_kinds(session: Session, key: str, owner: str | None = None) -> list[OptionKind]:
    """The options of this item's kind of case, worded for this item; [] for an item whose kind has no table (trust, a message, a part)."""
    fk = frame_kind(session, key)
    rows = OPTION_KINDS.get(fk)
    if not rows:
        return []
    hit = service.item_context(session, key)
    item, ctx = hit if hit else (None, {})
    sups = [r for r in getattr(item, "refs", []) or [] if r.type == "supplier"]
    ident = ctx.get("ident") or (sups[0].id if len(sups) == 1 else None)          # one supplier: the item's; a roll-up over several has none
    who = ctx.get("who") or (naming.supplier_name(session, ident) if ident else "the supplier")
    contact = suppliers.contact_on_file(session, ident).name if ident else None   # the contact on file, never a message's sender
    owners = (getattr(item, "owner", "") or "").split(" · ")
    holder = getattr(ctx.get("c"), "holder", None)                                  # a consignment: the contract manufacturer that holds the material
    if fk == "consignment":
        ident = next((r.id for r in sups if not holder or r.id != holder.id), None)
        who = naming.supplier_name(session, ident) if ident else who
        contact = suppliers.contact_on_file(session, ident).name if ident else None
    maker = naming.supplier_name(session, holder.id) if holder else "the maker"
    maker_contact = suppliers.contact_on_file(session, holder.id).name if holder else None
    fill = {"who": who, "maker": maker, "promised": service.md(ctx["promised"]) if ctx.get("promised") else "the promised date", "part": "", "month": "October"}
    rows = list(rows)
    if fk == "fire" and ident:   # a second source already on a PO line for a part the notice hits: named first among the alternates
        for sid, part in _alternates_on_file(session, ident, list(ctx.get("parts") or []))[:1]:     # a buy from the other supplier, not an allocation (Khalid: "two allocation requests, I don't understand")
            rows.insert(1, ("alternate_on_file", f"Buy from {naming.supplier_name(session, sid)} ({part})", "request", f"supplier:{sid}"))
            fill["part"], fill["alt"] = part, naming.supplier_name(session, sid)
    changes = dict(CHANGES)
    dated: dict[str, str] = {}
    rows = [r for r in rows if r[0] != "order_before"]
    if fk in ("fire", "slip", "incident", "risk") and ident:   # a lead-time cutoff in the supplier's own notice that would leave need uncovered: a route of its own, any kind of disruption
        from app.domain.attention.findings import notice_lead_time  # noqa: PLC0415
        from app.domain.attention.options import order_before  # noqa: PLC0415

        ob = order_before(session, ident, who, owners[0] or "the buyer")
        if ob is not None:
            rows.append(("order_before", "Order before the lead-time cutoff", "note", "owner"))
            changes[(fk, "order_before")] = notice_lead_time(session, ident) or CHANGES[("slip", "order_before")]
            dated["order_before"] = ob.earliest.date
    also_why = {k: f"order by {service.md(d)}, on or before the act-by" for k, d in dated.items() if getattr(item, "act_by", None) and d <= item.act_by}
    if fk in ("fire", "slip", "incident", "risk") and ident:      # a second source is never an alternative to the supplier ask when the supplier is the only source or often late (BUYER D4)
        why = _second_source_why(session, ident, list(ctx.get("parts") or []) or sorted(ctx.get("impacts") or []) or sorted(ctx.get("sole") or []))
        if why:
            also_why["second_source"] = why
            if fill.get("alt"):      # the other supplier has delivered this part before: a second plant for it, not the sole-source text about other parts
                also_why["alternate_on_file"] = f"{fill['alt']} has supplied {fill['part']} on a PO before: a second plant for that part"
        first = next((r for r in rows if r[2] == "request" and r[3] == "supplier"), None)      # the supplier's own ask: whatever route she picks, it goes beside it
        n = len(getattr(service.item_detail(session, key), "po_lines", None) or [])
        owes = {"allocation": "revised dates and allocation", "confirm_dates_hold": "confirmation of its new dates", "open_terms": "firm dates on normal terms"}
        if first is not None and first[0] in owes:
            rights = "; asking keeps your rights" if fk in ("fire", "slip", "incident") else ""
            also_why[first[0]] = f"{who} still owes {owes[first[0]]} for the {n} lines{rights}" if n else f"{who} still owes {owes[first[0]]}{rights}"
    linked: dict[str, list[EntityRef]] = {}
    if fk == "tariff:all":      # an alternate origin on file that lands cheaper than China with the duty: named, linked to its quote, ranked above the broker exclusion
        alts = alternate_origins(session)
        if owner:      # the viewer's slice: her parts lead, the rest follow
            alts = sorted(alts, key=lambda a: not _owns(session, owner, a["part"]))
        if alts:
            top = alts[0]
            name = lambda o: naming.supplier_name(session, o.supplier.id) if o.supplier else naming.firm_name(o.supplier_name)  # noqa: E731
            rows = [(k, f"Alternate origin · {name(top['offer'])} ({top['part']})", lt, to) if k == "switch_origin" else (k, lbl, lt, to) for k, lbl, lt, to in rows]
            changes[(fk, "switch_origin")] = " · ".join(f"{a['part']}: {name(a['offer'])} ${a['landed']:,.2f} landed vs ${a['with_duty']:,.2f} with the duty" for a in alts[:2]) \
                + (f" · {len(alts) - 2} more" if len(alts) > 2 else "") + "; no duty if the origin holds"
            linked["switch_origin"] = [r for a in alts for r in (a["offer"].message, EntityRef(type="part", id=a["part"]))]
        else:       # no cheaper quote from another origin on file: the exclusion comes first
            sw = next((r for r in rows if r[0] == "switch_origin"), None)
            if sw:
                rows = [r for r in rows if r[0] != "switch_origin"]
                rows.insert(next((i + 1 for i, r in enumerate(rows) if r[0] == "broker_exclusion"), len(rows)), sw)
    if fk == "consignment":      # D6: when stock is the open unknown, the stock check answers the question the case is built on: started beside the chosen route
        det = service.item_detail(session, key)
        stock = next((u for u in (getattr(det, "unknowns", None) or []) if "stock" in (u.what or "").lower()), None)
        if stock is not None:
            also_why["cm_stock"] = f"the records hold no {stock.what}"
    if fk == "tariff:all":      # T3: duty on lines that cannot ship before the duty starts is fixed: budgeting it starts beside whichever route the buyer chooses
        fixed = _fixed_duty(session, key, owner)
        if fixed:
            also_why["accept"] = fixed
    out = []
    for kind, label, leads_to, to in rows:
        if to.startswith("supplier:"):
            sid = to.split(":", 1)[1]
            c = suppliers.contact_on_file(session, sid).name
            whom = f"{c} ({naming.supplier_name(session, sid)})" if c else "its contact on file"
        else:
            whom = {"supplier": f"{contact} ({who})" if contact else "each supplier's contact on file",
                    "maker": f"{maker_contact} ({maker})" if maker_contact else f"{maker}'s contact on file",
                    "owner": owners[0] if len(owners) == 1 and owners[0] else "each line's buyer"}.get(to, to)
        button = {"request": "Write the email", "note": f"Write a note to {whom}" if to != "owner" else "Write the note", "record": "Record decision"}[leads_to]
        out.append(OptionKind(kind=kind, label=label.format(**fill), leads_to=leads_to, to=whom if leads_to != "record" else "", button=button,
                              erp=(fk, kind) in _ERP or kind == "order_before", changes=changes.get((fk, kind), "").format(**fill),
                              by=dated.get(kind), also_start=kind in also_why, also_why=also_why.get(kind, ""), refs=linked.get(kind, [])))
    return out
