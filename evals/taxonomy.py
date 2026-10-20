"""Tag each failure with a mode, from the dimension that failed, so the report can say what kinds of failure there were and not only how many."""
from __future__ import annotations

import ast
from pathlib import Path

import yaml

MODES = yaml.safe_load((Path(__file__).parent / "taxonomy.yaml").read_text())
_BY_DIM = {d: mode for mode, spec in MODES.items() for d in spec["dimensions"]}


def _missing(part: str) -> list[str]:
    try:
        return [str(x) for x in ast.literal_eval(part.split("missing:", 1)[1].strip())]
    except (IndexError, ValueError, SyntaxError):
        return []


def classify(detail: str, phrasing: frozenset | set | tuple = ()) -> list[str]:
    """Modes named by a failure detail of the form 'dimension: ...; dimension: ...'. A detail with no known dimension is 'other'.
    A must_mention miss is a wording miss only when every missing term is one the sheet lists as phrasing; otherwise a term a buyer would act on is missing."""
    modes = []
    for part in (detail or "").split("; "):
        head = part.split(":", 1)[0].strip()
        mode = _BY_DIM.get(head) or ("weak_prose" if head.startswith("prose (judge") else None)
        if "no number id agreed yet" in part:   # the sheet expects this fact but no tool gives it an id: it was not measured, which is not the same as wrong
            if "not_measured" not in modes:
                modes.append("not_measured")
            continue
        if head == "must_mention" and phrasing:
            miss = _missing(part)
            if miss and all(m in phrasing for m in miss):
                mode = "wording_miss"
        if mode and mode not in modes:
            modes.append(mode)
    if (detail or "").startswith("determinism") or "determinism:" in (detail or ""):
        modes.append("determinism") if "determinism" not in modes else None
    return modes or (["other"] if detail else [])


def tally(results: dict[str, dict], cases: dict[str, dict] | None = None) -> dict[str, int]:
    """Failed trials per mode across a run."""
    out: dict[str, int] = {}
    for i, r in results.items():
        phrasing = set(((cases or {}).get(i) or {}).get("expected", {}).get("phrasing_terms") or [])
        trials = r.get("trials") or []
        if r.get("status") == "FAIL" and trials and all(t["status"] == "PASS" for t in trials):  # failed across trials, not in one
            for m in classify(r.get("detail", ""), phrasing):
                out[m] = out.get(m, 0) + 1
        for t in r.get("trials") or [{"status": r["status"], "detail": r.get("detail", "")}]:
            if t["status"] == "FAIL":
                for m in classify(t.get("detail", ""), phrasing):
                    out[m] = out.get(m, 0) + 1
    return out
