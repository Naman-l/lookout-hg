"""The agent layer's routes: start a run on a case (replayed from a recording where one exists, else drafted by code), read and stream runs, Ask, the
inbox analyst on a message, the sourcing analyst on a material, and what Under the hood shows. Events are stored before they are pushed, so a page that
reconnects (Last-Event-ID) loses nothing. `mount(app)` adds the routes and the morning run at start-up."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .. import db as _db
from ..domain.common import EntityRef
from . import ask as ask_mod, coderun, replay
from .runs import store
from .runs.events import Recorder

router = APIRouter(tags=["runs"])
TASKS: dict[str, asyncio.Task] = {}


class StartRun(BaseModel):
    asked_by: str | None = None
    live: bool = False  # a live run needs a model: refused here (503), none is connected


class AskPage(BaseModel):
    kind: str = ""
    label: str = ""


class AskBody(BaseModel):
    question: str
    context: EntityRef | None = None
    page: AskPage | None = None
    thread_id: str | None = None
    asked_by: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active(key: str) -> str | None:
    for rid, t in TASKS.items():
        row = store.read_run(_db.DB_PATH, rid)
        if not t.done() and row and row["item_key"] == key and row["status"] == "running":
            return rid
    return None


async def _go(run_id: str, key: str, workflow: str, coro_fn, asked_by: str | None, model: str, recorded: int = 0, title: str | None = None) -> None:
    rec = Recorder(run_id, _db.DB_PATH)
    try:
        out = await coro_fn(rec)
    except Exception as e:  # noqa: BLE001  a failed run is stored as failed, with what failed, and the page says so
        rec.emit("run.failed", f"The run stopped: {type(e).__name__}: {e}")
        store.update_run(_db.DB_PATH, run_id, status="failed", wall_ms=rec.t_ms())
        return
    store.update_run(_db.DB_PATH, run_id, status=out.get("status", "ok"), wall_ms=rec.t_ms(), first_step_ms=rec.first_step_ms, tool_calls=rec.tool_calls,
                     recommendation_json=json.dumps(out.get("recommendation") or {}), verifier_json=json.dumps(out.get("verifier") or {}))
    from app.domain.cache import db_key  # noqa: F401,PLC0415  (the ledger's drafts are read fresh; nothing to clear)


def start(key: str, workflow: str, coro_fn, asked_by: str | None, model: str, recorded: int = 0, title: str | None = None, wait: bool = False):
    run_id = f"R-{uuid.uuid4().hex[:8]}"
    store.insert_run(_db.DB_PATH, run_id=run_id, item_key=key, workflow=workflow, status="running", started_at=_now(), model=model, asked_by=asked_by or "",
                     recorded=recorded, prompt_hash=title or "")
    t = asyncio.create_task(_go(run_id, key, workflow, coro_fn, asked_by, model, recorded, title))
    TASKS[run_id] = t
    return run_id, t


@router.post("/action-items/{key:path}/runs", summary="Work a case: replayed from its recording where one exists, else drafted by code (no model is connected)")
async def start_run(key: str, body: StartRun | None = None):
    body = body or StartRun()
    if body.live:
        raise HTTPException(503, "No model is connected on this machine: runs are drafted by code or replayed from a recording.")
    from ..domain.attention import service  # noqa: PLC0415

    with _db.SessionLocal() as s:
        if service.item_detail(s, key) is None:
            raise HTTPException(404, "no such case")
    running = _active(key)
    if running:
        return {"run_id": running, "status": "running", "existing": True}
    doc = replay.recording_for(key)
    if doc is not None:
        rid, _ = start(key, "work_item", lambda rec: replay.replay(rec, doc, body.asked_by), body.asked_by, doc.get("model", "recorded"), recorded=1)
    else:
        rid, _ = start(key, "work_item", lambda rec: coderun.run_case(rec, key, body.asked_by), body.asked_by, "code")
    return {"run_id": rid, "status": "running"}


@router.post("/ask", summary="Ask Lookout: answered from the records by code (no model is connected), every figure cited")
async def ask(body: AskBody):
    ctx = body.context.model_dump() if body.context else None
    rid, _ = start(f"ask:{uuid.uuid4().hex[:6]}", "ask", lambda rec: ask_mod.run_ask(rec, body.question, ctx, body.asked_by), body.asked_by, "code", title=body.question[:120])
    return {"run_id": rid, "status": "running"}


@router.get("/ask/examples", summary="Suggested questions for the page or case on screen, each with an answer by code")
def ask_examples(page: str | None = None, key: str | None = None, ctx_type: str | None = None, ctx_id: str | None = None, ctx_label: str | None = None):
    """`ctx_*`: the record on screen (a project, a vendor, a material, a member), so the suggestions name it."""
    ctx = {"type": ctx_type, "id": ctx_id, "label": ctx_label} if ctx_type and ctx_id else None
    with _db.SessionLocal() as s:
        return ask_mod.examples(s, page, key, ctx)


@router.get("/ask/everywhere", summary="Suggested questions about the whole company, each answered by code")
def ask_everywhere():
    with _db.SessionLocal() as s:
        return ask_mod.everywhere(s)


@router.post("/messages/{message_id}/triage-runs", summary="The inbox analyst reads a message: what it is and what it changes (by code)")
async def triage(message_id: str, body: StartRun | None = None):
    from .tools import read_message  # noqa: PLC0415

    async def go(rec: Recorder):
        with _db.SessionLocal() as s:
            rec.emit("run.started", "The inbox analyst reads the message as data.", mode="code")
            rec.emit("child.started", "Inbox analyst: what the message is and whether its sender is who they claim to be.", agent="inbox_analyst")
            rec.emit("tool.called", "read_message", agent="inbox_analyst", tool="read_message", args={"message_id": message_id}, gate="allowed")
            res = read_message(s, message_id)
            rec.emit("tool.result", f"{len(res.get('numbers', []))} figures", agent="inbox_analyst", tool="read_message", numbers=[n.model_dump(mode="json") for n in res.get("numbers", [])])
            await asyncio.sleep(coderun.PACE)
            text = f"{res.get('kind')}: {res.get('means')}" + (" Held: nothing is acted on from it." if res.get("trust") == "blocked" else "")
            rec.emit("step.text", text, agent="inbox_analyst")
            rec.emit("child.finished", "Inbox analyst handed off.", agent="inbox_analyst")
            rec.emit("run.finished", text[:200], status="ok")
            return {"status": "ok", "recommendation": {"finding": text, "numbers": [], "drafted_by": "code"}}
    rid, _ = start(f"triage:{message_id}", "triage", go, (body or StartRun()).asked_by, "code")
    return {"run_id": rid, "status": "running"}


@router.post("/messages/{message_id}/reply-runs", summary="Draft a reply through the case the message feeds (by code): the case's recommended route, for the owner's signature")
async def reply(message_id: str, body: StartRun | None = None):
    from ..domain.inbox import service as inbox  # noqa: PLC0415

    with _db.SessionLocal() as s:
        case = inbox._cases(s).get(message_id)
    if case is None:
        raise HTTPException(409, "This message feeds no case: there is nothing to reply to by rule. Open it with a colleague or the vendor on file.")
    rid, _ = start(case.key, "work_item", lambda rec: coderun.run_case(rec, case.key, (body or StartRun()).asked_by), (body or StartRun()).asked_by, "code")
    return {"run_id": rid, "status": "running"}


@router.post("/materials/{code}/compare-runs", summary="The sourcing analyst compares the quotes for a material (by code)")
async def compare(code: str, body: StartRun | None = None):
    from .tools import rate_history  # noqa: PLC0415

    async def go(rec: Recorder):
        with _db.SessionLocal() as s:
            rec.emit("run.started", "The sourcing analyst compares rates and quotes.", mode="code")
            rec.emit("tool.called", "rate_history", agent="sourcing_analyst", tool="rate_history", args={"material": code}, gate="allowed")
            res = rate_history(s, code)
            rec.emit("tool.result", f"{len(res.get('numbers', []))} figures", agent="sourcing_analyst", tool="rate_history", numbers=[n.model_dump(mode="json") for n in res.get("numbers", [])])
            sites = res.get("sites", [])
            text = (f"{len(sites)} sites buy it: lowest {sites[0]['project']} at ₹{sites[0]['rate']:,.0f}, highest {sites[-1]['project']} at ₹{sites[-1]['rate']:,.0f}. The records do not say why."
                    if sites else "No PO on file for this material.")
            rec.emit("run.finished", text, status="ok")
            return {"status": "ok", "recommendation": {"finding": text, "numbers": [], "drafted_by": "code"}}
    rid, _ = start(f"compare:{code}", "compare", go, (body or StartRun()).asked_by, "code")
    return {"run_id": rid, "status": "running"}


class ImportFile(BaseModel):
    filename: str
    text: str
    asked_by: str | None = None


@router.get("/imports/steward-example", summary="The example export waiting in data/incoming (a site office's own ME2N download), for the Data steward")
def steward_example():
    from ..domain.imports.steward import hg  # noqa: PLC0415

    return hg.example()


@router.post("/imports/steward-runs", summary="The Data steward reads an unfamiliar CSV (by code): which export it is, the column map, what drifted, the questions; nothing loads")
async def steward_run(body: ImportFile):
    if not body.filename.lower().endswith(".csv") or len(body.text) > 2_000_000:
        raise HTTPException(422, "a .csv file under 2 MB")
    from ..domain.imports.steward import hg  # noqa: PLC0415

    async def go(rec: Recorder):
        with _db.SessionLocal() as s:
            rec.emit("run.started", f"The Data steward reads {body.filename}.", mode="code")
            rec.emit("child.started", "Data steward: which export this is and what changed.", agent="data_steward")
            rec.emit("tool.called", "drift_report", agent="data_steward", tool="drift_report", args={"file": body.filename}, gate="allowed")
            r = hg.read_file(s, body.filename, body.text)
            await asyncio.sleep(coderun.PACE)
            rec.emit("tool.result", f"reads as {r['table']} ({r['rows_in']} rows); {len(r['mapping'])} columns matched", agent="data_steward", tool="drift_report", numbers=[])
            for f in r["findings"]:
                rec.emit("tool.called", "add_finding", agent="data_steward", tool="add_finding", args=f, gate="staged")
                await asyncio.sleep(coderun.PACE / 2)
            for q in r["questions"]:
                rec.emit("tool.called", "add_question", agent="data_steward", tool="add_question", args=q, gate="staged")
            rec.emit("tool.called", "try_step", agent="data_steward", tool="try_step", args={}, gate="allowed")
            rec.emit("tool.result", f"{sum(1 for c in r['checks'] if c['passed'])} of {len(r['checks'])} checks passed on a copy", agent="data_steward", tool="try_step", script=r["script"], checks=r["checks"])
            rec.emit("child.finished", "Data steward handed off.", agent="data_steward")
            finding = (f"{body.filename} is the {r['table']} export with {len(r['findings'])} differences; {len(r['questions'])} question(s) wait for a person. Nothing was loaded.")
            rec.emit("run.finished", finding, status="ok")
            return {"status": "ok", "recommendation": {"finding": finding, "steward": r, "numbers": [], "drafted_by": "code"}}
    rid, _ = start(f"import:{body.filename}", "import", go, body.asked_by, "code", title=body.filename)
    return {"run_id": rid, "status": "running"}


def _row(r: dict) -> dict:
    rec = json.loads(r.get("recommendation_json") or "{}")
    ver = json.loads(r.get("verifier_json") or "{}")
    grade = rec.get("grade") or {}
    return {"run_id": r["run_id"], "item_key": r["item_key"], "workflow": r["workflow"], "status": r["status"], "started_at": r["started_at"], "wall_ms": r.get("wall_ms"),
            "asked_by": r.get("asked_by"), "recorded": bool(r.get("recorded")), "mode": "recorded" if r.get("recorded") else "code", "model": r.get("model"),
            "title": r.get("prompt_hash") or None, "drafts": len(rec.get("action_ids") or []), "checks": f"{ver.get('checked', 0) - len(ver.get('failures') or [])} of {ver.get('checked', 0)}" if ver else None,
            "grade": grade.get("reviewer_score"), "cost_usd": "0"}


@router.get("/runs", summary="The runs, newest first")
def list_runs():
    with store.connect(_db.DB_PATH) as con:
        con.row_factory = __import__("sqlite3").Row
        rows = [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 200")]
    return [_row(r) for r in rows]


@router.get("/runs/{run_id}", summary="One run: its events, its Recommendation, its checks")
def get_run(run_id: str):
    r = store.read_run(_db.DB_PATH, run_id)
    if r is None:
        raise HTTPException(404, "no such run")
    events = [e.model_dump() for e in store.read_tree_events(_db.DB_PATH, run_id) for e in [e[1]]]
    rec = json.loads(r.get("recommendation_json") or "null")
    ver = json.loads(r.get("verifier_json") or "null")
    review = (rec or {}).get("grade")
    return {**_row(r), "events": events, "recommendation": rec, "verifier": ver, "review": {"grade": review.get("reviewer_score"), "notes": [f["reason"] for f in review.get("failed_checks", [])]} if review else None,
            "question": r.get("prompt_hash") or None}


@router.get("/runs/{run_id}/events", summary="The run's events as they happen (Server-Sent Events; resumes with Last-Event-ID)")
async def stream(run_id: str, last_event_id: str | None = Header(default=None)):
    if store.read_run(_db.DB_PATH, run_id) is None:
        raise HTTPException(404, "no such run")

    async def gen():
        after = int(last_event_id or 0)
        while True:
            for rowid, e in store.read_tree_events(_db.DB_PATH, run_id, after):
                after = rowid
                yield {"id": str(rowid), "event": e.type, "data": e.model_dump_json()}
            r = store.read_run(_db.DB_PATH, run_id)
            if r and r["status"] != "running":
                break
            await asyncio.sleep(0.3)
    return EventSourceResponse(gen())


def latest_for(key: str) -> tuple[dict | None, dict | None]:
    with store.connect(_db.DB_PATH) as con:
        row = con.execute("SELECT run_id, status, started_at, recommendation_json, recorded, model FROM runs WHERE item_key = ? AND status != 'running' ORDER BY started_at DESC LIMIT 1", (key,)).fetchone()
    if not row:
        return None, None
    return {"run_id": row[0], "status": row[1], "started_at": row[2], "mode": "recorded" if row[4] else "code", "model": row[5]}, json.loads(row[3] or "null")


def runs_on(key: str) -> list[dict]:
    with store.connect(_db.DB_PATH) as con:
        con.row_factory = __import__("sqlite3").Row
        return [_row(dict(r)) for r in con.execute("SELECT * FROM runs WHERE item_key = ? ORDER BY started_at DESC", (key,))]


async def morning() -> None:
    """At start-up, with no runs yet: replay the recordings and work the cases by code, so every case page opens with Lookout's reading ready.
    A run never sends anything; the drafts wait for their owners."""
    from ..domain.attention import service  # noqa: PLC0415

    with store.connect(_db.DB_PATH) as con:
        if con.execute("SELECT COUNT(*) FROM runs WHERE workflow = 'work_item'").fetchone()[0]:
            return
    pace = coderun.PACE
    coderun.PACE = 0
    try:
        with _db.SessionLocal() as s:
            keys = [i.key for i in service.what_needs_attention(s) if i.tab != "trust"]
        for key in keys:
            doc = replay.recording_for(key)
            if doc is not None:
                _, t = start(key, "work_item", lambda rec, d=doc: replay.replay(rec, d, None, fast=True), None, doc.get("model", "recorded"), recorded=1)
            else:
                _, t = start(key, "work_item", lambda rec, k=key: coderun.run_case(rec, k, None), None, "code")
            await t
    finally:
        coderun.PACE = pace


def mount(app: FastAPI) -> None:
    from ..domain.attention import api as attention_api  # noqa: PLC0415
    from . import agents_api  # noqa: PLC0415

    attention_api.LATEST_RUN_PROVIDER = latest_for
    attention_api.RUNS_PROVIDER = runs_on
    attention_api.COUNT_PROVIDERS["runs_running"] = lambda s: sum(1 for t in TASKS.values() if not t.done())
    app.include_router(router, prefix="/api")
    app.include_router(agents_api.router, prefix="/api")
    store.connect(_db.DB_PATH).close()      # the run tables exist before anyone reads them

    async def _morning() -> None:
        import os  # noqa: PLC0415

        if os.environ.get("LOOKOUT_MORNING", "1") != "0":
            asyncio.create_task(morning())
    app.state.on_start = [*getattr(app.state, "on_start", []), _morning]
