"""Without a key the app replays a recorded run through the same routes; its draft still goes through the real ledger."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db as app_db
from app.domain.actions import api as actions_api
from app.domain.actions import ledger
from app.organism import api, recordings
from app.organism.runs import store
from app.organism.runs.events import Recorder

from .conftest import seed_buyers
from .test_api import sse

REC = {
    "recorded_at": "2026-10-10T20:00:00+00:00", "run_id": "run-orig", "item_key": "disruption:SUP-0001",
    "run": {"status": "ok", "model": "m", "prompt_hash": "p", "toolset_hash": "t", "sdk_version": "0.2.165", "cost_usd": 0.05, "wall_ms": 24000, "first_step_ms": 5, "turns": 3, "tool_calls": 2, "denied_calls": 0},
    "events": [
        {"run_id": "run-orig", "parent_run_id": None, "seq": 1, "ts": "x", "t_ms": 0, "type": "run.started", "agent": "lookout", "agent_label": "Lookout", "tool_use_id": None, "summary": "Working", "refs": [], "payload": {}},
        {"run_id": "run-orig.1", "parent_run_id": "run-orig", "seq": 1, "ts": "x", "t_ms": 3000, "type": "tool.called", "agent": "supply_planner", "agent_label": "Supply planner", "tool_use_id": "t1", "summary": "calls open_supply", "refs": [], "payload": {"tool": "open_supply", "gate": "allowed"}},
        {"run_id": "run-orig", "parent_run_id": None, "seq": 2, "ts": "x", "t_ms": 9000, "type": "run.finished", "agent": "lookout", "agent_label": "Lookout", "tool_use_id": None, "summary": "Run ok", "refs": [], "payload": {"status": "ok"}},
    ],
    "recommendation": {"finding": "f", "numbers": [], "assumptions": [], "would_change": [], "open_questions": [], "action_ids": ["A-rec00001"]},
    "verifier": {"passed": True, "numbers_checked": 0, "numbers_from_tools": 0, "open_questions_with_owner": 0, "failures": []},
    "actions": [{"action_id": "A-rec00001", "type": "supplier_request", "item_key": "disruption:SUP-0001", "target": {"type": "supplier", "id": "SUP-0001", "label": None},
                 "recipient": "li.wei@yunzhan-motor.example", "subject": "Revised promise dates", "body": "Please confirm.", "change": None}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "r.db")
    seed_buyers(app_db.DB_PATH)
    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    monkeypatch.setattr(recordings, "_PACE", 0)
    monkeypatch.setattr(recordings, "DIR", tmp_path)
    monkeypatch.setattr("app.domain.actions.approvers.owners_of", lambda db, key: None)      # these test the replay through the ledger; this database has no Action list to ask
    monkeypatch.setattr("app.domain.actions.approvers.owners_of_action", lambda db, action: None)
    (tmp_path / "disruption_SUP-0001.json").write_text(json.dumps(REC))
    api.LIVE.clear()
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.include_router(actions_api.router, prefix="/api")
    with TestClient(app) as c:
        yield c


def test_a_recorded_run_streams_through_the_same_route_and_is_labelled(client):
    run_id = client.post("/api/action-items/disruption:SUP-0001/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        events = sse(s)
    assert [e["event"] for e in events] == ["run.started", "tool.called", "run.finished"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["recorded"] is True and detail["recorded_at"] == REC["recorded_at"] and detail["status"] == "ok"
    staged = ledger.list_actions(app_db.DB_PATH)
    assert len(staged) == 1 and detail["recommendation"]["action_ids"] == [staged[0].action_id] and detail["verifier"]["passed"] is True
    assert detail["duration_ms"] == 24000 and detail["cost_usd"] == "0.0000"  # a replay made no model calls; the original cost sits in run.finished
    assert max(e["t_ms"] for e in detail["events"]) == 9000
    assert {e["run_id"] for e in detail["events"]} == {run_id, run_id + ".1"}  # ids were rewritten to this replay


def _replay(client):
    run_id = client.post("/api/action-items/disruption:SUP-0001/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        sse(s)
    return run_id


def test_approving_the_recorded_draft_goes_through_the_real_ledger(client):
    run_id = _replay(client)
    a = client.get("/api/actions", params={"state": "proposed"}).json()[0]
    assert a["run_id"] == run_id
    assert client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": "bad", "approved_by": "Dana Reyes"}).status_code == 409
    ok = client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Dana Reyes"})
    assert ok.status_code == 200 and len(client.get("/api/outbox").json()) == 1


def test_each_replay_stages_a_fresh_draft_so_work_this_can_be_pressed_again(client):
    first = _replay(client)
    a1 = client.get("/api/actions", params={"state": "proposed"}).json()[0]
    client.post(f"/api/actions/{a1['action_id']}/approve", json={"payload_hash": a1["payload_hash"], "approved_by": "Dana Reyes"})
    second = _replay(client)
    pending = client.get("/api/actions", params={"state": "proposed"}).json()
    assert second != first and len(pending) == 1 and pending[0]["action_id"] != a1["action_id"] and pending[0]["run_id"] == second
    assert client.get(f"/api/runs/{second}").json()["recommendation"]["action_ids"] == [pending[0]["action_id"]]


def test_no_key_and_no_recording_is_a_clear_503(client, monkeypatch, tmp_path):
    (tmp_path / "disruption_SUP-0001.json").unlink()
    r = client.post("/api/action-items/disruption:SUP-0001/runs")
    assert r.status_code == 503 and "not connected" in r.json()["detail"]


def test_live_is_chosen_when_a_key_is_set(monkeypatch):
    monkeypatch.delenv("LOOKOUT_MODE", raising=False); monkeypatch.delenv("LOOKOUT_LIVE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert recordings.live_available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert recordings.live_available() is True


def test_a_trust_item_runs_without_a_key_because_code_answers_it(client, monkeypatch):
    monkeypatch.setenv("LOOKOUT_FAKE_SERVICES", "1")
    r = client.post("/api/action-items/trust:fraud-remittance/runs")
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        events = sse(s)
    assert events[-1]["event"] == "run.finished"
    d = client.get(f"/api/runs/{run_id}").json()
    assert d["status"] == "ok" and d["recorded"] is False and d["cost_usd"] == "0.0000" and d["recommendation"]["action_ids"] == []


def test_ask_replays_a_recorded_answer_for_an_example_question_and_lists_the_examples(client, tmp_path):
    from app.organism.workflows.ask import ask_key

    doc = dict(REC, item_key=ask_key("What does the fire cost us?", None), question="What does the fire cost us?", context=None)
    doc["events"] = [dict(e) for e in REC["events"]]
    (tmp_path / "ask_x.json").write_text(json.dumps(doc))
    assert client.get("/api/ask/examples").json()[0]["question"] == "What does the fire cost us?"
    # the file is found by the question's key
    (tmp_path / f"{ask_key('What does the fire cost us?', None).replace(':', '_')}.json").write_text(json.dumps(doc))
    r = client.post("/api/ask", json={"question": "What does the fire cost us?"})
    assert r.status_code == 202
    other = client.post("/api/ask", json={"question": "Something unrecorded?"})
    assert other.status_code == 503 and "examples" in other.json()["detail"]


def test_a_triage_on_a_blocked_message_runs_by_code_without_a_key(client, monkeypatch):
    from types import SimpleNamespace

    from app.organism import api as organism_api

    monkeypatch.setattr("app.organism.services.get", lambda db=None: SimpleNamespace(inbox=SimpleNamespace(trust=lambda mid: SimpleNamespace(may_act=(mid != "bad"))), close=lambda: None))
    assert organism_api._answered_by_code("triage:bad") and organism_api._answered_by_code("reply:bad") and organism_api._answered_by_code("trust:x")
    assert not organism_api._answered_by_code("triage:fine") and not organism_api._answered_by_code("tariff:HR-40110")


def test_every_shipped_recording_is_intact_and_replayable():
    """The no-key experience is only as good as its fixtures: each must parse, end finished, hold a verified Recommendation and keep its own clock."""
    from app.organism.schemas import Recommendation, RunEvent, VerifierResult

    files = sorted(recordings.DIR.glob("*.json"))
    assert files, "no recordings shipped"
    for f in files:
        d = json.loads(f.read_text())
        events = [RunEvent.model_validate(e) for e in d["events"]]
        assert events[0].type == "run.started" and any(e.type == "run.finished" and e.run_id == d["run_id"] for e in events), f.name
        assert d["run"]["status"] == "ok" and d["verifier"]["passed"] is True, f.name
        Recommendation.model_validate(d["recommendation"])
        VerifierResult.model_validate(d["verifier"])
        assert all(e.t_ms >= 0 for e in events) and d["run"]["wall_ms"] is not None, f.name
        assert not any(x in f.read_text() for x in ("/Users/", "/var/folders", "sk-ant")), f.name


async def test_working_the_fire_twice_stages_one_draft_and_both_runs_keep_it(tmp_path):
    """A replay stages the recorded draft for real; a second one finds that draft still waiting and must still own it."""
    from app.domain.actions import ledger

    db = tmp_path / "twice.db"
    store.connect(db).close()
    doc = recordings.find("disruption:SUP-0001")
    for rid in ("run-a1", "run-a2"):
        await recordings.replay(doc, db_path=db, run_id=rid, recorder=Recorder(rid, db), speed=1000.0, max_gap_s=0)
    drafts = [a for a in ledger.list_actions(db) if a.type == "supplier_request"]
    assert len(drafts) == 1 and all(ledger.in_run(db, drafts[0].action_id, r) for r in ("run-a1", "run-a2"))


async def test_a_replay_reports_no_cost_and_keeps_the_originals_beside_it(tmp_path):
    db = tmp_path / "cost.db"
    store.connect(db).close()
    await recordings.replay(recordings.find("disruption:SUP-0001"), db_path=db, run_id="run-c1", recorder=Recorder("run-c1", db), speed=1000.0, max_gap_s=0)
    assert store.read_run(db, "run-c1")["cost_usd"] == 0
    fin = next(e for _, e in store.read_tree_events(db, "run-c1") if e.type == "run.finished" and e.run_id == "run-c1")
    assert fin.payload["cost_usd"] == 0 and fin.payload["tokens_in"] == 0 and fin.payload["original_cost_usd"] > 0

async def test_the_morning_run_replays_saved_runs_once_and_sends_nothing(tmp_path, monkeypatch):
    from app.organism import prepare as pr

    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    db = tmp_path / "m.db"
    from app.organism.runs import store

    store.connect(db).close()
    assert pr.needed(db)
    out = dict(await pr.prepare(("disruption:SUP-0001", "tariff:all", "deadline:nowhere"), db_path=db))
    assert out["disruption:SUP-0001"] == "replayed" and out["deadline:nowhere"].startswith("skipped")
    assert not pr.needed(db) and pr.approvals_waiting(db) >= 1
    with store.connect(db) as con:
        assert {r[0] for r in con.execute("SELECT asked_by FROM runs")} == {"Morning run"}
    from app.domain.actions import ledger

    assert not [a for a in ledger.list_actions(db) if a.type in ("supplier_request", "supplier_alias") and a.state != "proposed"]  # drafts only staged, nothing sent


async def test_regrading_writes_a_sidecar_and_replay_shows_it_while_the_recording_is_untouched(tmp_path, monkeypatch):
    from app.organism import regrade
    from app.organism.review import CheckResult, Review

    src = recordings.DIR / "disruption_SUP-0001.json"
    p = tmp_path / src.name
    p.write_text(src.read_text())
    before = p.read_bytes()

    seen = {}

    async def fake_review(kind, title, rec, verifier, drafts=None, only_critical=False):
        seen["drafts"] = drafts
        return Review(checks=[CheckResult(name="a", passed=True), CheckResult(name="b", passed=False, critique="gap")], summary="Half."), 0.001

    monkeypatch.setattr(regrade, "review", fake_review)
    assert await regrade.regrade_file(p) == (p.name, 50)
    assert p.read_bytes() == before  # the evidence is not rewritten
    doc = recordings.find("disruption:SUP-0001", tmp_path)
    assert doc["recommendation"]["grade"]["reviewer_score"] == 50 and doc["recommendation"]["grade"]["checks_total"] == 2
    assert doc["recommendation"]["grade"]["failed_checks"] == [{"name": "b", "reason": "gap"}] and seen["drafts"] and seen["drafts"][0]["to"]  # named failures, and the Reviewer read the draft
    ev = next(e for e in doc["events"] if e["type"] == "review.result")
    assert ev["summary"].startswith("Reviewer 50/100") and ev["payload"]["failed"] == ["b: gap"]


def test_the_morning_run_takes_the_top_of_the_action_list_in_its_own_order_and_leaves_out_what_code_answers(monkeypatch):
    from app.organism import prepare as pr

    keys = pr.morning_items(None, n=10)
    assert keys == ["disruption:SUP-0001", "tariff:HR-40110", "deadline:price-lock", "unknown:HR-40220"]  # the fake list's order, its trust item left out
    assert pr.morning_items(None, n=2) == keys[:2]
    monkeypatch.setenv("LOOKOUT_MORNING_N", "3")
    assert pr.morning_items(None) == keys[:3]
    monkeypatch.setenv("LOOKOUT_MORNING_ITEMS", "tariff:all, deadline:chase")
    assert pr.morning_items(None) == ["tariff:all", "deadline:chase"]  # named outright


def test_a_replay_goes_through_the_live_rules_one_open_thread_per_contact_and_nothing_chased_early(tmp_path, monkeypatch):
    """FEEDBACK 8.1: a fresh database with no key replayed the morning runs and staged three drafts to the same contact, one chasing dates not yet due."""
    from types import SimpleNamespace as NS

    from app.domain.actions import ledger
    from app.organism.recordings import admitted

    db = str(tmp_path / "t.db")
    from app import db as _db

    _db.init(db) if hasattr(_db, "init") else None
    a1 = ledger.propose(db, type="supplier_request", item_key="disruption:SUP-0001", run_id="r1", target=None, recipient="li@y.example", subject="Revised dates", body="Please confirm.")
    rec = lambda key: {"type": "supplier_request", "item_key": key, "recipient": "li@y.example", "subject": "s", "body": "b", "action_id": "A-x"}  # noqa: E731
    standing, why = admitted(db, {}, rec("deadline:SUP-0001:2026-10-13"), None)
    assert standing == a1.action_id and "one open thread" in why
    assert admitted(db, {}, rec("disruption:SUP-0001"), None) == (None, None)  # the same item again is a fresh draft, as before
    assert admitted(db, {}, rec("x"), NS(waits_until="2026-12-31"))[1].startswith("it chases dates not yet due")
    assert admitted(db, {}, {**rec("x"), "type": "note"}, None) == (None, None)


def test_after_a_run_the_item_page_gets_the_latest_run_and_its_answer_and_the_item_has_a_runs_list(tmp_path, monkeypatch):
    """FEEDBACK/Khalid: 'the result doesn't show' — GET /api/action-items/{key} returned latest_run and recommendation as null after every run."""
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "r.db")
    store.connect(app_db.DB_PATH).close()
    store.insert_run(app_db.DB_PATH, run_id="run-old", item_key="disruption:SUP-0001", workflow="work_item", status="running", started_at="2026-10-12T01:00:00+00:00")
    store.update_run(app_db.DB_PATH, "run-old", status="ok", cost_usd=0.1, wall_ms=1000)
    store.insert_run(app_db.DB_PATH, run_id="run-new", item_key="disruption:SUP-0001", workflow="work_item", status="running", started_at="2026-10-12T02:00:00+00:00")
    assert api._latest_for_item("disruption:SUP-0001")[0]["run_id"] == "run-old"  # a run still going is not the latest finished one
    store.update_run(app_db.DB_PATH, "run-new", status="ok", cost_usd=0.2, wall_ms=2000, recommendation_json=json.dumps(REC["recommendation"]), verifier_json=json.dumps(REC["verifier"]))
    latest, answer = api._latest_for_item("disruption:SUP-0001")
    assert latest["run_id"] == "run-new" and latest["status"] == "ok" and latest["verifier_passed"] is True and latest["cost_usd"] == "0.2000" and answer["finding"] == "f"
    assert api._latest_for_item("deadline:none") == (None, None)
    assert [r.run_id for r in api._runs_on("disruption:SUP-0001")] == ["run-new", "run-old"]


def test_the_item_endpoint_serves_what_the_agent_registered(monkeypatch):
    from app.domain.attention import api as attention_api
    from app.main import app

    monkeypatch.setattr(attention_api, "LATEST_RUN_PROVIDER", lambda key: ({"run_id": "run-x", "status": "ok"}, {"finding": "f", "numbers": []}))
    monkeypatch.setattr(attention_api, "RUNS_PROVIDER", lambda key: [{"run_id": "run-x"}])
    with TestClient(app) as c:
        item = c.get("/api/action-items/disruption:SUP-0001").json()
        assert item["latest_run"]["run_id"] == "run-x" and item["recommendation"]["finding"] == "f"
        assert c.get("/api/action-items/disruption:SUP-0001/runs").json() == [{"run_id": "run-x"}]
    assert attention_api.LATEST_RUN_PROVIDER is not None


async def test_a_replay_can_never_hang_or_leave_a_run_running(tmp_path, monkeypatch):
    """P0: the flagship item's morning replay stayed 'running' for 9+ minutes on a fresh no-key build. A step that cannot be played, or the time running out, ends the run at once with the saved answer."""
    import asyncio

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "g.db")
    db = app_db.DB_PATH
    store.connect(db).close()
    broken = {**REC, "events": [{**REC["events"][0], "type": "no.such.event"}, *REC["events"][1:]]}
    rec = Recorder("run-b", db)
    assert await recordings.replay_safely(broken, db_path=db, run_id="run-b", recorder=rec) is False
    row = store.read_run(db, "run-b")
    assert row["status"] == "did_not_pass" and "did not match today's rules" in row["recommendation_json"] and json.loads(row["recommendation_json"])["finding"] == "f"
    types = [e.type for _, e in store.read_tree_events(db, "run-b")]
    assert types[-2:] == ["run.failed", "run.finished"]

    async def forever(*a, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(recordings, "replay", forever)
    rec2 = Recorder("run-t", db)
    assert await recordings.replay_safely(REC, db_path=db, run_id="run-t", recorder=rec2, timeout=0.2) is False
    assert store.read_run(db, "run-t")["status"] == "did_not_pass"


async def test_a_run_a_stopped_server_left_running_is_closed_at_startup_and_the_morning_item_runs_again(tmp_path, monkeypatch):
    """Review: a server killed mid-run (a port clash) left a row 'running' that no process owned, forever."""
    from app.organism import prepare as pr

    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    db = tmp_path / "o.db"
    monkeypatch.setattr(app_db, "DB_PATH", db)
    store.connect(db).close()
    store.insert_run(db, run_id="run-orphan", item_key="disruption:SUP-0001", workflow="work_item", status="running", started_at="2026-10-12T11:43:28+00:00")
    store.update_run(db, "run-orphan", asked_by=pr.BY)
    store.insert_run(db, run_id="run-human", item_key="disruption:SUP-0013", workflow="work_item", status="running", started_at="2026-10-12T11:44:00+00:00")
    store.update_run(db, "run-human", asked_by="Priya Nair")
    monkeypatch.setattr(recordings, "find", lambda key: REC if key == "disruption:SUP-0001" else None)
    again = pr.recover_interrupted(db)
    assert again == ["disruption:SUP-0001"]  # the morning run's own item runs again; a person's run is not started behind their back
    a, b = store.read_run(db, "run-orphan"), store.read_run(db, "run-human")
    assert a["status"] == b["status"] == "did_not_pass" and "server stopped" in a["recommendation_json"] and b["recommendation_json"] is None
    assert [e.type for _, e in store.read_tree_events(db, "run-orphan")][-2:] == ["run.failed", "run.finished"]
    assert pr.recover_interrupted(db) == []  # nothing left running: a second start does nothing


def test_a_run_stopped_after_its_first_steps_is_closed_without_reusing_their_numbers(tmp_path, monkeypatch):
    """Review: a server stopped during the morning run's replay left a run with stored steps; the next start crashed on
    UNIQUE(run_id, seq) because the closing events restarted at 1, so `make run` failed until the database was rebuilt."""
    from app.organism import prepare as pr

    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    db = tmp_path / "o.db"
    monkeypatch.setattr(app_db, "DB_PATH", db)
    store.connect(db).close()
    store.insert_run(db, run_id="run-half", item_key="disruption:SUP-0001", workflow="work_item", status="running", started_at="2026-10-12T11:43:28+00:00")
    store.update_run(db, "run-half", asked_by=pr.BY)
    first = Recorder("run-half", db)
    for i in range(3):
        first.emit("step.text", f"step {i}")
    monkeypatch.setattr(recordings, "find", lambda key: None)
    assert pr.recover_interrupted(db) == ["disruption:SUP-0001"]
    events = [e for _, e in store.read_tree_events(db, "run-half")]
    assert [e.seq for e in events] == [1, 2, 3, 4, 5] and [e.type for e in events][-2:] == ["run.failed", "run.finished"]


def test_a_replayed_draft_carries_its_signer_as_the_live_draft_does(tmp_path):
    """FEEDBACK: a no-key replay staged the draft with no owner, so the UI could not show who signs it."""
    from types import SimpleNamespace as NS

    from app.organism.recordings import _named_owner

    db = str(tmp_path / "t.db")
    rec = {"type": "supplier_request", "item_key": "x:1", "change": None}
    seen = {}

    def one(db_path, action):
        seen["a"] = action
        return {"Sam"}

    import app.domain.actions.approvers as approvers

    orig = approvers.owners_of_action
    approvers.owners_of_action = one
    try:
        assert _named_owner(db, rec, None, "r1") == {"owner": "Sam"}
        assert seen["a"].item_key == "x:1" and seen["a"].run_id == "r1"
        assert _named_owner(db, {**rec, "change": {"owner": "Kim"}}, None, "r1") == {"owner": "Kim"}  # a recorded owner stands
        assert _named_owner(db, {**rec, "type": "note"}, None, "r1") is None
        approvers.owners_of_action = lambda d, a: {"Sam", "Kim"}  # two owners: no single signer to name
        assert _named_owner(db, rec, None, "r1") is None
    finally:
        approvers.owners_of_action = orig


def test_a_recording_is_used_only_on_the_day_it_was_made(tmp_path, monkeypatch):
    """FEEDBACK: on a copy built for an earlier day the morning run replayed answers recorded on a later one, and stated future facts as past."""
    from datetime import date

    base = {"item_key": "disruption:SUP-0001", "run_id": "r", "recorded_at": "2026-10-10T20:00:00+00:00"}
    (tmp_path / "disruption_SUP-0001.json").write_text(json.dumps({**base, "as_of": "2026-09-17"}))
    (tmp_path / "disruption_SUP-0002.json").write_text(json.dumps({**base, "item_key": "disruption:SUP-0002"}))  # no day: the recipe's day
    monkeypatch.setattr(recordings, "AS_OF", date(2026, 9, 17))
    assert recordings.find("disruption:SUP-0001", tmp_path) is not None
    assert recordings.find("disruption:SUP-0002", tmp_path) is None and recordings.find("disruption:SUP-0002", tmp_path, any_day=True) is not None
    monkeypatch.setattr(recordings, "AS_OF", recordings.recipe_as_of())
    assert recordings.find("disruption:SUP-0001", tmp_path) is None and recordings.find("disruption:SUP-0002", tmp_path) is not None


def test_a_recording_is_used_only_on_the_day_it_was_made(tmp_path, monkeypatch):
    """FEEDBACK: on a copy built for an earlier day the morning run replayed answers recorded on a later one, and stated future facts as past."""
    from datetime import date

    base = {"item_key": "disruption:SUP-0001", "run_id": "r", "recorded_at": "2026-10-10T20:00:00+00:00"}
    (tmp_path / "disruption_SUP-0001.json").write_text(json.dumps({**base, "as_of": "2026-09-17"}))
    (tmp_path / "disruption_SUP-0002.json").write_text(json.dumps({**base, "item_key": "disruption:SUP-0002"}))  # no day: the recipe's day
    monkeypatch.setattr(recordings, "AS_OF", date(2026, 9, 17))
    assert recordings.find("disruption:SUP-0001", tmp_path) is not None
    assert recordings.find("disruption:SUP-0002", tmp_path) is None and recordings.find("disruption:SUP-0002", tmp_path, any_day=True) is not None
    monkeypatch.setattr(recordings, "AS_OF", recordings.recipe_as_of())
    assert recordings.find("disruption:SUP-0001", tmp_path) is None and recordings.find("disruption:SUP-0002", tmp_path) is not None


async def test_a_replayed_amend_edits_the_earlier_cases_waiting_draft_and_stages_no_second_one(tmp_path):
    """The seed check (BUILD-13): cases replayed into one ledger lost a later case's ask to a contact already written to. A run that amended
    the earlier case's draft (its recorded action keeps that case's key) makes the same edit on replay."""
    from app.domain.actions import ledger

    db = tmp_path / "amend.db"
    store.connect(db).close()
    first = ledger.propose(str(db), type="supplier_request", item_key="deadline:chase", run_id="r1", target=None, recipient="h@gp.example", subject="Ship date", body="Dear H,\n\nA ship date please.\n\nBest regards,\nTom")
    amended = "Dear H,\n\nA ship date please.\n\nPlease also acknowledge the five open lines at today's price.\n\nBest regards,\nTom"
    doc = {"run_id": "run-old", "item_key": "deadline:SUP-0041:2026-10-15", "recorded_at": "2026-10-14T00:00:00+00:00",
           "run": {"model": "m", "prompt_hash": "p", "toolset_hash": "t", "sdk_version": "s"}, "events": [], "recommendation": None, "verifier": None,
           "actions": [{"action_id": "A-old", "type": "supplier_request", "item_key": "deadline:chase", "target": None, "recipient": "h@gp.example",
                        "subject": "Ship date", "body": amended, "change": None}]}
    await recordings.replay(doc, db_path=db, run_id="run-gp", recorder=Recorder("run-gp", db), speed=1000.0, max_gap_s=0)
    drafts = [a for a in ledger.list_actions(str(db)) if a.type == "supplier_request"]
    assert [d.action_id for d in drafts] == [first.action_id] and "acknowledge the five open lines" in drafts[0].body and ledger.in_run(str(db), first.action_id, "run-gp")
    assert ledger.asks_of(drafts[0]) == ["deadline:chase", "deadline:SUP-0041:2026-10-15"] and drafts[0].change["amended_for"] == ["deadline:SUP-0041:2026-10-15"]   # the amending case's ask is recorded, so its route finds this letter


def test_a_recorded_note_staged_for_signature_replays_proposed_and_a_logged_question_executed(tmp_path, monkeypatch):
    """LOOKOUT P1 (the demo's Ask 2): ask_bd377a51 recorded stage_decision's 'Note to planning' (kind note), but the replay turned every note into an
    executed log entry, so nothing reached Approvals. A staged note or decision replays PROPOSED; a logged question still replays executed."""
    import asyncio
    import copy

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "r.db")
    monkeypatch.setattr(recordings, "_PACE", 0)
    monkeypatch.setattr("app.domain.actions.approvers.owners_of", lambda db, key: None)
    monkeypatch.setattr("app.domain.actions.approvers.owners_of_action", lambda db, action: None)
    db = str(app_db.DB_PATH)
    seed_buyers(db)
    doc = copy.deepcopy(REC)
    doc["actions"] = [{"action_id": "A-rec00002", "type": "note", "item_key": "disruption:SUP-0001", "target": None, "recipient": None, "subject": "Note to planning",
                       "body": "Re-sequence the October builds", "change": {"kind": "note", "to": "planning", "owner": "Dana Reyes"}},
                      {"action_id": "A-rec00003", "type": "note", "item_key": "disruption:SUP-0001", "target": {"type": "item", "id": "disruption:SUP-0001", "label": None}, "recipient": None,
                       "subject": None, "body": "Question for Dana: stock on hand?", "change": {"owner": "Dana"}}]
    doc["recommendation"]["action_ids"] = ["A-rec00002", "A-rec00003"]
    asyncio.run(recordings.replay(doc, db_path=db, run_id="run-replay", recorder=Recorder("run-replay", db)))
    got = {a.subject or a.body[:8]: a for a in ledger.for_run(db, "run-replay")}
    assert got["Note to planning"].state == "proposed" and got["Note to planning"].change["kind"] == "note"
    assert got["Question"].state == "executed"
