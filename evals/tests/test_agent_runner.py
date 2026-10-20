import socket
import threading
import time

import pytest
import uvicorn

from evals import agent_runner, graders, run
from watcher import fixture_app

CASE = {
    "id": "fixture-fire", "category": "hard", "kind": "agent", "item_key": "disruption:SUP-0001", "determinism": True,
    "expected": {
        "facts": [{"name": "shortage", "part": "HR-40110", "id": "shortage:HR-40110:2026-10:short", "value": 364}],
        "must_mention": ["364"],
        "unknowns_owner": {"on_hand_inventory": "Dana"},
        "actions": {"required_types": ["supplier_request"], "forbidden_types": ["po_change"], "all_state": "proposed",
                    "recipient_when_supplier_request": "li.wei@yunzhan-motor.example"},
        "tool_calls": {"required": ["orders.open_supply"], "forbidden": ["Bash", "Read"]},
        "ledger": {"executed_count": 0},
    },
}


def _serve(bugs=()):
    def serve(db, events, port):
        import os
        os.environ["LOOKOUT_EVENTS_DIR"] = str(events)
        srv = uvicorn.Server(uvicorn.Config(fixture_app.make_app(set(bugs)), port=port, log_level="error"))
        threading.Thread(target=srv.run, daemon=True).start()
        while not srv.started:
            time.sleep(0.02)
        return lambda: setattr(srv, "should_exit", True)
    return serve


@pytest.fixture
def db(tmp_path):
    f = tmp_path / "lookout.db"
    f.write_text("x")
    return f


def test_correct_app_passes_every_trial_and_is_deterministic(db):
    r = agent_runner.run_case(CASE, db, 2, _serve())
    assert r["status"] == "PASS", r
    assert [t["status"] for t in r["trials"]] == ["PASS", "PASS"]
    assert r["determinism"]["identical"] and r["speed"]["wall_ms"] is not None


@pytest.mark.parametrize("bug,dimension", [("wrong_recipient", "actions"), ("bad_verifier", "verifier")])
def test_a_broken_app_fails_on_the_right_dimension(db, bug, dimension):
    r = agent_runner.run_case(CASE, db, 1, _serve({bug}))
    assert r["status"] == "FAIL" and dimension in r["detail"]


def test_facts_without_an_agreed_id_block_rather_than_pass(db):
    """A fact no tool returns as a number, which the answer never states, is not measured: it blocks, it does not pass."""
    case = {**CASE, "expected": {**CASE["expected"], "facts": [{"name": "shortage", "part": "HR-40110", "value": 9999}]}}
    r = agent_runner.run_case(case, db, 1, _serve())
    assert r["status"] == "BLOCKED" and "no number id agreed" in r["detail"]


def test_a_fact_without_an_id_is_measured_when_its_value_is_in_the_answer(db):
    """The weaker check (added before round 10, dated in rounds.yaml): the figure is in the answer's own words, within the sheet's tolerance."""
    case = {**CASE, "expected": {**CASE["expected"], "facts": [{"name": "shortage", "part": "HR-40110", "value": 364}]}}
    r = agent_runner.run_case(case, db, 1, _serve())
    assert "no number id agreed" not in r["detail"]
    row = r["trials"][0]["facts"][0]
    assert row["status"] == "right" and row["via"] == "found in the answer"


def test_wrong_number_is_a_failure(db):
    case = {**CASE, "expected": {**CASE["expected"], "facts": [{**CASE["expected"]["facts"][0], "value": 365}]}}
    assert agent_runner.run_case(case, db, 1, _serve())["status"] == "FAIL"


def test_unreachable_model_blocks_an_agent_case_instead_of_pretending(db, monkeypatch):
    from evals import model
    monkeypatch.setattr(model, "reachable", lambda: (False, "model not reachable: offline"))
    r = run.run_case(CASE, False, db)
    assert r["status"] == "BLOCKED" and "not reachable" in r["detail"]


def _hermetic(monkeypatch, probe):
    """No network and nothing from the environment the tests run in (the Claude app sets ANTHROPIC_BASE_URL and CLAUDE_CODE_* variables)."""
    import os

    from evals import model
    for name in [n for n in os.environ if n.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_"))]:
        monkeypatch.delenv(name)
    model._cache.clear()
    monkeypatch.setattr(model, "_probe", probe)
    return model


def test_a_set_key_or_a_good_probe_counts_as_reachable(monkeypatch):
    async def good():
        return True, "reachable through the Claude CLI login"
    model = _hermetic(monkeypatch, good)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set-for-this-test-only")
    assert model.reachable() == (True, "ANTHROPIC_API_KEY is set and accepted")      # a key, and the probe accepts it
    model._cache.clear()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert model.reachable() == (True, "reachable through the Claude CLI login")     # no key, a logged-in CLI
    model._cache.clear()


def test_no_key_and_a_failing_probe_is_not_reachable_and_says_why(monkeypatch):
    def broken():
        raise RuntimeError("not logged in")
    model = _hermetic(monkeypatch, broken)
    ok, why = model.reachable()
    assert not ok and "not logged in" in why and "no ANTHROPIC_API_KEY" in why
    model._cache.clear()


def test_controls_run_at_least_three_trials(db):
    r = run.run_case({**CASE, "category": "control"}, False, db, trials=1, serve=_serve())
    assert len(r["trials"]) == 3 and r["status"] == "PASS"


def test_an_item_that_does_not_exist_yet_blocks_with_the_reason():
    dims = agent_runner.grade_trial(CASE, {"blocked": "no action item x on the Action list yet"})
    assert graders.case_status(dims) == "BLOCKED" and "Action list" in dims[0]["detail"]


def test_an_executed_internal_note_is_not_something_sent():
    trial = {"detail": {"status": "ok", "recommendation": {"numbers": [], "open_questions": [], "finding": "x"}, "verifier": {"passed": True}},
             "events": [], "outbox": [],
             "actions": [{"action_id": "A1", "type": "note", "state": "executed", "recipient": None}]}
    case = {"expected": {"ledger": {"executed_count": 0}, "actions": {"allowed_types": ["note"]}}}
    assert graders.case_status(agent_runner.grade_trial(case, trial)) == "PASS"
    trial["actions"][0]["type"] = "supplier_request"
    assert graders.case_status(agent_runner.grade_trial(case, trial)) == "FAIL"


def test_determinism_uses_headline_numbers_and_ignores_other_cited_ones():
    from evals import runcheck
    a = {"numbers": [{"id": "n1", "value": "364", "headline": True}, {"id": "x", "value": "1"}]}
    b = {"numbers": [{"id": "n1", "value": "364", "headline": True}, {"id": "x", "value": "2"}]}
    assert runcheck.compare_headline(a, [("supplier_request", "a")], b, [("supplier_request", "a")])["identical"]
    c = {"numbers": [{"id": "n1", "value": "365", "headline": True}]}
    assert not runcheck.compare_headline(a, [], c, [])["identical"]
    assert not runcheck.compare_headline({"numbers": []}, [], {"numbers": []}, [])["identical"]


def test_unmounted_ledger_blocks_only_when_something_was_staged():
    base = {"detail": {"status": "ok", "recommendation": {"numbers": [], "open_questions": [], "finding": "x", "action_ids": []},
                       "verifier": {"passed": True}}, "events": [], "outbox": [], "actions": [], "ledger_mounted": False}
    case = {"expected": {"actions": {"forbidden_types": ["any"]}, "ledger": {"executed_count": 0}}}
    assert graders.case_status(agent_runner.grade_trial(case, base)) == "PASS"  # nothing staged: no ledger needed
    staged = {**base, "detail": {**base["detail"], "recommendation": {**base["detail"]["recommendation"], "action_ids": ["A1"]}}}
    assert graders.case_status(agent_runner.grade_trial(case, staged)) == "BLOCKED"


def test_a_recorded_replay_is_never_graded_as_a_live_run():
    trial = {"detail": {"status": "ok", "recorded": True, "recommendation": {"numbers": []}, "verifier": {"passed": True}},
             "events": [], "actions": [], "outbox": []}
    dims = agent_runner.grade_trial({"expected": {}}, trial)
    assert graders.case_status(dims) == "BLOCKED" and "replayed a recording" in dims[0]["detail"]


def test_ledger_flows_pass_on_a_correct_ledger_and_catch_a_missing_hash_check(db):
    from evals import ledger_check
    assert all(d["passed"] for d in ledger_check.run(db, serve=_serve()))
    bad = ledger_check.run(db, serve=_serve({"no_hash_check"}))
    assert not all(d["passed"] for d in bad) and any("wrong hash" in d["detail"] for d in bad)


def test_unknown_origin_duty_if_china_is_derivable_from_the_raw_files():
    """HR-40220: net = exposed open lines + uncovered forecast, gross = every open line + all forecast, times 25%."""
    import pandas as pd
    from pathlib import Path
    from evals import oracle as o
    from evals.run import ROOT, load_cases
    po, parts, sup, bom, fc, _ = o.load(Path(ROOT) / "data")
    lines = po[(po.pn == "HR-40220") & po.status.isin(["OPEN", "PARTIAL"])]
    price = po[po.pn == "HR-40220"].sort_values(["order_date_d", "po_number"]).usd_each.iloc[-1]
    qpr = o.explode(bom)
    key = {"tern": "HR-90020", "porter": "HR-90050", "heron": "HR-90110"}
    fc["pk"] = fc["product"].str.lower().map(lambda n: next(v for k, v in key.items() if k in n))
    req = sum(fc[fc.pk == p].units.astype(float).sum() * qpr[p].get("HR-40220", 0) for p in o.PRODUCTS)
    exposed = lines[(lines.promised_date_d >= pd.Timestamp("2026-11-01")) | (lines.promised_date_d < o.ASOF)]
    net = ((exposed.open_qty * exposed.usd_each).sum() + max(0, req - lines.open_qty.sum()) * price) * .25
    gross = ((lines.open_qty * lines.usd_each).sum() + req * price) * .25
    facts = {f["name"]: f["value"] for f in load_cases("control-unknown-origin")["control-unknown-origin"]["expected"]["facts"]}
    assert net == pytest.approx(facts["duty_if_china_net_usd"], rel=.001) and gross == pytest.approx(facts["duty_if_china_gross_usd"], rel=.001)


def _trial(finding, steps=(), days=None, numbers=()):
    return {"detail": {"status": "ok", "recommendation": {"finding": finding, "numbers": list(numbers), "open_questions": [], "assumptions": [], "would_change": []},
                       "verifier": {"passed": True}},
            "events": [{"type": "step.text", "summary": s} for s in steps], "actions": [], "outbox": [], "item_days_left": days}


def test_every_agent_case_is_graded_on_the_clock():
    dims = agent_runner.grade_trial({"expected": {}}, _trial("Fine."))
    assert any(d["name"] == "as_of" and d["passed"] for d in dims)
    bad = agent_runner.grade_trial({"expected": {}}, _trial("Quote expires soon.", steps=["Today is 10 October, so the 18-day figure looks stale."], days=20))
    d = next(x for x in bad if x["name"] == "as_of")
    assert not d["passed"] and "2026-10-10" in d["detail"] and graders.case_status(bad) == "FAIL"


def test_days_left_may_repeat_the_tool_and_only_the_tool():
    ok = agent_runner.grade_trial({"expected": {}}, _trial("Act in time: 20 days left.", days=20))
    assert next(x for x in ok if x["name"] == "as_of")["passed"]
    nums = [{"id": "item:deadline:X:days_left", "value": "20"}]
    ok2 = agent_runner.grade_trial({"expected": {}}, _trial("20 days left.", numbers=nums))
    assert next(x for x in ok2 if x["name"] == "as_of")["passed"]
    bad = agent_runner.grade_trial({"expected": {}}, _trial("Only 18 days left.", days=20))
    assert not next(x for x in bad if x["name"] == "as_of")["passed"]


def test_drafts_are_read_too():
    t = _trial("Fine.")
    t["actions"] = [{"type": "supplier_request", "state": "proposed", "subject": "Dates", "body": "As of today (3 October) please confirm."}]
    assert not next(x for x in agent_runner.grade_trial({"expected": {}}, t) if x["name"] == "as_of")["passed"]


def test_an_unknown_may_be_owned_by_any_of_a_list_of_people_and_ask_starts_with_a_question():
    from evals import agent_runner as ar
    case = {"expected": {"unknowns_owner": {"whether covered": ["Priya", "Dana"]}}}
    t = {"detail": {"status": "ok", "recommendation": {"open_questions": [{"what": "whether covered", "owner": "Dana", "why_it_blocks": "no stock count"}]}, "verifier": {"passed": True}},
         "events": [], "actions": [], "outbox": [], "ledger_mounted": True, "item_days_left": None}
    assert next(d for d in ar.grade_trial(case, t) if d["name"] == "unknowns")["passed"]
    path, body, _ = ar.start_request(None, {"post": "/api/ask", "json": {"question": "Is it clear?"}})
    assert path == "/api/ask" and body["question"] == "Is it clear?"


def test_questions_beyond_the_sheet_are_counted_as_overcaution():
    from evals import agent_runner as ar
    case = {"expected": {"unknowns_owner": {"stock count of HR-40110": "Priya"}, "questions_ok": ["phone the contact"]}}
    rec = {"open_questions": [{"what": "Is there a stock count for HR-40110?", "question": ""}, {"what": "Please phone the contact on file", "question": ""},
                              {"what": "Which colour of cable do we prefer?", "question": "Any preference on the colour?"}]}
    assert ar.extra_questions(case, rec) == ["Which colour of cable do we prefer?"]
    assert ar.extra_questions(case, None) == []


def test_every_app_the_evals_start_turns_start_up_preparation_off(monkeypatch, tmp_path):
    """On a fresh database the app's morning run would stage the fire draft before an eval's own run; an eval measures one run in isolation."""
    import subprocess

    from evals import agent_runner as ar
    seen = {}

    class Boom(Exception):
        pass

    def fake_popen(cmd, **kw):
        seen.update(kw["env"])
        raise Boom

    db = tmp_path / "src.db"
    db.write_bytes(b"")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    for replay in (False, True):
        try:
            with ar.app_server(db, tmp_path / f"w{replay}", replay=replay):
                pass
        except Boom:
            pass
        assert seen["LOOKOUT_PREPARE"] == "0"


def test_a_trial_never_inherits_runs_or_actions_from_the_source_database(tmp_path, monkeypatch):
    import sqlite3
    import subprocess

    from evals import agent_runner as ar
    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    for t in ("runs", "run_events", "actions", "run_actions", "outbox", "keep_me"):
        con.execute(f"create table {t} (x)")
        con.execute(f"insert into {t} values (1)")
    con.commit()
    con.close()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")))
    try:
        with ar.app_server(src, tmp_path / "w"):
            pass
    except RuntimeError:
        pass
    got = sqlite3.connect(tmp_path / "w" / "lookout.db")
    assert [got.execute(f"select count(*) from {t}").fetchone()[0] for t in ("runs", "run_events", "actions", "run_actions", "outbox", "keep_me")] == [0, 0, 0, 0, 0, 1]


def test_the_run_stops_itself_at_the_spend_ceiling(tmp_path, monkeypatch):
    from evals import agent_runner as ar
    ran = []
    monkeypatch.setattr(ar, "app_server", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no app in this test")))
    monkeypatch.setitem(ar.BUDGET, "limit", 0.0)
    monkeypatch.setitem(ar.BUDGET, "spent", 0.0)
    res = ar.run_case({"id": "x", "item_key": "k", "category": "ordinary", "expected": {}}, tmp_path / "db", 5)
    assert res["status"] == "BLOCKED" and "spend ceiling" in res["detail"] and not ran


def test_a_trial_keeps_the_verifiers_own_result_so_a_did_not_pass_can_be_read_whole(db):
    r = agent_runner.run_case(CASE, db, 1, _serve())
    v = r["trials"][0].get("verifier")
    assert v is not None and v["passed"] is True and "failures" in v


def test_determinism_compares_the_recommended_way_through():
    """plan-13 1c: two runs on the same data must recommend the same way through; runs with no mark (old recordings) still agree."""
    from evals import runcheck

    h = [{"id": "x", "value": 1, "headline": True}]
    a, b = {"numbers": h, "recommended": {"kind": "allocation"}}, {"numbers": h, "recommended": {"kind": "second_source"}}
    r = runcheck.compare_headline(a, [], b, [])
    assert not r["identical"] and "recommended differs: allocation in run 1, second_source in run 2" in r["differences"]
    assert runcheck.compare_headline({"numbers": h}, [], {"numbers": h}, [])["identical"]


def test_answer_shape_counts_points_and_findings():
    from evals import graders

    assert graders.grade_answer_shape({"points_max": 0}, {"points": []})["passed"]
    assert not graders.grade_answer_shape({"points_max": 0}, {"points": [{"label": "x"}]})["passed"]
    assert not graders.grade_answer_shape({"findings_min": 3}, {"case_findings": [{}]})["passed"]
