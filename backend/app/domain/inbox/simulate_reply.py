"""Demo only: a simulated reply, marked as such, from the recipient on file of every letter or note that went out (simulated) and has no answer yet,
so a case shows Replied and the Response step can show what the reply changes. Writes backend/lookout.db (the messages table), never data/.

A vendor answers the route it was asked on with the dates or terms that route asks for; a colleague answers a note with the fact it asks for. The
figures are the case's own (a partial dispatch by the need date, the validity extended by the 90 days asked, the plinth date on file), never new ones.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.common import AS_OF
from app.domain.fmt import long_date
from app.domain.inbox.model import Message, MessageEvent


def message_id(action_id: str) -> str:
    return f"sim-{action_id}"


def _reply(session: Session, a) -> tuple[str, list[dict]]:
    """(the reply's text, the facts it states as message events)."""
    kind = (a.change or {}).get("option_kind") or ""
    from app.domain.attention import service  # noqa: PLC0415

    d = service.item_detail(session, a.item_key) if a.item_key else None
    events: list[dict] = []
    if kind == "hold_original" and d:
        need = d.act_by
        lines = []
        for l in d.po_lines:
            half = round(l.open_qty / 2)
            lines.append(f"PO {l.po} item {l.item}: {half} nos. by {long_date(need)} and the balance {round(l.open_qty - half)} nos. by {long_date(max(r.date for r in l.revised) if l.revised else l.delivery_date)}")
            events += [dict(kind="promise_revision", ref_type="po_line", ref_id=l.ref.id, date_from=l.delivery_date, date_to=need, qty=half, detail="partial dispatch by the need date"),
                       dict(kind="promise_revision", ref_type="po_line", ref_id=l.ref.id, date_from=l.delivery_date, date_to=max(r.date for r in l.revised) if l.revised else l.delivery_date,
                            qty=l.open_qty - half, detail="balance on the revised date")]
        return "We can dispatch half of each line by the need date from finished stock and the balance on the revised date:\n" + "\n".join(lines), events
    if kind == "extend_validity" and d and d.po_lines:
        new = (date.fromisoformat(d.po_lines[0].validity_end) + timedelta(days=90)).isoformat()
        events.append(dict(kind="po_validity", ref_type="po", ref_id=d.po_lines[0].po, date_to=new, detail="validity extended at the PO price"))
        return f"We agree to hold the PO price up to {long_date(new)}, on condition that the MFC is issued by then.", events
    if kind in ("firm_dates", "ld_reminder") and d:
        lines = [f"PO {l.po} item {l.item}: {long_date(max(r.date for r in l.revised) if l.revised else l.delivery_date)}" for l in d.po_lines[:6]]
        for l in d.po_lines[:6]:
            events.append(dict(kind="promise_revision", ref_type="po_line", ref_id=l.ref.id, date_from=l.delivery_date, date_to=max(r.date for r in l.revised) if l.revised else l.delivery_date,
                               qty=l.open_qty, detail="firm date confirmed"))
        return "We confirm the following firm dates:\n" + "\n".join(lines), events
    if kind == "ask_plinth" and d:
        ready = next((x.date for x in d.deadlines if "ready" in x.what), None)
        return f"The plinth is planned ready by {long_date(ready)}; we will confirm a week before." if ready else "We will send the plinth date this week.", events
    if kind == "cancel_approval":
        return "Approved. The PRs are cancelled because the client's design approval and the SIP are pending; Projects is accountable for the enquiry raised against them.", events
    if kind in ("ask_projects",) and d and d.kind == "pr-stuck":
        return "The specification and load details are attached; please re-issue the RFQ.", events
    if kind == "reply_computed":
        return "We accept the price variation on the PO's base month and will revise our invoice accordingly.", events
    if kind in ("ask_finance",):
        return "Noted. Treasury will complete it before the date and confirm.", events
    if kind == "vendor_extend":
        return "We will extend as requested and send the amendment within the week.", events
    return "We acknowledge your letter and will revert with the details by the date asked.", events


def write(session: Session, a, now: datetime | None = None) -> Message | None:
    if not a.recipient or session.get(Message, message_id(a.action_id)) is not None:
        return None
    when = now or (datetime.fromisoformat(a.confirmed_at) + timedelta(hours=2) if a.confirmed_at else datetime.now(timezone.utc))
    text, events = _reply(session, a)
    name = next((c.name for c in lookups.contacts(session).values() if (c.email or "").lower() == a.recipient.lower()), None) or \
        next((r.contact_name for r in lookups.records(session).values() if (r.contact_email or "").lower() == a.recipient.lower()), None) or a.recipient
    ident = next((r.identity_id for r in lookups.records(session).values() if (r.contact_email or "").lower() == a.recipient.lower()), None)
    owner = (a.change or {}).get("owner") or ""
    body = f"[Simulated reply for the demo: no real message was received.]\n\n{text}\n\nRegards,\n{name}"
    m = Message(id=message_id(a.action_id), file="(simulated)", date=when.isoformat(), kind="sim", from_name=name, from_email=a.recipient,
                from_domain=a.recipient.split("@")[1], reply_to=None, to_addrs=next((b.email for b in lookups.team(session).values() if b.name == owner), ""),
                subject=f"RE: {a.subject}", body=body, identity_id=ident, sender_class="vendor" if ident else "internal", contact=None,
                sender_match="record" if ident else "internal", trust_flags="", trust="ok", attachments="")
    session.add(m)
    for e in events:
        session.add(MessageEvent(message_id=m.id, kind=e["kind"], ref_type=e.get("ref_type"), ref_id=e.get("ref_id"), date_from=e.get("date_from"), date_to=e.get("date_to"),
                                 qty=e.get("qty"), detail=e["detail"], line_ref="L3", method="stated"))
    session.commit()
    _touch(session)
    return m


def _touch(session: Session) -> None:
    """The memo caches key on the database file's mtime; the WAL may not move it, so touch the file."""
    import os  # noqa: PLC0415

    path = session.get_bind().url.database
    if path:
        os.utime(path, None)


def simulate_all(session: Session, db_path) -> list[str]:
    from app.domain.actions import ledger  # noqa: PLC0415

    out = []
    for a in ledger.list_actions(db_path, "executed"):
        if a.type in ("supplier_request", "internal_note") and write(session, a):
            out.append(a.action_id)
    return out


def main(argv: list[str] | None = None) -> int:
    from app import db  # noqa: PLC0415

    with db.SessionLocal() as s:
        done = simulate_all(s, db.DB_PATH)
    print(f"{len(done)} simulated replies written" + (f": {', '.join(done)}" if done else " (nothing sent is waiting for an answer)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


__all__ = ["simulate_all", "write", "AS_OF"]
