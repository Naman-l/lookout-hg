"""Judge the answers a run kept, again, and say how steady the judge is.   python -m evals.regrade_judge [--runs 2]

A run keeps the Recommendation of every trial that failed. This judges each of them `--runs` times with the current judge and reconcile rules and
writes evals/report_judge_regrade.json: per case, per trial, each run's verdict per check; and the judge's repeatability, the share of
checks on which two runs of the judge agree. It does not replace the run's own result: the report keeps what the run recorded, and this says
what the judge says now and how much to trust one judging. Live: one judge call per answer per run (about 0.03 USD each).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import config, judge

EV = Path(__file__).parent


def regrade(results: dict, bench: dict, runs: int = 2, call=None) -> tuple[dict, float]:
    cost, out, agree, total = 0.0, {}, 0, 0
    for case in bench["agent"]:
        r = results.get(case) or {}
        trials = []
        for t in r.get("trials", []):
            rec = t.get("recommendation")
            if not rec:
                continue
            judged = []
            for _ in range(runs):
                verdicts, c, why = judge.judge_checks(rec, judge.CHECKS, call)
                cost += c
                judged.append(verdicts)
            ok_runs = [v for v in judged if v is not None]
            for a, b in zip(ok_runs, ok_runs[1:]):
                agree += sum(x["ok"] == y["ok"] for x, y in zip(a, b))
                total += len(a)
            trials.append({"runs": [[{"check": v["name"], "ok": v["ok"], "why": v["why"]} for v in vs] if vs else None for vs in judged],
                           "all_met_each_run": [bool(vs) and all(v["ok"] for v in vs) for vs in judged]})
        out[case] = trials
    n_trials = sum(len(v) for v in out.values())
    met = [sum(t["all_met_each_run"][i] for v in out.values() for t in v) for i in range(runs)]
    summary = {"runs": runs, "trials_judged": n_trials, "trials_all_checks_met_per_run": met,
               "repeatability": {"checks_agreeing": agree, "checks_compared": total, "rate": round(agree / total, 2) if total else None},
               "cost_usd": round(cost, 2), "judge_model": judge.JUDGE_MODEL}
    return {"summary": summary, "cases": out}, cost


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    ap = argparse.ArgumentParser(prog="evals.regrade_judge")
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args(argv)
    saved = json.loads((EV / "report.json").read_text())
    bench = yaml.safe_load((EV / "bench.yaml").read_text())
    res, cost = regrade(saved["results"], bench, a.runs)
    (EV / "report_judge_regrade.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
