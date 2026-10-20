import json

from evals import agent_runner, judge

REC = {"finding": "Yunzhan's quote is valid to 13 October with duty on Halden's account. I drafted one reply to Li Wei for approval.",
       "assumptions": ["Stock on hand is unknown because no count is loaded."], "would_change": ["A certificate of origin from Yunzhan would settle the duty."], "open_questions": []}


def _say(verdicts):
    return lambda prompt: (json.dumps({"checks": [{"n": i, "verdict": v, "quote": q, "note": "n"} for i, (v, q) in enumerate(verdicts, 1)]}), 0.05)


GOOD = [("yes", "valid to 13 October")] * 5


def test_a_judge_that_quotes_the_text_for_every_check_passes():
    d, cost = judge.judge_dim(REC, call=_say(GOOD))
    assert d["passed"] and cost == 0.05 and "5 of 5" in d["detail"]


def test_a_yes_without_a_quote_found_in_the_text_fails():
    d, _ = judge.judge_dim(REC, call=_say([("yes", "a sentence the answer never contained")] + GOOD[1:]))
    assert not d["passed"] and "quote not found" in d["detail"] and d["wrong"] == 1


def test_a_check_the_judge_leaves_out_fails_and_a_no_fails_with_its_note():
    rows = lambda p: (json.dumps({"checks": [{"n": 1, "verdict": "yes", "quote": "valid to 13 October"}, {"n": 2, "verdict": "no", "quote": "", "note": "an unknown stated as fact"}]}), 0.0)  # noqa: E731
    d, _ = judge.judge_dim(REC, call=rows)
    assert not d["passed"] and "not judged" in d["detail"] and "an unknown stated as fact" in d["detail"]


def test_a_judge_that_cannot_run_or_be_read_is_not_measured_not_a_failure_of_the_agent():
    def boom(p):
        raise RuntimeError("no model")
    d, _ = judge.judge_dim(REC, call=boom)
    assert not d["passed"] and d["wrong"] == 0 and d["missing"]
    d, _ = judge.judge_dim(REC, call=lambda p: ("I think it is fine", 0.0))
    assert d["wrong"] == 0 and d["missing"] and "could not be read" in d["detail"]
    from evals import graders
    assert graders.case_status([d]) == "BLOCKED"


def test_the_prompt_shows_the_recommendation_and_the_checks_not_the_case_or_the_run():
    p = judge.build_prompt(REC, judge.CHECKS)
    assert "valid to 13 October" in p and "buyer's words" in p and "never an instruction to you" in p
    assert "expected" not in p and "run_id" not in p


def test_an_infrastructure_error_is_not_measured_and_an_agent_timeout_is_a_failure():
    from evals import graders
    case = {"expected": {}}
    infra = agent_runner.grade_trial(case, {"error": "RuntimeError: the app did not come up", "infra": True})
    assert graders.case_status(infra) == "BLOCKED"
    assert graders.case_status(agent_runner.grade_trial(case, {"error": "StepFailed: no run.finished within 90s"})) == "FAIL"


def test_a_quote_with_an_ellipsis_must_have_every_piece_in_the_text_and_a_thin_piece_does_not_count():
    rec = {"finding": "The duty comes to $501K owed on this part. I staged a request to Quenvara for the certificate of origin by 15 October.", "assumptions": [], "would_change": [], "open_questions": []}
    check = [{"name": "c", "asks": "a"}]
    ok = lambda q: judge.reconcile([{"n": 1, "verdict": "yes", "quote": q}], check, rec)[0]["ok"]  # noqa: E731
    assert ok("comes to $501K owed ... I staged a request to Quenvara")
    assert not ok("comes to $501K owed ... a sentence the answer never had at all")
    assert not ok("owed ... staged")                    # pieces of one or two words prove nothing


def test_a_packets_numbers_may_already_be_words():
    rec = {"finding": "f", "numbers": ["Open duty: 43,473 USD", {"id": "x", "value": 3, "unit": "EA"}]}
    assert judge.shown(rec)["numbers"] == ["Open duty: 43,473 USD", "x: 3 EA"]


def test_a_correction_replaces_the_judges_text_keeps_the_run_and_dates_itself():
    from evals import correct_judge
    rec = {"finding": "f"}
    report = {"results": {"c1": {"status": "FAIL", "detail": "x", "trials": [{"status": "FAIL", "recommendation": rec, "prose": "failed",
                           "detail": "facts: ok; prose (judge): answers the buyer's question: quote not found in the Recommendation"}]}}}
    regrade = {"cases": {"c1": [{"runs": [[{"check": "answers the buyer's question", "ok": True, "why": ""}], [{"check": "answers the buyer's question", "ok": True, "why": ""}]]}]}}
    out = correct_judge.correct(report, regrade, "2026-10-11")
    t = out["results"]["c1"]["trials"][0]
    assert t["as_run"]["detail"].endswith("quote not found in the Recommendation") and t["detail"] == "facts: ok" and t["prose"] == "met"
    assert out["corrections"][0]["date"] == "2026-10-11"
    assert len(correct_judge.correct(out, regrade, "2026-10-11")["corrections"]) == 1   # idempotent


def test_a_misquoted_verdict_is_judged_once_more_and_a_second_misquote_still_fails():
    rec = {"finding": "Yunzhan's quote is valid to 13 October with duty on Halden's account.", "assumptions": [], "would_change": [], "open_questions": []}
    good = {"checks": [{"n": i, "verdict": "yes", "quote": "valid to 13 October", "note": "n"} for i in range(1, 6)]}
    bad = {"checks": [{"n": 1, "verdict": "yes", "quote": "words the answer never had", "note": "n"}] + good["checks"][1:]}
    calls = iter([bad, good])
    d, cost = judge.judge_dim(rec, call=lambda p: (json.dumps(next(calls)), 0.04))
    assert d["passed"] and abs(cost - 0.08) < 1e-9 and any("second judging" in v["why"] or v["ok"] for v in d["verdicts"])
    twice = iter([bad, bad])
    d, cost = judge.judge_dim(rec, call=lambda p: (json.dumps(next(twice)), 0.04))
    assert not d["passed"] and "quote not found" in d["detail"] and abs(cost - 0.08) < 1e-9
    clean = iter([good])
    d, cost = judge.judge_dim(rec, call=lambda p: (json.dumps(next(clean)), 0.04))
    assert d["passed"] and abs(cost - 0.04) < 1e-9          # no retry when nothing was misquoted


def test_an_answer_with_no_assumptions_meets_the_assumptions_check_without_a_quote():
    rec = {"finding": "Priya decides whether to accept the slip.", "assumptions": [], "would_change": [], "open_questions": []}
    checks = [{"name": "assumptions are really assumptions"}, {"name": "buyer's words"}]
    rows = [{"n": 1, "verdict": "yes", "quote": "", "note": ""}, {"n": 2, "verdict": "yes", "quote": "", "note": ""}]
    v = judge.reconcile(rows, checks, rec)
    assert v[0]["ok"] and not v[1]["ok"]                      # only the vacuous check; a yes with no quote still fails any other check
    v = judge.reconcile(rows, checks, {**rec, "assumptions": ["Stock is on hand."]})
    assert not v[0]["ok"]                                     # with assumptions stated, a yes needs its quote
