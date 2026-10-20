"""Run endpoints (api/openapi.yaml): start a run on an action item, list runs, read one, and watch it over SSE.

ORCH mounts this router under /api. Events are stored before they are pushed, so the stream replays what was
stored and then follows the live recorder; a reconnecting page resumes with Last-Event-ID and loses nothing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..domain.common import AS_OF, EntityRef
from sse_starlette.sse import EventSourceResponse

from .. import db as _db
from . import entities, id_shapes, recordings
from .runs import stages as run_stages, store, tables as run_tables
from .runs.events import Recorder, mark_superseded
from .schemas import Recommendation, Run, RunDetail, RunRef, VerifierResult
from .workflows.ask import ask_key, run_ask
from .workflows.import_file import run_import
from .workflows.work_item import run_workflow

router = APIRouter(tags=["runs"])
LIVE: dict[str, tuple[Recorder, asyncio.Task, str]] = {}  # run_id -> (recorder, task, item_key); root runs only


def _active_run(key: str) -> str | None:
    """The run already working this item, if any. A run counts until it reaches a final status; the Reviewer's grade, added after delivery in the same task, does not hold the item."""
    for rid, (_, t, k) in LIVE.items():
        if k == key and not t.done():
            row = store.read_run(_db.DB_PATH, rid)
            if row is None or row["status"] == "running":
                return rid
    return None


class StartRun(BaseModel):
    asked_by: str | None = None
    live: bool = False  # "Run live": work a recorded item live anyway (hybrid mode); refused when no model is available


class ImportFile(BaseModel):
    filename: str  # a .csv name, no path
    text: str  # the file's text
    asked_by: str | None = None


class AskPage(BaseModel):
    kind: str  # the route kind: today, case, approvals, inbox, build, supplier, part, orders, forecast, data, hood, activity, ...
    label: str = ""  # what the buyer sees: the page title and its active tab or filters ("Today · Yours · Disruption")


class AskBody(BaseModel):
    question: str
    context: EntityRef | None = None  # the record on screen, if any
    page: AskPage | None = None  # the page the question was asked from (h10): the agent may say where the buyer is and what it can do from there
    thread_id: str | None = None  # the run id of the answer this question follows: "those", "it" and "the same" mean what that answer was about
    asked_by: str | None = None


def _operator_fields(row: dict, events: list[dict]) -> dict:
    """The per-run columns an operator reads, from the stored recommendation, verifier and the few events that carry them."""
    out: dict = {"workflow": row.get("workflow") or ""}
    out["specialists"] = [{"agent": e["agent"], "label": e["agent_label"]} for e in events if e["type"] == "child.started"]
    fin = next((e["payload"] for e in reversed(events) if e["type"] == "run.finished"), {})
    out.update(first_token_ms=fin.get("first_token_ms"), tokens_in=fin.get("tokens_in"), tokens_out=fin.get("tokens_out"))
    if row.get("recorded") and fin.get("original_cost_usd") is not None:  # a replay costs nothing; the run it replays did, and the row says so
        out["original_cost_usd"] = f"{float(fin['original_cost_usd']):.4f}"
        out.update(original_tokens_in=fin.get("original_tokens_in"), original_tokens_out=fin.get("original_tokens_out"))  # a replay reads and writes nothing; the run it replays did
    started = next((e["payload"] for e in events if e["type"] == "run.started"), {})
    if started.get("question"):  # an Ask run is named by its question, not by its key
        out["title"] = started["question"]
    if row.get("verifier_json"):
        out["verifier_passed"] = bool(json.loads(row["verifier_json"]).get("passed"))
    if row.get("recommendation_json"):
        g = json.loads(row["recommendation_json"]).get("grade") or {}
        out.update(reviewer_score=g.get("reviewer_score"), checks_passed=g.get("checks_passed"), checks_total=g.get("checks_total"), revised=bool(g.get("revised")))
    return out


def _run(row: dict, events: list[dict] | None = None) -> Run:
    return Run(
        **_operator_fields(row, events or []),
        run_id=row["run_id"], item_key=row["item_key"], asked_by=row.get("asked_by"), status=row["status"], started_at=row["started_at"],
        first_step_ms=row["first_step_ms"], duration_ms=row["wall_ms"], recorded=bool(row.get("recorded")), recorded_at=row.get("recorded_at"), tool_calls=row["tool_calls"] or 0, denied_calls=row["denied_calls"] or 0,
        cost_usd=None if row["cost_usd"] is None else f"{row['cost_usd']:.4f}", model=row["model"] or "", prompt_hash=row["prompt_hash"] or "",
    )


def _answered_by_code(key: str) -> bool:
    """A trust item, or a triage or reply on a message whose sender failed the trust checks: code answers it, so no model and no key are needed."""
    if key.startswith("trust:"):
        return True
    if key.startswith(("triage:", "reply:")):
        from . import services as _services  # noqa: PLC0415

        svc = _services.get(str(_db.DB_PATH))
        try:
            v = svc.inbox.trust(key.split(":", 1)[1])
            return v is not None and not v.may_act
        finally:
            svc.close()
    return False


@router.post("/action-items/{key}/runs", status_code=202, response_model=RunRef, responses={409: {"model": RunRef}}, operation_id="startRun")
async def start_run(key: str, body: StartRun | None = None):
    """Work this item with the agent. Returns at once; follow the run on /runs/{run_id}/events."""
    active = _active_run(key)
    if active:  # one run per item at a time: the second request is told which run is already going
        return JSONResponse(status_code=409, content=RunRef(run_id=active, status="running").model_dump())
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    rec = Recorder(run_id, _db.DB_PATH)
    doc = recordings.find(key)
    if body and body.live and not recordings.live_available():
        raise HTTPException(503, "The agent is not connected, so this item cannot run live. Its saved run can still be shown.")
    if (body and body.live) or recordings.runs_live(doc) or _answered_by_code(key):  # a trust item is answered by code, so it needs no model and no key
        task = asyncio.create_task(_execute(key, run_id, rec, body.asked_by if body else None))
    else:  # no model, or hybrid with a recording: serve a real recorded run, labelled as such
        if doc is None:
            raise HTTPException(503, _no_recording(key))
        task = asyncio.create_task(_replay(doc, run_id, rec))
    LIVE[run_id] = (rec, task, key)
    for _ in range(100):  # the runner writes the run row first; wait for it so the ref is readable at once
        if store.read_run(_db.DB_PATH, run_id):
            break
        await asyncio.sleep(0.02)
    return RunRef(run_id=run_id, status="running")


@router.post("/parts/{part}/compare-runs", status_code=202, response_model=RunRef, responses={409: {"model": RunRef}}, operation_id="startCompareRun")
async def start_compare_run(part: str, body: StartRun | None = None):
    """Compare quotes on a part with the Sourcing analyst. A run on a part rather than on an Action list item."""
    return await start_run(f"compare:{part}", body)


INCOMING = Path(os.environ.get("LOOKOUT_INCOMING", Path(tempfile.gettempdir()) / "lookout-incoming"))
MAX_UPLOAD = 2_000_000


@router.post("/messages/{message_id}/triage-runs", status_code=202, response_model=RunRef, responses={409: {"model": RunRef}}, operation_id="startTriageRun")
async def start_triage(message_id: str, body: StartRun | None = None):
    """Triage one message with the Inbox analyst: what it is, what it changes, whether its sender is who they claim."""
    return await start_run(f"triage:{message_id}", body)


@router.post("/messages/{message_id}/reply-runs", status_code=202, response_model=RunRef, responses={409: {"model": RunRef}}, operation_id="startReplyRun")
async def start_reply(message_id: str, body: StartRun | None = None):
    """Draft a reply: the analyst reads the thread, the clerk drafts one reply to the contact on file, awaiting approval."""
    return await start_run(f"reply:{message_id}", body)


@router.post("/imports/steward-runs", status_code=202, response_model=RunRef, operation_id="startImportRun")
async def start_import(body: ImportFile):
    """Onboard a CSV with the Data steward: code reports its drift from the known export, the steward writes and tries one normaliser step, nothing is loaded."""
    name = Path(body.filename).name
    if not name.lower().endswith(".csv") or len(body.text) > MAX_UPLOAD:
        raise HTTPException(422, "Send a .csv file under 2 MB")
    key = f"import:{name}"
    active = _active_run(key)
    if active:
        return JSONResponse(status_code=409, content=RunRef(run_id=active, status="running").model_dump())
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    rec = Recorder(run_id, _db.DB_PATH)
    doc = recordings.find(key)
    if recordings.runs_live(doc):
        INCOMING.mkdir(parents=True, exist_ok=True)
        (INCOMING / name).write_text(body.text, encoding="utf-8")
        task = asyncio.create_task(_execute_import(name, run_id, rec, body.asked_by))
    else:  # no model (or hybrid): the shipped example replays; any other file needs a key
        if doc is None:
            raise HTTPException(503, "The agent is not connected. Only the example file (purchase_orders_export_2026-10.csv) can be shown without it.")
        task = asyncio.create_task(_replay(doc, run_id, rec))
    LIVE[run_id] = (rec, task, key)
    for _ in range(100):
        if store.read_run(_db.DB_PATH, run_id):
            break
        await asyncio.sleep(0.02)
    return RunRef(run_id=run_id, status="running")


async def _execute_import(name: str, run_id: str, rec: Recorder, asked_by: str | None) -> None:
    try:
        await run_import(name, db_path=str(_db.DB_PATH), incoming_dir=INCOMING, run_id=run_id, recorder=rec, asked_by=asked_by)
    except Exception as e:  # noqa: BLE001
        if store.read_run(_db.DB_PATH, run_id) is None:
            store.insert_run(_db.DB_PATH, run_id=run_id, item_key=f"import:{name}", workflow="import", status="failed", started_at=datetime.now(timezone.utc).isoformat())
        store.update_run(_db.DB_PATH, run_id, status="failed")
        rec.emit("run.failed", f"The run failed: {e}", error_kind=type(e).__name__, message=str(e))
        rec.emit("run.finished", "Run failed", status="failed")


@router.get("/ask/examples", operation_id="askExamples")
def ask_examples() -> list[dict]:
    """Questions that have a recorded answer: what the Ask box can offer when no model is available."""
    return recordings.ask_examples()


@router.post("/ask", status_code=202, response_model=RunRef, operation_id="ask")
async def ask(body: AskBody):
    """Ask Lookout a question. It decides whom to ask; the answer streams like any run and has the Recommendation shape."""
    if not body.question.strip():
        raise HTTPException(422, "Ask a question")
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    rec = Recorder(run_id, _db.DB_PATH)
    doc = recordings.find(ask_key(body.question, body.context))
    if recordings.runs_live(doc):
        task = asyncio.create_task(_execute_ask(body, run_id, rec))
    else:  # no model (or hybrid): the example questions replay a recorded answer; any other question needs a key
        if doc is None:
            raise HTTPException(503, _no_recording(ask_key(body.question, body.context), "The agent is not connected. The example questions (GET /api/ask/examples) still show recorded answers."))
        task = asyncio.create_task(_replay(doc, run_id, rec))
    LIVE[run_id] = (rec, task, ask_key(body.question, body.context))
    for _ in range(100):
        if store.read_run(_db.DB_PATH, run_id):
            break
        await asyncio.sleep(0.02)
    return RunRef(run_id=run_id, status="running")


THREAD_TURNS = 3  # a follow-up carries the last three turns of the conversation (F100), each with its question, answer and case


def order_open_questions(questions: list, answer_text: str, part_rx) -> tuple[list, int]:
    """Display order only (BUYER Q3; SIDEQ: never drop): the questions about a part the answer names first, then the rest, which the UI folds.
    Every question stays in the list. Returns (ordered, how many are about the answer's parts)."""
    named = set(part_rx.findall(answer_text or ""))
    about = lambda q: bool(named & set(part_rx.findall(f"{q.what} {q.question}")))  # noqa: E731
    mine = [q for q in questions if about(q)]
    if not named or not mine:
        return list(questions), len(questions)
    return mine + [q for q in questions if not about(q)], len(mine)


def _thread(thread_id: str | None) -> dict | None:
    """The earlier turn a follow-up continues: its question, its answer and what it was about, from the stored run; and, under `earlier`, the turns
    before it (newest first, up to THREAD_TURNS in all), followed through each run's own thread_id."""
    turn = _turn(thread_id)
    if turn is None:
        return None
    earlier, prev, seen = [], turn.get("thread_id"), {thread_id}
    while prev and prev not in seen and len(earlier) < THREAD_TURNS - 1:
        seen.add(prev)
        t = _turn(prev)
        if t is None:
            break
        earlier.append({k: t[k] for k in ("question", "answer", "context")})
        prev = t.get("thread_id")
    return {**turn, "earlier": earlier}


def _turn(thread_id: str | None) -> dict | None:
    if not thread_id:
        return None
    row = store.read_run(_db.DB_PATH, thread_id)
    if not row:
        return None
    events = [e for _, e in store.read_tree_events(_db.DB_PATH, thread_id)]
    started = next((e.payload for e in events if e.type == "run.started" and e.run_id == thread_id), {})
    rec = json.loads(row["recommendation_json"]) if row.get("recommendation_json") else {}
    refs, seen = [], set()
    for e in events:
        for r in e.refs:
            if r.type != "item" and (r.type, r.id) not in seen and len(refs) < 8:
                seen.add((r.type, r.id))
                refs.append(f"{r.type} {r.id}" + (f" ({r.label})" if r.label else ""))
    ids = {"supplier": set(), "part": set()}  # what the earlier turn worked on, as ids: a follow-up passes ids to the tools, never names
    shapes = {"supplier": id_shapes.pattern(_db.DB_PATH, "supplier", "legacy_supplier"), "part": id_shapes.pattern(_db.DB_PATH, "part")}
    blobs = [json.dumps(e.payload.get("args") or {}, default=str) for e in events if e.type == "tool.called"] + [n.get("id", "") for n in rec.get("numbers", [])]
    for blob in blobs:
        for kind, rx in shapes.items():
            ids[kind].update(rx.findall(blob))
    import sqlite3  # noqa: PLC0415

    try:  # finished goods (the robot assemblies) are not imports: the tariff analyst is not handed them
        with sqlite3.connect(f"file:{_db.DB_PATH}?mode=ro", uri=True) as con:
            products = {r[0] for r in con.execute("SELECT part_number FROM products")}
    except sqlite3.Error:
        products = set()
    return {"question": started.get("question") or "", "answer": rec.get("finding") or "", "about": refs, "ids": {k: sorted(v - products)[:12] for k, v in ids.items() if v - products},
            "context": started.get("context"), "run_id": thread_id, "thread_id": started.get("thread_id")}


async def _execute_ask(body: AskBody, run_id: str, rec: Recorder) -> None:
    try:
        await run_ask(body.question, db_path=str(_db.DB_PATH), context=body.context, asked_by=body.asked_by, run_id=run_id, recorder=rec, thread=_thread(body.thread_id),
                      page=body.page.model_dump() if body.page else None)
    except Exception as e:  # noqa: BLE001
        if store.read_run(_db.DB_PATH, run_id) is None:
            store.insert_run(_db.DB_PATH, run_id=run_id, item_key="ask", workflow="ask", status="failed", started_at=datetime.now(timezone.utc).isoformat())
        store.update_run(_db.DB_PATH, run_id, status="failed")
        rec.emit("run.failed", f"The run failed: {e}", error_kind=type(e).__name__, message=str(e))
        rec.emit("run.finished", "Run failed", status="failed")


async def _execute(key: str, run_id: str, rec: Recorder, asked_by: str | None) -> None:
    try:
        await run_workflow(key, db_path=str(_db.DB_PATH), run_id=run_id, recorder=rec, asked_by=asked_by)
    except Exception as e:  # noqa: BLE001  a crashed run is recorded, so the page never waits on it
        if store.read_run(_db.DB_PATH, run_id) is None:
            store.insert_run(_db.DB_PATH, run_id=run_id, item_key=key, workflow="work_item", status="failed", started_at=datetime.now(timezone.utc).isoformat())
        store.update_run(_db.DB_PATH, run_id, status="failed")
        rec.emit("run.failed", f"The run failed: {e}", error_kind=type(e).__name__, message=str(e))
        rec.emit("run.finished", "Run failed", status="failed")


def _no_recording(key: str, default: str = "The agent is not connected, and there is no recorded run for this item.") -> str:
    if recordings.find(key, any_day=True) is not None:  # a run was saved, for another day's data: it would state that day's facts as today's
        return f"The agent is not connected, and the saved run for this was made on another day's data than the {AS_OF.isoformat()} this database holds: it needs a live agent for this day."
    return default


async def _replay(doc: dict, run_id: str, rec: Recorder) -> None:
    await recordings.replay_safely(doc, db_path=_db.DB_PATH, run_id=run_id, recorder=rec)  # never hangs, never leaves the run running


def _runs_on(key: str) -> list[Run]:
    with store.connect(_db.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM runs WHERE parent_run_id IS NULL AND item_key = ? ORDER BY started_at DESC LIMIT 50", (key,)).fetchall()
    return [_run(dict(r), []) for r in rows]


def _latest_for_item(key: str) -> tuple[dict | None, dict | None]:
    """What the item page shows after a run: the newest finished run on the item (status, verifier, reviewer, cost, time) and its answer, with entities attached."""
    with store.connect(_db.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM runs WHERE parent_run_id IS NULL AND item_key = ? AND status != 'running' ORDER BY started_at DESC LIMIT 1", (key,)).fetchone()
    if row is None:
        return None, None
    row = dict(row)
    run = _run(row, [])
    latest = {"run_id": run.run_id, "status": run.status, "verifier_passed": run.verifier_passed, "reviewer_score": run.reviewer_score,
              "cost_usd": run.cost_usd, "duration_ms": run.duration_ms, "started_at": run.started_at, "recorded": run.recorded, "recorded_at": run.recorded_at}
    answer = None
    if row.get("recommendation_json"):
        rec = Recommendation.model_validate_json(row["recommendation_json"])
        from . import services as _services  # noqa: PLC0415

        svc = _services.get(_db.DB_PATH)
        try:
            entities.attach(rec, getattr(svc, "_session", None))
        finally:
            svc.close()
        answer = rec.model_dump(mode="json")
    return latest, answer


@router.get("/runs", response_model=list[Run], operation_id="listRuns")
def list_runs() -> list[Run]:
    with store.connect(_db.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM runs WHERE parent_run_id IS NULL ORDER BY started_at DESC LIMIT 100").fetchall()
        ids = [r["run_id"] for r in rows]
        by_run: dict[str, list[dict]] = {i: [] for i in ids}
        for rid, ej in con.execute(f"SELECT run_id, event_json FROM run_events WHERE run_id IN ({','.join('?' * len(ids))}) AND (event_json LIKE '%child.started%' OR event_json LIKE '%run.finished%' OR event_json LIKE '%run.started%') ORDER BY seq", ids) if ids else []:
            ev = json.loads(ej)
            if ev["type"] in ("child.started", "run.finished", "run.started"):
                by_run[rid].append(ev)
    return [_run(dict(r), by_run[r["run_id"]]) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetail, operation_id="getRun")
def get_run(run_id: str) -> RunDetail:
    row = store.read_run(_db.DB_PATH, run_id)
    if not row:
        raise HTTPException(404, "no such run")
    events = mark_superseded([e for _, e in store.read_tree_events(_db.DB_PATH, run_id)])
    rec = Recommendation.model_validate_json(row["recommendation_json"]) if row.get("recommendation_json") else None
    if rec is not None:
        from . import services as _services  # noqa: PLC0415

        svc = _services.get(_db.DB_PATH)
        try:
            session = getattr(svc, "_session", None)
            if session is not None and row.get("item_key"):      # the item page's correction of a recorded finding, applied here too: both pages say one thing
                from ..domain.attention import service as attention  # noqa: PLC0415
                from .answer_rules import correct_recommendation  # noqa: PLC0415

                try:
                    rec = correct_recommendation(rec, attention.item_detail(session, row["item_key"]))
                except Exception:  # noqa: BLE001  an item that is gone: the run is shown as recorded
                    pass
            entities.attach(rec, session)
        finally:
            svc.close()
    events, stages = run_stages.attach(events)
    said = " ".join([rec.finding, *[p.text for p in (rec.points or [])]]) if rec is not None else ""
    tables = run_tables.build(events, asked_by=row.get("asked_by"), answer_text=said) if row.get("workflow") == "ask" else []
    first = None
    if row.get("workflow") == "ask" and rec is not None and rec.open_questions:
        rec.open_questions, first = order_open_questions(rec.open_questions, said, id_shapes.pattern(_db.DB_PATH, "part"))
    return RunDetail(
        **_run(row, [e.model_dump() for e in events if e.parent_run_id is None or e.type == "child.started"]).model_dump(),
        events=events, stages=stages, tables=tables, open_questions_first=first,
        recommendation=rec,
        verifier=VerifierResult.model_validate_json(row["verifier_json"]) if row.get("verifier_json") else None,
    )


@router.get("/runs/{run_id}/events", operation_id="streamRunEvents", response_class=EventSourceResponse)
async def stream_run(run_id: str, last_event_id: str | None = Header(default=None)):
    """Server-sent events: the stored steps after Last-Event-ID, then the live ones until the run finishes.
    Each event's data is a RunEvent; `step.delta` events are streamed with no id and are never stored."""
    if not store.read_run(_db.DB_PATH, run_id):
        raise HTTPException(404, "no such run")
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def gen():
        live = LIVE.get(run_id)
        queue = live[0].subscribe() if live else None  # subscribe before replaying, so nothing falls between the two
        last = after
        for rid, e in store.read_tree_events(_db.DB_PATH, run_id, after):
            last = rid
            yield {"id": str(rid), "event": e.type, "data": e.model_dump_json()}
            if e.type in ("run.finished", "run.failed") and e.run_id == run_id and e.type == "run.finished":
                return
        if queue is None:
            return
        while True:
            try:
                rid, e = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                if live[1].done():  # the run ended without a finished event we could see: stop, never hang
                    return
                continue
            if rid is not None and rid <= last:
                continue
            if rid is not None:
                last = rid
            yield {**({"id": str(rid)} if rid is not None else {}), "event": e.type, "data": e.model_dump_json()}
            if e.type == "run.finished" and e.run_id == run_id:
                return

    return EventSourceResponse(gen())


from ..domain.attention import api as _attention_api  # noqa: E402

_attention_api.LATEST_RUN_PROVIDER = _latest_for_item
_attention_api.RUNS_PROVIDER = _runs_on
