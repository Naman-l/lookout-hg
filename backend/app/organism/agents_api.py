"""Under the hood: Lookout's specialists, their tools, how many runs each has done, and how runs are made on this machine (drafted by code; two mocked
recordings replayed). Nothing here is measured that was not run."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter

from .. import db as _db
from . import replay
from .specialists.registry import PLANS, SPECIALISTS

router = APIRouter(tags=["agents"])


@router.get("/agents", summary="The specialists, their tools and runs, and how runs are made here")
def agents() -> dict:
    counts: dict[str, int] = {}
    try:
        con = sqlite3.connect(f"file:{_db.DB_PATH}?mode=ro", uri=True)
        try:
            for (agent,) in con.execute("SELECT json_extract(event_json, '$.agent') FROM run_events WHERE json_extract(event_json, '$.type') = 'child.started'"):
                counts[agent] = counts.get(agent, 0) + 1
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return {"agents": [{"name": s.name, "label": s.label, "does": s.description, "tools": list(s.tools), "runs": counts.get(s.name, 0)} for s in SPECIALISTS.values()],
            "plans": {k: [SPECIALISTS[x].label for x in v] for k, v in PLANS.items()},
            "mode": "No model is connected on this machine: runs are drafted by code (labelled 'drafted by code, no model') and two mocked recordings are replayed (labelled as mocked).",
            "recordings": len(replay.recordings())}


@router.get("/evals/summary", summary="What has been measured: the number check and the hindsight check (run by make numbers / make hindsight)")
def evals_summary() -> dict:
    return {"rounds": [], "note": "The previous recipe's agent evals and answer sheets are not carried over; `make numbers` and `make hindsight` are the HG checks."}
