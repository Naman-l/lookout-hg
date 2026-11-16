"""Replaying a recorded run. The two recordings in `recordings/hg/` are mocked: written by hand to show how a model's run on those cases reads (no model
ran on this machine), and labelled as mocked wherever they are shown. A replay streams the recording's steps, stages the Buyer's clerk's draft for the
recorded route from today's records (so the text a person signs is the code's house style, never the recording's), and runs the verifier and the
Reviewer on today's figures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app import db as app_db
from app.domain import lookups
from app.domain.attention import service as attention

from . import coderun, tools, verify
from .runs.events import Recorder

HERE = Path(__file__).parent / "recordings" / "hg"


def recordings() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(HERE.glob("*.json"))] if HERE.exists() else []


def recording_for(key: str) -> dict | None:
    return next((d for d in recordings() if d.get("key") == key), None)


async def replay(rec: Recorder, doc: dict, asked_by: str | None, fast: bool = False) -> dict:
    key = doc["key"]
    with app_db.SessionLocal() as s:
        d = attention.item_detail(s, key)
        if d is None:
            rec.emit("run.failed", f"The recording is for {key}, which is not on Today any more.")
            return {"status": "failed"}
        rec.emit("run.started", f"Replaying a recorded run (mocked: {doc.get('note', 'written by hand; no model ran')}).", mode="recorded", mocked=True, model=doc.get("model"))
        last = 0
        for e in doc.get("events", []):
            if not fast:
                await asyncio.sleep(min(0.6, max(0.0, (e.get("t_ms", last) - last) / 1000 / 6)))
            last = e.get("t_ms", last)
            rec.emit(e["type"], e["summary"], agent=e.get("agent", "lookout"), _t_ms=e.get("t_ms"), **(e.get("payload") or {}))
        numbers = {}
        for spec in ("site_planner", "sourcing_analyst", "price_analyst"):
            for tool_name, args in coderun._tool_plan(spec, d):
                res = getattr(tools, tool_name)(s, **{k: v for k, v in args.items() if v is not None})
                numbers.update({n.id: n for n in res.get("numbers", [])})
        routes = tools.routes_of(s, key, asked_by)
        drafts = []
        kind = (doc.get("recommendation") or {}).get("recommended", {}).get("kind")
        if kind and any(r.kind == kind and r.leads_to in ("request", "internal_note") for r in routes):
            from app.domain.actions.routes import draft_route  # noqa: PLC0415

            owner = lookups.member_name(s, d.owner_ids[0]) if d.owner_ids else asked_by
            drafts, how = draft_route(s, app_db.DB_PATH, key, kind, owner, run_id=rec.run_id)
            for a in drafts:
                rec.emit("action.staged", f"Drafted a {'letter' if a.type == 'supplier_request' else 'note'} to {a.recipient} for {owner.split()[0]}'s signature ({how}).", agent="buyers_clerk",
                         action_id=a.action_id)
        recommendation = {**doc.get("recommendation", {}), "action_ids": [a.action_id for a in drafts], "drafted_by": "recording (mocked)",
                          "numbers": [{"id": n.id, "value": str(n.value), "unit": n.unit, "name": n.name, "say": n.say} for i in (doc.get("recommendation", {}).get("recommended") or {}).get("number_ids", [])
                                      for n in [numbers.get(i)] if n is not None]}
        v = verify.check(s, d, recommendation, numbers, drafts, routes)
        rec.emit("verifier.result", f"{v['checked'] - len(v['failures'])} of {v['checked']} checks passed", agent="verifier", verifier=v)
        g = verify.review(s, d, recommendation, drafts, routes)
        recommendation["grade"] = g
        rec.emit("review.result", f"Reviewer {g['reviewer_score']}: {g['summary']}", agent="reviewer", grade=g)
        status = "ok" if not v["failures"] else "did_not_pass"
        rec.emit("run.finished", f"Replayed · {len(drafts)} draft(s) · {v['checked'] - len(v['failures'])} of {v['checked']} checks · Reviewer {g['reviewer_score']}", status=status)
        return {"status": status, "recommendation": recommendation, "verifier": v}
