"""The morning run: work the top items before the buyer arrives, so the drafts wait in Approvals and the runs show in Agent activity.

`python -m app.organism.prepare` (also run once at app start when no run exists). With a model it works each item live; without one it replays the
saved run of that item, labelled as a replay. Either way the drafts are only staged: nothing is sent. Runs are one at a time."""

from __future__ import annotations

import asyncio
import sys
import uuid

from .. import db as _db
from .. import watcher
from ..domain.actions import ledger
from . import recordings
from .runs import store
from .runs.events import Recorder

MORNING_N = 5  # how many items the morning run works; LOOKOUT_MORNING_N changes it
BY = "Morning run"


def needed(db_path=None) -> bool:
    """True when the run store is empty: a fresh install, where Approvals and Agent activity would otherwise show nothing."""
    with store.connect(db_path or _db.DB_PATH) as con:
        return con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def recover_interrupted(db_path=None) -> list[str]:
    """At startup no run of this process is alive: a run row still 'running' belongs to a server that stopped during it (a restart, Ctrl-C, a port clash). Each is closed as
    'interrupted' (did_not_pass, the saved answer attached if there is one) and the keys of the morning run's own interrupted items are returned, to be run again.
    A run that cannot be closed is reported to the Watcher and skipped: recovering one run must never stop the app starting."""
    db_path = db_path or _db.DB_PATH
    with store.connect(db_path) as con:
        con.row_factory = __import__("sqlite3").Row
        rows = [dict(r) for r in con.execute("SELECT run_id, parent_run_id, item_key, asked_by FROM runs WHERE status = 'running'")]
    again: list[str] = []
    for r in rows:
        try:
            _close_interrupted(db_path, r)
        except Exception as e:  # noqa: BLE001
            watcher.emit("agent", "run.recover_failed", f"Could not close interrupted run {r['run_id']}: {e}", severity="warn", run_id=r["run_id"])
            continue
        if not r["parent_run_id"] and r["asked_by"] in (BY, None) and r["item_key"] not in again:
            again.append(r["item_key"])
    return again


def _close_interrupted(db_path, r: dict) -> None:
    """Close one run a stopped server left 'running': a child run is marked did_not_pass; a top run also gets its saved answer, if any, and the closing events."""
    import json  # noqa: PLC0415

    if r["parent_run_id"]:
        store.update_run(db_path, r["run_id"], status="did_not_pass")
        return
    doc = recordings.find(r["item_key"])
    rec_json = json.dumps({**doc["recommendation"], "replay_note": "This is the saved answer: the server stopped during this run."}) if doc and doc.get("recommendation") else None
    store.update_run(db_path, r["run_id"], status="did_not_pass", recommendation_json=rec_json, cost_usd=0.0)
    rec = Recorder(r["run_id"], db_path)
    rec.seq = store.last_seq(db_path, r["run_id"])  # the stopped run already stored events: continue its numbering, never restart it
    rec.emit("run.failed", "Interrupted: the server stopped during this run", error_kind="Interrupted", message="the server stopped during this run")
    rec.emit("run.finished", "Run interrupted", status="did_not_pass")


def morning_items(db_path=None, n: int | None = None) -> list[str]:
    """The items the morning run works: the top N of the Action list in its own order, leaving out the ones code answers alone (a trust item has no
    draft to prepare). N is LOOKOUT_MORNING_N (default 5). LOOKOUT_MORNING_ITEMS, a comma-separated list of item keys, names them outright."""
    import os  # noqa: PLC0415

    from . import services as _services  # noqa: PLC0415
    from .workflows.work_item import kind_of, plan_for  # noqa: PLC0415

    if os.environ.get("LOOKOUT_MORNING_ITEMS"):
        return [k.strip() for k in os.environ["LOOKOUT_MORNING_ITEMS"].split(",") if k.strip()]
    n = n if n is not None else int(os.environ.get("LOOKOUT_MORNING_N", MORNING_N))
    svc = _services.get(str(db_path or _db.DB_PATH))
    try:
        worked = [i.key for i in svc.attention.list_items() if plan_for(kind_of(i), i.key)]
    finally:
        svc.close()
    return worked[:n]


async def prepare(items=None, *, db_path=None) -> list[tuple[str, str]]:
    """Work each item once, one after another. Returns [(item_key, how)] where how is live, replayed or skipped."""
    from .workflows.work_item import run_workflow  # noqa: PLC0415

    db_path = db_path or _db.DB_PATH
    items = items if items is not None else morning_items(db_path)
    done = []
    for key in items:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        rec = Recorder(run_id, db_path)
        try:
            if recordings.runs_live(recordings.find(key)):      # hybrid: the morning replays what is recorded, no start-up spend
                await run_workflow(key, db_path=str(db_path), run_id=run_id, recorder=rec, asked_by=BY)
                done.append((key, "live"))
            elif (doc := recordings.find(key)) is not None:
                await recordings.replay_safely(doc, db_path=db_path, run_id=run_id, recorder=rec, speed=1000.0, max_gap_s=0)
                store.update_run(db_path, run_id, asked_by=BY)
                done.append((key, "replayed"))
            else:
                done.append((key, "skipped: no saved run"))
        except Exception as e:  # noqa: BLE001  one item failing must not stop the others
            done.append((key, f"failed: {type(e).__name__}"))
    return done


def approvals_waiting(db_path=None) -> int:
    return sum(1 for a in ledger.list_actions(db_path or _db.DB_PATH) if a.state == "proposed")


_TASKS: set = set()


async def on_startup() -> None:
    """At app start on an empty run store, prepare in the background so the first page already has its drafts. LOOKOUT_PREPARE=0 turns it off."""
    import os  # noqa: PLC0415

    if os.environ.get("LOOKOUT_PREPARE") == "0" or "PYTEST_CURRENT_TEST" in os.environ:
        return
    again = recover_interrupted()  # a run a stopped server left 'running' is closed, and the morning run's own items start again
    if not again and not needed():
        return
    task = asyncio.create_task(prepare(again or None))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


if __name__ == "__main__":
    out = asyncio.run(prepare())
    for key, how in out:
        print(f"{how:>22}  {key}")
    print(f"{approvals_waiting()} drafts wait for approval; nothing was sent")
    sys.exit(0 if all(not h.startswith("failed") for _, h in out) else 1)
