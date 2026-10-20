from evals import runcheck


def _run(num_value=364, extra_call=False, recipient="li.wei@yunzhan-motor.example"):
    ev = [
        {"type": "tool.called", "payload": {"name": "orders.open_supply", "args": {"part": "HR-40110"}}},
        {"type": "tool.result", "payload": {"numbers": [{"id": "shortage:HR-40110:2026-10:short", "value": num_value}]}},
        {"type": "action.staged", "payload": {"type": "supplier_request", "recipient": recipient}},
        {"type": "step.text", "summary": "prose differs every time " + str(num_value)},
    ]
    if extra_call:
        ev.append({"type": "tool.called", "payload": {"name": "bom.where_used", "args": {}}})
    return ev


def test_identical_runs_ignore_prose():
    a, b = _run(), _run()
    b[3]["summary"] = "different words"
    assert runcheck.compare(a, b)["identical"]


def test_a_moved_number_a_new_call_and_a_new_recipient_are_each_named():
    r = runcheck.compare(_run(), _run(num_value=365, extra_call=True, recipient="x@y.example"))
    assert not r["identical"] and len(r["differences"]) == 3


def test_speed_missing_measurement_is_a_miss():
    assert runcheck.speed_verdict({"first_step_ms": None, "wall_ms": None})


def test_speed_targets():
    ok = {"first_step_ms": 1350, "wall_ms": 16800}
    assert runcheck.speed_verdict(ok) == []
    assert runcheck.speed_verdict({"first_step_ms": 2500, "wall_ms": 40000}) != []


def test_speed_reads_the_parent_run_finish_not_a_childs():
    ev = [{"type": "run.finished", "parent_run_id": "r1", "payload": {"wall_ms": 5}},
          {"type": "run.finished", "payload": {"first_step_ms": 900, "wall_ms": 7000, "status": "ok"}}]
    assert runcheck.speed(ev)["wall_ms"] == 7000


def test_page_latency_percentiles():
    out = runcheck.page_latency(lambda p: None, ["/api/items"], n=20)
    assert set(out["/api/items"]) == {"p50", "p95"}


def test_report_shows_every_trial_failures_and_rounds(tmp_path):
    from evals import report
    cases = {"control-fraud": {"category": "control"}, "disruption-fm": {"category": "hard"}}
    results = {
        "control-fraud": {"status": "PASS", "trials": [{"status": "PASS"}] * 3},
        "disruption-fm": {"status": "FAIL", "trials": [{"status": "PASS"}, {"status": "FAIL", "detail": "unknowns: on_hand_inventory missing"}],
                          "speed": {"first_step_ms": 1400, "wall_ms": 17000, "cost_usd": 0.05}},
    }
    rp = tmp_path / "rounds.yaml"
    rp.write_text("- {round: 1, passed: '1/2', changed: 'baseline'}\n")
    cfg = {"date": "2026-10-12", "model": "m", "prompt_hash": "p", "data_hash": "d", "sdk": "s", "git_sha": "g"}
    text = report.render(cfg, results, cases, "2 trials", {"disruption-fm": "tell the planner to list on-hand as unknown"}, rp)
    assert "CONTROL  3/3" not in text  # three trials of one control are not three controls
    assert "control-fraud" in text and "3 trials" in text and "guardrail held" in text
    assert "PASS FAIL(unknowns: on_hand_inventory missing)" in text
    assert "HARD     0/1" in text and "To change: tell the planner" in text and "| 1 | 1/2 | baseline |" in text
    assert "cost 0.05 USD" in text


def test_blocked_cases_are_not_counted_as_run():
    from evals import report
    line = report.category_line("ordinary", [("a", {"status": "BLOCKED", "detail": "no build"})])
    assert "0/0 (1 not run)" in line


def test_long_details_are_summarised_for_the_readme_not_listed():
    from evals import report
    keys = "; ".join(f"msg{i}.trust: not measured" for i in range(85))
    assert report.short(keys) == "85 checks not measured yet"
    mixed = "run: status failed; actions: missing supplier_request; unknowns: missing owner; facts: x; " + keys
    out = report.short(mixed)
    assert out.startswith("run: status failed; actions: missing supplier_request; +2 more") and out.endswith("85 checks not measured yet")
    assert len(report.short("x" * 500)) <= 111
