"""The run API and its SSE stream, with the workflow replaced by a scripted one (no model)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db as app_db
from app.organism import api
from app.organism.runs import store


def sse(stream):
    out, cur = [], {}
    for line in stream.iter_lines():
        if not line:
            if cur:
                out.append(cur)
            cur = {}
        elif ":" in line:
            k, v = line.split(":", 1)
            cur[k] = v.strip()
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setenv("LOOKOUT_MODE", "live")
    api.LIVE.clear()

    async def scripted(item_key, *, db_path, run_id, recorder, asked_by=None, **_):
        store.insert_run(db_path, run_id=run_id, item_key=item_key, workflow="work_item", status="running", started_at="now", model="m", asked_by=asked_by)
        recorder.emit("run.started", "start")
        await asyncio.sleep(0.2)
        child = recorder.child(run_id + ".1")
        child.emit("step.text", "planner note", agent="supply_planner")
        recorder.emit("tool.called", "refused", gate="denied")
        recorder.emit("step.text", "lookout note")
        recorder.emit("run.finished", "done", status="ok")
        store.update_run(db_path, run_id, status="ok", wall_ms=200, denied_calls=1)

    monkeypatch.setattr(api, "run_workflow", scripted)
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    with TestClient(app) as c:  # a persistent portal, so the background run survives between requests
        yield c


def test_start_then_stream_ends_with_run_finished(client):
    r = client.post("/api/action-items/disruption:SUP-0001/runs", json={"asked_by": "Dana Reyes"})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        events = sse(s)
    types = [e["event"] for e in events]
    assert types[0] == "run.started" and types[-1] == "run.finished" and types.count("step.text") == 2
    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids)


def test_resume_with_last_event_id_skips_what_was_seen(client):
    run_id = client.post("/api/action-items/disruption:SUP-0001/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        events = sse(s)
    with client.stream("GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": events[1]["id"]}) as s:
        again = sse(s)
    assert [e["id"] for e in again] == [e["id"] for e in events[2:]]


def test_second_start_while_running_is_409_with_the_running_run(client):
    first = client.post("/api/action-items/disruption:SUP-0001/runs").json()
    second = client.post("/api/action-items/disruption:SUP-0001/runs")
    assert second.status_code == 409 and second.json()["run_id"] == first["run_id"]


def test_run_detail_has_stored_events_of_the_tree_and_the_denied_count(client):
    run_id = client.post("/api/action-items/disruption:SUP-0001/runs", json={"asked_by": "Dana Reyes"}).json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as s:
        sse(s)
    d = client.get(f"/api/runs/{run_id}").json()
    assert d["status"] == "ok" and d["asked_by"] == "Dana Reyes" and d["denied_calls"] == 1
    assert {e["run_id"] for e in d["events"]} == {run_id, run_id + ".1"}
    assert client.get("/api/runs").json()[0]["run_id"] == run_id


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404


def test_ask_returns_a_run_ref_and_streams_like_any_run(client, monkeypatch):
    async def scripted_ask(question, *, db_path, context, asked_by, run_id, recorder, **_):
        store.insert_run(db_path, run_id=run_id, item_key="ask:x", workflow="ask", status="running", started_at="now", model="m", asked_by=asked_by)
        recorder.emit("run.started", f"Asked: {question}", question=question)
        recorder.emit("run.finished", "done", status="ok")
        store.update_run(db_path, run_id, status="ok")

    monkeypatch.setattr(api, "run_ask", scripted_ask)
    r = client.post("/api/ask", json={"question": "What does the fire cost us?", "context": {"type": "item", "id": "disruption:SUP-0001"}, "asked_by": "Dana Reyes"})
    assert r.status_code == 202
    with client.stream("GET", f"/api/runs/{r.json()['run_id']}/events") as s:
        events = sse(s)
    assert [e["event"] for e in events] == ["run.started", "run.finished"]
    assert client.get(f"/api/runs/{r.json()['run_id']}").json()["asked_by"] == "Dana Reyes"
    assert client.post("/api/ask", json={"question": "  "}).status_code == 422


def test_ask_without_a_model_is_a_clear_503(client, monkeypatch):
    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    r = client.post("/api/ask", json={"question": "What is late?"})
    assert r.status_code == 503 and "not connected" in r.json()["detail"]


def test_the_data_steward_route_takes_a_csv_and_streams_like_any_run(client, monkeypatch, tmp_path):
    seen = {}

    async def scripted_import(name, *, db_path, incoming_dir, run_id, recorder, asked_by=None, **_):
        seen["text"] = (api.Path(incoming_dir) / name).read_text()
        store.insert_run(db_path, run_id=run_id, item_key=f"import:{name}", workflow="import", status="running", started_at="now", model="m")
        recorder.emit("run.started", f"Import {name}")
        recorder.emit("run.finished", "done", status="ok")
        store.update_run(db_path, run_id, status="ok")

    monkeypatch.setattr(api, "run_import", scripted_import)
    monkeypatch.setattr(api, "INCOMING", tmp_path / "incoming")
    r = client.post("/api/imports/steward-runs", json={"filename": "../../etc/orders.csv", "text": "a,b\n1,2\n"})
    assert r.status_code == 202
    with client.stream("GET", f"/api/runs/{r.json()['run_id']}/events") as s:
        assert [e["event"] for e in sse(s)] == ["run.started", "run.finished"]
    assert seen["text"] == "a,b\n1,2\n" and (tmp_path / "incoming" / "orders.csv").exists()  # the path part of the name is dropped
    assert client.post("/api/imports/steward-runs", json={"filename": "x.exe", "text": "x"}).status_code == 422
    assert client.post("/api/imports/steward-runs", json={"filename": "big.csv", "text": "x" * 2_000_001}).status_code == 422


def test_without_a_model_only_the_shipped_example_replays(client, monkeypatch):
    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    r = client.post("/api/imports/steward-runs", json={"filename": "something_else.csv", "text": "a\n1\n"})
    assert r.status_code == 503 and "not connected" in r.json()["detail"]


def test_an_item_can_be_worked_again_as_soon_as_its_run_has_a_final_status_even_while_the_grade_is_still_being_added(client, monkeypatch):
    """The Reviewer's grade runs inside the same task after delivery; it must not make 'Work this again' answer 409."""
    import asyncio

    release = asyncio.Event()

    async def scripted(item_key, *, db_path, run_id, recorder, asked_by=None, **_):
        store.insert_run(db_path, run_id=run_id, item_key=item_key, workflow="work_item", status="running", started_at="now", model="m")
        store.update_run(db_path, run_id, status="ok")
        recorder.emit("run.finished", "Run ok", status="ok")
        await release.wait()  # still grading

    monkeypatch.setattr(api, "run_workflow", scripted)
    monkeypatch.setattr(api.recordings, "live_available", lambda: True)
    first = client.post("/api/action-items/disruption:SUP-0001/runs")
    assert first.status_code == 202
    again = client.post("/api/action-items/disruption:SUP-0001/runs")
    assert again.status_code == 202 and again.json()["run_id"] != first.json()["run_id"]


def test_the_run_list_carries_what_an_operator_reads_in_one_row(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.organism import recordings

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "ops.db")  # never the main database
    monkeypatch.setenv("LOOKOUT_PREPARE", "0")
    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    api.LIVE.clear()

    with TestClient(app) as c:
        key = next(iter(recordings.available_keys())) if hasattr(recordings, "available_keys") else "disruption:SUP-0001"
        r = c.post(f"/api/action-items/{key}/runs").json()
        c.get(f"/api/runs/{r['run_id']}/events")
        row = next(x for x in c.get("/api/runs").json() if x["run_id"] == r["run_id"])
    assert row["workflow"] and row["verifier_passed"] is not None and row["checks_total"] and row["specialists"]


def test_a_replay_says_what_the_recorded_run_cost_and_an_ask_run_carries_its_question():
    from app.organism.api import _operator_fields

    events = [{"type": "run.started", "agent": "lookout", "agent_label": "Lookout", "payload": {"question": "Where is HR-40110?"}},
              {"type": "run.finished", "agent": "lookout", "agent_label": "Lookout", "payload": {"cost_usd": 0, "original_cost_usd": 0.0402}}]
    out = _operator_fields({"recorded": 1, "workflow": "ask"}, events)
    assert out["original_cost_usd"] == "0.0402" and out["title"] == "Where is HR-40110?"
    assert "original_cost_usd" not in _operator_fields({"recorded": 0, "workflow": "work_item"}, events[1:])  # a live run's cost is its own


def test_a_follow_up_carries_the_earlier_question_its_answer_and_what_it_was_about(tmp_path, monkeypatch):
    """O10 (run-9116a7f8): the follow-up started with context null and 'those' meant nothing."""
    import json

    from app import db as app_db
    from app.organism import api as organism_api
    from app.organism.runs import store
    from app.organism.runs.events import Recorder
    from app.organism.schemas import EntityRef
    from app.organism.workflows.ask import build_prompt

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "t.db")
    db = str(app_db.DB_PATH)
    store.insert_run(db, run_id="run-first", item_key="ask:1", workflow="ask", status="ok", started_at="now", recommendation_json=json.dumps({"finding": "Three parts are short: the Tern motor, its gearmotor and the brake."}))
    rec = Recorder("run-first", db)
    rec.emit("run.started", "Asked: which parts are short?", question="Which parts are short?", context=None)
    rec.emit("tool.result", "Shortage for 3 parts", refs=[EntityRef(type="part", id="HR-40110", label="Tern motor"), EntityRef(type="part", id="HR-40120")], tool="shortage_for_parts", numbers=[], unknowns=[])
    thread = organism_api._thread("run-first")
    assert thread["question"] == "Which parts are short?" and "Tern motor" in thread["answer"] and thread["about"] == ["part HR-40110 (Tern motor)", "part HR-40120"]
    prompt = build_prompt("What do those cost?", None, "Dana Reyes", thread)
    assert "Earlier question: Which parts are short?" in prompt and "Your earlier answer: Three parts are short" in prompt and "It was about: part HR-40110 (Tern motor); part HR-40120." in prompt and "mean what that answer was about" in prompt
    assert "earlier turn" not in build_prompt("What do those cost?", None, "Dana Reyes")  # no thread: nothing added
    assert organism_api._thread("run-nope") is None and organism_api._thread(None) is None


def test_a_run_detail_carries_the_entities_of_its_answer_and_its_points(tmp_path, monkeypatch):
    """The screen must not post text to /api/annotate on every render: the server attaches the spans."""
    from app.organism import entities
    from app.organism.schemas import Point, Recommendation

    rec = Recommendation(finding="Order from Shenzhen Yunzhan before 13 Oct.", numbers=[], assumptions=["Stock is unknown."], points=[Point(label="Short", text="Part HR-40110 is short.")])
    calls = []
    import app.domain.annotate.service as svc

    monkeypatch.setattr(svc, "annotate", lambda session, text, **kw: calls.append(text) or [type("S", (), {"model_dump": lambda self: {"start": 0, "end": 1, "type": "part", "ref": "HR-40110", "label": "x", "text": text[:1]}})()])
    out = entities.attach(rec, object())
    assert out.answer_entities and out.points[0].entities and len(out.recommendation_entities) == 1
    assert calls == ["Order from Shenzhen Yunzhan before 13 Oct.", "Stock is unknown.", "Part HR-40110 is short."]
    assert entities.attach(rec, None) is rec  # no session (fakes): nothing attached, nothing breaks


def test_a_follow_up_carries_the_last_three_turns_of_the_conversation(tmp_path, monkeypatch):
    """F100 / Rev 4.2: a multi-turn decision analysis keeps what was asked and answered before, not only the turn before."""
    import json

    from app import db as app_db
    from app.organism import api as organism_api
    from app.organism.runs import store
    from app.organism.runs.events import Recorder
    from app.organism.workflows.ask import build_prompt

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "t.db")
    db = str(app_db.DB_PATH)
    for i, (q, a, prev) in enumerate([("Which parts are short?", "Five drive parts are short.", None), ("Which of those owe duty?", "Two owe the new duty.", "run-1"),
                                       ("Who supplies them?", "Yunzhan supplies both.", "run-2"), ("Can we fly them?", "x", "run-3")], 1):
        store.insert_run(db, run_id=f"run-{i}", item_key=f"ask:{i}", workflow="ask", status="ok", started_at=f"2026-10-14T0{i}:00", recommendation_json=json.dumps({"finding": a}))
        Recorder(f"run-{i}", db).emit("run.started", f"Asked: {q}", question=q, context={"type": "item", "id": "disruption:SUP-0001"} if i == 2 else None, thread_id=prev)
    t = organism_api._thread("run-4")
    assert t["question"] == "Can we fly them?" and [e["question"] for e in t["earlier"]] == ["Who supplies them?", "Which of those owe duty?"]   # 3 turns in all, newest first
    p = build_prompt("And by air?", None, "Dana Reyes", t)
    assert "Before that, they asked: Who supplies them? · your answer: Yunzhan supplies both." in p and "on item disruption:SUP-0001" in p
    assert organism_api._thread("run-1")["earlier"] == []


def test_a_new_subject_in_the_same_session_does_not_inherit_the_earlier_one():
    """BUYER Q6: 'How much of my duty share can I still avoid?' after a Hallerbeck question was answered about Hallerbeck. The thread is background;
    the earlier ids and subject carry over only when the question points back ('those', 'it', 'the same')."""
    from app.organism.workflows.ask import build_prompt, refers_back

    thread = {"question": "If Hallerbeck stops today, how many Porters can we still build?", "answer": "Up to 169 Porters on order.", "about": ["supplier SUP-0002 (Hallerbeck)"],
              "ids": {"supplier": ["SUP-0002"], "part": ["HR-12210"]}, "earlier": []}
    p = build_prompt("How much of my duty share can I still avoid?", None, "Dana Reyes", thread)
    assert "background only" in p and "does not point back" in p and "SUP-0002" not in p and "HR-12210" not in p and "mean what that answer was about" not in p
    follow = build_prompt("And what do those cost?", None, "Dana Reyes", thread)
    assert "HR-12210" in follow and "mean what that answer was about" in follow
    assert refers_back("Can those ship sooner?") and refers_back("What about the brake?") and not refers_back("Which of my late lines stops a build first?")
    assert not refers_back("Is it cheaper after duty?") and not refers_back("Also, how much of my duty share can I avoid?")  # loose words carry nothing over
    assert "never 'cannot be given'" in p and "Speak to the buyer as 'you' (they are Dana Reyes)" in p


def test_an_ask_on_a_case_starts_from_the_cases_code_packet_and_its_current_answer(tmp_path, monkeypatch):
    """BUYER Q1/Q2/Q10/Q11: an Ask on the fire missed the Siam alternate on file, Jadepeak's order-by date and the reason behind the recommendation,
    all of which code already had. The Ask now gets the case's packet (its figures registered as evidence) and the case's current answer."""
    import json
    from decimal import Decimal
    from types import SimpleNamespace as NS

    from app.organism import context_packet
    from app.organism.runs import store
    from app.organism.schemas import Number
    from app.organism.workflows import ask

    db = str(tmp_path / "t.db")
    store.insert_run(db, run_id="run-case", item_key="disruption:A", workflow="work_item", status="ok", started_at="2026-10-14T01:00:00",
                     recommendation_json=json.dumps({"finding": "Motors short in October.", "recommended": {"kind": "allocation", "reason": "covers all 10 lines"}}))
    pk = context_packet.Packet(text="What the records show:\n- [alt_on_file] Siam Motion has supplied HR-40120 before.", numbers=[Number(id="option:disruption:A:x:cost_delta", name="x", value=Decimal(5), unit="USD")])
    monkeypatch.setattr(context_packet, "build", lambda item, services, db_path=None: pk)
    svc = NS(attention=NS(get_item=lambda k: NS(key=k)))
    text, packet, _ = ask.case_brief("disruption:A", svc, db)
    assert "Siam Motion has supplied HR-40120" in text and "Recommended way through: allocation (covers all 10 lines)" in text and packet is pk
    assert ask.case_brief(None, svc, db) == ("", None, "")
    assert ask._case_answer("nope:x", db) == ""


def test_the_case_brief_names_the_cases_source_messages_to_read(tmp_path, monkeypatch):
    """BUYER Q10 (run-f25debb5): 'What if I order by Oct 1?' said no lead time was on file; the slip notice states the cut-off. The brief names the
    case's source messages so the run reads their exact terms."""
    from types import SimpleNamespace as NS

    from app.domain.common import EntityRef
    from app.organism import context_packet
    from app.organism.workflows import ask

    monkeypatch.setattr(context_packet, "build", lambda item, services, db_path=None: context_packet.Packet(text="x"))
    item = NS(key="disruption:B", refs=[EntityRef(type="message", id="2026-09-18_notice"), EntityRef(type="supplier", id="S")])
    text, _, _ = ask.case_brief("disruption:B", NS(attention=NS(get_item=lambda k: item)), str(tmp_path / "t.db"))
    assert "read them with read_message" in text and "2026-09-18_notice" in text
    slip = NS(key="disruption:C", refs=[], messages=[NS(ref=EntityRef(type="message", id="2026-09-18_cut_off_notice"))])  # the slip case: its notice is in messages
    assert "2026-09-18_cut_off_notice" in ask.case_brief("disruption:C", NS(attention=NS(get_item=lambda k: slip)), str(tmp_path / "t.db"))[0]


def test_a_figure_only_in_the_cases_earlier_answer_is_never_counted_as_checked(tmp_path, monkeypatch, ctx):
    """AGENT-EXPERT M2: the Ask preload registered the WHOLE brief as seen, including the earlier run's answer (a model's text), so a stale figure
    became 'checked' in the new answer and its email. Only code's words count; a numeral or date only in the old answer stays stray."""
    import json

    from app.organism import context_packet
    from app.organism.runs import store
    from app.organism.verifier import stray_in_text
    from app.organism.workflows import ask
    from types import SimpleNamespace as NS

    db = str(tmp_path / "t.db")
    store.insert_run(db, run_id="run-old", item_key="disruption:A", workflow="work_item", status="ok", started_at="2026-10-14T01:00:00",
                     recommendation_json=json.dumps({"finding": "Ship 777 by 23 October.", "recommended": {"kind": "allocation", "reason": "covers 919 units"}}))
    store.insert_run(db, run_id="run-bad", item_key="disruption:A", workflow="work_item", status="did_not_pass", started_at="2026-10-14T02:00:00",
                     recommendation_json=json.dumps({"finding": "A failed answer."}))
    monkeypatch.setattr(context_packet, "build", lambda item, services, db_path=None: context_packet.Packet(text="Restart estimated Nov 3, 12 lines."))
    text, packet, quotable = ask.case_brief("disruption:A", NS(attention=NS(get_item=lambda k: NS(key=k, refs=[]))), db)
    assert "777" in text and "A failed answer" not in text  # the answer is shown to the run (from an ok run only) ...
    ask.ask_preload("Why?", packet, quotable)(ctx)
    nums, days = stray_in_text(ctx, "Please ship 777 by 23 October; 12 lines restart Nov 3.")
    assert "777" in nums and "23 October" in days  # ... but nothing in it counts as checked
    assert "12" not in nums and not any("Nov" in d or "November" in d for d in days)  # code's own words do


def test_the_ask_prompt_carries_the_buyer_round_2_rules():
    """BUYER round 2: units (parts vs robots, cumulative months), 'first' only from code's order, no-quote parts with an RFQ offer, 'With <name>'."""
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("Which of my late lines stops a build first?", None, "Dana Reyes")
    for rule in ("parts (EA, per part) are never robots", "a total across months only if a tool returns that total, never one you add up", "'first' only when code orders it", "shortfall is not computed without stock data",
                 "offer to prepare an RFQ note", "'With <first name>'"):
        assert rule in p, rule


def test_the_ask_prompt_carries_the_round_2_follow_ups():
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("What if I order by Oct 1?", None, "Dana Reyes")
    assert "offer a planned order for the next need" in p and "quantity to set" in p and "never as 'zero can be built'" in p


def test_the_ask_prompt_never_invites_the_model_to_add_months():
    """AGENT-EXPERT minor on bb138b8: 'cumulative Oct + Nov, 182 + 188' invited a model-made sum (only a warning in the verifier)."""
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("How many Terns?", None, "Dana Reyes")
    assert "182 + 188" not in p and "cumulative Oct" not in p and "never one you add up" in p


def test_the_ask_prompt_carries_the_round_3_rules():
    """BUYER round 3: Q8 'not short on open orders'; Q5 the card's invoiced price and code's change, never 'to be confirmed'; Q2 four parts can be compared."""
    import inspect

    from app.organism.workflows import ask

    p = ask.build_prompt("x", None, "Dana Reyes")
    assert "'not short on open orders'" in p and "vs_last_paid_pct" in p and "never 'to be confirmed'" in p and "order_<qty>_prepayment_usd" in p
    assert '"compare_offers": 5' in inspect.getsource(ask.run_ask)


def test_an_asks_open_questions_about_its_own_parts_come_first_and_none_is_dropped():
    """BUYER Q3 / SIDEQ ruling: the wall of other owners' shelf questions is a display matter. The verifier still carries every tool question;
    the answer's own parts come first and the rest fold as '+N other open questions'."""
    import re
    from types import SimpleNamespace as NS

    from app.organism.api import order_open_questions

    rx = re.compile(r"\bP-\d{3}\b")
    qs = [NS(what="stock of P-900", question="How many P-900?"), NS(what="stock of P-101", question="How many P-101 on the shelf?"), NS(what="who", question="Who owns it?")]
    out, first = order_open_questions(qs, "Short by up to 182 on P-101.", rx)
    assert [q.what for q in out] == ["stock of P-101", "stock of P-900", "who"] and first == 1 and len(out) == 3
    assert order_open_questions(qs, "No part named.", rx) == (qs, 3)


def test_the_ask_prompt_routes_a_note_for_a_team_to_staging_not_to_a_logged_question():
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("Prepare a note to planning", None, "Dana Reyes")
    assert "stage_decision with `to` set" in p and "log_buyer_question is refused in Ask" in p
