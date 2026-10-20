import json

from evals import regrade_judge

REC = {"finding": "Yunzhan's quote is valid to 13 October with duty on Halden's account.", "assumptions": [], "would_change": [], "open_questions": []}


def _say(verdict):
    return lambda p: (json.dumps({"checks": [{"n": i, "verdict": verdict, "quote": "valid to 13 October with duty", "note": "n"} for i in range(1, 6)]}), 0.02)


def test_each_kept_answer_is_judged_again_and_repeatability_is_counted():
    results = {"c1": {"trials": [{"status": "FAIL", "recommendation": REC}, {"status": "PASS"}]}}
    res, cost = regrade_judge.regrade(results, {"agent": ["c1"]}, runs=2, call=_say("yes"))
    s = res["summary"]
    assert s["trials_judged"] == 1 and s["trials_all_checks_met_per_run"] == [1, 1] and s["repeatability"]["rate"] == 1.0 and abs(cost - 0.04) < 1e-9
    flip = iter([_say("yes"), _say("no")] * 5)
    res, _ = regrade_judge.regrade(results, {"agent": ["c1"]}, runs=2, call=lambda p: next(flip)(p))
    assert res["summary"]["repeatability"]["rate"] == 0.0 and res["summary"]["trials_all_checks_met_per_run"] == [1, 0]
