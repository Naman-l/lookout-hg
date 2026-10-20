import json

from evals import spend


def test_a_rounds_ledger_rows_are_computed_from_its_report_and_older_rows_stop_pointing_at_report_json(tmp_path, monkeypatch):
    ledger = tmp_path / "spend.yaml"
    ledger.write_text('cap: {usd: 50, covers: [a]}\nruns:\n  - {run: "round 9", usd: 2.65, report: report.json, in_cap: true, note: "x"}\n')
    rep = tmp_path / "report.json"
    rep.write_text(json.dumps({"results": {"c1": {"runs": 2, "speed": {"cost_usd": 1.0, "judge_cost_usd": 0.1}}, "c2": {"runs": 3, "speed": {"cost_usd": 0.5, "judge_cost_usd": 0.0}}, "_baselines": {}}}))
    monkeypatch.setattr(spend, "HERE", tmp_path)
    rows = spend.add_round("round 10", rep, "on the final agent")
    assert rows[0]["usd"] == 1.5 and rows[1]["usd"] == 0.1
    doc = spend._doc(ledger)
    by = {r["run"]: r for r in doc["runs"]}
    assert by["round 9"]["report"] is None and by["round 10"]["report"] == "report.json" and by["round 10"]["usd"] == 1.5 and by["round 10, prose judge in the run"]["usd"] == 0.1
    assert "5 live agent runs on the final agent" in by["round 10"]["note"]
