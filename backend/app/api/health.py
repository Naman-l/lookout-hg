"""Health and build info. ORCH owns this file."""

from __future__ import annotations

from fastapi import APIRouter

from .. import db
from ..domain.common import AS_OF
from ..organism import company, id_shapes
from ..organism.recordings import live_available

router = APIRouter(tags=["health"])


BOOT = __import__("uuid").uuid4().hex[:12]      # this server process: a demo reset restarts it, so a choice the browser kept from before cannot survive the reset


def _sources() -> list[dict]:
    """Every source with its own export or build date, and whether it is stale (older than the recipe's limit before the data date): the shell's
    data-as-of hover."""
    import sqlite3  # noqa: PLC0415

    try:
        con = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT key, title, file, stamped_at, stale, kind FROM sources ORDER BY rowid").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [{"key": k, "title": t + (f" ({f.split('(')[0].split('/')[-1].strip()})" if k == "fund" else ""), "date": (d or "")[:10] or None, "stale": bool(st), "kind": kind}
            for k, t, f, d, st, kind in rows]


@router.get("/health")
def health() -> dict:
    full, short = company.names(db.DB_PATH)      # the customer, from the build (configuration, not code): the brand and copy of the screens
    return {"ok": True, "boot": BOOT, "agent_live": live_available(), "as_of": AS_OF.isoformat(), "company": full, "company_short": short,
            "id_patterns": id_shapes.shapes(db.DB_PATH), "base_currency": company.base_currency(db.DB_PATH), "sources": _sources()}
