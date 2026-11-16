"""What people decided about an item, read from the ledger: approved, rejected, or recorded, with who, when and why."""

from __future__ import annotations

from app.domain.actions import ledger
from app.domain.attention.schema import Decision

APP_WORDS = {"note": "left a note"}


def _names(db_path) -> dict[str, str]:
    import sqlite3  # noqa: PLC0415

    con = sqlite3.connect(str(db_path))
    try:
        out = {(e or "").lower(): n for e, n in con.execute("select contact_email, contact_name from supplier_records where contact_email is not null")}
        out.update({(e or "").lower(): n for e, n in con.execute("select email, name from contacts where email is not null")})
        out.update({(e or "").lower(): n for e, n in con.execute("select email, name from buyers where email is not null")})
        return out
    except sqlite3.Error:
        return {}
    finally:
        con.close()


_NAMES: dict = {}


def _who(a) -> str:
    return _NAMES.get((a.recipient or "").lower()) or a.recipient or ""


def _what(a) -> str:
    if a.type == "supplier_request":
        return "the letter" + (f" to {_who(a)}" if a.recipient else "")
    if a.type == "internal_note":
        return "the note" + (f" to {_who(a)}" if a.recipient else "")
    return {"supplier_alias": "the vendor link"}.get(a.type, "the action")


def decisions_for(db_path, key: str) -> list[Decision]:
    """Decided actions on one item, newest first. A proposal still waiting is not a decision."""
    _NAMES.clear()
    _NAMES.update(_names(db_path))
    out = []
    for a in ledger.list_actions(db_path):
        if a.item_key == key and a.state == "signed" and a.signed_at:
            out.append(Decision(action_id=a.action_id, type=a.type, state="signed", by=a.signed_by or "", at=a.signed_at, text=f"{(a.signed_by or '').split()[0]} signed {_what(a)}; it waits for {a.countersign}'s countersign"))
            continue
        if a.item_key != key or not a.decided_at:
            continue
        who = (a.decided_by or "someone").split()[0]
        if a.type in APP_WORDS:
            text, state = f"{who} {APP_WORDS[a.type]}" + (f": {a.body}" if a.body else ""), "recorded"
        elif a.state == "rejected":
            text, state = f"{who} rejected {_what(a)}" + (f": {a.reason}" if a.reason else ""), "rejected"
        else:
            signer = (a.signed_by or "").split()[0] if a.signed_by else ""
            two = f"{signer} signed and {who} countersigned {_what(a)}" if a.signed_by and a.signed_by != a.decided_by else f"{who} approved {_what(a)}"
            text, state = two + (" and it was sent" if a.state == "executed" and a.confirmed_at else ""), "approved"
        out.append(Decision(action_id=a.action_id, type=a.type, state=state, by=a.decided_by or "", at=a.decided_at, reason=a.reason, text=text))
    return sorted(out, key=lambda d: d.at, reverse=True)
