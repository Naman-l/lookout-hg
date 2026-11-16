"""The shared SCM inbox: each message with its sender class (vendor on file, a colleague on the company domain, a look-alike, a stranger), its
trust verdict (computed in code by the recipe before anyone reads it), what kind of message it is and what it means in one line, the dates it carries,
the PR and PO lines it moves, the Today case it feeds and who owns it. A held message is shown as quoted data only."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.annotate import service as annotate
from app.domain.cache import memo
from app.domain.fmt import dmy, inr, md, qty_text
from app.domain.inbox import trust as trust_rules
from app.domain.inbox.model import Message, MessageEvent, MessageRef
from app.domain.inbox.schema import DatedFact, LineMove, Match, MessageDetail, MessageSummary, QuoteFacts, RelatedStage, SentLetter
from app.domain.values import money, prov, ref

# What a message is, read from the facts it states: the first kind in this order whose fact the message carries.
KINDS = [("remittance_change", "Payment to a new account"), ("short_close_instruction", "Cancellation instruction"), ("reasons", "Cancellation reasons"),
         ("mfc_needed_by", "MFC request"), ("inspection_call", "Inspection call"), ("pv_claim", "PV claim"), ("price_change", "Price notice"),
         ("lc_deadline", "LC request"), ("guarantee_expiry", "ABG reminder"), ("inspection_failed", "Inspection failure"), ("closure", "Quarry closure"),
         ("strike", "Strike"), ("warranty_end", "Warranty notice"), ("fund_mismatch_reported", "Fund mismatch"), ("promise_revision", "Revised schedule"),
         ("spec_awaited", "Spec chase"), ("rename", "Change of name"), ("needed_by", "PR request"), ("quote_validity", "Quote"), ("reply", "Reply")]
DATE_WORDS = {"mfc_needed_by": "MFC wanted by", "po_validity": "PO firm to", "inspection_call": "Inspection", "price_lock": "Acknowledge orders by",
              "quote_validity": "Quote valid to", "lc_deadline": "Open the LC by", "guarantee_expiry": "ABG expires", "warranty_end": "Warranty ends",
              "deadline": "Asked by", "needed_by": "Needed at site", "rfq_sent": "RFQ dated", "supplied_on": "Delivered", "rename": "New company from",
              "rename_invoices_from": "Old entity invoices until", "price_change": "New price from", "closure": "Closed from", "strike": "Strike from"}


@memo
def _events(session: Session) -> dict[str, list[MessageEvent]]:
    out: dict[str, list[MessageEvent]] = {}
    for e in session.scalars(select(MessageEvent).order_by(MessageEvent.id)):
        out.setdefault(e.message_id, []).append(e)
    return out


def kind_of(session: Session, m: Message) -> str:
    if m.id.startswith("sim-"):
        return "Reply (simulated)"
    kinds = {e.kind for e in _events(session).get(m.id, [])}
    from app.domain.quotes.service import mail_quotes  # noqa: PLC0415

    if m.trust == "blocked" and mail_quotes(session, m.id):
        return "Spot offer"
    if m.sender_class == "lookalike_internal":
        return "Urgent transfer request"
    if mail_quotes(session, m.id) and "quote_validity" in kinds:
        return "Quote"
    return next((w for k, w in KINDS if k in kinds), "Message")


def means(session: Session, m: Message) -> str:
    """What it means, in one line, from the facts the recipe read (each with its line)."""
    ev = {e.kind: e for e in _events(session).get(m.id, [])}
    k = kind_of(session, m)
    if m.trust == "blocked":
        flags = [trust_rules.FLAG_WORDS.get(f, f) for f in (m.trust_flags or "").split(",") if f in trust_rules.BLOCK]
        claim = ev.get("remittance_change")
        return f"Held: {'; '.join(flags)}" + (f". It asks for {inr(claim.qty, exact=True)}." if claim else ".")
    if k == "MFC request":
        return f"The vendor wants the MFC by {md(ev['mfc_needed_by'].date_to)}; the PO is firm only to {md(ev['po_validity'].date_to)}" + (
            f", {inr(ev['price_claim'].qty)} more after that." if "price_claim" in ev else ".")
    if k == "Inspection call":
        return f"Inspection on {md(ev['inspection_call'].date_to)}; {int(ev['free_storage_days'].qty)} days' free storage, then {inr(ev['storage_rate'].qty)} a day." if "storage_rate" in ev else "An inspection call."
    if k == "PV claim":
        return f"Claims {inr(ev['pv_claim'].qty, exact=True)} of price variation, on a base month of {ev['pv_claim_base'].date_from}." if "pv_claim_base" in ev else "A PV claim."
    if k == "Price notice":
        return f"+₹{int(ev['price_change'].qty):,}/MT from {md(ev['price_change'].date_from)}" + (f"; orders acknowledged by {md(ev['price_lock'].date_to)} keep today's rate." if "price_lock" in ev else ".")
    if k == "LC request":
        return f"Open the LC for {inr(ev['lc_deadline'].qty)} by {md(ev['lc_deadline'].date_to)}, or the production slot is released."
    if k == "ABG reminder":
        return f"The ABG expires {md(ev['guarantee_expiry'].date_to)} with the advance not recovered" + (f"; Finance wants it extended by {md(ev['deadline'].date_to)}." if "deadline" in ev else ".")
    if k == "Inspection failure":
        return "QA rejected the contractor's material; QA asks whether to buy it on a supply PO instead."
    if k == "Quarry closure":
        return f"Quarries closed {md(ev['closure'].date_from)} to {md(ev['closure'].date_to)}: supply to {', '.join(lookups.project_name(session, p) for p in (ev['closure'].ref_id or '').split(',') if p)} stops."
    if k == "Strike":
        return f"Transport strike from {md(ev['strike'].date_from)}: dispatches to {', '.join(lookups.project_name(session, p) for p in (ev['strike'].ref_id or '').split(',') if p)} may be held."
    if k == "Warranty notice":
        return f"Delivered {md(ev['supplied_on'].date_to)}, never commissioned; the warranty ends {md(ev['warranty_end'].date_to)}" + (f"; extension quoted at {inr(ev['offer'].qty)}." if "offer" in ev else ".")
    if k == "Fund mismatch":
        return "Finance says the fund requirement does not match the material requirement" + (f"; wants the sheet by {md(ev['deadline'].date_to)}." if "deadline" in ev else ".")
    if k == "Revised schedule":
        moves = [e for e in _events(session).get(m.id, []) if e.kind == "promise_revision"]
        return f"Moves {len({e.ref_id for e in moves})} PO line(s) to {', '.join(sorted({md(e.date_to) for e in moves}))}."
    if k == "Spec chase":
        return "The vendor cannot quote: it waits for the specification from Projects" + (f"; its price holds to {md(ev['quote_validity'].date_to)}." if "quote_validity" in ev else ".")
    if k == "Change of name":
        return f"The vendor is a new company from {md(ev['rename'].date_from)}; it asks to move open POs to the new name" + (f"; invoices only under the new GSTIN from {md(ev['rename_invoices_from'].date_from)}." if "rename_invoices_from" in ev else ".")
    if k == "PR request":
        return f"The site needs the material by {md(ev['needed_by'].date_to)}."
    if k == "Cancellation instruction":
        return f"Projects asks SCM to short-close {int(ev['short_close_instruction'].qty)} PR lines."
    if k == "Cancellation reasons":
        return "Projects' reasons for deleting the PRs."
    if k == "Quote":
        from app.domain.quotes.service import mail_quotes  # noqa: PLC0415

        qs = mail_quotes(session, m.id)
        return f"{len(qs)} quote(s), valid to {md(qs[0].validity)}: " + ", ".join(f"{inr(q.rate)}/{q.uom or 'unit'}" for q in qs[:3]) + "." if qs else "A quote."
    if k == "Reply (simulated)":
        return (m.body or "").split("\n\n")[1][:160] if "\n\n" in (m.body or "") else ""
    return m.subject


def company(session: Session, m: Message) -> str:
    if m.sender_class == "internal":
        return f"{lookups.answers().get('company_short') or 'the company'} (internal)"
    if m.sender_class == "vendor" and m.identity_id:
        return lookups.vendor_name(session, m.identity_id)
    if m.sender_class.startswith("lookalike"):
        return "look-alike sender (not on file)"
    return "not on file"


def _contact_role(session: Session, m: Message) -> str | None:
    if not m.contact:
        return None
    b = lookups.team(session).get(m.contact)
    if b:
        return b.role
    c = lookups.contacts(session).get(m.contact)
    if c:
        return (c.title or c.function.replace("_", " ").title()) + (f", {lookups.project_name(session, c.project_id)}" if c.project_id else "")
    return None


def _cases(session: Session) -> dict[str, object]:
    """{message id: the Today case that cites it} (the most urgent, as ranked)."""
    from app.domain.attention import service as attention  # noqa: PLC0415

    out = {}
    for f in attention._found(session).values():
        for r in f.item.messages:
            out.setdefault(r.id, f.item)
    return out


def owners_of_message(session: Session, message_id: str) -> set[str]:
    """Who owns a message: the owners of the case it feeds, else the members it is addressed to."""
    case = _cases(session).get(message_id)
    if case is not None and case.owner:
        return {n.strip() for n in case.owner.split("·") if n.strip()}
    m = session.get(Message, message_id)
    by_mail = {(b.email or "").lower(): b.name for b in lookups.team(session).values()}
    return {by_mail[a.strip().lower()] for a in ((m.to_addrs or "").split(",") if m else []) if a.strip().lower() in by_mail}


def summary(session: Session, m: Message, cases: dict | None = None) -> MessageSummary:
    cases = cases if cases is not None else _cases(session)
    c = cases.get(m.id)
    flags = [trust_rules.FLAG_WORDS.get(f, f.replace("_", " ")) for f in (m.trust_flags or "").split(",") if f]
    owners = owners_of_message(session, m.id)
    return MessageSummary(**{"from": m.from_name or m.from_email or ""}, ref=ref("message", m.id, m.subject), date=m.date, from_email=m.from_email, sender_class=m.sender_class,
                          vendor=ref("supplier", m.identity_id, lookups.vendor_name(session, m.identity_id)) if m.identity_id and m.sender_class == "vendor" else None,
                          company=company(session, m), contact=_contact_role(session, m), trust=m.trust, trust_flags=flags, kind=kind_of(session, m),
                          summary=means(session, m), owner=" · ".join(sorted(owners)) or None, related_item=c.key if c else None, related_title=c.title if c else None,
                          simulated=m.id.startswith("sim-"))


def list_messages(session: Session) -> list[MessageSummary]:
    cases = _cases(session)
    rows = [summary(session, m, cases) for m in session.scalars(select(Message).order_by(Message.date.desc()))]
    return mark_replied(session, rows)


def search(session: Session, rows: list[MessageSummary], q: str) -> list[MessageSummary]:
    want = q.strip().lower()
    out = []
    for r in rows:
        m = session.get(Message, r.ref.id)
        fields = [("subject", m.subject), ("from", f"{m.from_name} {m.from_email}"), ("company", r.company), ("facts", r.summary), ("body", m.body or "")]
        refs = " ".join(x.ref_id for x in session.scalars(select(MessageRef).where(MessageRef.message_id == m.id)))
        fields.insert(3, ("refs", refs))
        for name, text in fields:
            i = (text or "").lower().find(want)
            if i >= 0:
                lo = max(0, i - 48)
                snip = text[lo: i + len(want) + 48]
                out.append(r.model_copy(update={"matches": [Match(field=name, snippet=snip, start=i - lo, end=i - lo + len(want))]}))
                break
    return out


def sent_letters(db_path) -> list:
    from app.domain.actions import ledger  # noqa: PLC0415

    return [a for a in ledger.list_actions(db_path, "executed") if a.type in ("supplier_request", "internal_note")]


def mark_replied(session: Session, rows: list[MessageSummary]) -> list[MessageSummary]:
    from app import db  # noqa: PLC0415

    sent = sent_letters(db.DB_PATH)
    out = []
    for r in rows:
        when = _dt(r.date)
        replied = any(a.recipient and r.from_email and a.recipient.lower() == r.from_email.lower() and _dt(a.confirmed_at) and when and _dt(a.confirmed_at) > when for a in sent)
        out.append(r.model_copy(update={"replied": replied}))
    return out


def _dt(s: str | None):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        from datetime import timezone  # noqa: PLC0415

        t = t.replace(tzinfo=timezone.utc)
    return t


def detail(session: Session, message_id: str) -> MessageDetail | None:
    m = session.get(Message, message_id)
    if m is None:
        return None
    s = summary(session, m)
    held = m.trust == "blocked"
    ev = _events(session).get(m.id, [])
    dates = [DatedFact(what=DATE_WORDS[e.kind], date=e.date_to or e.date_from, line=e.line_ref) for e in ev if e.kind in DATE_WORDS and (e.date_to or e.date_from) and not held]
    moves: list[LineMove] = []
    from app.domain.orders.service import line as po_line  # noqa: PLC0415
    from app.domain.prs.service import all_lines as prs  # noqa: PLC0415

    for e in ev:
        if e.kind == "promise_revision" and e.ref_type == "po_line":
            l = po_line(session, e.ref_id)
            moves.append(LineMove(ref=ref("po_line", e.ref_id, l.short_text if l else None), label=f"PO {e.ref_id.replace('/', ' item ')}", was=l.delivery_date if l else e.date_from,
                                  now=e.date_to, qty=e.qty, line=e.line_ref))
        if e.kind == "short_close" and e.ref_type == "pr_line":
            l = prs(session).get(e.ref_id)
            moves.append(LineMove(ref=ref("pr_line", e.ref_id, l.short_text if l else None), label=f"PR {e.ref_id.replace('/', ' item ')}", was="open (RFQ out)",
                                  now=f"{l.status} {md(l.changed_on)}" if l and l.changed_on else (l.status if l else "short-close asked"), qty=l.qty if l else None, line=e.line_ref))
    claim = next((e for e in ev if e.kind == "remittance_change"), None)
    quote = None
    from app.domain.quotes.service import compare, mail_quotes  # noqa: PLC0415
    from app.domain.suppliers.service import library_verticals  # noqa: PLC0415

    qs = mail_quotes(session, m.id)
    if qs:
        q0 = qs[0]
        c = compare(session, qs, q0.project_id, q0.material)
        recs = lookups.records_of(session).get(q0.identity_id or "", [])
        body = m.body or ""
        import re  # noqa: PLC0415

        pay = re.search(r"(?im)^\s*(?:Payment|Terms)\s*:\s*(.+)$", body) or re.search(r"Terms: ([^.]+)\.", body)
        dlv = re.search(r"(?im)^\s*Delivery\s*:\s*(.+)$", body)
        quote = QuoteFacts(validity=q0.validity, delivery=dlv.group(1).strip() if dlv else None, minimum=None, payment=pay.group(1).strip() if pay else None,
                           price_basis=q0.price_basis + (f": {q0.pv_formula}" if q0.pv_formula else ""), vendor=q0.vendor_name,
                           in_library=bool(q0.identity_id and library_verticals(session, q0.identity_id)) if q0.identity_id else None,
                           msme=any(r.msme for r in recs) if recs else None,
                           rows=[dict(vendor=q.vendor_name, material=lookups.materials(session)[q.material].description if q.material in lookups.materials(session) else q.material,
                                      qty=qty_text(q.qty, q.uom), rate=q.rate, last_po=c["last"][0] if c["last"] else None, budget=c["budget"].rate if c["budget"] else None,
                                      line=q.line_ref) for q in qs])
    from app import db  # noqa: PLC0415

    sent = [SentLetter(action_id=a.action_id, subject=a.subject or "", sent_on=(a.confirmed_at or "")[:10], recipient=a.recipient) for a in sent_letters(db.DB_PATH)
            if a.recipient and m.from_email and a.recipient.lower() == m.from_email.lower()]
    known = {r.email_domain for r in lookups.records(session).values() if r.email_domain} | {lookups.answers().get("internal_domain")}
    imit = trust_rules.imitated_domain(m.from_domain or "", known) if m.sender_class.startswith("lookalike") else None
    return MessageDetail(summary=s, subject=m.subject, to=m.to_addrs, reply_to=m.reply_to, body=m.body or "", entities=annotate.annotate(session, m.body, held=held),
                         subject_entities=annotate.annotate(session, m.subject, held=held), imitates=imit[0] if imit else None, dates=dates, moves=moves,
                         claimed=money(claim.qty, prov("extracted", f"message:{m.id}", row=claim.line_ref, by="inbox.service")) if claim and claim.qty else None,
                         quote=quote, sent=sent)


def with_stage(rows: list[MessageSummary], items_by_key: dict) -> list[MessageSummary]:
    out = []
    for r in rows:
        it = items_by_key.get(r.related_item or "")
        out.append(r.model_copy(update={"related_stage": RelatedStage(key=it.stage.key, label=it.stage.label, waiting_on=it.stage.waiting_on)}) if it is not None and it.stage else r)
    return out
