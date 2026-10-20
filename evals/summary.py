"""The evals summary Under the hood shows (FINAL 08 B-c): one dated round, as measured, never one pass rate.

  python -m evals.summary     print the summary as JSON

Every value comes from the committed reports through the same counting as the README block (readme_block.py), so the
screen, the README and the report cannot disagree.
"""
from __future__ import annotations

import json
from functools import lru_cache

import yaml

from . import report
from .readme_block import EV, _counts, _load
from .run import load_bench, load_cases


@lru_cache(maxsize=1)
def summary() -> dict:
    main, held = _load("report.json"), _load("report_heldout.json")
    spec, cases = load_bench(), load_cases()
    ids = report.bench_ids(spec)
    res, cfg = main["results"], main["config"]
    ctl = {i: cases[i] for i in ids["controls"] if i in res}
    ag = {i: cases[i] for i in ids["agent"] if i in res}
    sysc = [res[i]["status"] == "PASS" for i in ids["system"] if i in res]
    code = [i for i, c in ctl.items() if report._kind(c) == "code"]
    model = [i for i, c in ctl.items() if report._kind(c) == "model"]
    model_n = sum(len(report._trials(res[i])) for i in model)
    model_bad = sum(report._control_failures(res[i]) for i in model)
    failed_models = [f"{i}, {report._control_failures(res[i])} of {len(report._trials(res[i]))} trials" for i in model if report._control_failures(res[i])]
    held_ctl = sum(report._control_failures(res[i]) == 0 for i in ctl)
    k = {i: _counts(res[i], c.get("expected", {}).get("phrasing_terms") or []) for i, c in ag.items()}
    every = lambda g: sum(1 for x in k.values() if x[g][1] and x[g][0] == x[g][1])      # noqa: E731
    hres = {i: r for i, r in held["results"].items() if not i.startswith("_")}
    rnd = next((r["round"] for r in reversed(yaml.safe_load((EV / "rounds.yaml").read_text()) or []) if isinstance(r.get("round"), int)), None)
    trials = max((len(report._trials(r)) for r in (res[i] for i in ag)), default=0)
    n = len(ag)
    rows = [
        {"label": "Right action", "sub": f"right contact, nothing wrongly staged · {n} agent cases", "value": f"{every('behaviour')} of {n}"},
        {"label": "Guardrails held", "sub": f"{len(ctl)} controls: fraud, injection, bypass, unknown origin…", "value": f"{held_ctl} of {len(ctl)}"},
        {"label": "Guardrails held, model controls", "sub": ("failed: " + "; ".join(failed_models)) if failed_models else "", "value": f"{model_n - model_bad} of {model_n} trials"},
        {"label": "System checks", "sub": "code against the records", "value": f"{sum(sysc)} of {len(sysc)}"},
        {"label": "Conditions stated", "sub": "what the buyer must know to act", "value": f"{every('conditions')} of {n}"},
        {"label": "Right wording", "sub": "", "value": f"{every('prose')} of {n}"},
        {"label": "Every figure, owner and date right, in every trial", "sub": "", "value": f"{every('facts')} of {n}"},
        {"label": "Held-out sheets", "sub": "written apart from the cases the builders saw", "value": f"{sum(report._case_passed(r) for r in hres.values())} of {len(hres)}"},
    ]
    return {"date": cfg.get("date"), "round": rnd, "model": cfg.get("model"), "trials": trials, "git": cfg.get("git_sha"), "code_controls": f"{sum(report._control_failures(res[i]) == 0 for i in code)} of {len(code)}", "rows": rows}


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2))
