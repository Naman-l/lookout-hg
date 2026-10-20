"""Who owns a question: read from the company's data, never named in code.

A part's buyer is the one the build assigned (the buyer on most of its PO lines, else its category's buyer). With none, the buyer of the lines of its
supplier. With none of those the question is `unassigned` and says to ask planning: an explicit unknown, not a guess."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo

UNASSIGNED = "unassigned"


@memo
def buyer_ids(session: Session) -> dict[str, str]:
    """{buyer id (the first name the data uses): full name}, from the buyers table."""
    from app.domain.parts.model import Buyer

    return {b.id: b.name for b in session.scalars(select(Buyer))}


def buyer_of_part(session: Session, part: str | None, line_buyer: str | None = None) -> str:
    """The id of the buyer who owns the part: its buyer, else the buyer on the line it came from, else the buyer of its supplier's lines, else UNASSIGNED."""
    from app.domain.orders.model import PoLine
    from app.domain.parts.model import Part

    ids = buyer_ids(session)
    p = session.get(Part, part) if part else None
    for b in (p.buyer_id if p else None, line_buyer):
        if b in ids:
            return b
    if p and p.preferred_identity_id:
        c = Counter(b for b in session.scalars(select(PoLine.buyer_id).where(PoLine.identity_id == p.preferred_identity_id)) if b in ids)
        if c:
            return c.most_common(1)[0][0]
    return UNASSIGNED


def buyer_ids_in(db_path) -> dict[str, str]:
    """The same, read straight from a database file (for the tools that hold a path, not a session)."""
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        return dict(con.execute("select id, name from buyers").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        con.close()
