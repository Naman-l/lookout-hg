"""Intervals and the do-nothing baselines."""
import glob
from pathlib import Path

import yaml

from evals import baselines, report, stats

CASES = {c["id"]: c for c in (yaml.safe_load(Path(f).read_text()) for f in glob.glob(str(Path(__file__).resolve().parents[1] / "cases" / "*.yaml")))}


def test_three_of_three_proves_little_and_twenty_nine_prove_ninety_percent():
    assert round(stats.lower_bound(3, 3), 2) == 0.37
    assert stats.trials_for(0.90) == 29 and stats.trials_for(0.95) == 59
    assert stats.lower_bound(29, 29) >= 0.90 > stats.lower_bound(28, 29)


def test_wilson_interval_for_eighteen_of_nineteen():
    lo, hi = stats.wilson(18, 19)
    assert round(lo, 2) == 0.75 and round(hi, 2) == 0.99


def test_claim_names_failures_and_never_overstates():
    assert "no failure in 3" in stats.claim(3, 3) and "at least 0.37" in stats.claim(3, 3)
    assert "1 of 10 failed" in stats.claim(9, 10)


def test_pass_hat_k_estimator():
    assert stats.pass_hat_k(3, 3, 3) == 1.0 and abs(stats.pass_hat_k(2, 3, 2) - 1 / 3) < 1e-9


def test_a_do_nothing_and_an_always_refuse_agent_pass_only_the_stop_case_that_says_so():
    r = baselines.run(CASES)
    assert r["status"] == "PASS", r["detail"]
    stop_cases = ["control-injection-model-reply", "inbox-vpm-reply"]
    assert sorted(r["baselines"]["null"]) == stop_cases == sorted(r["baselines"]["refuse"])


def test_a_baseline_that_passes_an_unmarked_case_fails_the_check():
    cases = {**CASES, "inbox-vpm-reply": {k: v for k, v in CASES["inbox-vpm-reply"].items() if k != "baseline_ok"}}
    r = baselines.run(cases)
    assert r["status"] == "FAIL" and "null agent passes inbox-vpm-reply" in r["detail"]


def test_the_report_carries_intervals_and_the_baseline_line():
    res = {"control-x": {"status": "PASS", "trials": [{"status": "PASS", "detail": ""}] * 3, "speed": {"cost_usd": 0.1}}, "_baselines": {"status": "PASS", "detail": "neither passes any of 3 agent cases"}}
    cfg = {"date": "d", "model": "m", "prompt_hash": "p", "data_hash": "h", "sdk": "s", "git_sha": "g"}
    text = report.render(cfg, res, {"control-x": {"category": "control"}}, "3 trials")
    assert "control-x" in text and "3 trials" in text and "guardrail held" in text and "Baselines" in text
    assert "At a glance: control" not in text and "Reliability, CONTROL" not in text  # a control is a row, never a rate


def test_failure_modes_are_named_from_the_failed_dimension():
    from evals import taxonomy
    assert taxonomy.classify("must_mention: missing: ['x']; trajectory: y") == ["omitted_term", "wrong_path"]
    assert taxonomy.classify("something odd") == ["other"] and taxonomy.classify("") == []
    res = {"a": {"status": "FAIL", "trials": [{"status": "PASS", "detail": ""}, {"status": "FAIL", "detail": "as_of: today is 10 October"}]}}
    assert taxonomy.tally(res) == {"clock": 1}


def test_the_gate_flags_only_cases_that_passed_before_and_fail_now(tmp_path):
    import json

    from evals import run
    saved = tmp_path / "report.json"
    saved.write_text(json.dumps({"results": {"a": {"status": "PASS"}, "b": {"status": "FAIL"}, "c": {"status": "PASS"}}}))
    now = {"a": {"status": "FAIL"}, "b": {"status": "FAIL"}, "c": {"status": "SKIPPED"}, "d": {"status": "FAIL"}}
    assert run.regressions(now, saved) == ["a"]


def test_reviewer_agreement_is_scored_against_labels_with_intervals():
    from evals import judge_packets as jp
    key = {"P1": {"reviewer": {"a": 2, "b": 2}}, "P2": {"reviewer": {"a": 0, "b": 1}}}
    s = jp.score(key, {"P1": {"a": "yes", "b": "no"}, "P2": {"a": "no", "b": "no"}})
    assert s["labels"] == 4 and s["agreement"][0] == 0.75 and s["reviewer_rejects_when_human_no"][0] == 2 / 3


def test_bare_yes_and_no_in_a_yaml_labels_file_are_read_as_labels():
    import yaml

    from evals import judge_packets as jp
    labels = yaml.safe_load("P1:\n  a: yes\n  b: no\n")
    assert jp.score({"P1": {"reviewer": {"a": 2, "b": 0}}}, labels)["labels"] == 2


def test_a_loose_check_is_named_in_the_report():
    cfg = {"date": "d", "model": "m", "prompt_hash": "p", "data_hash": "h", "sdk": "s", "git_sha": "g"}
    res = {"h": {"status": "PASS", "trials": [{"status": "PASS", "detail": ""}], "loose": True}}
    assert "h (loose numeric check)" in report.render(cfg, res, {"h": {"category": "hard"}}, "2 trials")


def test_a_case_that_fails_across_trials_is_not_shown_as_passing():
    """Round 4's disruption-fm: both trials passed, the determinism check between them failed, and the report said PASS PASS."""
    from evals import taxonomy
    res = {"disruption-fm": {"status": "FAIL", "detail": "determinism: staged actions differ: [('note', None)]", "trials": [{"status": "PASS", "detail": ""}, {"status": "PASS", "detail": ""}]}}
    cfg = {"date": "d", "model": "m", "prompt_hash": "p", "data_hash": "h", "sdk": "s", "git_sha": "g"}
    text = report.render(cfg, res, {"disruption-fm": {"category": "hard", "core": True}}, "2 trials")
    assert "hard 0/1" in text and "determinism" in text and "case-level" in text
    assert taxonomy.tally(res) == {"determinism": 1}


def test_a_sheet_that_was_not_run_is_not_counted_as_a_case():
    cfg = {"date": "d", "model": "m", "prompt_hash": "p", "data_hash": "d", "sdk": "s", "git_sha": "g"}
    cases = {"a": {"category": "hard"}, "parked": {"category": "hard", "stale": "does this in code"}}
    text = report.render(cfg, {"a": {"status": "PASS", "trials": [{"status": "PASS"}]}}, cases, "2 trials")
    assert "SHEETS RUN: 1 cases" in text


def test_controls_are_one_row_each_and_a_replay_is_not_a_trial_count():
    cfg = {"date": "d", "model": "m", "prompt_hash": "p", "data_hash": "h", "sdk": "s", "git_sha": "g"}
    cases = {"stop-code": {"category": "control", "kind": "ledger", "tests": "code"},
             "stop-model": {"category": "control", "kind": "agent", "tests": "model"},
             "stop-model-2": {"category": "control", "kind": "agent", "tests": "model"}}
    res = {"stop-code": {"status": "PASS", "replayed": True, "trials": [{"status": "PASS"}] * 29},
           "stop-model": {"status": "FAIL", "trials": [{"status": "PASS"}, {"status": "FAIL", "detail": "ledger: staged_count: expected 0, got 1"}, {"status": "PASS"}], "speed": {"cost_usd": 0.1}},
           "stop-model-2": {"status": "PASS", "trials": [{"status": "PASS"}] * 3, "speed": {"cost_usd": 0.1}}}
    text = report.render(cfg, res, cases, "3 trials")
    assert "No guardrail failed in code (1 run); model controls: guardrail held in 5 of 6 trials (failed: stop-model 1/3)" in text
    row = next(x for x in text.splitlines() if x.strip().startswith("stop-code"))
    assert "replayed, deterministic" in row and "29 trials" not in row
    assert "guardrail FAILED 1" in next(x for x in text.splitlines() if x.strip().startswith("stop-model "))
    code_broken = report.controls_headline({"stop-code": {"status": "FAIL", "trials": [{"status": "FAIL", "detail": "x"}]}}, {"stop-code": {"category": "control", "tests": "code"}})
    assert code_broken.startswith("1 guardrail(s) failed in code: stop-code")


def test_the_gate_says_what_its_exit_code_hides():
    from evals import run
    saved = {"bcx": {"status": "FAIL", "trials": [{"status": "FAIL"}]}, "gp": {"status": "FAIL", "trials": [{"status": "FAIL"}]}, "ok": {"status": "PASS", "trials": [{"status": "PASS"}]}}
    now = {"bcx": {"status": "PASS", "replayed": True}, "gp": {"status": "FAIL"}, "ok": {"status": "PASS"}}
    notes = run.gate_notes(now, saved, "482bdf9")
    assert any("Known failures" in n and "gp" in n and "bcx" not in n for n in notes)
    assert any("Replayed PASS, live FAIL at 482bdf9: bcx" in n for n in notes)


def test_a_missing_commercial_term_is_not_a_wording_miss():
    from evals import taxonomy
    assert taxonomy.classify("must_mention: missing: ['FOB']", {"approv"}) == ["omitted_term"]
    assert taxonomy.classify("must_mention: missing: ['approv']", {"approv"}) == ["wording_miss"]
    assert taxonomy.classify("must_mention: missing: ['approv', 'FOB']", {"approv"}) == ["omitted_term"]


def test_an_unmeasured_fact_is_not_a_wrong_number_and_the_headline_counts_it_apart():
    from evals import report, taxonomy
    assert taxonomy.classify("facts: duty_rate: no number id agreed yet; x:HR-1: no number id agreed yet") == ["not_measured"]
    assert taxonomy.classify("facts: a: expected 1, got 2; b: no number id agreed yet") == ["wrong_number", "not_measured"]
    assert taxonomy.classify("prose (judge, re-judged after the quote-rule fix): buyer's words: x") == ["weak_prose"]
    res = {"a": {"status": "FAIL", "trials": [{"status": "FAIL", "detail": "facts: f: no number id agreed yet; g: no number id agreed yet"}]},
           "b": {"status": "PASS", "trials": [{"status": "PASS"}]}}
    h = report.agent_headline(res, {"a": {}, "b": {}})
    assert h.startswith("Agent cases: 1 passed every check in every trial, 0 more held every check that could be made, 1 failed") and "facts not measured" in h and "a 2" in h


def test_a_control_is_graded_on_what_the_agent_did_and_its_words_are_graded_apart():
    from evals import report
    cases = {"c": {"category": "control", "kind": "agent", "tests": "model"}}
    stored = {"status": "FAIL", "trials": [{"status": "PASS"}, {"status": "FAIL", "detail": "must_mention: missing: ['approv']"}, {"status": "PASS"}]}   # a round-9-shaped result
    assert report._control_failures(stored) == 0 and report._control_words(stored) == (2, 3)
    new = {"status": "PASS", "trials": [{"status": "PASS", "said": True}, {"status": "PASS", "said": False, "words": "must_mention: missing: ['approv']"}, {"status": "PASS", "said": True}]}
    assert report._control_failures(new) == 0 and report._control_words(new) == (2, 3)
    held = report.controls_headline({"c": new}, cases)
    assert "guardrail held in 3 of 3 trials" in held and "said it in words in 2 of 3 trials" in held
    broke = {"status": "FAIL", "trials": [{"status": "FAIL", "detail": "ledger: staged_count: expected 0, got 1; must_mention: missing: ['approv']"}, {"status": "PASS"}]}
    assert report._control_failures(broke) == 1   # a missing word beside a real failure does not hide the failure
    line = "\n".join(report.controls_block({"c": new}, cases))
    assert "guardrail held" in line and "said it in words 2 of 3" in line


def test_an_agent_case_shows_each_kind_of_check_over_its_own_trials_apart():
    from evals import report
    r = {"status": "FAIL", "trials": [
        {"status": "FAIL", "prose": "met", "detail": "must_mention: missing: ['Tijuana', 'EXW']; facts: a: expected 1, got 2"},
        {"status": "FAIL", "prose": "failed", "detail": "actions: missing action type supplier_request; prose (judge): buyer's words: x"}]}
    line = report.groups_line(r)
    assert "behaviour held 1 of 2" in line and "numbers, owners and dates right 1 of 2" in line
    assert "conditions the buyer needs stated 1 of 2" in line and "prose met 1 of 2" in line
    assert report.trial_groups({"detail": "must_mention: missing: ['approv']"}, {"approv"}) == {"prose"}   # a phrase-list term is words, not a condition
