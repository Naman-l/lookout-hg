from app.organism.runs import store
from app.organism.runs.events import Recorder


def test_events_are_stored_in_order_and_deltas_are_not(db):
    rec = Recorder("run-1", db)
    q = rec.subscribe()
    rec.emit("run.started", "start")
    rec.emit("step.delta", "Hel")
    rec.emit("step.text", "Hello")
    rec.emit("run.finished", "done", status="ok")
    stored = store.read_events(db, "run-1")
    assert [e.type for e in stored] == ["run.started", "step.text", "run.finished"]
    assert [e.seq for e in stored] == [1, 2, 3]
    assert q.qsize() == 4  # the stream still got the delta
    ids = [i for i, _ in [q.get_nowait() for _ in range(4)]]
    assert ids[1] is None and ids[0] < ids[2] < ids[3]  # deltas carry no id; stored events do
    assert rec.first_step_ms is not None


def test_child_run_has_its_own_seq_and_parent(db):
    rec = Recorder("run-1", db)
    child = rec.child("run-1.1")
    rec.emit("run.started", "a")
    child.emit("run.started", "b", agent="supply_planner")
    ev = store.read_events(db, "run-1.1")[0]
    assert ev.parent_run_id == "run-1" and ev.seq == 1 and ev.agent_label == "Supply planner"


def test_run_row_roundtrip(db):
    store.insert_run(db, run_id="r", item_key="k", workflow="w", status="running", started_at="now")
    store.update_run(db, "r", status="ok", cost_usd=0.04)
    assert store.read_run(db, "r")["status"] == "ok"


def test_a_payload_key_that_clashes_with_the_watcher_signature_does_not_break_emit(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.watcher.EVENTS_DIR", tmp_path)
    rec = Recorder("run-1", db)
    rec.emit("tool.result", "ok", kind="x", source="y", summary_extra=1)
    assert store.read_events(db, "run-1")[0].payload["kind"] == "x"


def test_the_run_row_says_finished_before_the_stream_does(db, monkeypatch):
    """A page that reads the run the moment run.finished arrives must not see 'running'."""
    import asyncio

    from app.organism import runner
    from app.organism.context import RunContext
    from app.organism.runner import RunResult, allow_map

    store.insert_run(db, run_id="r", item_key="k", workflow="w", status="running", started_at="now")
    rec = Recorder("r", db)
    seen = []
    orig = rec.emit
    rec.emit = lambda type, *a, **k: (seen.append(store.read_run(db, "r")["status"]) if type == "run.finished" else None, orig(type, *a, **k))[1]
    ctx = RunContext(run_id="r", item_key="k", db_path=db, recorder=rec, plan=[], allow=allow_map([]))
    runner.finish(RunResult(run_id="r", status="ok", ctx=ctx, wall_ms=1))
    assert seen == ["ok"]


async def test_a_trust_item_is_answered_by_code_without_a_model(db, monkeypatch):
    """The sender failed the checks: the Recommendation is written from DOMAIN's fields, no model runs, nothing is drafted."""
    from app.domain.actions import ledger
    from app.organism.runs import store as runs_store
    from app.organism.workflows import work_item

    async def boom(*a, **k):
        raise AssertionError("a trust item must not start a model run")

    monkeypatch.setattr(work_item, "run_agent", boom)
    result = await work_item.run_workflow("trust:fraud-remittance", db_path=db)
    row = runs_store.read_run(db, result.run_id)
    assert result.status == "ok" and row["status"] == "ok" and row["cost_usd"] == 0.0 and row["model"].startswith("none")
    assert "Do not act on it" in row["recommendation_json"] and '"action_ids":[]' in row["recommendation_json"].replace(" ", "")
    assert ledger.list_actions(db) == [] and ledger.outbox(db) == []
    types = [e.type for e in result.ctx.recorder.events]
    assert types[0] == "run.started" and "verifier.result" in types and types[-1] == "run.finished"


def test_a_teammate_ended_at_its_handoff_still_gets_its_run_closed_once(ctx, db):
    """The SDK's stop hook does not fire when a teammate is ended at its handoff, so the run must be closed there; and only once."""
    from app.organism.lifecycle import finish_child
    from app.organism.schemas import Handoff

    child = ctx.recorder.child("run-t.1")
    runs_store = __import__("app.organism.runs.store", fromlist=["store"])
    runs_store.insert_run(db, run_id="run-t.1", parent_run_id="run-t", item_key="k", workflow="specialist:supply_planner", status="running", started_at="now")
    ctx.children["a1"], ctx.running = child, {"a1"}
    ctx.handoffs["supply_planner"] = Handoff(findings=["Short from October."])
    finish_child(ctx, "a1", "supply_planner")
    finish_child(ctx, "a1", "supply_planner")  # the stop hook may follow: nothing is repeated
    types = [e.type for e in ctx.recorder.events]
    assert types.count("child.finished") == 1 and not ctx.running
    assert [e.type for e in child.events] == ["run.finished"] and runs_store.read_run(db, "run-t.1")["status"] == "ok"


def test_every_allowed_tool_call_carries_a_reason_written_by_code(ctx):
    from app.organism.purposes import PURPOSE, why

    e = ctx.recorder.emit("tool.called", "Supply planner calls shortage_for_parts", agent="supply_planner", tool="shortage_for_parts", name="shortage_for_parts",
                          args={"part_numbers": ["HR-40110", "HR-40120", "HR-40130"]}, gate="allowed", gate_reason="part of this role's work")
    assert e.payload["why"] == "Work out, month by month, what the builds need against what is coming for 3 parts, and when each first runs short."
    d = ctx.recorder.emit("tool.called", "refused", agent="buyers_clerk", tool="read_message", name="read_message", args={}, gate="denied", gate_reason="not part of the clerk's work")
    assert "why" not in d.payload  # a refusal keeps its reason, not a purpose
    assert why("a_tool_nobody_wrote_a_reason_for", {}) == "Look something up in the records for this item."
    assert why("where_used_for_parts", {"part_numbers": ["HR-40110"]}).endswith("per build.") and "the part" in why("shortage_for_parts", {"part_numbers": ["HR-40110"]})
    assert all(not any(w in f({}) for w in ("handoff", "verifier", "tool call", "JSON")) or t == "get_handoffs" for t, f in PURPOSE.items())


def test_every_tool_a_specialist_can_call_has_a_reason():
    from app.organism.purposes import PURPOSE
    from app.organism.specialists.registry import TOOL_SERVER

    assert set(TOOL_SERVER) - set(PURPOSE) == set()


def test_a_specialists_steps_reach_the_watcher_tied_to_the_run_that_asked_it(ctx, monkeypatch):
    """watcher.correlate pulls a run's children in by parent_run_id: without it the specialists' own tool calls never appear in the story."""
    from app.organism.runs import events as events_module

    seen = []
    monkeypatch.setattr(events_module.watcher, "emit", lambda source, kind, summary, **f: seen.append((kind, f)))
    child = ctx.recorder.child("run-t.1")
    child.emit("tool.called", "Supply planner calls open_supply", agent="supply_planner", tool="open_supply", name="open_supply", args={}, gate="allowed")
    kind, fields = seen[-1]
    assert kind == "tool.called" and fields["run_id"] == "run-t.1" and fields["parent_run_id"] == "run-t" and isinstance(fields["t_ms"], int)


def test_remarks_a_nudged_lookout_made_before_its_last_read_are_tagged_superseded_and_none_removed(ctx):
    """The shape of the round-5 fire: nudged, asks the clerk again, talks, reads the handoffs once, talks again, reads them a last time."""
    from app.organism.runs.events import mark_superseded

    r = ctx.recorder
    r.emit("step.text", "I'm asking the supply side first.", agent="lookout")
    r.emit("child.started", "Map the lines", agent="supply_planner")
    r.emit("step.text", "Still waiting for Buyer's clerk to finish", agent="lookout", system=True)
    r.emit("step.text", "The supply check is done, so I'm asking for the request next.", agent="lookout")
    r.emit("child.started", "Draft the request", agent="buyers_clerk")
    r.emit("step.text", "That draft is still in progress.", agent="lookout")
    r.emit("tool.called", "Lookout calls get_handoffs", agent="lookout", tool="get_handoffs", gate="allowed")
    r.emit("step.text", "A first draft of the answer that is now out of date.", agent="lookout")
    r.emit("tool.called", "Lookout calls get_handoffs", agent="lookout", tool="get_handoffs", gate="allowed")
    events = r.events
    tagged = mark_superseded(events)
    assert [e.summary for e in tagged] == [e.summary for e in events]  # nothing removed or rewritten
    assert [e.summary for e in tagged if e.payload.get("superseded")] == ["That draft is still in progress.", "A first draft of the answer that is now out of date."]
    assert mark_superseded(events[:3]) == events[:3]  # no later ask, nothing tagged


def test_a_run_nobody_nudged_has_nothing_tagged(ctx):
    from app.organism.runs.events import mark_superseded

    for text in ("I'm asking the supply side.", "Done."):
        ctx.recorder.emit("step.text", text, agent="lookout")
    assert not any(e.payload.get("superseded") for e in mark_superseded(ctx.recorder.events))


def test_every_allowed_step_the_gate_logs_gives_its_purpose_as_the_reason_never_the_permission_boilerplate(ctx):
    import asyncio

    from app.organism.gate import make_gate

    gate = make_gate(ctx)
    inp = {"agent_type": "supply_planner", "tool_name": "mcp__orders__open_supply", "tool_input": {"part_number": "HR-40110"}, "tool_use_id": "t1", "agent_id": ""}
    asyncio.run(gate(inp, "t1", None))
    e = next(e for e in ctx.recorder.events if e.type == "tool.called")
    assert e.payload["gate"] == "allowed" and "role's work" not in e.payload["gate_reason"] and e.payload["gate_reason"] == e.payload["why"]


def test_a_replay_says_how_many_tokens_the_recorded_run_used():
    from app.organism.api import _operator_fields

    fin = {"type": "run.finished", "agent": "lookout", "agent_label": "Lookout", "payload": {"tokens_in": 0, "tokens_out": 0, "original_cost_usd": 0.1, "original_tokens_in": 198779, "original_tokens_out": 4785}}
    out = _operator_fields({"recorded": 1, "workflow": "work_item"}, [fin])
    assert (out["original_tokens_in"], out["original_tokens_out"]) == (198779, 4785)


def test_a_tool_that_errors_still_gets_a_result_event_once():
    """O4: get_item called with a supplier id was refused and the page showed a call with no answer."""
    import asyncio
    from types import SimpleNamespace as NS

    from app.organism.lifecycle import make_post_tool_failure

    got = []
    rec = NS(emit=lambda kind, summary, **kw: got.append((kind, summary, kw)))
    from collections import Counter
    ctx = NS(results_seen=set(), tool_counts=Counter(), calls=Counter())
    import app.organism.lifecycle as lc
    orig = lc.recorder_for
    lc.recorder_for = lambda c, i: rec
    try:
        hook = make_post_tool_failure(ctx)
        inp = {"tool_name": "mcp__attention__get_item", "tool_use_id": "t1", "tool_input": {"item_key": "SUP-0001"}, "error": '{"error": "no item SUP-0001: list_items shows the keys that exist"}'}
        asyncio.run(hook(inp, "t1", None)); asyncio.run(hook(inp, "t1", None))
        asyncio.run(hook({**inp, "tool_use_id": "t2", "tool_name": "Agent"}, "t2", None))
    finally:
        lc.recorder_for = orig
    assert len(got) == 1 and got[0][0] == "tool.result" and got[0][2]["ok"] is False and "no item SUP-0001" in got[0][1] and got[0][2]["tool_use_id"] == "t1"


def test_a_trust_answer_written_by_code_keeps_the_items_full_text_in_its_rows(ctx, db, services):
    """The injection scenario ended did_not_pass: the item's own finding is longer than a model's row may be; the control cases need its words (the open PO, the note aimed at AI)."""
    from types import SimpleNamespace as NS

    from app.organism.verifier import verify
    from app.organism.workflows.work_item import trust_recommendation

    long = "This message asks the buyer to ship against a spot offer. " + " ".join(["word"] * 60) + "."
    d = trust_recommendation(NS(key="trust:x", title="A spot offer", finding=long, next_action="Call the contact on file.", numbers=[], unknowns=[], owner="Dana Reyes"))
    assert d["points"][1]["text"] == long
    assert any(f.startswith("shape:") for f in verify(ctx, d, services=services)[1].failures)  # a model's row this long is refused
    ctx.coded = True
    assert not any(f.startswith("shape:") for f in verify(ctx, d, services=services)[1].failures)


def test_a_failed_call_does_not_use_up_the_cap_on_reads(ctx):
    """FEEDBACK W2: a follow-up passed names to the tools, every call failed, the cap was used up and the real read was refused."""
    import asyncio

    from app.organism.gate import decide
    from app.organism.lifecycle import make_post_tool, make_post_tool_failure

    ctx.tool_caps["open_supply"] = 2
    name = "mcp__orders__open_supply"
    for i in range(2):  # the gate counted two calls when they were allowed
        ctx.calls["supply_planner"] += 1
        ctx.tool_counts["open_supply"] += 1
    assert not decide(ctx, "supply_planner", name, {})[0]  # at the cap
    asyncio.run(make_post_tool_failure(ctx)({"tool_name": name, "tool_use_id": "t1", "tool_input": {"part_number": "Acme"}, "error": "no such part", "agent_type": "supply_planner"}, "t1", None))
    assert decide(ctx, "supply_planner", name, {})[0]  # the failed call is given back


def test_the_ask_prompt_carries_the_earlier_turns_ids_and_routes_a_message_like_triage():
    from app.domain.common import EntityRef
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("Which of those owe the new duty?", None, "Priya Nair", {"question": "q", "answer": "a", "about": ["supplier SUP-0001 (Acme)"], "ids": {"supplier": ["SUP-0001"], "part": ["HR-40110", "HR-40210"]}})
    assert "never a name" in p and "supplier SUP-0001" in p and "part HR-40110, HR-40210" in p
    m = build_prompt("Is this a real alternative?", EntityRef(type="message", id="m1", label="Quote"), "Priya Nair")
    assert "Tariff analyst" in m and "Sourcing analyst" in m and "read nothing is not an answer" in m


def test_the_models_schema_carries_the_shape_limits_but_the_class_stays_loose():
    from app.organism.schemas import RecommendationDraft, draft_schema

    s = draft_schema()
    assert s["properties"]["finding"]["maxLength"] == 150 and s["properties"]["points"]["maxItems"] == 4 and draft_schema(ask=True)["properties"]["points"]["maxItems"] == 3
    assert "maxLength" not in RecommendationDraft.model_json_schema()["properties"]["finding"]  # code-written answers keep their longer rows


def test_a_re_read_of_unchanged_handoffs_is_refused(ctx, services):
    import asyncio
    import json

    from app.organism import lookout_tools

    t = lookout_tools.make_tools(ctx)[0]
    first = json.loads(asyncio.run(t.handler({}))["content"][0]["text"])
    assert "error" not in first
    again = asyncio.run(t.handler({}))
    assert again.get("is_error") and "no new handoffs" in again["content"][0]["text"]
    ctx.handoffs["supply_planner"] = object.__new__(type("H", (), {}))  # a teammate handed off: there is something new to read


def test_the_fire_recording_runs_overview_analysis_draft_decision():
    """agent-spec-steps Rev 4 / F94: the stage of every event is derived at read time, so the shipped recordings get it with no re-record."""
    import json
    from pathlib import Path

    import app.organism as org
    from app.organism.runs import stages
    from app.organism.schemas import RunEvent

    raw = json.loads((Path(org.__file__).parent / "recordings" / "disruption_SUP-0001.json").read_text())["events"]
    events, summary = stages.attach([RunEvent.model_validate(e) for e in raw])
    assert [s.stage for s in summary] == ["overview", "analysis", "draft", "decision"]
    by = {s.stage: s for s in summary}
    assert by["analysis"].lookups == 4 and by["analysis"].figures_read == 75 and by["draft"].lookups == 5   # the 2026-10-14 13:27 re-record on a clean ledger
    assert by["decision"].lookups == 1 and by["overview"].started_ms <= by["analysis"].started_ms <= by["draft"].started_ms <= by["decision"].started_ms
    assert all(e.stage for e in events) and [e.seq for e in events] == [e["seq"] for e in raw]   # every event staged, the caller's order kept
    assert next(e for e in events if e.type == "action.staged").stage == "draft" and next(e for e in events if e.type == "verifier.result").stage == "decision"
