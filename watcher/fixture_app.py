"""A contract-level stand-in for the app (api/openapi.yaml), with the Yunzhan fire in it.

It exists so the scenarios and their graders are proven before the real app does; the same scenario then
runs against the real app. `bugs` switches on deliberate defects, so tests can show the scenario catches them.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

CONTACT = "li.wei@yunzhan-motor.example"
BODY = ("Dear Li Wei,\n\nWe need revised delivery dates and an allocation from Plant 1 for HPO-26-00450 line 10, "
        "HPO-26-00614 lines 10 and 20 (HR-40110, 1,140 pcs open). Halden's October Tern build needs 364 of these.\n\nDana")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Reject(BaseModel):
    reason: str
    rejected_by: str


class Approve(BaseModel):
    payload_hash: str
    approved_by: str


def make_app(bugs: set[str] | None = None) -> FastAPI:
    bugs = bugs or set()
    app = FastAPI()
    st: dict = {"runs": {}, "actions": {}, "outbox": [], "n": 0}

    def emit_file(ev: dict) -> None:
        d = Path(os.environ.get("LOOKOUT_EVENTS_DIR", "watcher/events"))
        d.mkdir(parents=True, exist_ok=True)
        line = {"event_id": f"evt-{ev['seq']}", "ts": ev["ts"], "source": "agent", "kind": ev["type"], "severity": "info",
                "summary": ev["summary"], "run_id": ev["run_id"], "request_id": None, "item_id": None,
                "body": {k: ev[k] for k in ("seq", "t_ms", "agent_label", "parent_run_id") if k in ev} | (ev["payload"] or {})}
        with (d / f"{datetime.now(timezone.utc):%Y-%m-%d}.ndjson").open("a") as fh:
            fh.write(json.dumps(line) + "\n")

    def item(key: str, group: str) -> dict:
        return {"key": key, "group": group, "severity": "high", "title": key, "owner": "Dana Reyes"}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "snapshot_date": "2026-09-25"}

    @app.get("/api/action-items")
    def items():
        first = [item("disruption:SUP-0001", "disruption")]
        rest = [item("tariff:HR-50110", "tariff"), item("unknown:HR-40220", "unknown")]
        return rest + first if "fire_not_first" in bugs else first + rest

    @app.post("/api/action-items/{key}/runs", status_code=202)
    def start(key: str):
        st["n"] += 1
        rid = f"run-{st['n']}"
        child = f"{rid}-planner"
        gate = "denied" if "no_gate" not in bugs else None
        rows = [
            ("run.started", rid, None, "Lookout began work on the Yunzhan fire", None, 0, {}),
            ("step.text", rid, None, "Reading the notice: ten lines are affected", "Lookout", 700, {}),
            ("child.started", child, rid, "Is the October Tern build short of HR-40110?", "Supply planner", 900, {}),
            ("tool.called", child, rid, "open_supply HR-40110", "Supply planner", 1200, {"gate": "allowed" if "no_gate" not in bugs else None, "name": "open_supply"}),
            ("tool.result", child, rid, "1,140 open, all on the notice", "Supply planner", 1500, {"numbers": [{"id": "shortage:HR-40110:2026-10:short", "value": "364"}]}),
            ("child.finished", child, rid, "October is short of 364 motors before stock on hand", "Supply planner", 2100, {}),
            ("action.staged", rid, None, "Request to Li Wei staged", "Buyer's clerk", 2600, {"type": "supplier_request", "recipient": CONTACT}),
            ("run.finished", rid, None, "Done", None, 4200, {"status": "ok", "tool_calls": 1, "first_step_ms": 700, "wall_ms": 4200, "cost_usd": 0.05}),
        ]
        evs = []
        for seq, (t, r, parent, summ, label, ms, payload) in enumerate(rows, 1):
            ev = {"run_id": r, "parent_run_id": parent, "seq": seq, "ts": _now(), "t_ms": ms, "type": t, "agent_label": label,
                  "summary": summ, "refs": [], "payload": payload}
            evs.append(ev)
            emit_file(ev)
            if t == "step.text":  # a streamed token delta repeats the seq of the step it extends, as the real stream does
                evs.append({**ev, "type": "step.delta", "summary": "Reading", "t_ms": ev["t_ms"] - 10})
        recipient = "accounts@yunzhan-rnotor.example" if "wrong_recipient" in bugs else CONTACT
        h = hashlib.sha256((BODY + recipient).encode()).hexdigest()
        aid = f"A-2026-{st['n']:04d}"
        st["actions"][aid] = {"action_id": aid, "type": "supplier_request", "state": "proposed", "recipient": recipient, "subject": "Revised dates and allocation",
                              "body": BODY, "payload_hash": h, "run_id": rid, "item_key": key, "proposed_at": _now()}
        st["runs"][rid] = {"run_id": rid, "status": "ok", "recorded": False, "item_key": key, "events": evs,
                           "recommendation": {"finding": "October Tern build is short of 364 motors", "numbers": [{"id": "shortage:HR-40110:2026-10:short", "value": "364", "unit": "pcs", "headline": True}],
                                              "assumptions": [], "would_change": [], "action_ids": [aid],
                                              "open_questions": [{"what": "on-hand stock", "why_it_blocks": "no inventory file", "owner": "Dana", "question": "How many HR-40110 are on hand?"}]},
                           "verifier": {"passed": "bad_verifier" not in bugs, "numbers_checked": 1, "numbers_from_tools": 1, "failures": []}}
        return {"run_id": rid, "status": "running"}

    @app.get("/api/runs/{rid}/events")
    def events(rid: str):
        run = st["runs"].get(rid) or (_ for _ in ()).throw(HTTPException(404))
        def gen():
            for e in run["events"]:
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/runs/{rid}")
    def run_detail(rid: str):
        return st["runs"].get(rid) or (_ for _ in ()).throw(HTTPException(404))

    @app.get("/api/actions")
    def actions(state: str | None = None):
        return [a for a in st["actions"].values() if state is None or a["state"] == state]

    @app.get("/api/actions/{aid}")
    def action(aid: str):
        return st["actions"].get(aid) or (_ for _ in ()).throw(HTTPException(404))

    @app.post("/api/actions/{aid}/approve")
    def approve(aid: str, body: Approve):
        a = st["actions"].get(aid) or (_ for _ in ()).throw(HTTPException(404))
        if a["state"] != "proposed":
            raise HTTPException(409, "not proposed")
        if "no_hash_check" not in bugs and body.payload_hash != a["payload_hash"]:
            raise HTTPException(409, "hash mismatch")
        a["state"] = "executed"
        st["outbox"].append({"outbox_id": f"O-{aid}", "action_id": aid, "to": a["recipient"], "subject": a["subject"],
                             "body": a["body"], "sent_at": _now(), "status": "sent_simulated"})
        return a

    @app.post("/api/actions/{aid}/reject")
    def reject(aid: str, body: Reject):
        a = st["actions"].get(aid) or (_ for _ in ()).throw(HTTPException(404))
        if a["state"] != "proposed":
            raise HTTPException(409, "not proposed")
        a["state"] = "rejected"
        return a

    @app.get("/api/outbox")
    def outbox():
        return st["outbox"]

    return app
