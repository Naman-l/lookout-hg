"""How far to trust the prose judge: run it on the packets a labeller has marked and compare.   python -m evals.judge_calibrate --labels model|human [--budget 4]

The judge sees each packet's Recommendation and that packet's own checks (the wording the labeller read), answers yes or no with a quote, and code
reconciles it exactly as in a run. Its yes is compared with the labeller's yes, and its no with the labeller's no: agreement, how many bad answers
it catches (rejects what the labeller rejects), how many good ones it passes, and kappa, each with a 95% interval. The labeller is named in the result:
`model` is the integration lead's model-read labels (not a person); `human` is the 40 items a person labels with evals/human_sheet.py.
Live: one judge call per packet (about 0.1 USD each on the judge's model); `--limit N` runs fewer. A packet whose reply cannot be read is not scored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import config, judge, stats

OUT = Path(__file__).parent / "judge"


def confusion(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs of (judge says met, labeller says met)."""
    tp = sum(j and h for j, h in pairs)
    tn = sum((not j) and (not h) for j, h in pairs)
    fp = sum(j and (not h) for j, h in pairs)
    fn = sum((not j) and h for j, h in pairs)
    n = len(pairs)
    po = (tp + tn) / n if n else 0.0
    pe = ((tp + fn) * (tp + fp) + (tn + fp) * (tn + fn)) / (n * n) if n else 0.0
    rate = lambda k, d: {"rate": round(k / d, 2), "ci": [round(x, 2) for x in stats.wilson(k, d)], "n": d} if d else None  # noqa: E731
    return {"items": n, "agreement": rate(tp + tn, n), "judge_passes_what_labeller_passes": rate(tp, tp + fn),
            "judge_rejects_what_labeller_rejects": rate(tn, tn + fp), "kappa": round((po - pe) / (1 - pe), 2) if pe < 1 else 1.0}


def run(labels: dict[str, dict[str, str]], packets: list[dict], call=None, limit: int | None = None) -> tuple[dict, float]:
    pairs, cost, unread = [], 0.0, 0
    for p in packets[:limit]:
        want = labels.get(p["id"]) or {}
        if not any(want.get(c["name"]) in ("yes", "no") for c in p["checks"]):
            continue
        verdicts, c, _ = judge.judge_checks(p["recommendation"], p["checks"], call)
        cost += c
        if verdicts is None:
            unread += 1
            continue
        for v in verdicts:
            said = want.get(v["name"])
            if said in ("yes", "no"):
                pairs.append((v["ok"], said == "yes"))
    res = confusion(pairs)
    res["packets_unread"] = unread
    return res, cost


def _norm(labels: dict) -> dict:
    return {pid: {k: {True: "yes", False: "no"}.get(v, v) for k, v in (lab or {}).items()} for pid, lab in (labels or {}).items()}


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    ap = argparse.ArgumentParser(prog="evals.judge_calibrate")
    ap.add_argument("--labels", choices=["model", "human"], default="model")
    ap.add_argument("--human-answers", type=Path, help="with --labels human: the lines the labelling page copies out")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    packets = yaml.safe_load((OUT / "packets.yaml").read_text())
    if a.labels == "model":
        labels = _norm(yaml.safe_load((OUT / "labels.yaml").read_text()))
        labeller = "a model reading the rubric (the integration lead), not a person"
    else:
        from .human_sheet import parse
        got = parse(a.human_answers.read_text())
        labels = {}
        for (pid, check), v in got.items():
            labels.setdefault(pid, {})[check] = v
        labeller = "a person (Khalid), 40 items"
    res, cost = run(labels, packets, limit=a.limit)
    res.update(labeller=labeller, judge_model=judge.JUDGE_MODEL, cost_usd=round(cost, 2))
    (OUT / f"calibration_judge_{a.labels}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
