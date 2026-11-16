"""Who owns a question: read from the company's data, never named in code. A PR or PO line's owner is the member whose purchasing group it is on;
with none, the question is `unassigned` and says who could be asked."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import lookups

UNASSIGNED = "unassigned"


def buyer_ids(session: Session) -> dict[str, str]:
    """{member id: full name}, from the team table."""
    return {b.id: b.name for b in lookups.team(session).values()}


def owner_of_group(session: Session, group: str | None) -> str:
    return lookups.group_owner(session).get(group or "", UNASSIGNED)


def buyer_ids_in(db_path) -> dict[str, str]:
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        return dict(con.execute("select id, name from buyers").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        con.close()
