"""Correct a run's prose-judge results after a judge defect, keeping the run as recorded.   python -m evals.correct_judge --date 2026-10-11

Round 6's judge rejected quotes that skipped words with an ellipsis, so some "quote not found" failures were the grader's, not the agent's.
The fixed rule was applied to the answers the run kept (evals/regrade_judge.py: each judged twice more). Here each affected trial's prose dimension is
replaced by what the corrected judging says, in both judgings: a check counts as met only if both judgings met it. The trial's original status and detail
are kept under `as_run`; a trial whose only failure was the prose dimension and which now meets all five checks becomes a pass; the case and the counts
follow. A dated `corrections` entry on the report says what was done. Nothing is re-run and nothing is guessed: an answer that was not kept stays as it was.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EV = Path(__file__).parent


def correct(report: dict, regrade: dict, date: str) -> dict:
    res, fixed, flipped = report["results"], 0, 0
    for case, kept in regrade["cases"].items():
        r = res.get(case)
        if not r:
            continue
        idx = 0
        for t in r.get("trials", []):
            if not t.get("recommendation"):
                continue
            judged, idx = kept[idx], idx + 1
            if "prose (judge)" not in t.get("detail", "") and t.get("prose") != "failed":
                continue
            runs = [run for run in judged["runs"] if run]
            failing = {}
            for run in runs:
                for v in run:
                    if not v["ok"]:
                        failing.setdefault(v["check"], v["why"])
            parts = [p for p in t["detail"].split("; ") if p.strip()]
            keep, skipping = [], False
            for p in parts:                     # everything from "prose (judge):" on is the judge's text; the rest are the code graders'
                if p.startswith("prose (judge)"):
                    skipping = True
                if not skipping:
                    keep.append(p)
            new_detail = "; ".join(keep + ([f"prose (judge, re-judged after the quote-rule fix): " + "; ".join(f"{c}: {w}" for c, w in failing.items())] if failing else []))
            if "as_run" not in t:
                t["as_run"] = {"status": t["status"], "detail": t["detail"]}
            before = t["status"]
            t["detail"], t["prose"] = new_detail, "failed" if failing else "met"
            t["status"] = "PASS" if not new_detail else "FAIL"
            fixed += 1
            flipped += before != t["status"]
        statuses = [t["status"] for t in r.get("trials", [])]
        r["detail"] = next((t["detail"] for t in r["trials"] if t["detail"]), "")
        if statuses and all(s == "PASS" for s in statuses) and not r.get("determinism_failed"):
            r["status"] = "PASS"
    report.setdefault("corrections", [])
    if not any(c["date"] == date and c["what"] == "prose judge quote rule" for c in report["corrections"]):
        report["corrections"].append({"date": date, "what": "prose judge quote rule", "trials_re_judged": fixed, "trials_whose_status_changed": flipped,
                                      "note": "the judge's first quote rule rejected quotes that skip words with an ellipsis; the answers the run kept were re-judged twice with the fixed rule and each affected trial's prose result replaced by the corrected one; the run's own result is under as_run"})
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.correct_judge")
    ap.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    report = json.loads((EV / "report.json").read_text())
    out = correct(report, json.loads((EV / "report_judge_regrade.json").read_text()), a.date)
    (EV / "report.json").write_text(json.dumps(out, indent=2, default=str))
    c = out["corrections"][-1]
    print(f"{c['trials_re_judged']} trials re-judged, {c['trials_whose_status_changed']} changed status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
