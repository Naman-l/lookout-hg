"""The notes that are history, not the current result: the many-trials run on an earlier agent, the held-out set, how far the graders are trusted, the corrections,
the sheet checks that changed and their reasons, and the cost. They moved out of the README to evals/report.md, which this feeds."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import report, spend

EV = Path(__file__).parent


def lines(main: dict, cases: dict[str, dict]) -> list[str]:
    cfg = main["config"]
    gate = json.loads((EV / "report_gate29.json").read_text())
    held = json.loads((EV / "report_heldout.json").read_text())
    gres = {i: r for i, r in gate["results"].items() if not i.startswith("_") and i in cases and r["status"] not in ("BLOCKED", "SKIPPED")}
    many = [f"{i} {report._control_failures(r)} of {len(report._trials(r))}" for i, r in gres.items() if report._kind(cases[i]) == "model"]
    hres = {i: r for i, r in held["results"].items() if not i.startswith("_")}
    hp = sum(report._case_passed(r) for r in hres.values())
    cal = json.loads((EV / "judge" / "calibration_binary.json").read_text())["binary"]
    out = [f"Controls run many times (evals/report_gate29.md; an earlier agent, git {gate['config']['git_sha']}, not today's; history): model controls failed " + ", ".join(many) + " trials.",
           f"Held out (evals/report_heldout.md; sheets written apart): {hp} of {len(hres)} passed every trial, on the agent at git {held['config']['git_sha']}"
           + (" (the latest run's agent)." if held["config"]["git_sha"] == cfg["git_sha"] else f" (an older agent than the latest run's, git {cfg['git_sha']}).")]
    graders = f"Graders: the product's Reviewer against {cal['labels']} labels from a model reading the rubric (not a person): agreement {cal['agreement'][0]:.2f}, kappa {cal['kappa']}."
    for which in ("model", "human"):
        jp = EV / "judge" / f"calibration_judge_{which}.json"
        if jp.exists():
            j = json.loads(jp.read_text())
            graders += f" The prose judge ({j['judge_model']}) against {j['items']} checks labelled by {j['labeller']}: agreement {j['agreement']['rate']:.2f}, kappa {j['kappa']}."
    if not (EV / "judge" / "calibration_human.json").exists():
        graders += " The judge and the Reviewer are calibrated against a model's labels only; no person has labelled them yet."
    out.append(graders)
    rg = EV / "report_judge_regrade.json"
    if rg.exists():
        j = json.loads(rg.read_text())["summary"]
        out.append(f"Judge steadiness (the answers round 6 kept): two judgings of the same answer agree on {j['repeatability']['checks_agreeing']} of {j['repeatability']['checks_compared']} checks.")
    for c in main.get("corrections", []):
        out.append(f"Correction, {c['date']}: {c['note']}; {c['trials_whose_status_changed']} of {c['trials_re_judged']} re-judged trials changed status.")
    fix = next((r for r in reversed(yaml.safe_load((EV / "rounds.yaml").read_text()) or []) if "sheet checks" in str(r.get("round"))), None)
    if fix:
        out.append("Sheet checks changed before round 10, each because the raw files do not support what it expected: " + fix["changed"].split(" Proof:")[0].replace(
            "Three sheet checks changed, each because the check expected something the raw files do not support; approved by the integration lead (feedback: round 9 failure analysis). ", "")
            + " The proof is in evals/rounds.yaml; the failed round 9 trials stay failed.")
    out.append(f"Cost to date: {spend.line()}.")
    return out
