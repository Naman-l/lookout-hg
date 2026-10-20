"""The Decision table's figures for every kind of case (FINAL-SPEC §2: Route · Covers · Earliest · Cost · Goes to, the same columns for every kind).
A disruption's ways through are computed in `options`; every other kind's routes take their figures here from what the case already holds: its own
numbers (cited by id, never recomputed), its PO lines, the quotes on file, and code dates (the reply an email asks for). Where the records hold no
figure the field is empty and its basis says so ("not in the records"); nothing is estimated and no model writes any of it."""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.orm import Session

from app.domain.attention import service
from app.domain.attention.schema import DateValue, FireOption
from app.domain.common import AS_OF
from app.domain.values import prov, usd

NOT_KNOWN = "not in the records"


def _num(detail, prefix: str):
    return next((n for n in detail.numbers if n.id == prefix or n.id.startswith(prefix + ":")), None)


def _date(d: str, rule: str, inputs=None) -> DateValue:
    return DateValue(date=d[:10], provenance=prov("computed", "action_items", rule=rule, inputs=inputs or [], by="attention.route_figures"))


def _count(detail) -> str | None:
    n = _num(detail, "tile:count")
    if n is None:
        return None
    what = n.label.lower().removeprefix("how many ").strip() or "items"
    return f"{int(float(n.value.value))} {what}"


_REPLY = re.compile(r"\breply\b[^.]{0,40}?\bby (\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December)\b", re.I)
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _route_drafts(session: Session, key: str, kind: str) -> list:
    """The waiting emails a request route sends: to the route's recipient on file, on this case (a roll-up: every request on it)."""
    from app.domain.actions import ledger, routes  # noqa: PLC0415

    DB_PATH = session.get_bind().url.database      # the drafts of the database this session reads, never another one
    from app.domain.suppliers import service as suppliers  # noqa: PLC0415

    hit = service.item_context(session, key)
    if hit is None:
        return []
    mine = [a for a in ledger.list_actions(DB_PATH, "proposed") if a.type == "supplier_request" and (a.item_key == key or key in ledger.asks_of(a))]
    sid, _ = routes._recipient(session, key, kind, hit[1], hit[0])
    if sid is None:
        return mine
    email = suppliers.contact_on_file(session, sid).email
    return [a for a in mine if email and a.recipient == email]


def _reply_by_in(body: str | None):
    """The reply-by date the email itself asks for (its year: the data date's, or the next one for a month already past)."""
    from datetime import date  # noqa: PLC0415

    days = []
    for m in _REPLY.finditer(body or ""):      # one letter, one date: the earliest it asks for (BUYER D7)
        d = date(AS_OF.year, _MONTHS.index(m.group(2).capitalize()) + 1, int(m.group(1)))
        days.append(d if d >= AS_OF else date(AS_OF.year + 1, d.month, d.day))
    return min(days) if days else None


def _named_lines(detail, bodies: list[str]) -> int:
    """How many of the case's PO lines the emails name ("<PO>/<line>" or "<PO> lines 10, 20 and 30")."""
    text = "\n".join(b or "" for b in bodies)
    n = 0
    for l in detail.po_lines or []:
        po, _, ln = l.ref.id.partition("/")
        if l.ref.id in text or re.search(rf"{re.escape(po)},? lines? (?:\d+(?:, | and | & ))*{int(ln) if ln.isdigit() else ln}\b", text):
            n += 1
    return n


def _viewer_slice(session: Session, detail, owner: str | None):
    """A team roll-up under a viewer (R-1, like T1): its lines, its count and its stake are the viewer's own, as the header shows them; the team's
    figures only with no viewer."""
    if not owner or " · " not in (detail.owner or ""):
        return detail
    mine = next((i for i in service.what_needs_attention(session, owner) if i.key == detail.key), None)
    lines = [l for l in detail.po_lines or [] if getattr(l, "buyer", None) == owner]
    nums = [n for n in detail.numbers if not n.id.startswith(("chase:", "tile:count"))]      # team counts and totals leave; the viewer's come from her slice
    hit = service.item_context(session, detail.key)
    members = [m for m, _ in (hit[1].get("members") or [])] if hit else []
    own = [m for m in members if (m.owner or "") == owner]
    if members:
        count = next((n for n in detail.numbers if n.id == "tile:count"), None)
        if count is not None:
            nums.append(count.model_copy(update={"value": count.value.model_copy(update={"value": len(own)})}))
    stake = getattr(mine, "at_stake", None) if mine is not None and getattr(getattr(mine, "at_stake", None), "usd", None) is not None else None
    if stake is not None and any(n.id == "chase:open_total" for n in detail.numbers):
        nums.append(next(n for n in detail.numbers if n.id == "chase:open_total").model_copy(update={"id": f"chase:open_total:{owner.split()[0]}", "value": stake,
                                                                                                    "label": "Open value of your lines waiting on a date"}))
    return detail.model_copy(update={"po_lines": lines, "numbers": nums, "at_stake": stake or detail.at_stake})


def _lines(n: int) -> str:
    return f"{n} PO line{'' if n == 1 else 's'}"


def _covers(detail, kind: str, leads_to: str) -> str | None:
    if detail.key == "tariff:all":      # the roll-up's lines on the page are a sample: what a route covers there is said per route below
        return "all the duty owed" if kind == "accept" else None
    if leads_to == "record" and kind in ("wait", "recheck", "lapse", "accept", "enter_answer"):
        base = _lines(len(detail.po_lines)) if detail.po_lines else _count(detail)
        return f"all {base}" if base else None
    if detail.po_lines:
        return _lines(len(detail.po_lines))
    quotes = [n for n in detail.numbers if n.id.startswith("act_by:deadline:")]
    if quotes:
        return f"{len(quotes)} quotes"
    return _count(detail)


def figures(session: Session, key: str, owner: str | None = None) -> list[FireOption]:
    """One row per route of the case's code table, in its order, for a case that is not a disruption (a disruption's rows come from `options`)."""
    from app.domain.actions.routes import reply_by  # noqa: PLC0415
    from app.domain.attention import option_kinds  # noqa: PLC0415

    detail = service.item_detail(session, key)
    if detail is None:
        return []
    detail = _viewer_slice(session, detail, owner)
    table = option_kinds.option_kinds(session, key, owner)
    act = detail.act_by
    out = []
    for t in table:
        named = re.search(r"\(([^()]+)\)$", t.label)        # a route named for one part ("Allocation request · <supplier> (<part>)") covers that part only
        covers = f"{named.group(1)} only" if named and key != "tariff:all" else None if t.kind == "bridge" else _covers(detail, t.kind, t.leads_to)
        row = FireOption(kind=t.kind, label=t.label, covers=covers, refs=list(t.refs))
        if t.leads_to == "request":
            drafts = _route_drafts(session, key, t.kind)
            asked = sorted(d for d in (_reply_by_in(a.body) for a in drafts) if d)
            if asked:      # the prepared email's own date: what the supplier was actually asked (AI-UI-SYNC G2)
                row.earliest = DateValue(date=asked[0].isoformat(), provenance=prov("extracted", "actions", rule="the reply-by date the prepared email asks for", by="attention.route_figures"))
                row.earliest_basis = "the reply the prepared email asks for"
            else:
                row.earliest = _date(reply_by(act).isoformat(), "the reply the email asks for: two weeks before the act-by, never sooner than five days from the data date")
                row.earliest_basis = "the supplier's reply, asked for by this date"
            named = _named_lines(detail, [a.body for a in drafts]) if drafts and detail.po_lines else 0
            if named and row.covers and row.covers.endswith(("PO line", "PO lines")):      # the lines the prepared emails name, not the case's count (G3)
                row.covers = _lines(named)
        elif t.leads_to == "record":
            row.earliest_basis = "takes effect when recorded"
        else:
            row.earliest_basis = f"when the note is acted on ({NOT_KNOWN})"
        if t.kind == "recheck" and act:
            row.earliest, row.earliest_basis = _date(act, "the case's act-by: the date to look again"), "the re-check date"
        if t.kind in ("pull_in", "buy_ahead") and act:
            row.earliest, row.earliest_basis = _date(act, "the case's act-by"), "by the act-by the supplier set"
        row.cost_basis = NOT_KNOWN
        # cost, from the case's own figures (cited by number id in the provenance), per kind of route
        if t.kind == "buy_ahead":      # R-2: what the acknowledgement keeps today's price on is the need open orders don't cover, as its cost says
            row.covers = "the need open orders don't cover"
        if t.kind == "buy_ahead" and detail.at_stake is not None:
            row.cost_delta, row.cost_basis = usd(-float(detail.at_stake.usd), prov("computed", "action_items", rule="the rise the acknowledgement avoids: the case's at-stake, negated", by="attention.route_figures")), f"kept by ordering the need open orders don't cover by {service.md(act)}, at today's price" if act else "kept by ordering the uncovered need at today's price"
        elif t.kind == "accept" and key.startswith("deadline:") and detail.at_stake is not None and _num(detail, "price_increase_pct"):
            row.cost_delta, row.cost_basis = detail.at_stake, "the announced rise on the need open orders don't cover"
        elif key == "tariff:all":
            owed, late = _num(detail, "tile:owed"), _num(detail, "tile:if_late")
            fixed = _num(detail, f"duty_share_fixed:{owner.split()[0]}") if owner else None
            if t.kind == "accept" and fixed is not None:      # the viewer's slice (G1): what she budgets is her share that cannot be avoided
                row.cost, row.cost_basis, row.covers = fixed.value, f"your duty on lines that cannot ship before it starts [{fixed.id}]", "your fixed share"
            elif t.kind == "accept" and owner:      # T1: under a viewer never the team total: her own share, or nothing with the reason
                first = owner.split()[0]
                share = _num(detail, f"duty_share_open:{first}") or _num(detail, f"duty_share:{first}")
                if share is not None:
                    row.cost, row.cost_basis, row.covers = share.value, f"your share of the duty owed [{share.id}]", "your share"
                else:
                    row.cost, row.cost_basis, row.covers = None, "your share of the duty is not in the records", "your share"
            elif t.kind == "accept" and owed is not None:
                row.cost, row.cost_basis = owed.value, "the duty owed, budgeted [tile:owed]"
            elif t.kind == "ship_before" and late is not None:
                row.cost_delta, row.cost_basis = usd(-float(late.value.usd), prov("computed", "action_items", rule="duty avoided if the open orders ship before the duty starts [tile:if_late], negated", by="attention.route_figures")), "duty avoided if they ship in time"
            elif t.kind == "switch_origin" and t.refs:
                alts = option_kinds.alternate_origins(session)
                if owner:
                    alts = sorted(alts, key=lambda a: not option_kinds._owns(session, owner, a["part"]))
                a = alts[0] if alts else None
                if a:
                    row.covers = f"{a['part']}" + (f" (+{len(alts) - 1} parts)" if len(alts) > 1 else "")
                    row.cost_delta = usd(a["landed"] - a["with_duty"], prov("computed", "offers", rule="landed per piece from the other origin minus the cheapest China column with the duty (compare_offers)", inputs=[a["offer"].message], by="attention.route_figures"))
                    row.cost_basis = "per piece, landed vs China with the duty"
                    lt = a["offer"].lead_time
                    if lt and getattr(lt, "value", None) and str(lt.value).split()[0].isdigit():
                        days = int(str(lt.value).split()[0]) * (7 if "week" in str(lt.value) else 1)
                        row.not_before = _date((AS_OF + timedelta(days=days)).isoformat(), f"the data date plus the quote's lead time ({lt.value})", [a["offer"].message])
                        row.earliest_basis = f"{lt.value}" + (f" {lt.condition}" if getattr(lt, "condition", None) else "")
        elif key == "unknown:origin" and t.kind == "ask_origin":
            ifc = _num(detail, "tile:if_china")
            if ifc is not None:
                row.cost_basis = f"set by the certificate: ${float(ifc.value.usd):,.0f} if every part is China-origin [tile:if_china]"
        elif key == "deadline:chase" and t.kind in ("ship_date", "reorder", "accept_date"):
            tot = _num(detail, "chase:open_total")
            if tot is not None and t.kind == "ship_date":
                row.cost, row.cost_basis = tot.value, f"open value of the lines waiting on a date [{tot.id}]"
        elif key.startswith("deadline:SUP-") and t.kind == "pull_in":
            v = next((n for n in detail.numbers if n.id.startswith("closure_open_value:")), None)
            if v is not None:
                row.cost, row.cost_basis = v.value, "open value of the lines due through the closure"
        out.append(row)
    return out


def disruption_rows(session: Session, key: str, computed: list[FireOption], owner: str | None = None) -> list[FireOption]:
    """A disruption's routes in its code table's order: the ways computed in `options` with what each covers, and the table's other routes (confirm the
    dates hold, open terms, a bridge, a re-check) with the figures the case holds."""
    from app.domain.attention import option_kinds  # noqa: PLC0415

    built = {o.kind: o for o in disruption_covers(session, key, computed)}
    rest = {o.kind: o for o in figures(session, key, owner)}
    return [built.get(t.kind) or rest[t.kind] for t in option_kinds.option_kinds(session, key, owner) if t.kind in built or t.kind in rest]


def disruption_covers(session: Session, key: str, rows: list[FireOption]) -> list[FireOption]:
    """A disruption's ways through, with what each covers: the PO lines under the notice, the products laid out, the part a quote is for, the need a
    cutoff order covers."""
    hit = service.item_context(session, key)
    ctx = hit[1] if hit else {}
    detail = service.item_detail(session, key)
    n_lines = len(detail.po_lines or []) if detail else 0
    for o in rows:
        if o.covers:
            continue
        if o.kind in ("allocation", "air_freight") and n_lines:
            o.covers = _lines(n_lines)
        elif o.kind == "resequence" and o.products:
            o.covers = f"{len(o.products)} products"
        elif o.kind == "second_source":
            part = next((r.id for r in o.refs if r.type == "part"), None)
            o.covers = f"{part} only" if part else None
        elif o.kind == "order_before" and o.cost_basis:
            o.covers = o.cost_basis.split(" are on no open order")[0]
    return rows
