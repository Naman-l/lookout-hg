from evals import behaviour

LI = "li.wei@yunzhan-motor.example"


def _act(i, state="proposed", to=LI):
    return {"action_id": f"A-{i}", "type": "supplier_request", "recipient": to, "state": state}


def test_one_open_request_per_contact_is_read_from_the_ledger_and_a_failed_run_counts():
    spec = {"type": "supplier_request", "recipient": LI, "count": 1}
    ok = {"all_actions": [_act(1, "executed")], "runs": [{"detail": {"status": "ok"}}, {"approve": 200}, {"detail": {"status": "ok"}}]}
    assert behaviour.grade_sequence(spec, ok)["passed"]
    three = {"all_actions": [_act(1), _act(2), _act(3)], "runs": [{"detail": {"status": "ok"}}]}
    d = behaviour.grade_sequence(spec, three)
    assert not d["passed"] and "3 supplier_request" in d["detail"]
    cited = {"all_actions": [_act(1)], "runs": [{"detail": {"status": "did_not_pass", "verifier": {"failures": ["A-c2d96d49 is not in the ledger for this run"]}}}]}
    assert not behaviour.grade_sequence(spec, cited)["passed"]
    other = {"all_actions": [_act(1), _act(2, to="someone@else.example")], "runs": []}
    assert behaviour.grade_sequence(spec, other)["passed"]          # a request to another contact is not a second thread to this one
    assert behaviour.grade_sequence(spec, {"all_actions": [_act(1), _act(2, "rejected")], "runs": []})["passed"]   # a rejected draft is closed


def _turn(parts, follows=None, text="", denied=0):
    ev = [{"type": "run.started", "payload": {"follows": follows}, "refs": []}] if follows is not None else []
    ev += [{"type": "step.text", "refs": [{"type": "part", "id": p}], "payload": {}} for p in parts]
    ev += [{"type": "tool.called", "summary": "x", "payload": {"gate": "denied"}, "refs": []}] * denied
    return {"events": ev, "detail": {"recommendation": {"finding": text}}}


def test_a_followup_must_carry_the_first_turn_stay_inside_it_and_name_the_owed_parts():
    one = _turn(["HR-40110", "HR-40210", "HR-12210"], text="At risk: HR-40110, HR-40210 and HR-12210.")
    good = _turn(["HR-40110", "HR-40210"], follows=True, text="HR-40110 and HR-40210 owe the new duty.")
    owed = {"HR-40110", "HR-40210", "HR-50110"}
    assert behaviour.grade_followup({}, {"runs": [one, good]}, owed)["passed"]
    assert not behaviour.grade_followup({}, {"runs": [one, _turn(["HR-40110", "HR-40210"], follows=False)]}, owed)["passed"]               # did not carry turn 1
    stray = behaviour.grade_followup({}, {"runs": [one, _turn(["HR-40110", "HR-40210", "HR-50110"], follows=True)]}, owed)             # another buyer's battery packs
    assert not stray["passed"] and "HR-50110" in stray["detail"]
    missed = behaviour.grade_followup({}, {"runs": [one, _turn(["HR-40110"], follows=True)]}, owed)
    assert not missed["passed"] and "HR-40210" in missed["detail"]
    assert not behaviour.grade_followup({}, {"runs": [one, _turn(["HR-40110", "HR-40210"], follows=True, denied=1)]}, owed)["passed"]
    assert not behaviour.grade_followup({}, {"runs": [one]}, owed)["passed"]


def test_a_robots_figure_for_a_month_cannot_exceed_that_months_forecast_unless_it_says_it_is_carried():
    fc = {("Heron H1", 11): 24, ("Tern T2", 10): 182}
    assert behaviour.grade_robots("The Heron misses by 20 robots in November.", fc)["passed"]
    bad = behaviour.grade_robots("The Heron misses by up to 46 robots in November.", fc)
    assert not bad["passed"] and "46" in bad["detail"] and "24" in bad["detail"]
    assert behaviour.grade_robots("The Heron carries 46 robots of cumulative backlog into November.", fc)["passed"]
    assert behaviour.grade_robots("The Tern misses 150 robots in October. The Heron misses 10 robots in November.", fc)["passed"]
    assert not behaviour.grade_robots("", fc)["passed"]      # an empty answer says nothing and cannot pass by it
