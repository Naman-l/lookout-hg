"""Run the eval set and print the report.   python -m evals.run [--no-model] [--only ID] [--trials N]

`--no-model` runs the detector and code cases and needs no key. `--self-check` grades the answer sheets
against the oracle (no app needed). A case whose system under test does not exist yet is BLOCKED; with
`--strict` that is a failure, which is how the integration gate runs it.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import yaml

from . import baselines, agent_runner, apicheck, config, graders, history_notes, model, report, selfcheck, subject
from .oracle import compute  # noqa: F401  (imported so a broken oracle fails fast)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases"


HELDOUT = ROOT / "evals" / "heldout"


def load_cases(only: str | None = None, include_unbuilt: bool = True, directory: Path | None = None) -> dict[str, dict]:
    """Answer sheets by id. A sheet with `stale` is kept but not run by default: the field says why.
    `directory` reads the held-out sheets instead: written apart from the cases the builders see, run only at release rounds."""
    cases = {}
    for f in sorted((directory or CASES).glob("*.yaml")):
        c = yaml.safe_load(f.read_text())
        if (only is None or c["id"] == only) and (include_unbuilt or only or not c.get("stale")):
            cases[c["id"]] = c
    return cases


def grade_detector(case: dict, measured: dict) -> list[dict]:
    e, dims = case["expected"], []
    if "counts" in e:
        dims.append(graders.grade_counts(e["counts"], measured.get("counts", {})))
    if "facts" in e:
        dims.append(graders.grade_facts(e["facts"], measured.get("facts", {})))
    if "messages" in e:
        got = measured.get("messages", {})
        want = {f"{stem}.{k}": (sorted(v) if isinstance(v, list) else v)
                for stem, spec in e["messages"].items() for k, v in _flat(spec).items()
                if k.split(".")[0] in ("sender", "trust", "kind", "flags", "dates", "supersedes", "untrusted")}
        have = {f"{stem}.{k}": (sorted(v) if isinstance(v, list) else v) for stem, spec in got.items() for k, v in _flat(spec).items()}
        dims.append(graders.grade_counts(want, have))
        dims.append(graders.grade_counts({"message_count": e["message_count"], "untrusted_count": e["untrusted_count"]},
                                         {k: measured.get(k) for k in ("message_count", "untrusted_count") if k in measured}))
    if "subsets" in e:
        bad = [f"{k}: expected {sorted(want)} within the measured list, missing {sorted(set(want) - set(_flat(measured).get(k, [])))}"
               for k, want in e["subsets"].items() if k in _flat(measured) and not set(want) <= set(_flat(measured)[k])]
        unmeasured = [k for k in e["subsets"] if k not in _flat(measured)]
        dims.append(graders._dim("subsets", not bad and not unmeasured, "; ".join(bad + [f"{k}: not measured" for k in unmeasured]), unmeasured, len(bad)))
    for key in ("news_matches", "shortage", "quotes", "tariff", "ledger"):
        if key in e:
            dims.append(graders.grade_counts(_flat(e[key]), _flat(measured.get(key, {}))))
    return dims


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def run_case(case: dict, no_model: bool, db: Path, trials: int = 2, serve=None) -> dict:
    kind = case["kind"]
    if kind == "api":
        with agent_runner.app_server(db, Path(tempfile.mkdtemp(prefix="lookout-api-"))) as base:
            dims = apicheck.run(base, case["checks"])
        status = graders.case_status(dims)
        return {"status": status, "dims": dims, "detail": "; ".join(f"{d['name']}: {d['detail']}" for d in dims if not d["passed"])}
    if kind == "ledger":
        from . import ledger_check
        reps = trials if trials >= 10 else 1  # a 29-trial gate repeats the attack; that many live fire runs would cost more than they teach, and the ledger is code, so it replays
        if not no_model and reps == 1:  # a live run stages the action; with --no-model the shipped recording does, and the ledger rules under attack are the same code
            ok, why = model.reachable()
            if not ok:
                return {"status": "BLOCKED", "detail": why}
        replay = no_model or reps > 1
        out = [ledger_check.run(db, replay=replay) for _ in range(reps)]
        dims = out[-1] if reps == 1 else [graders._dim("ledger attacks", all(d["passed"] for o in out for d in o), f"{reps} repeats of both flows")]
        res = {"status": graders.case_status([d for o in out for d in o]), "dims": dims, "detail": "; ".join(f"{d['name']}: {d['detail']}" for o in out for d in o if not d["passed"])[:300]}
        if reps > 1:
            res["trials"] = [{"status": graders.case_status(o), "detail": ""} for o in out]
            res["replayed"] = True
        elif not replay:
            res.update({"runs": 2, "speed": {"cost_usd": ledger_check.run.last_cost}})
        return res
    if kind == "sandbox":
        try:
            from . import sandbox_attack
            results = sandbox_attack.run_default()
        except ModuleNotFoundError as e:
            return {"status": "BLOCKED", "detail": f"the Data steward's sandbox is not on this branch yet ({e.name})"}
        bad = [f"{r['id']}: {'host crashed: ' + r['host_error'] if r['host_error'] else 'leaked' if r['leaked_canary'] else 'wrote outside' if r['wrote_outside'] else 'connected out' if r['connected'] else 'ran to completion through the allowlist'}"
               for r in results if r["id"] != "benign-step" and not r["contained"]]
        benign = next((r for r in results if r["id"] == "benign-step"), None)
        if not (benign and benign["benign_ok"]):
            bad.append("benign-step: a legitimate step no longer runs")
        from . import egress_check
        dims = [graders._dim("contained", not bad, "; ".join(bad) or f"{len(results) - 1} attacks contained, benign step runs"), *egress_check.run()]
        return {"status": graders.case_status(dims), "dims": dims, "detail": "; ".join(f"{d['name']}: {d['detail']}" for d in dims if not d["passed"])}
    if kind in ("agent", "import") and no_model:
        if kind == "agent" and case.get("tests") == "code":
            return agent_runner.replay_case(case, db, code=True)   # a code control is answered by code before any model reads it: it runs for real, with no key
        if kind == "agent" and agent_runner.has_recording(case):
            return agent_runner.replay_case(case, db)  # graded on the shipped recording, no model, labelled replayed
        return {"status": "SKIPPED", "detail": "needs the model (--no-model); no shipped recording to replay"}
    try:
        if kind in ("detector", "code"):  # "import" and "agent" need their own runners (steward, run_workflow)
            dims = grade_detector(case, subject.measure(db))
        elif kind == "agent":
            ok, why = (True, "test server") if serve else model.reachable()
            if not ok:
                return {"status": "BLOCKED", "detail": why}
            k = max(trials, 3) if case["category"] == "control" else trials  # controls are pass^k with k = 3
            return agent_runner.run_case(case, db, k, serve)
        else:
            return {"status": "BLOCKED", "detail": "this sheet describes a flow the product now does in code; see its `stale` field"}
    except subject.Blocked as e:
        return {"status": "BLOCKED", "detail": str(e)}
    except Exception as e:  # noqa: BLE001  (the system under test raised: that is a result, not a crash of the evals)
        return {"status": "FAIL", "detail": f"system error: {type(e).__name__}: {e}"}
    status = graders.case_status(dims)
    fails = [d for d in dims if not d["passed"]]
    return {"status": status, "dims": dims, "detail": "; ".join(f"{d['name']}: {d['detail']}" for d in fails)}


def regressions(results: dict[str, dict], saved_path: Path | None = None) -> list[str]:
    """Cases that passed in the committed report and fail now (SKIPPED and not-run cases are not compared)."""
    path = saved_path or ROOT / "evals" / "report.json"
    if not path.exists():
        return []
    saved = json.loads(path.read_text())["results"]
    return sorted(i for i, r in results.items() if i in saved and not i.startswith("_") and report._case_passed(saved[i]) and r["status"] in ("FAIL", "BLOCKED"))


def load_bench() -> dict:
    return yaml.safe_load((ROOT / "evals" / "bench.yaml").read_text())


def gate_notes(results: dict[str, dict], saved_results: dict[str, dict], saved_git: str = "") -> list[str]:
    """What the gate's exit code hides: failures it already knew about, and replayed passes the live run contradicts."""
    saved = {i: r for i, r in saved_results.items() if not i.startswith("_")}
    known = sorted(i for i, r in results.items() if r["status"] == "FAIL" and i in saved and not report._case_passed(saved[i]))
    contradicted = sorted(i for i, r in results.items() if r.get("replayed") and r["status"] == "PASS" and i in saved
                          and not saved[i].get("replayed") and not report._case_passed(saved[i]))
    out = []
    if known:
        out.append("Known failures (in the committed report too, so not regressions): " + ", ".join(known))
    if contradicted:
        out.append(f"Replayed PASS, live FAIL{' at ' + saved_git if saved_git else ''}: " + ", ".join(contradicted)
                   + ". A recording is not the agent: read the live result, or re-record from the frozen agent.")
    return out


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    ap = argparse.ArgumentParser(prog="evals.run")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--trials", type=int, default=2)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--self-check", action="store_true", help="grade the answer sheets against the oracle")
    ap.add_argument("--heldout", action="store_true", help="run the held-out sheets (evals/heldout) instead of the cases; --write goes to report_heldout.*")
    ap.add_argument("--category", choices=["control", "ordinary", "hard"], help="run only this category (the 29-trial control gate: --category control --trials 29)")
    ap.add_argument("--budget", type=float, default=None, help="stop live runs once this many USD have been spent in this process (what is left of the ledger cap, or LOOKOUT_EVAL_BUDGET_USD; the run reports what it did not get to)")
    ap.add_argument("--stem", help="write the report to evals/<stem>.md and .json instead of report.* (the 29-trial gate writes report_gate29.*)")
    ap.add_argument("--gate", action="store_true", help="fail if a case that passed in the committed report.json no longer does")
    ap.add_argument("--strict", action="store_true", help="BLOCKED counts as a failure")
    ap.add_argument("--db", type=Path, default=ROOT / "backend" / "lookout.db")
    ap.add_argument("--no-judge", action="store_true", help="do not call the prose judge on the agent's ordinary and hard cases (it is on for live runs)")
    ap.add_argument("--full", action="store_true", help="every sheet that is not parked, not only the answer sheet in evals/bench.yaml (the gate runs this)")
    ap.add_argument("--bench", action="store_true", help="the answer sheet in evals/bench.yaml (the default when no other selection is given); with --rerender, show the saved report through it")
    ap.add_argument("--all", action="store_true", help="also run the sheets of limbs that are not built (their baseline on the base agent)")
    ap.add_argument("--rerender", action="store_true", help="rewrite evals/report.md from the saved evals/report.json (no runs, no cost)")
    ap.add_argument("--merge", action="store_true", help="with --only/--write: refresh just these cases inside the saved report and say so in its header")
    ap.add_argument("--write", action="store_true", help="write evals/report.md and report.json")
    a = ap.parse_args(argv)

    if a.rerender:
        saved = json.loads((ROOT / "evals" / "report.json").read_text())
        ch = ROOT / "evals" / "changes.yaml"
        changes = (yaml.safe_load(ch.read_text()) or {}) if ch.exists() else {}
        every = load_cases()
        ref = saved.get("refreshed") or {}
        shown = {**saved["config"], "git_sha": saved["config"]["git_sha"] + (", refreshed: " + ", ".join(f"{i} at {g}" for i, g in ref.items()) if ref else "")}
        if a.bench or saved.get("bench"):
            text = report.render_bench(shown, saved["results"], every, load_bench(), saved.get("mode", "re-rendered"), changes=changes, rounds_path=ROOT / "evals" / "rounds.yaml", corrections=saved.get("corrections"), notes=history_notes.lines(saved, every))
        else:
            text = report.render(shown, saved["results"], every, saved.get("mode", "re-rendered"), changes=changes, rounds_path=ROOT / "evals" / "rounds.yaml")
            text += report.not_run_note(every)
        (ROOT / "evals" / "report.md").write_text(text + "\n")
        print(text)
        return 0
    if a.heldout and not any(HELDOUT.glob("*.yaml")):
        print("The held-out sheets are written apart from the cases the builders see and are committed after the last agent change is merged; none are in this checkout. Their results are in evals/report_heldout.md when committed.", file=sys.stderr)
        return 2
    cases = load_cases(a.only, include_unbuilt=a.all or a.self_check, directory=HELDOUT if a.heldout else None)
    use_bench = a.bench or not (a.only or a.category or a.heldout or a.self_check or a.all or a.full or a.merge)
    if use_bench:
        keep = {i for ids in report.bench_ids(load_bench()).values() for i in ids}
        cases = {i: c for i, c in cases.items() if i in keep}
    if a.category:
        cases = {i: c for i, c in cases.items() if c["category"] == a.category}
    if not cases:
        print(f"no case {a.only!r}", file=sys.stderr)
        return 2
    agent_runner.JUDGE["on"] = not (a.no_judge or a.no_model or a.self_check)
    agent_runner.BUDGET["limit"] = a.budget if a.budget is not None else config.default_budget()
    if a.heldout:
        cfg_sheets = config._tree_hash(list(HELDOUT.glob("*.yaml")))
    cfg = config.snapshot(None if a.no_model or a.self_check else a.model, a.trials)
    if a.heldout:
        cfg["sheets_hash"] = cfg_sheets  # the held-out sheets, not the cases

    if a.self_check:
        graded = selfcheck.run(cases, ROOT / "data")
        results = {i: {"status": "PASS" if graders.case_passed(d) else "FAIL", "dims": d,
                       "detail": "; ".join(x["detail"] for x in d if not x["passed"])} for i, d in graded.items()}
        mode = "answer sheets vs oracle"
        left = selfcheck.unchecked(cases, ROOT / "data")
        print("Not re-derived by the oracle's self-check (checked elsewhere or by hand): " + ("; ".join(f"{k}: {', '.join(v)}" for k, v in left.items()) or "none"))
    else:
        results = {i: {**run_case(c, a.no_model, a.db, a.trials), **({"loose": True} if c.get("check_strength") == "loose" else {})} for i, c in cases.items()}
        mode = "no-model" if a.no_model else f"{a.trials} trials"
        if not a.only:
            results["_baselines"] = baselines.run(cases)

    ch = ROOT / "evals" / "changes.yaml"
    changes = (yaml.safe_load(ch.read_text()) or {}) if ch.exists() else {}
    if a.merge:  # keep the saved run, replace only the cases just run, and record that in the report itself
        saved = json.loads((ROOT / "evals" / "report.json").read_text())
        refreshed = saved.get("refreshed", {})
        refreshed.update({i: cfg["git_sha"] for i in results})
        results, cases, cfg = {**saved["results"], **results}, load_cases(), saved["config"]  # cfg stays the saved run's, undecorated
        mode = saved.get("mode", mode)
        a.refreshed = refreshed
    shown = ({**cfg, "git_sha": f"{cfg['git_sha']}, refreshed: " + ", ".join(f"{i} at {g}" for i, g in a.refreshed.items())}
             if getattr(a, "refreshed", None) else cfg)
    if a.gate and not a.write:
        text = report.gate_summary(results, load_cases(include_unbuilt=True), load_bench())   # the gate prints a summary and its verdict, not the whole report
    elif use_bench and not a.self_check:
        text = report.render_bench(shown, results, cases, load_bench(), mode, changes=changes, rounds_path=ROOT / "evals" / "rounds.yaml", calibration=not a.stem, notes=history_notes.lines({"config": cfg, "corrections": []}, load_cases()))
    else:
        text = report.render(shown, results, cases, mode, changes=changes, rounds_path=ROOT / "evals" / "rounds.yaml", calibration=not (a.stem or a.heldout))
        text += report.not_run_note(load_cases(include_unbuilt=True)) if not a.heldout else ""
    print(text)
    if a.write:
        stem = a.stem or ("report_heldout" if a.heldout else "report")
        (ROOT / "evals" / f"{stem}.md").write_text(text + "\n")
        (ROOT / "evals" / f"{stem}.json").write_text(json.dumps({"config": cfg, "mode": mode, "results": results, "refreshed": getattr(a, "refreshed", {}), **({"bench": True} if use_bench and not a.self_check else {})}, indent=2, default=str))
    if a.write and not a.stem and not a.heldout and use_bench and not a.self_check:
        from . import report_html
        report_html.main([])   # the one-screen page, from the files just written
    regressed = regressions(results) if a.gate else []
    if a.gate:
        saved_report = json.loads((ROOT / "evals" / "report.json").read_text())
        for note in gate_notes(results, saved_report["results"], saved_report.get("config", {}).get("git_sha", "")):
            print("\n" + note)
        print("\nHistory, the rounds and the live results: evals/report.md and evals/report.html.")
        print("\nGate: " + (f"{len(regressed)} regression(s) against the committed report: " + ", ".join(regressed) if regressed else "no case that passed in the committed report fails now"))
    if a.gate:  # a gate guards against going backwards: a case that fails for the first time is in the report, kept in, but is not a regression
        failed = bool(regressed) or (a.strict and any(r["status"] == "BLOCKED" for r in results.values()))
    else:
        failed = any(r["status"] == "FAIL" or (a.strict and r["status"] == "BLOCKED") for r in results.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
