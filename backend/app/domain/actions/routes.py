"""The buyer chooses a route; the draft follows the choice (Khalid 2026-10-14: "the buyer drives the decision ... when the buyer decides, then the draft").
`choose` records the choice (an app action, append-only, who and when), then returns the route's prepared draft if the morning run already staged one,
else drafts it in code. A route drafted in code, with no model: the route's template filled from the case's records, to the route's real recipient (the code table's
`to`), in house style, staged `proposed` for the owner's signature like any draft. Used by the case page's "Also start" and "Draft this instead".

- leads_to "request": an email to the contact on file of the route's supplier (the case's, the maker's, or the other supplier the route names). One open
  thread per contact: a request still waiting to that address gets this route's ask as a paragraph (its owner must own this case too); one already
  approved or sent leaves room for a new request.
- leads_to "note": a note to the route's reader inside the company (planning, a buyer), "to enter in the ERP" where the route changes a PO or orders.
- leads_to "record": the buyer's decision on record, with the reason the buyer gives.
Every figure and date in the text is a record's (PO lines, promises, the act-by); the ask sentences are fixed per kind of route, like the labels.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.attention import option_kinds as kinds_table
from app.domain.attention import service
from app.domain.common import AS_OF
from app.domain.suppliers import service as suppliers
from app.organism import company

from . import approvers, ledger
from .letters import house_style
from .tools import _FORBIDDEN, insert_before_signoff, with_signature

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

# The ask each kind of request makes, as a buyer writes it. {lines} is "these lines" or the part named; {co} the company's short name.
ASKS: dict[str, str] = {
    "allocation": "Please give us a revised promise date and quantity for each of {lines}, and tell us how much you can allocate to {co} from capacity the notice does not cover, and by when.",
    "alternate_on_file": "Please tell us how many of {part} you could supply us in the coming weeks, at what price and by what dates.",
    "air_freight": "Please tell us whether any of {lines} can ship earlier by air, how many pieces, and from what date.",
    "confirm_dates_hold": "Please confirm that the dates on {lines} still hold, and give us a new promise date for any line that is already late.",
    "open_terms": "Please confirm firm ship dates for {lines} on our normal payment terms, with no payment before shipment.",
    "bridge": "Please confirm whether you can supply a bridge quantity of {part} at the quoted price, with no prepayment, and by what date.",
    "earlier_date": "Please tell us whether {lines} can ship earlier than the new dates, in full or in part, and how many pieces by which date.",
    "cm_partial": "Please tell us whether you can start building on a partial receipt of the consigned material, and how many pieces that would let you deliver, by when.",
    "cm_stock": "Please tell us how much of the consigned material you hold today, received and not yet used, and how many builds it covers.",
    "pull_in": "Please ship {lines} before the closure, and confirm the ship date for each.",
    "buy_ahead": "Please acknowledge {lines} at today's price, for delivery on the current dates.",
    "extend": "Please extend the validity of your quote, at the same prices and terms, and tell us the new date.",
    "ship_date": "Please give us a firm ship date for {lines}.",
    "ask_origin": "Please send us a certificate of origin for {part}.",
    "price_lock:extend": "Please tell us whether today's price can be extended past the date it changes, for {lines}.",
}


# What a waiting email already asks, per kind of route: when the email to that contact matches, the route is covered by it (chosen, not asked twice).
MARKERS: dict[str, str] = {
    "allocation": r"\ballocat", "alternate_on_file": r"could supply|how many of", "air_freight": r"\bby air\b|air[- ]freight|air[- ]ship",
    "confirm_dates_hold": r"\b(dates?)\b[^.]{0,60}\bhold", "open_terms": r"payment terms|no payment before|no prepayment", "bridge": r"\bbridge\b",
    "earlier_date": r"\bearlier\b", "cm_partial": r"partial receipt|partial start", "cm_stock": r"consigned material you hold|stock",
    "pull_in": r"before the closure", "buy_ahead": r"today's price", "extend": r"\bvalidity\b|\bextend", "ship_date": r"ship date",
    "ask_origin": r"certificate of origin",
}


def _covered(kind: str, text: str | None) -> bool:
    import re  # noqa: PLC0415

    return bool(MARKERS.get(kind) and re.search(MARKERS[kind], text or "", re.I))


def _before_reply_by(body: str, para: str) -> str:
    """The new ask goes before the reply-by paragraph, so the letter still ends on its date; with none, before the sign-off."""
    paras = body.split("\n\n")
    at = next((i for i, p in enumerate(paras) if p.lstrip().lower().startswith("please reply by") or " please reply by " in f" {p.lower()}"), None)
    return "\n\n".join([*paras[:at], para, *paras[at:]]) if at is not None else insert_before_signoff(body, para)


def _day(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]}"


def reply_by(act_by: str | None) -> date:
    """The reply asked for: two weeks before the act-by so the answer can still be acted on, never sooner than five days from the data date, never after
    the act-by; a case already due asks for three days (BUYER R2: never the act-by itself when there is time before it)."""
    if not act_by:
        return AS_OF + timedelta(days=5)
    due = date.fromisoformat(act_by[:10])
    if due <= AS_OF:
        return AS_OF + timedelta(days=3)
    return min(due, max(AS_OF + timedelta(days=5), due - timedelta(days=14)))


class RouteError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _route(session: Session, key: str, kind: str, by: str):
    for o in kinds_table.option_kinds(session, key, by):
        if o.kind == kind:
            return o
    raise RouteError(404, f"this case has no route '{kind}'")


def _recipient(session: Session, key: str, kind: str, ctx: dict, item) -> tuple[str | None, str]:
    """The supplier id the route writes to: the other supplier a route names, the maker on a consignment, else the case's own supplier."""
    rows = {k: to for k, _l, _lt, to in kinds_table.OPTION_KINDS.get(kinds_table.frame_kind(session, key), [])}
    to = rows.get(kind, "supplier")
    if kind == "alternate_on_file":
        alt = kinds_table._alternates_on_file(session, ctx.get("ident"), list(ctx.get("parts") or []))[:1]
        return (alt[0][0], alt[0][1]) if alt else (None, "")
    holder = getattr(ctx.get("c"), "holder", None)
    if to == "maker" and holder is not None:
        return holder.id, ""
    sups = [r.id for r in item.refs if r.type == "supplier"]
    if holder is not None:      # a consignment: the material's supplier, not the maker
        sups = [s for s in sups if s != holder.id]
    return (ctx.get("ident") or (sups[0] if len(sups) == 1 else None)), ""


def _lines_of(detail, sid: str | None) -> list:
    return [l for l in (detail.po_lines or []) if sid and l.supplier and l.supplier.id == sid]


def _line_row(l) -> str:
    q = int(l.qty.value) if l.qty and l.qty.value == int(l.qty.value) else l.qty.value
    when = f"promised {_day(date.fromisoformat(l.promise_date))}" if l.promise_date else "no promise date"
    if l.revised_date:
        when += f", now {_day(date.fromisoformat(l.revised_date))}"
    return f"{l.ref.id} · {l.part.id} · {q} {l.qty.uom} · {when}"


def _email(session: Session, db_path, key: str, kind: str, by: str, route, item, detail, ctx) -> tuple[ledger.Action, str]:
    sid, part = _recipient(session, key, kind, ctx, item)
    if not sid:
        raise RouteError(409, "this route names no supplier to write to")
    contact = suppliers.contact_on_file(session, sid)
    if not contact.email:
        raise RouteError(409, f"no contact on file for {naming.supplier_name(session, sid)}, so nothing can be drafted")
    full, co = company.names(db_path)
    lines = _lines_of(detail, sid)
    parts = sorted({l.part.id for l in lines}) or ([part] if part else [r.id for r in item.refs if r.type == "part"][:3])
    template = ASKS.get(f"{kinds_table.frame_kind(session, key)}:{kind}") or ASKS.get(kind)
    ask = template
    if ask is None:
        raise RouteError(409, f"no email template for the route '{kind}'")
    ask = ask.format(lines="these lines" if lines else (", ".join(parts) or "the parts below"), part=", ".join(parts) or "the part", co=co)
    by_day = reply_by(item.act_by)
    held = ledger.open_thread(db_path, contact.email)
    if held is not None and held.state == "proposed":        # one thread per contact: this route's ask joins the waiting request
        try:
            theirs = approvers.owners_of_action(db_path, held)
        except Exception:  # noqa: BLE001
            theirs = set()
        if theirs and by not in theirs and not set(approvers.owners_of(db_path, key) or set()) & theirs:
            raise RouteError(409, f"A request to {contact.name or contact.email} is waiting for {' and '.join(sorted(theirs))}'s signature ({held.action_id}): it is theirs to change.")
        done = set((held.change or {}).get("option_kinds") or ([(held.change or {}).get("option_kind")] if (held.change or {}).get("option_kind") else []))
        if kind in done or _covered(kind, held.body):
            return held, "covered"
        ask = template.format(lines="the lines above" if lines else (", ".join(parts) or "the parts above"), part=", ".join(parts) or "the part", co=co)
        asks = ledger.asks_of(held)
        change = {**(held.change or {}), "option_kinds": sorted(done | {kind}), "asks": asks + ([key] if key not in asks else []),
                  **({"amended_for": [*((held.change or {}).get("amended_for") or []), key]} if key != held.item_key else {})}
        body = house_style(_before_reply_by(held.body or "", ask), db_path=db_path, item_key=held.item_key or key, subject=held.subject or "", company_short=co, recipient=contact.email)
        return ledger.update_draft(db_path, held.action_id, subject=held.subject or "", body=body, edited_by=by, change=change), "amended"
    rows = [_line_row(l) for l in lines]
    body = f"Dear {contact.name or naming.supplier_name(session, sid)},\n\n" + (f"Our open order lines with you:\n" + "\n".join(rows) + "\n\n" if rows else "") \
        + f"{ask}\n\nPlease reply by {_day(by_day)}.\n\nRegards,"
    body = with_signature(body, by, full)
    head = "Quote request" if kind == "alternate_on_file" else route.label.split(" · ")[0]      # the buyer's label names the supplier ("Buy from …"); the supplier reads a request
    subject = head + (": " + ", ".join(sorted({l.ref.id.split("/")[0] for l in lines})) if lines else f": {', '.join(parts)}" if parts else "")
    if _FORBIDDEN.search(f"{subject} {body}"):
        raise RouteError(422, "a draft may not mention bank details or payments")
    body = house_style(body, db_path=db_path, item_key=key, subject=subject, company_short=co, recipient=contact.email)
    a = ledger.propose(db_path, type="supplier_request", item_key=key, run_id=None, target=ledger.EntityRef(type="supplier", id=sid), recipient=contact.email,
                       subject=subject, body=body, change={"owner": by, "option_kind": kind, "option_kinds": [kind]})
    return a, "drafted"


def draft_route(session: Session, db_path, key: str, kind: str, by: str, reason: str = "") -> tuple[ledger.Action, str]:
    """Draft one route of a case for its owner `by` (a full name). Returns (the draft, how: "drafted", "amended" (the ask added to the request waiting
    to that contact) or "covered" (that request already asks it))."""
    if key.startswith("trust:"):
        raise RouteError(409, "nothing is drafted on a trust item: phone the contact on file")
    hit = service.item_context(session, key)
    if hit is None:
        raise RouteError(404, "no such item")
    item, ctx = hit
    try:
        owners = approvers.owners_of(db_path, key)
    except (approvers.NoOwner, approvers.OwnerLookupError) as e:
        raise RouteError(409, f"Nobody can sign this now: {e}") from e
    if owners and by not in owners:
        raise RouteError(403, f"This case belongs to {' and '.join(sorted(owners))}: only they can draft for it, and you are {by}.")
    route = _route(session, key, kind, by)
    detail = service.item_detail(session, key)
    if route.leads_to == "request":
        return _email(session, db_path, key, kind, by, route, item, detail, ctx)
    text = f"{route.label}" + (f": {route.changes}" if route.changes else "") + "."
    lines = [l.ref.id for l in (detail.po_lines or [])][:12]
    if lines and route.leads_to == "note":
        text += " PO lines: " + ", ".join(lines) + "."
    if route.erp:
        text += " To enter in the ERP."
    if route.leads_to == "record":
        if not reason.strip():
            raise RouteError(422, "a decision on record needs a reason")
        change = {"kind": "record", "to": None, "reason": reason.strip(), "lines": None, "recheck_on": None, "option_kind": kind, "owner": by}
        return ledger.propose(db_path, type="note", item_key=key, run_id=None, target=None, recipient=None, subject="Decision", body=text, change=change), "drafted"
    change = {"kind": "note", "to": route.to or None, "reason": reason.strip() or None, "lines": None, "recheck_on": None, "option_kind": kind, "owner": by}
    return ledger.propose(db_path, type="note", item_key=key, run_id=None, target=None, recipient=None, subject=f"Note to {route.to}", body=text, change=change), "drafted"


def _owned_by(db_path, a, by: str) -> bool:
    """The buyer choosing signs this draft: a draft another buyer owns is never handed back as theirs."""
    try:
        owners = approvers.owners_of_action(db_path, a)
    except Exception:  # noqa: BLE001
        return False
    return not owners or by in owners


def _prepared(session: Session, db_path, key: str, kind: str, route, ctx, item, by: str) -> ledger.Action | None:
    """A draft already waiting for this route on this case: one staged for its kind, or (a run's email carries no kind) the waiting request to the route's
    own recipient, the one thread with that contact."""
    mine = [a for a in ledger.list_actions(db_path, "proposed") if (a.item_key == key or key in ledger.asks_of(a)) and _owned_by(db_path, a, by)]
    for a in mine:
        ch = a.change or {}
        if kind == ch.get("option_kind") or kind in (ch.get("option_kinds") or []):
            return a
    if route.leads_to == "request":
        sid, _ = _recipient(session, key, kind, ctx, item)
        email = suppliers.contact_on_file(session, sid).email if sid else None
        return next((a for a in mine if a.type == "supplier_request" and email and a.recipient == email and not (a.change or {}).get("option_kind")
                     and _covered(kind, a.body)), None)      # the run's email is this route's only when it already asks it; otherwise the route's ask is added to it (_email)
    return None


def choose(session: Session, db_path, key: str, kind: str, by: str, reason: str = "") -> tuple[ledger.Action, str]:
    """Record that `by` chose route `kind` on case `key`, and return its draft with how it came: "prepared" (the run's, unchanged), "drafted" (new, in code)
    or "amended" (the route's ask added to the request already waiting to that contact)."""
    if key.startswith("trust:"):
        raise RouteError(409, "nothing is drafted on a trust item: phone the contact on file")
    hit = service.item_context(session, key)
    if hit is None:
        raise RouteError(404, "no such item")
    item, ctx = hit
    try:
        owners = approvers.owners_of(db_path, key)
    except (approvers.NoOwner, approvers.OwnerLookupError) as e:
        raise RouteError(409, f"Nobody can sign this now: {e}") from e
    if owners and by not in owners:
        raise RouteError(403, f"This case belongs to {' and '.join(sorted(owners))}: only they can choose for it, and you are {by}.")
    route = _route(session, key, kind, by)
    draft, how = _prepared(session, db_path, key, kind, route, ctx, item, by), "prepared"
    many = []
    if draft is None and route.leads_to == "request" and _recipient(session, key, kind, ctx, item)[0] is None:   # a roll-up over several suppliers: the run's one request per supplier
        all_ = [a for a in ledger.list_actions(db_path, "proposed") if a.type == "supplier_request" and (a.item_key == key or key in ledger.asks_of(a))]
        many = [a for a in all_ if _owned_by(db_path, a, by)]      # the chooser's own suppliers' requests; another buyer's are theirs to choose
        if not many:
            raise RouteError(409, "no request on this case is yours to sign" + (f" (they belong to {', '.join(sorted({o for a in all_ for o in (approvers.owners_of_action(db_path, a) or [])}))})" if all_ else "")
                             + ": choose the route on each supplier's own case")
        draft = many[0]
    for extra in many[1:]:
        ledger.record_app_action(db_path, type="note", item_key=key, target=None, body=f"Chose: {route.label}", by=by,
                                 change={"kind": "choice", "option_kind": kind, "action_id": extra.action_id, "how": "prepared"})
    if draft is None:
        draft, how = draft_route(session, db_path, key, kind, by, reason)
    ledger.record_app_action(db_path, type="note", item_key=key, target=None, body=f"Chose: {route.label}", by=by,
                             change={"kind": "choice", "option_kind": kind, "action_id": draft.action_id, "how": how})
    return ledger.get(db_path, draft.action_id), how
