"""The inbox: trust computed in code before any model reads a message, and what each message changes."""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.annotate import service as annotate
from app.domain.cache import memo
from app.domain.fmt import humanize, md
from app.domain.inbox import trust as trust_rules
from app.domain.inbox.model import Message, MessageEvent, MessageRef
from app.domain.inbox.trust import FLAG_WORDS
from app.domain.inbox.schema import Classification, Match, MessageChange, MessageDetail, MessageSummary, SentRequest, Thread, TrustFlag, TrustVerdict
from app.domain.orders.model import PoLine
from app.domain.quotes.model import Offer
from app.domain.suppliers.model import SupplierIdentity
from app.domain.values import ref

WORDS = FLAG_WORDS   # one vocabulary for the flag names, kept beside the rules that set them (inbox/trust.py)
_RESUME = re.compile(r"resumes in (\d+) to (\d+) weeks")


def _restart_span(detail: str | None, notice_date: str | None) -> str | None:
    """'Nov 3 - Nov 17 (6 to 8 weeks)': the supplier's own range, counted from the notice date. None when the words or the date are missing."""
    found = _RESUME.search(detail or "")
    if not found or not notice_date:
        return None
    start_w, end_w = int(found.group(1)), int(found.group(2))
    sent = date.fromisoformat(notice_date[:10])
    return f"{md((sent + timedelta(weeks=start_w)).isoformat())} \u2013 {md((sent + timedelta(weeks=end_w)).isoformat())} ({start_w} to {end_w} weeks)"


def _api_trust(m: Message) -> str:
    flags = (m.trust_flags or "").split(",")
    if m.trust == "blocked":
        return "suspicious"
    return "new_sender" if "sender_not_in_master" in flags else "on_file"


def trust(session: Session, message_id: str) -> TrustVerdict | None:
    m = session.get(Message, message_id)
    if m is None:
        return None
    flags = [f for f in (m.trust_flags or "").split(",") if f]
    return TrustVerdict(message=ref("message", m.id), verdict=m.trust, api_trust=_api_trust(m), may_act=m.trust != "blocked",
                        flags=[TrustFlag(name=f, words=WORDS.get(f, f)) for f in flags])


def _kind_summary(session: Session, m: Message, events: list[MessageEvent]) -> tuple[str | None, str]:
    """One plain line per message, built from what the recipe read out of it (events, offers); no figure is typed here."""
    kinds = [e.kind for e in events]
    offers = session.scalars(select(Offer).where(Offer.message_id == m.id)).all()
    blocked = "Blocked: " + "; ".join(WORDS.get(f, f) for f in (m.trust_flags or "").split(",") if f) + "." if m.trust == "blocked" else ""
    if "remittance_change" in kinds:
        ev = next(e for e in events if e.kind == "remittance_change")
        sum_ = f"USD {ev.qty:,.0f}" if ev.qty else "a payment"
        return "payment change", f"Asks to send {sum_} to new bank details and update the vendor master. {blocked} Nothing may follow from it."
    if "offer" in kinds:
        o = next((o for o in offers if o.unit_price_each), None)
        what = f"{o.qty_break:,} x {o.part_number} at USD {o.unit_price_each:,.2f} each" + (f", {o.payment_terms}" if o.payment_terms else "") if o else "a spot lot"
        return "spot offer", f"Spot offer: {what}. {blocked}".strip()
    if "force_majeure" in kinds:
        n = sum(1 for e in events if e.kind == "force_majeure" and e.ref_type == "po_line")
        due = next((e.date_to for e in events if e.kind == "deadline" and e.date_to), None)
        return "force majeure", f"Force majeure: {n} open PO lines cannot ship" + (f"; revised dates promised by {md(due)}." if due else ".")
    if any(o.superseded_by for o in offers):
        return "correction", "Quote with a corrected price: the number quoted below it no longer holds."
    if "promise_revision" in kinds:
        n = len({e.ref_id for e in events if e.kind == "promise_revision"})
        return "slip", f"Moves the promise date of {n} PO lines."
    for kind, label in (("price_change", "price change"), ("closure", "closure")):
        ev = next((e for e in events if e.kind == kind), None)
        if ev and not (kind == "closure" and offers):      # a holiday line inside a quote does not make the quote a closure notice

            d = humanize(ev.detail or "")
            return label, d[:1].upper() + d[1:] + ("." if not d.endswith(".") else "")
    if offers:
        parts = sorted({o.part_number for o in offers if o.part_number})
        return "quote", f"Quote for {len(parts)} part{'s' if len(parts) != 1 else ''}: {', '.join(parts[:4])}{'…' if len(parts) > 4 else ''}."
    return None, m.subject


def _company(m, names: dict[str, str]) -> str:
    """Who the sender works for, as the master knows them: a look-alike is not that company."""
    name = names.get(m.identity_id) if m.identity_id else None
    if not name:
        return "not on file"
    return name if m.sender_match in ("record", "domain") else f"not on file (looks like {name})"


FIELD_WEIGHT = {"subject": 5, "from": 4, "supplier": 4, "refs": 3, "facts": 3, "tags": 3, "body": 1}
HELD_WORDS = "held fraud scam phishing look-alike lookalike spoof suspicious blocked unsafe"      # what a buyer calls a message the code would not act on


def _u16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


@memo
def _corpus(session: Session) -> dict[str, dict[str, str]]:
    """What a search reads of each message, by field: the subject, the sender, the company (its names, former names, domain and contact), the part and PO numbers it names
    (a PO line also as 'PO 450/10' and '450/10'), the facts read out of it (events and offers), and the body."""
    from app.domain.suppliers.model import SupplierRecord

    names: dict[str, set[str]] = {}
    for r in session.scalars(select(SupplierRecord)):
        names.setdefault(r.identity_id, set()).update(x for x in (r.name, r.email_domain, r.contact_name) if x)
    for i in session.scalars(select(SupplierIdentity)):
        names.setdefault(i.id, set()).add(i.name)
    refs: dict[str, list[str]] = {}
    for r in session.scalars(select(MessageRef)):
        refs.setdefault(r.message_id, []).append(r.ref_id)
        m = re.match(r".*-0*(\d+)/(\d+)$", r.ref_id)
        if r.ref_type == "po_line" and m:
            refs[r.message_id] += [f"PO {m.group(1)}/{m.group(2)}", f"{m.group(1)}/{m.group(2)}"]
    facts: dict[str, list[str]] = {}
    for e in session.scalars(select(MessageEvent)):
        facts.setdefault(e.message_id, []).append(e.detail or "")
        if e.ref_id and e.ref_type == "po_line":
            refs.setdefault(e.message_id, []).append(e.ref_id)
    for o in session.scalars(select(Offer)):
        facts.setdefault(o.message_id, []).append(" ".join(str(x) for x in (o.quote_no, o.part_number, o.price_raw, o.currency, o.qty_break, o.conditions) if x))
    out = {}
    for m in session.scalars(select(Message)):
        out[m.id] = dict(subject=m.subject or "", body=m.body or "", **{"from": " ".join(x for x in (m.from_name, m.from_email) if x)},
                         supplier=" · ".join(sorted(names.get(m.identity_id, ()))) if m.identity_id else "", tags=HELD_WORDS if m.trust == "blocked" else "",      # held: the code would not act on it (a look-alike sender, a bank-detail change, an instruction to a machine); "for review" is not fraud
                          refs=" ".join(dict.fromkeys(refs.get(m.id, []))), facts=" | ".join(facts.get(m.id, [])))
    return out


def _snippet(text: str, start: int, end: int, pad: int = 48) -> Match | None:
    a, b = max(0, start - pad), min(len(text), end + pad)
    lead = "…" if a else ""
    shown = lead + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")
    # re-find the match inside the cleaned snippet (whitespace may have collapsed)
    k = shown.lower().find(text[start:end].lower())
    return (shown, k, k + (end - start)) if k >= 0 else None


def search_messages(session: Session, q: str | None = None, *, kind: str | None = None, supplier: str | None = None, trust: str | None = None,
                    date_from: str | None = None, date_to: str | None = None) -> list[MessageSummary]:
    """The inbox, filtered (kind, supplier, trust, a date range) and searched: every word of `q` must be found, in the subject, the sender, the company, the part and PO numbers, the facts
    or the body. Best match first, then newest. Each row says where it matched. No model."""
    rows = [s for s in mark_replied(session, list_messages(session))
            if (not kind or (s.kind or "").lower() == kind.lower()) and (not supplier or (s.supplier and s.supplier.id == supplier)) and (not trust or s.trust == trust)
            and (not date_from or s.date[:10] >= date_from) and (not date_to or s.date[:10] <= date_to)]
    words = [w for w in (q or "").lower().split() if w]
    if not words:
        return rows
    corpus, scored = _corpus(session), []
    for s in rows:
        fields = corpus.get(s.ref.id, {})
        hits: dict[str, tuple[int, int]] = {}
        score = 0
        ok = True
        for w in words:
            best = None
            for f, weight in FIELD_WEIGHT.items():
                k = fields.get(f, "").lower().find(w)
                if k >= 0 and (best is None or weight > best[0]):
                    best = (weight + (2 if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", fields[f].lower()) else 0), f, k, len(w))
            if best is None:
                ok = False
                break
            score += best[0]
            hits.setdefault(best[1], (best[2], best[2] + best[3]))
        if not ok:
            continue
        matches = []
        for f in sorted(hits, key=lambda f: -FIELD_WEIGHT[f]):
            sn = _snippet(fields[f], *hits[f])
            if sn:
                matches.append(Match(field=f, snippet=sn[0], start=_u16(sn[0][:sn[1]]), end=_u16(sn[0][:sn[2]])))
        scored.append((score, s.date, s.model_copy(update={"matches": matches})))
    return [s for _, _, s in sorted(scored, key=lambda t: (t[0], t[1]), reverse=True)]


@memo
def list_messages(session: Session) -> list[MessageSummary]:
    names = {i.id: i.name for i in session.scalars(select(SupplierIdentity))}
    ev: dict[str, list[MessageEvent]] = {}
    for e in session.scalars(select(MessageEvent)):
        ev.setdefault(e.message_id, []).append(e)
    out = []
    for m in session.scalars(select(Message).order_by(Message.date.desc(), Message.id)):
        kind, summary = _kind_summary(session, m, ev.get(m.id, []))
        out.append(MessageSummary(ref=ref("message", m.id, m.subject), date=m.date, from_=m.from_name or m.from_email or "", from_email=m.from_email, trust=_api_trust(m),
                                  trust_flags=[f for f in (m.trust_flags or "").split(",") if f], kind=kind, summary=summary,
                                  supplier=ref("supplier", m.identity_id, names.get(m.identity_id)) if m.identity_id else None, company=_company(m, names)))
    return out


def sent_requests(session: Session) -> dict[str, list[SentRequest]]:
    """{supplier id: the requests sent to it, newest first}, read from the ledger on every call: the list of messages is cached, a send is not."""
    from app.domain.actions import ledger
    from app.domain.fmt import local_date

    out: dict[str, list[SentRequest]] = {}
    for a in ledger.list_actions(session.get_bind().url.database):
        if a.type == "supplier_request" and a.state == "executed" and a.target and a.target.type == "supplier":
            out.setdefault(a.target.id, []).append(SentRequest(action_id=a.action_id, subject=a.subject or "", sent_on=local_date(a.confirmed_at or a.decided_at), recipient=a.recipient))
    return {k: sorted(v, key=lambda r: r.sent_on, reverse=True) for k, v in out.items()}


def mark_replied(session: Session, rows: list[MessageSummary]) -> list[MessageSummary]:
    """The rows with `replied` set where a request to the sender's company went out on or after the message's day."""
    sent = sent_requests(session)
    return [r.model_copy(update={"replied": True}) if r.supplier and any(x.sent_on >= r.date[:10] for x in sent.get(r.supplier.id, [])) else r for r in rows]


def message_changes(session: Session, message_id: str) -> list[MessageChange]:
    """What the message changes, one row per PO line or supplier, each citing the text line it rests on."""
    m = session.get(Message, message_id)
    if m is None:
        return []
    lines = m.body.splitlines()
    pos = {l.id: l for l in session.scalars(select(PoLine).where(PoLine.id.in_(
        [e.ref_id for e in session.scalars(select(MessageEvent).where(MessageEvent.message_id == message_id)) if e.ref_type == "po_line"])))}

    def text(line_ref):
        if line_ref and line_ref.startswith("L") and line_ref[1:].isdigit():
            i = int(line_ref[1:]) - 1
            return lines[i].strip() if 0 <= i < len(lines) else None
        return None

    out = []
    seen: dict[str, int] = {}

    def delivery(e, line: str | None) -> tuple[int | None, str | None]:
        """The quantity and ship date the source line gives for this change: "890 pcs ship 10/09"; with partials ("57 pcs ship 10/09, 58 pcs ship 10/30") the n-th change on the same PO line takes the n-th; else the number after the part id ("<part>  830")."""
        if not line:
            return None, None
        n = seen.get(e.ref_id, 0)
        seen[e.ref_id] = n + 1
        deliveries = re.findall(r"([\d,]+)\s*(?:pcs|EA|pieces|units)\b\s*,?\s*(?:ship(?:s|ping)?\s+(\d{1,2})/(\d{1,2}))?", line)
        if deliveries:
            q, mo, d = deliveries[min(n, len(deliveries) - 1)]
            return int(q.replace(",", "")), (f"{m.date[:4]}-{int(mo):02d}-{int(d):02d}" if mo else None)
        part = pos[e.ref_id].part_number if e.ref_id in pos else None
        after = re.search(rf"{re.escape(part)}\s*,?\s+([\d,]+)\b", line) if part else None
        return (int(after.group(1).replace(",", "")) if after else None), None

    def open_qty(po_line: str | None) -> int | None:
        """The PO line's open quantity (ordered minus received, part's unit): the "Open qty" a row shows when the message itself gives none (a reply that only re-dates)."""
        pl = pos.get(po_line) if po_line else None
        return int(round(pl.open_qty_ea)) if pl is not None and pl.open_qty_ea is not None else None

    all_ev = list(session.scalars(select(MessageEvent).where(MessageEvent.message_id == message_id).order_by(MessageEvent.id)))
    due = next((x.date_to for x in all_ev if x.kind == "deadline" and x.date_to), None)
    for e in all_ev:
        line = text(e.line_ref) or e.line_ref
        if e.kind == "force_majeure" and e.ref_type == "po_line":
            pl = pos.get(e.ref_id)
            q, ship = delivery(e, line)
            out.append(MessageChange(ref=ref("po_line", e.ref_id), label=f"Cannot ship: force majeure ({pl.part_number})" if pl else "Cannot ship: force majeure",
                                     before=e.date_from, after=f"unknown (revised dates due {md(due)})" if due else "unknown (no revised date given)", line=line, qty=q if q is not None else open_qty(e.ref_id), ship=ship))
        elif e.kind == "promise_revision":
            q, ship = delivery(e, line)
            out.append(MessageChange(ref=ref("po_line", e.ref_id), label="Promise date moves" + (f" ({pos[e.ref_id].part_number})" if e.ref_id in pos else ""),
                                     before=e.date_from, after=e.date_to, line=line, qty=q if q is not None else open_qty(e.ref_id), ship=ship))
        elif e.kind == "force_majeure" and (span := _restart_span(e.detail, m.date)):
            out.append(MessageChange(ref=ref(e.ref_type or "supplier", e.ref_id or (m.identity_id or "")), label="Partial restart", before=None, after=span, line=e.detail if not line else line))
        elif e.kind in ("price_change", "closure", "deadline", "validity", "force_majeure", "remittance_change", "offer"):
            label = {"price_change": "Price change", "closure": "Factory closure", "deadline": "Deadline", "validity": "Quote expires",
                     "force_majeure": "Recovery estimate", "remittance_change": "Payment change request (blocked)", "offer": "Spot offer (blocked)"}[e.kind]
            out.append(MessageChange(ref=ref(e.ref_type or "supplier", e.ref_id or (m.identity_id or "")), label=label, before=e.date_from,
                                     after=e.date_to or e.detail, line=e.detail if not line else line))
    for o in session.scalars(select(Offer).where(Offer.message_id == message_id, Offer.superseded_by.is_(None)).limit(40)):
        if o.part_number and o.trust != "blocked":
            out.append(MessageChange(ref=ref("part", o.part_number), label=f"Offer {o.price_raw} {o.currency}" + (f" at {o.qty_break}" if o.qty_break else ""),
                                     before=None, after=f"{o.unit_price_each:.4g} {o.currency} each" + (f", valid to {o.validity_date}" if o.validity_date else ""), line=o.line_ref))
    return out


def _owner_text(session: Session, message_id: str) -> str | None:
    from app.domain.actions import approvers

    try:
        return " · ".join(sorted(approvers._reply_owners(session, message_id)))
    except approvers.NoOwner:
        return None


def message_detail(session: Session, message_id: str, related_item: str | None = None) -> MessageDetail | None:
    m = session.get(Message, message_id)
    if m is None:
        return None
    summary = next(s for s in list_messages(session) if s.ref.id == message_id)
    changes = message_changes(session, message_id)
    hl = [c.line for c in changes if c.line and c.line in m.body]
    held = m.trust == "blocked" or bool(set((m.trust_flags or "").split(",")) & trust_rules.BLOCK)      # names in a held message are claims, never records
    summary = mark_replied(session, [summary])[0]
    mine = [x for x in sent_requests(session).get(summary.supplier.id, []) if x.sent_on >= summary.date[:10]] if summary.supplier else []
    from app.domain.suppliers.model import SupplierRecord  # noqa: PLC0415

    known = {d for d in session.scalars(select(SupplierRecord.email_domain)) if d}
    hit = trust_rules.imitated_domain(m.from_domain or "", known) if m.from_domain else None
    return MessageDetail(summary=summary, sent=mine, imitates=hit[0] if hit else None, subject=m.subject, to=m.to_addrs, reply_to=m.reply_to, body=m.body,
                         owner=_owner_text(session, message_id), subject_entities=annotate.annotate(session, m.subject, held=held), entities=annotate.annotate(session, m.body, held=held), highlights=list(dict.fromkeys(hl)), changes=changes, related_item=related_item)


# --- the ladder ----------------------------------------------------------------------------------------------------


# L2: keyword families. Each has words that point to it and anti-patterns that cancel it (a quote that merely mentions "holiday" is not a closure).
FAMILIES = {
    "force majeure": (r"force majeure|unable to perform deliveries|plant .{0,30}(fire|flood|earthquake)", r"^$"),
    "slip": (r"revised (ship|delivery) date|lead time (update|extension|increases?)|placing .* on allocation|new date", r"price adjustment"),
    "price change": (r"price (adjustment|increase)|will increase prices|effective .{0,20}(?:november|december|january)", r"honou?red at current pricing only"),
    "closure": (r"(factory|plant) (will be )?closed|holiday notice|national day", r"^$"),
    "correction": (r"correction to my (note|mail)|should read|typo on my side", r"^$"),
    "payment change": (r"remit(tance)? (all )?payments?|updated remittance|beneficiary|bank details|vendor master", r"^$"),
    "spot offer": (r"spot offer|in stock.{0,20}ships today|this lot won't last", r"^$"),
    "quote": (r"quotation|angebot|cotizaci[oó]n|\bquote\b|unit price|price.{0,10}(at|per) \d", r"^$"),
}


def _l2(text: str) -> list[tuple[str, str]]:
    """The families a text points to, each with the line that does: anti-patterns cancel a family."""
    out = []
    for kind, (yes, no) in FAMILIES.items():
        m = re.search(yes, text, re.I)
        if m and not (no != r"^$" and re.search(no, text, re.I)):
            line = next((l.strip() for l in text.splitlines() if re.search(yes, l, re.I)), m.group(0))
            out.append((kind, line[:160]))
    return out


@memo
def classify(session: Session, message_id: str) -> Classification | None:
    """L0 trust, then L1 (a known format the parser read), then L2 (keyword families). Anything the ladder cannot settle is level 3: the model, labelled."""
    m = session.get(Message, message_id)
    if m is None:
        return None
    me = ref("message", m.id)
    events = list(session.scalars(select(MessageEvent).where(MessageEvent.message_id == m.id)))
    kind1, _ = _kind_summary(session, m, events)
    fresh = m.subject + "\n" + "\n".join(l for l in m.body.splitlines() if not l.startswith(">"))
    fam = _l2(fresh)
    kinds2 = [k for k, _ in fam]
    if m.trust == "blocked":
        flags = [f for f in (m.trust_flags or "").split(",") if f]
        return Classification(message=me, level=0, kind=kind1 or (kinds2[0] if kinds2 else "other"), confidence=1.0, evidence=[WORDS.get(f, f) for f in flags], agrees=True,
                              decision="blocked", reason="blocked by the sender and content checks before any model reads it: nothing may be drafted from it")
    if kind1:
        agrees = not kinds2 or kind1 in kinds2 or (kind1 == "correction" and "quote" in kinds2) or (kind1 == "slip" and "force majeure" not in kinds2)
        ev = [e.detail for e in events[:2]] or [l for k, l in fam if k == kind1][:1]
        conf = 0.95 if agrees else 0.7
        return Classification(message=me, level=1, kind=kind1, confidence=conf, evidence=ev, agrees=agrees,
                              decision="auto" if (agrees and m.trust == "ok") else "review",
                              reason="a known format read by rule" + ("" if agrees else f"; the words also point to {', '.join(k for k in kinds2 if k != kind1)}") + ("" if m.trust == "ok" else f"; sender check says {m.trust}"))
    if len(kinds2) == 1:
        return Classification(message=me, level=2, kind=kinds2[0], confidence=0.8, evidence=[fam[0][1]], agrees=True, decision="auto" if m.trust == "ok" else "review", reason="one keyword family, no anti-pattern")
    if kinds2:
        return Classification(message=me, level=2, kind=kinds2[0], confidence=0.5, evidence=[l for _, l in fam][:3], agrees=False, decision="review",
                              reason=f"several families fit ({', '.join(kinds2)}): needs a person or the model")
    return Classification(message=me, level=3, kind=None, confidence=0.0, evidence=[], agrees=False, decision="review", reason="no rule fits: left for the model (labelled 'classified by the model') or a person")


def classify_all(session: Session) -> list[Classification]:
    return [classify(session, m.ref.id) for m in list_messages(session)]


def check_these(session: Session) -> list[Classification]:
    """The review list: everything the code would not act on alone."""
    return [c for c in classify_all(session) if c.decision != "auto"]


def _root(subject: str) -> str:
    return re.sub(r"^(\s*(re|fw|fwd|aw|wg)\s*:\s*)+", "", subject.strip(), flags=re.I).strip().lower()


def list_threads(session: Session, *, kind: str | None = None, supplier: str | None = None, trust: str | None = None, needs_review: bool | None = None) -> list[Thread]:
    """One thread per subject (RE:/FW: removed), newest first, with the corrections linked: a later price that replaces a quoted one says so."""
    by_root: dict[str, list[MessageSummary]] = {}
    for s in list_messages(session):
        by_root.setdefault(_root(s.ref.label or ""), []).append(s)
    offers = list(session.scalars(select(Offer).where(Offer.superseded_by.is_not(None))))
    out = []
    for root, ms in by_root.items():
        ms = sorted(ms, key=lambda x: (x.date, x.ref.id))
        corr = []
        for o in offers:
            if o.message_id in {x.ref.id for x in ms}:
                new = session.get(Offer, o.superseded_by)
                corr.append(f"{o.part_number} at {o.qty_break}/yr: {o.price_raw} is corrected to {new.price_raw} in the same message")
        review = any(classify(session, x.ref.id).decision != "auto" for x in ms)
        t = Thread(id=root, subject=ms[-1].ref.label or root, supplier=next((x.supplier for x in ms if x.supplier), None), messages=ms, corrects=corr, last_date=ms[-1].date, needs_review=review)
        if kind and not any(x.kind == kind for x in ms):
            continue
        if supplier and not (t.supplier and t.supplier.id == supplier):
            continue
        if trust and not any(x.trust == trust for x in ms):
            continue
        if needs_review is not None and t.needs_review != needs_review:
            continue
        out.append(t)
    return sorted(out, key=lambda t: t.last_date, reverse=True)


