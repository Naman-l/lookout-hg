import pytest
import json

from evals import agent_runner, config, spend
from evals.spend import HERE


def test_the_ledger_sums_and_names_runs_with_no_recorded_cost():
    rows = spend.load()
    assert spend.total(rows) == round(sum(r["usd"] for r in rows if r.get("usd") is not None), 2)
    text = spend.line()
    assert f"{spend.total(rows):.2f} USD" in text and "round 2" in text and "Reviewer calibration" in text
    spent, done, n = spend.capped(rows)
    assert f"{spent:.2f} of a {spend.cap()["usd"]} USD cap spent, {done} of {n} done" in text and "pending" not in text   # pending runs are not "not recorded"


def test_the_cap_counts_only_the_runs_it_covers():
    rows = [{"run": "a", "usd": 5.0}, {"run": "b", "usd": 4.0, "in_cap": True}, {"run": "c", "usd": None, "in_cap": True, "pending": True}]
    assert spend.capped(rows) == (4.0, 1, 2)
    assert "4.00 of a 17 USD cap spent, 1 of 2 done" in spend.line(rows, {"usd": 17})


def test_each_committed_report_costs_what_the_ledger_says():
    for r in spend.load():
        if not r.get("report"):
            continue
        res = json.loads((HERE / r["report"]).read_text())["results"]
        cost = sum((v.get("speed") or {}).get("cost_usd") or 0 for k, v in res.items() if not k.startswith("_"))
        assert abs(cost - r["usd"]) < 0.02, (r["run"], cost, r["usd"])


def test_a_live_run_has_a_spending_ceiling_by_default(monkeypatch):
    monkeypatch.delenv("LOOKOUT_EVAL_BUDGET_USD", raising=False)
    assert config.default_budget() == pytest.approx(max(spend.cap()["usd"] - spend.capped(spend.load())[0], 0.0))   # the cap in the ledger less what the capped runs have spent
    monkeypatch.setenv("LOOKOUT_EVAL_BUDGET_USD", "3")
    assert config.default_budget() == 3.0
    monkeypatch.setitem(agent_runner.BUDGET, "limit", 3.0)
    monkeypatch.setitem(agent_runner.BUDGET, "spent", 3.0)
    assert agent_runner.over_budget()


def test_the_eval_commands_read_the_key_from_dot_env_without_overriding_the_shell(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-dot-env\nLOOKOUT_JUDGE_MODEL_TEST=x\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config.load_env(env)
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "from-dot-env"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-shell")
    config.load_env(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "from-the-shell"
    monkeypatch.delenv("LOOKOUT_JUDGE_MODEL_TEST", raising=False)


def test_the_run_snapshot_carries_every_key_the_report_header_reads():
    snap = config.snapshot("claude-sonnet-5-5", 2)
    for key in ("date", "model", "prompt_hash", "data_hash", "sheets_hash", "sdk", "git_sha", "trials"):
        assert key in snap, key
    assert len(snap["date"]) == 10 and snap["model"] == "claude-sonnet-5-5"
