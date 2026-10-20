"""Health and build info. ORCH owns this file."""

from __future__ import annotations

from fastapi import APIRouter

from .. import db
from ..domain.common import AS_OF
from ..organism import company, id_shapes
from ..organism.recordings import live_available

router = APIRouter(tags=["health"])


BOOT = __import__("uuid").uuid4().hex[:12]      # this server process: a demo reset restarts it, so a choice the browser kept from before cannot survive the reset


@router.get("/health")
def health() -> dict:
    full, short = company.names(db.DB_PATH)      # the customer, from the build (configuration, not code): the brand and copy of the screens
    return {"ok": True, "boot": BOOT, "agent_live": live_available(), "as_of": AS_OF.isoformat(), "company": full, "company_short": short,
            "id_patterns": {k: id_shapes.shape(db.DB_PATH, k) for k in ("part", "po_number", "po_line", "supplier", "legacy_supplier")}}      # what an id looks like here, from the recipe: the screens never write a prefix
