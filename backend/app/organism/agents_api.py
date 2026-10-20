"""Under the hood (FINAL 08): who works a case and what they have done, read from the registry, the recordings and the run store; and
the evals summary of the last measured round. Read only: nothing here starts a run or reaches a model."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import db as _db
from .runs import store
from .specialists.registry import SPECIALISTS

router = APIRouter()
RECORDINGS = Path(__file__).parent / "recordings"

# The stage of a case each agent serves (Rev 4): Overview reads the case, Analysis works it out, Decision chooses, Approval is the draft the owner signs.
STAGES = {
    "lookout": ["overview", "decision"], "inbox_analyst": ["analysis"], "supply_planner": ["analysis"], "tariff_analyst": ["analysis"],
    "sourcing_analyst": ["analysis"], "buyers_clerk": ["approval"], "data_steward": ["data"],
}
# What each agent works on, in a buyer's words (not the model-facing description).
WORKS_ON = {
    "lookout": "Reads the case and the Action list; asks the specialists the case needs",
    "inbox_analyst": "What a supplier message is, what it changes, whether the sender is who they claim",
    "supply_planner": "What is stuck, what runs short and which robot-month it hits; where an order is; whether a build is clear",
    "tariff_analyst": "Duty owed, duty if shipped late, duty if origin is China; which lines enter in time; who is importer of record",
    "sourcing_analyst": "Landed cost per piece for each offer against the last price paid, with its conditions",
    "buyers_clerk": "Drafts the request to the supplier, logs questions for a buyer, proposes supplier-name links. The only one that drafts; nothing is sent",
    "data_steward": "Finds what changed in a supplier's or ERP file, writes one step, tests it in a sandbox",
}
LOOKOUT_TOOLS = ["get_item", "list_items", "Agent", "get_handoffs"]
# Lookout serves two stages with different work: it opens the case and, after the analysts, decides.
LOOKOUT_BY_STAGE = {"overview": {"works_on": WORKS_ON["lookout"], "tools": ["get_item", "list_items", "Agent"]},
                    "decision": {"works_on": "Reads the handoffs, orders the options, recommends one; then the checks below", "tools": ["get_handoffs"]}}


def _recordings() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(RECORDINGS.glob("*.json"))]


@lru_cache(maxsize=1)
def _recorded() -> dict:
    """Counts over the recorded runs: per agent, the runs it called a tool in, its lookups, and the clerk's drafts and questions."""
    runs: dict[str, int] = {}
    lookups: dict[str, int] = {}
    used: dict[tuple[str, str], int] = {}
    drafts = questions = 0
    recs = _recordings()
    for r in recs:
        seen = set()
        for e in r.get("events", []):
            if e.get("type") != "tool.called":
                continue
            a = e.get("agent") or "lookout"
            seen.add(a)
            lookups[a] = lookups.get(a, 0) + 1
            tool = (e.get("payload") or {}).get("tool") or e.get("summary") or ""
            used[(a, tool)] = used.get((a, tool), 0) + 1
            drafts += a == "buyers_clerk" and "draft_supplier_request" in tool
            questions += a == "buyers_clerk" and "log_buyer_question" in tool
        for a in seen | {"lookout"}:
            runs[a] = runs.get(a, 0) + 1
    stale = RECORDINGS / "STALE.md"
    earlier = len(re.findall(r"^- `", stale.read_text(), re.M)) if stale.exists() else 0
    cost = sum(float((r.get("run") or {}).get("cost_usd") or 0) for r in recs)
    return {"runs": runs, "lookups": lookups, "used": used, "drafts": drafts, "questions": questions, "recorded_runs": len(recs), "recorded_cost_usd": round(cost, 2), "earlier_prompt": earlier}


def _latest_runs() -> dict[str, str]:
    """The newest run in the store each agent worked in (Lookout: the newest run), so a row can open its latest work."""
    out: dict[str, str] = {}
    try:
        with store.connect(_db.DB_PATH) as con:
            con.row_factory = sqlite3.Row
            top = [r[0] for r in con.execute("SELECT run_id FROM runs WHERE parent_run_id IS NULL ORDER BY started_at DESC LIMIT 200")]
            agents_in: dict[str, set[str]] = {}
            for (ej,) in con.execute("SELECT event_json FROM run_events WHERE event_json LIKE '%tool.called%'"):
                e = json.loads(ej)      # a specialist's events carry its child run id and the parent's
                agents_in.setdefault(e.get("parent_run_id") or e.get("run_id"), set()).add(e.get("agent") or "lookout")
            for rid in top:
                out.setdefault("lookout", rid)
                for a in agents_in.get(rid, ()):
                    out.setdefault(a, rid)
    except sqlite3.Error:
        pass
    return out


@router.get("/agents", operation_id="listAgents", summary="Lookout and its specialists: the stage each serves, what it works on, its tools and what the recorded runs show it did")
def agents() -> dict:
    rec, latest = _recorded(), _latest_runs()
    names = ["lookout", "inbox_analyst", "supply_planner", "tariff_analyst", "sourcing_analyst", "buyers_clerk", "data_steward"]
    rows = []
    for n in names:
        s = SPECIALISTS.get(n)
        tools = LOOKOUT_TOOLS if n == "lookout" else sorted(s.tools, key=lambda t: (t in ("get_item", "get_handoffs"), -rec["used"].get((n, t), 0)))      # its own work first (reading the case is everyone's), most used first
        row = {"name": n, "label": "Lookout" if n == "lookout" else s.label, "role": "orchestrator" if n == "lookout" else "specialist", "stages": STAGES[n],
               "works_on": WORKS_ON[n], "tools": tools, "runs": rec["runs"].get(n, 0), "lookups": rec["lookups"].get(n, 0), "latest_run_id": latest.get(n)}
        if n == "lookout":
            row["by_stage"] = LOOKOUT_BY_STAGE
        if n == "buyers_clerk":
            row.update(drafts=rec["drafts"], questions=rec["questions"])
        rows.append(row)
    return {"recorded_runs": rec["recorded_runs"], "recorded_cost_usd": rec["recorded_cost_usd"], "earlier_prompt": rec["earlier_prompt"], "agents": rows}


@router.get("/evals/summary", operation_id="evalsSummary", summary="The last measured eval round, dated: each kind of check as measured, never one pass rate")
def evals_summary() -> dict:
    root = str(Path(__file__).resolve().parents[3])      # the repo root, where evals/ lives; the app runs from backend/
    if root not in sys.path:
        sys.path.append(root)
    try:
        from evals.summary import summary  # noqa: PLC0415
    except ImportError as e:
        raise HTTPException(404, "no eval report") from e
    try:
        return summary()
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, "no eval report") from e


@router.get("/evals/report", include_in_schema=False)
def evals_report():
    """The committed eval report page (evals/report.html), so "Full report" opens from the app."""
    from fastapi.responses import FileResponse  # noqa: PLC0415

    page = Path(__file__).resolve().parents[3] / "evals" / "report.html"
    if not page.exists():
        raise HTTPException(404, "no eval report")
    return FileResponse(page, media_type="text/html")
