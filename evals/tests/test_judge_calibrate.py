import json

from evals import judge_calibrate

PACKETS = [{"id": "P1", "recommendation": {"finding": "Yunzhan's quote is valid to 13 October.", "assumptions": [], "would_change": [], "open_questions": []},
            "checks": [{"name": "answers the buyer's question", "asks": "a"}, {"name": "nothing is committed", "asks": "b"}]}]


def _judge(verdicts):
    return lambda prompt: (json.dumps({"checks": [{"n": i, "verdict": v, "quote": "valid to 13 October", "note": "n"} for i, v in enumerate(verdicts, 1)]}), 0.1)


def test_the_judge_is_compared_with_the_labeller_per_check_and_costed():
    labels = {"P1": {"answers the buyer's question": "yes", "nothing is committed": "no"}}
    res, cost = judge_calibrate.run(labels, PACKETS, call=_judge(["yes", "no"]))
    assert res["items"] == 2 and res["agreement"]["rate"] == 1.0 and cost == 0.1
    res, _ = judge_calibrate.run(labels, PACKETS, call=_judge(["no", "yes"]))
    assert res["agreement"]["rate"] == 0.0 and res["kappa"] < 0


def test_an_unlabelled_packet_is_not_judged_and_an_unreadable_reply_is_not_scored():
    res, cost = judge_calibrate.run({}, PACKETS, call=_judge(["yes", "yes"]))
    assert res["items"] == 0 and cost == 0
    res, _ = judge_calibrate.run({"P1": {"nothing is committed": "yes"}}, PACKETS, call=lambda p: ("not json", 0.0))
    assert res["items"] == 0 and res["packets_unread"] == 1
