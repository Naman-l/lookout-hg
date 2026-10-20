"""Recorded runs: a real run of ours, saved with everything the screens show, replayed through the same SSE
route when there is no API key. The replay is labelled `recorded` with its date; approving its draft goes
through the real ledger (the draft is staged for real, with the recorded id and payload).

`python -m app.organism.record <item_key>` makes a recording from a live run."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..domain.actions import ledger
from ..domain.common import AS_OF, EntityRef, recipe_as_of
from .runs import store
from .runs.events import Recorder
from .schemas import RunEvent

DIR = Path(__file__).parent / "recordings"
_PACE = float(os.environ.get("LOOKOUT_REPLAY_PACE", "1"))  # 0 in tests: no waiting


def live_available() -> bool:
    """Live runs need a model. LOOKOUT_MODE=live|recorded forces it; otherwise a key (or LOOKOUT_LIVE=1, for a
    machine logged in through the CLI) means live and its absence means recorded."""
    mode = os.environ.get("LOOKOUT_MODE", "auto")
    if mode in ("live", "recorded"):
        return mode == "live"
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or os.environ.get("LOOKOUT_LIVE") == "1"      # auto and hybrid: a model only with a key


def runs_live(recording: dict | None) -> bool:
    """Whether this run goes to the model. LOOKOUT_MODE=hybrid replays whatever has a recording (the demo cases: fast, the same every
    time) and runs live only what has none (a new message, another part, a new question), and only with a key. Other modes: live_available()."""
    if os.environ.get("LOOKOUT_MODE") == "hybrid" and recording is not None:
        return False
    return live_available()


def _path(item_key: str, directory: Path | None = None) -> Path:
    return (directory or DIR) / (item_key.replace(":", "_") + ".json")


def sidecar_path(p: Path) -> Path:
    return p.parent / "grades" / p.name


def with_grade(doc: dict, sidecar: dict) -> dict:
    """A recording with a later grade laid over it: the recording itself is never rewritten, the grade of the Reviewer that read it is kept beside it."""
    doc = json.loads(json.dumps(doc))
    if doc.get("recommendation"):
        doc["recommendation"]["grade"] = sidecar["grade"]
    for e in doc["events"]:
        if e["type"] == "review.result":
            e["summary"], e["payload"] = sidecar["review_summary"], sidecar["review_payload"]
    return doc


def for_today(doc: dict) -> bool:
    """A recording speaks of the day it was made on: it is shown only when the data is that day. One with no day was made on the recipe's day."""
    return str(doc.get("as_of") or recipe_as_of().isoformat()) == AS_OF.isoformat()


def find(item_key: str, directory: Path | None = None, *, any_day: bool = False) -> dict | None:
    """The recording of an item for the data's day; None when there is none or it was made on another day (`any_day` for the caller that must know it exists)."""
    p = _path(item_key, directory)
    if not p.exists():
        return None
    doc, side = json.loads(p.read_text()), sidecar_path(p)
    doc = with_grade(doc, json.loads(side.read_text())) if side.exists() else doc
    return doc if any_day or for_today(doc) else None


def save(db_path, run_id: str, directory: Path | None = None) -> Path:
    """Write a finished run (events, Recommendation, verifier result, staged drafts) as a fixture."""
    row = store.read_run(db_path, run_id)
    events = [e.model_dump(mode="json") for _, e in store.read_tree_events(db_path, run_id)]
    actions = [a.model_dump(mode="json") for a in ledger.for_run(db_path, run_id)]
    doc = {
        "recorded_at": datetime.now(timezone.utc).isoformat(), "as_of": AS_OF.isoformat(), "run_id": run_id, "item_key": row["item_key"],
        "run": {k: row[k] for k in ("status", "model", "prompt_hash", "toolset_hash", "sdk_version", "cost_usd", "wall_ms", "first_step_ms", "turns", "tool_calls", "denied_calls")},
        "shape": "tree", "reviewer_mode": os.environ.get("LOOKOUT_REVIEW_MODE", "after"),  # how the agent was run: the stamp beside the prompt hash
        "events": events, "recommendation": json.loads(row["recommendation_json"]) if row["recommendation_json"] else None,
        "verifier": json.loads(row["verifier_json"]) if row["verifier_json"] else None,
        "actions": [{k: a[k] for k in ("action_id", "type", "item_key", "target", "recipient", "subject", "body", "change")} for a in actions],
    }
    started = next((e for e in events if e["type"] == "run.started" and e.get("payload", {}).get("question")), None)
    if started:  # an Ask recording keeps the question (and the record on screen) so the Ask box can offer it as an example
        doc["question"], doc["context"] = started["payload"]["question"], started["payload"].get("context")
    p = _path(row["item_key"], directory)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return p


def _rewrite(text: str, old: str, new: str) -> str:
    return text.replace(old, new)


def admitted(db_path, doc: dict, a: dict, item=None) -> tuple[str | None, str | None]:
    """(the action id that stands for this recorded draft, why it was not staged). A saved draft goes through the rules the live path applies:
    nothing is chased before the date the item waits for, and one open thread per supplier contact. A refused draft stands for the request already there, if any."""
    from .workflows.work_item import waiting  # noqa: PLC0415

    if a["type"] != "supplier_request":
        return None, None
    if item is not None and waiting(item):
        return None, f"it chases dates not yet due (nothing is chased before {item.waits_until})"
    held = ledger.open_thread(db_path, a["recipient"])
    if held is not None and held.item_key != a["item_key"] and held.state in ("proposed", "approved", "executed"):
        return held.action_id, f"a request to this contact is already {'sent' if held.state != 'proposed' else 'waiting'} ({held.action_id}): one open thread per supplier contact"
    return None, None


def _styled(db_path, a: dict) -> str:
    """A recorded letter in the house style the live draft tool applies (letters.house_style), so the seed reads as a live run would."""
    from ..domain.actions.letters import house_style  # noqa: PLC0415
    from . import company  # noqa: PLC0415

    return house_style(a["body"] or "", db_path=db_path, item_key=a["item_key"] or "", subject=a["subject"] or "", company_short=company.names(db_path)[1], recipient=a["recipient"] or "") if a["type"] == "supplier_request" else a["body"]


def _named_owner(db_path, a: dict, target, run_id: str) -> dict | None:
    """The recorded change, with the draft's one signer named when the recording did not: the live draft tool names the buyer of its lines, and the ledger's
    own rule (`owners_of_action`) finds the same buyer for a saved draft, so the UI shows who signs it."""
    change = a["change"]
    if a["type"] != "supplier_request" or (change or {}).get("owner"):
        return change
    from types import SimpleNamespace  # noqa: PLC0415

    from ..domain.actions import approvers  # noqa: PLC0415

    try:
        owners = approvers.owners_of_action(db_path, SimpleNamespace(change=change, owner=None, item_key=a["item_key"], run_id=run_id, target=target))
    except Exception:  # noqa: BLE001  owners unknown: the draft is staged as saved
        return change
    return {**(change or {}), "owner": next(iter(owners))} if owners and len(owners) == 1 else change


async def replay(doc: dict, *, db_path, run_id: str, recorder: Recorder, speed: float = 1.0, max_gap_s: float = 0.7) -> None:
    """Stage the recorded draft in the real ledger, then emit the recorded events with their original rhythm
    (long model pauses are shortened), so the run page behaves exactly as it does live."""
    old = doc["run_id"]
    renamed: dict[str, str] = {}  # recorded action id -> the draft this replay actually stages
    dropped: dict[str, str] = {}  # recorded action id -> why the live rules would not stage it
    from . import services as default_services  # noqa: PLC0415

    svc = default_services.get(db_path)
    try:
        item = svc.attention.get_item(doc["item_key"])
    except Exception:  # noqa: BLE001  an item that is gone is replayed as saved
        item = None
    finally:
        svc.close()
    for a in doc["actions"]:
        target = EntityRef.model_validate(a["target"]) if a["target"] else None
        held = ledger.open_thread(db_path, a["recipient"]) if a["type"] == "supplier_request" else None
        if held is not None and held.state == "proposed" and held.item_key == a["item_key"] != doc["item_key"]:
            # this run amended an earlier case's waiting draft (amend_draft: one letter per contact): the replay makes the same edit, never a second draft
            body = _styled(db_path, a)
            asks = ledger.asks_of(held)
            change = None if doc["item_key"] in asks else {**(held.change or {}), "asks": [*asks, doc["item_key"]],     # the amending case's ask rides in this letter, as amend_draft records it live
                                                           "amended_for": [*((held.change or {}).get("amended_for") or []), doc["item_key"]]}
            if (held.body or "") != body or change is not None:
                ledger.update_draft(db_path, held.action_id, subject=a["subject"] or held.subject or "", body=body, edited_by="Lookout", change=change, run_id=run_id)
            ledger.link_to_run(db_path, run_id, held.action_id)
            renamed[a["action_id"]] = held.action_id
            continue
        standing, why = admitted(db_path, doc, a, item)
        if why:
            dropped[a["action_id"]] = why
            if standing:
                renamed[a["action_id"]] = standing
                ledger.link_to_run(db_path, run_id, standing)
            continue
        if a["type"] == "note" and (a.get("change") or {}).get("kind") in ("record", "note"):  # a decision or a note staged for the owner's signature (stage_decision): staged again, PROPOSED, never executed by the replay (LOOKOUT P1: the demo's Ask 2 replayed its note as executed)
            staged = ledger.propose(db_path, type="note", item_key=a["item_key"], run_id=run_id, target=target, recipient=None, subject=a.get("subject"), body=a["body"], change=a["change"])
        elif a["type"] == "note":  # a logged question: executed at once, as it was
            staged = ledger.record_app_action(db_path, type=a["type"], item_key=a["item_key"], target=target, body=a["body"], by="Lookout", change=a["change"], run_id=run_id)
        else:  # a draft: staged for real, a fresh one per replay, so Work this can be pressed again after an approval
            staged = ledger.propose(db_path, type=a["type"], item_key=a["item_key"], run_id=run_id, target=target, recipient=a["recipient"],
                                    subject=a["subject"], body=_styled(db_path, a), change=_named_owner(db_path, a, target, run_id))
        renamed[a["action_id"]] = staged.action_id
    store.insert_run(db_path, run_id=run_id, item_key=doc["item_key"], workflow="work_item", status="running", started_at=datetime.now(timezone.utc).isoformat(),
                     model=doc["run"]["model"], prompt_hash=doc["run"]["prompt_hash"], toolset_hash=doc["run"]["toolset_hash"], sdk_version=doc["run"]["sdk_version"],
                     recorded=1, recorded_at=doc["recorded_at"])
    previous = 0
    children: dict[str, Recorder] = {}
    for raw in doc["events"]:
        text = _rewrite(json.dumps(raw), old, run_id)
        for was, now in renamed.items():
            text = text.replace(was, now)
        e = RunEvent.model_validate(json.loads(text))
        if e.type == "action.staged" and (e.payload or {}).get("action_id") in dropped.keys() | {v for k, v in renamed.items() if k in dropped}:
            gone = next(k for k in dropped if k in text or renamed.get(k) == (e.payload or {}).get("action_id"))
            recorder.emit("step.text", f"The saved draft was not staged: {dropped[gone]}", agent="lookout", _t_ms=e.t_ms)
            continue
        await asyncio.sleep(min(max(e.t_ms - previous, 0) / 1000 / speed, max_gap_s) * _PACE)
        previous = e.t_ms
        if e.type == "run.finished" and e.run_id == run_id:  # save the final state first, then announce it
            _finish_row(doc, db_path, run_id, renamed, dropped)
        rec = recorder if e.run_id == run_id else children.setdefault(e.run_id, recorder.child(e.run_id))
        payload = dict(e.payload)
        if e.type == "run.finished" and e.run_id == run_id:  # a replay made no model calls: its cost is 0 and the recording's is shown as the original's
            payload.update(original_cost_usd=payload.get("cost_usd"), cost_usd=0, original_tokens_in=payload.get("tokens_in"), original_tokens_out=payload.get("tokens_out"), tokens_in=0, tokens_out=0)
        rec.emit(e.type, e.summary, agent=e.agent, tool_use_id=e.tool_use_id, refs=e.refs, _t_ms=e.t_ms, **payload)


REPLAY_TIMEOUT_S = float(os.environ.get("LOOKOUT_REPLAY_TIMEOUT", "60"))


async def replay_safely(doc: dict, *, db_path, run_id: str, recorder: Recorder, timeout: float | None = None, **kw) -> bool:
    """A replay can never hang or leave a run 'running': if a saved step cannot be played under today's rules, an error is raised, or the time is up, the run ends at once as
    'replay did not match today's rules' and shows the saved answer, marked as such. True when it played through."""
    try:
        await asyncio.wait_for(replay(doc, db_path=db_path, run_id=run_id, recorder=recorder, **kw), timeout or REPLAY_TIMEOUT_S)
        return True
    except BaseException as e:  # noqa: BLE001  a cancelled or failed replay still ends the run
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        why = "it took too long" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"
        if store.read_run(db_path, run_id) is None:
            store.insert_run(db_path, run_id=run_id, item_key=doc["item_key"], workflow="work_item", status="running", started_at=datetime.now(timezone.utc).isoformat(), recorded=1, recorded_at=doc["recorded_at"])
        rec_json = json.dumps({**doc["recommendation"], "replay_note": "This is the saved answer: the replay did not match today's rules."}) if doc.get("recommendation") else None
        store.update_run(db_path, run_id, status="did_not_pass", recommendation_json=rec_json, verifier_json=json.dumps(doc["verifier"]) if doc.get("verifier") else None, cost_usd=0.0)
        recorder.emit("run.failed", f"The saved run did not match today's rules ({why}); the saved answer is shown", error_kind=type(e).__name__, message=why)
        recorder.emit("run.finished", "Replay did not match today's rules", status="did_not_pass")
        return False


def _finish_row(doc: dict, db_path, run_id: str, renamed: dict, dropped: dict | None = None) -> None:
    r = doc["run"]
    rec = dict(doc["recommendation"]) if doc["recommendation"] else None
    if rec and dropped:  # a draft the live rules would not stage is not in the answer's actions either
        rec["action_ids"] = [x for x in rec.get("action_ids", []) if x not in dropped or x in renamed]
    rec_json = json.dumps(rec) if rec else None
    for was, now in renamed.items():
        rec_json = rec_json.replace(was, now) if rec_json else rec_json
    store.update_run(db_path, run_id, status=r["status"], cost_usd=0.0, wall_ms=r["wall_ms"], first_step_ms=r["first_step_ms"], turns=r["turns"],
                     tool_calls=r["tool_calls"], denied_calls=r["denied_calls"],
                     recommendation_json=rec_json,
                     verifier_json=json.dumps(doc["verifier"]) if doc["verifier"] else None)


def ask_examples(directory: Path | None = None) -> list[dict]:
    """The questions that have a recording, for the Ask box to offer when no model is available."""
    out = []
    for p in sorted((directory or DIR).glob("ask_*.json")):
        d = json.loads(p.read_text())
        if d.get("question") and for_today(d):
            out.append({"question": d["question"], "context": d.get("context"), "recorded_at": d["recorded_at"]})
    return out
