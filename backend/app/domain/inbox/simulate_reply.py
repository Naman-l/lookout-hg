"""A simulated supplier reply, for the demo: it closes the loop from a sent request to an answered item. No model, no network, never touches data/.

    python -m app.domain.inbox.simulate_reply <action_id>      one reply to one sent request
    python -m app.domain.inbox.simulate_reply --all            one reply to every sent request that has none yet

The reply is written into the live database as a message from the request's recipient (the contact on file), dated now and carrying the subject of the
request, with a short body built from a template over the request's PO lines. It gets the same records the recipe gives a real message: the references
it makes, the promise revisions it states (each with the line's old date) and the trust verdict from the same rules (`app.domain.inbox.trust`). It is
marked simulated in its subject, its body and its file name; a real inbound message is never replaced by it.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.domain.actions import ledger
from app.domain.fmt import local_date
from app.domain.inbox import trust as trust_rules
from app.domain.inbox.model import Message, MessageEvent, MessageRef
from app.domain.orders.model import PoLine
from app.domain.suppliers.model import SupplierRecord

LINE_ID = re.compile(r"[A-Z]+-[\d-]+/\d+")
DAYS_OUT = 21                      # the template's promise: three weeks from the day the reply is written
MARK = "[simulated reply]"


def message_id(action_id: str) -> str:
    return f"simulated-reply-{action_id}"


def _lines(session: Session, text: str) -> list[PoLine]:
    seen: list[str] = []
    for lid in LINE_ID.findall(text):
        if lid not in seen:
            seen.append(lid)
    return [pl for lid in seen if (pl := session.get(PoLine, lid))]


def write(session: Session, action, now: datetime | None = None) -> Message | None:
    """Insert the reply to one sent supplier request. None when the request is not a sent supplier request or already has its reply."""
    if action is None or action.type != "supplier_request" or action.state != "executed" or not action.recipient:
        return None
    mid = message_id(action.action_id)
    if session.get(Message, mid):
        return None
    now = now or datetime.now().astimezone()
    stamp = now.isoformat(timespec="seconds")
    day = local_date(stamp)
    # the date carries the time: an item is answered by a message dated after the day of the send, so a reply written the same day sorts after it
    sent_at = f"{day}T{now.strftime('%H:%M:%S')}"
    reply_day = (now + timedelta(days=DAYS_OUT)).date().isoformat()
    lines = _lines(session, f"{action.subject or ''}\n{action.body or ''}")
    rec = session.scalars(select(SupplierRecord).where(SupplierRecord.contact_email.ilike(action.recipient))).first()
    contacts = {c.lower() for c in session.scalars(select(SupplierRecord.contact_email)) if c}
    domains = {c.split("@")[1] for c in contacts}
    match, flags = trust_rules.sender_flags(action.recipient, None, domains, contacts)
    subject = f"Re: {action.subject or 'your request'} {MARK}"
    body_lines = ["We confirm new dates:"] + [f"{pl.id} ships {reply_day}." for pl in lines] if lines else ["We have your request and will confirm dates shortly."]
    body = "\n".join([*body_lines, "", f"({MARK.strip('[]').capitalize()} written for the demo from your request {action.action_id}; it is not a real message.)"])
    flags += trust_rules.content_flags(subject, body)
    msg = Message(id=mid, file=f"{mid}.eml", date=sent_at, kind="eml", from_name=(rec.contact_name if rec else None), from_email=action.recipient,
                  from_domain=action.recipient.split("@")[1].lower(), reply_to=None, to_addrs=None, subject=subject, body=body,
                  identity_id=(action.target.id if action.target and action.target.type == "supplier" else (rec.identity_id if rec else None)),
                  sender_match=match, trust_flags=",".join(flags) or None, trust=trust_rules.verdict(flags), attachments=None)
    session.add(msg)
    session.flush()
    for po in sorted({pl.po_number for pl in lines}):
        session.add(MessageRef(message_id=mid, ref_type="po", ref_id=po, line_ref="L2", quoted=0))
    for i, pl in enumerate(lines, 2):
        session.add(MessageEvent(message_id=mid, kind="promise_revision", ref_type="po_line", ref_id=pl.id, date_from=pl.promised_date, date_to=reply_day, qty=None,
                                 detail=f"{pl.part_number}: promise {pl.promised_date or '?'} -> {reply_day}", line_ref=f"L{i}", method="stated"))
    session.commit()
    memo_clear()
    _touch(session)
    return msg


def _touch(session: Session) -> None:
    """In WAL mode a write lands in the -wal file and the database file's change time stays put, so a running server's caches would keep the old inbox. Moving the
    file's change time makes every cache keyed on it look again on the next request."""
    import os
    path = session.get_bind().url.database
    if path and os.path.exists(path):
        os.utime(path, None)


def memo_clear() -> None:
    """The caches key on the database file's change time, so a running server sees the new rows on its next request; this only clears this process's."""
    from app.domain.inbox import service
    for fn in vars(service).values():
        if callable(fn) and hasattr(fn, "cache_clear"):
            fn.cache_clear()


def simulate_all(session: Session, db_path) -> list[str]:
    done = []
    for a in ledger.list_actions(db_path):
        if write(session, a):
            done.append(a.action_id)
    return done


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    with db.SessionLocal() as session:
        if args[0] == "--all":
            done = simulate_all(session, db.DB_PATH)
            print(f"simulated {len(done)} supplier repl{'y' if len(done) == 1 else 'ies'}: {', '.join(done) or 'none (no sent request without one)'}")
            return 0
        a = ledger.get(db.DB_PATH, args[0])
        m = write(session, a)
        if not m:
            print(f"{args[0]}: not a sent supplier request, or it already has its simulated reply")
            return 1
        print(f"wrote {m.id} from {m.from_email} dated {m.date} (trust {m.trust}); the item shows Answered on its next load")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
