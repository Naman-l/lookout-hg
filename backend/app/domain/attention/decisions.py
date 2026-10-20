"""What people decided about an item, read from the ledger: approved, rejected, or recorded, with who, when and why."""

from __future__ import annotations

from app.domain.actions import ledger
from app.domain.attention.schema import Decision

APP_WORDS = {"note": "left a note"}


def _what(a) -> str:
    if a.type == "supplier_request":
        return "the request" + (f" to {a.recipient}" if a.recipient else "")
    return {"supplier_alias": "the supplier link"}.get(a.type, "the action")


def decisions_for(db_path, key: str) -> list[Decision]:
    """Decided actions on one item, newest first. A proposal still waiting is not a decision."""
    out = []
    for a in ledger.list_actions(db_path):
        if a.item_key != key or not a.decided_at:
            continue
        who = (a.decided_by or "someone").split()[0]
        if a.type in APP_WORDS:
            text, state = f"{who} {APP_WORDS[a.type]}" + (f": {a.body}" if a.body else ""), "recorded"
        elif a.state == "rejected":
            text, state = f"{who} rejected {_what(a)}" + (f": {a.reason}" if a.reason else ""), "rejected"
        else:
            text, state = f"{who} approved {_what(a)}" + (" and it was sent" if a.state == "executed" and a.confirmed_at else ""), "approved"
        out.append(Decision(action_id=a.action_id, type=a.type, state=state, by=a.decided_by or "", at=a.decided_at, reason=a.reason, text=text))
    return sorted(out, key=lambda d: d.at, reverse=True)
