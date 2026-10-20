"""Render the report the README shows.

Controls first, then ordinary, then hard; every trial of every case; each failure in a sentence with the
dimension that failed; speed and cost; and the rounds (what we changed between runs and what it did).
Failures stay in. A result is {"status", "detail", "trials": [{"status", "detail"}], "speed": {...}}.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import stats, taxonomy

ORDER = ["control", "ordinary", "hard"]


def _trials(r: dict) -> list[dict]:
    return r.get("trials") or [{"status": r["status"], "detail": r.get("detail", "")}]


def _case_passed(r: dict) -> bool:
    """pass^k: every trial passed AND the case as a whole did (a determinism check compares two trials, so it can fail the case when each trial passed)."""
    return r.get("status", "PASS") == "PASS" and all(t["status"] == "PASS" for t in _trials(r))


def _case_held(r: dict) -> bool:
    """Every check that could be made held: no trial failed; a trial that is only 'not measured' (a fact no tool returns and the answer does not state) is not a failure."""
    return r.get("status", "PASS") in ("PASS", "BLOCKED") and all(t["status"] in ("PASS", "BLOCKED") for t in _trials(r))


def _case_only_failure(r: dict) -> bool:
    return r.get("status") == "FAIL" and all(t["status"] == "PASS" for t in _trials(r))


def short(detail: str, limit: int = 110) -> str:
    """One readable line for a long failure detail; the full text stays in report.json.
    Keys that were not measured, or have no number id yet, are counted, not listed."""
    parts = [p.strip() for p in (detail or "").split("; ") if p.strip()]
    unmeasured = [p for p in parts if "not measured" in p or "no number id agreed yet" in p or "not in the Recommendation" in p and False]
    named = [p for p in parts if p not in unmeasured]
    out = [p if len(p) <= limit else p[: limit - 1].rstrip() + "…" for p in named[:2]]
    if len(named) > 2:
        out.append(f"+{len(named) - 2} more")
    if unmeasured:
        out.append(f"{len(unmeasured)} checks not measured yet")
    return "; ".join(out)


def _cell(t: dict) -> str:
    return t["status"] if t["status"] == "PASS" else f"{t['status']}({short(t.get('detail', ''))})" if t.get("detail") else t["status"]


def category_line(cat: str, rows: list[tuple[str, dict]]) -> str:
    done = [(i, r) for i, r in rows if r["status"] not in ("BLOCKED", "SKIPPED")]
    passed = sum(_case_passed(r) for _, r in done)
    cells = " · ".join(f"{i}{' (loose numeric check)' if r.get('loose') else ''}{' (replayed)' if r.get('replayed') else ''} " + " ".join(_cell(t) for t in _trials(r))
                       + (f" FAIL({short(r.get('detail', ''))})" if _case_only_failure(r) else "") for i, r in rows)
    skipped = len(rows) - len(done)
    tail = f" ({skipped} not run)" if skipped else ""
    return f"{cat.upper():8} {passed}/{len(done)}{tail}  {cells}"


def _kind(c: dict) -> str:
    """What a control tests: `code` (a stop the application enforces, whoever or whatever asks) or `model` (what the agent itself chose to do)."""
    return c.get("tests") or ("model" if c.get("kind") == "agent" else "code")


def _words_only(t: dict) -> bool:
    """A stored trial whose only failure is a missing expected word (before the grade was split): the stop held, the words were not said."""
    parts = [p for p in (t.get("detail") or "").split("; ") if p.strip()]
    return t["status"] != "PASS" and bool(parts) and all(p.startswith("must_mention") for p in parts)


def _behaviour_failed(t: dict) -> bool:
    return t["status"] != "PASS" and not _words_only(t)


def _words_missed(t: dict) -> bool:
    return t.get("said") is False or _words_only(t)


def _control_failures(r: dict) -> int:
    """Trials in which the stop failed: what the agent did. A missing word is not one (see _control_words)."""
    return sum(_behaviour_failed(t) for t in _trials(r)) + (1 if _case_only_failure(r) else 0)


def _control_words(r: dict) -> tuple[int, int]:
    """(trials in which the control said what its sheet asks in words, trials). Only a control that has words to say counts."""
    ts = _trials(r)
    return sum(not _words_missed(t) for t in ts), len(ts)


GROUPS = {"bad_action": "behaviour", "wrong_path": "behaviour", "no_finish": "behaviour", "escape": "behaviour", "determinism": "behaviour", "bad_output": "behaviour",
          "wrong_number": "facts", "unasked": "facts", "clock": "facts", "unverified": "facts", "wrong_claim": "facts",
          "omitted_term": "conditions", "wording_miss": "prose", "weak_prose": "prose"}
GROUP_LABEL = {"behaviour": "behaviour held", "facts": "numbers, owners and dates right", "conditions": "conditions the buyer needs stated", "prose": "prose met"}


def trial_groups(t: dict, phrasing=()) -> set[str]:
    """The kinds of check a trial failed: behaviour (what it did), facts (numbers, owners, dates), conditions (a term the buyer needs), prose (the words)."""
    return {GROUPS[m] for m in taxonomy.classify(t.get("detail", ""), set(phrasing)) if m in GROUPS}


def groups_line(r: dict, phrasing=()) -> str:
    """'behaviour held 2 of 2 · numbers, owners and dates right 1 of 2 · ...' over the case's own trials, each kind apart. Prose only counts trials it was judged in."""
    ts = _trials(r)
    n = len(ts)
    failed = [trial_groups(t, phrasing) for t in ts]
    parts = [f"{GROUP_LABEL[g]} {sum(g not in f for f in failed)} of {n}" for g in ("behaviour", "facts", "conditions")]
    judged = [i for i, t in enumerate(ts) if t.get("prose") in ("met", "failed")]
    if judged:
        parts.append(f"{GROUP_LABEL['prose']} {sum('prose' not in failed[i] for i in judged)} of {len(judged)}")
    return " · ".join(parts)


def controls_block(results: dict[str, dict], cases: dict[str, dict]) -> list[str]:
    """One row per control: what tests it (code or model), how many trials ran, how many failed. Never averaged with another control."""
    rows = [(i, c) for i, c in cases.items() if c["category"] == "control" and i in results]
    if not rows:
        return []
    out = ["CONTROLS (guardrails graded on behaviour; one row each, never averaged; the words a control says are a separate grade)"]
    for i, c in rows:
        r = results[i]
        if r["status"] in ("BLOCKED", "SKIPPED"):
            out.append(f"  {i:34} {_kind(c):5} not run ({r['status'].lower()})")
            continue
        ts = _trials(r)
        ran = "replayed, deterministic" if r.get("replayed") and len(ts) > 1 else "replayed" if r.get("replayed") else f"{len(ts)} trial{'s' if len(ts) != 1 else ''}"
        bad = _control_failures(r)
        why = f" · {short(next((t.get('detail') for t in ts if _behaviour_failed(t) and t.get('detail')), r.get('detail', '')))}" if bad else ""
        said, n_said = _control_words(r)
        words = f" · said it in words {said} of {n_said}" if any(t.get("said") is not None or _words_only(t) for t in ts) else ""
        out.append(f"  {i:34} {_kind(c):5} {ran:24} {'guardrail FAILED ' + str(bad) if bad else 'guardrail held'}{why}{words}")
    return out


def controls_headline(results: dict[str, dict], cases: dict[str, dict]) -> str:
    """The sentence a reader needs first: did a stop fail in code, and how many model-control trials failed."""
    code_n = code_bad = model_n = model_bad = 0
    code_failed, model_parts = [], []
    for i, c in cases.items():
        r = results.get(i)
        if c["category"] != "control" or not r or r["status"] in ("BLOCKED", "SKIPPED"):
            continue
        bad = _control_failures(r)
        if _kind(c) == "code":
            code_n += 1
            code_bad += bool(bad)
            if bad:
                code_failed.append(i)
        else:
            n = len(_trials(r))
            model_n += n
            model_bad += bad
            if bad:
                model_parts.append(f"{i} {bad}/{n}")
    said = tot = 0
    for i, c in cases.items():
        r = results.get(i)
        if c["category"] == "control" and r and r["status"] not in ("BLOCKED", "SKIPPED") and any(t.get("said") is not None or _words_only(t) for t in _trials(r)):
            a, b = _control_words(r)
            said, tot = said + a, tot + b
    parts = []
    if code_n:
        parts.append(("No guardrail failed in code" if not code_bad else f"{code_bad} guardrail(s) failed in code: " + ", ".join(code_failed)) + f" ({code_n} run)")
    if model_n:
        parts.append(f"model controls: guardrail held in {model_n - model_bad} of {model_n} trials" + (f" (failed: {', '.join(model_parts)})" if model_parts else ""))
    if tot:
        parts.append(f"said it in words in {said} of {tot} trials")
    return "; ".join(parts) or "no control ran"


def reliability_lines(results: dict[str, dict], cases: dict[str, dict]) -> list[str]:
    """What the trials of the live (model) cases support, per category, in words that do not claim more than the counts show."""
    out = []
    for cat in ORDER:
        if cat == "control":
            continue  # controls are one row each, never pooled
        n = f = 0
        for i, c in cases.items():
            r = results.get(i)
            if c["category"] != cat or not r or r["status"] in ("BLOCKED", "SKIPPED") or not r.get("speed"):
                continue  # only runs that used the model: detector and code cases are exact, not sampled
            ts = _trials(r)
            n += len(ts)
            f += sum(t["status"] != "PASS" for t in ts)
        if n:
            out.append(f"{cat.upper():8} {stats.claim(n - f, n)}")
    return out


def failures(results: dict[str, dict], changes: dict[str, str] | None = None) -> list[str]:
    """One sentence per failed case: what failed, and what we would change (from `changes`, written by hand)."""
    out = []
    for i, r in results.items():
        bad = [t for t in _trials(r) if t["status"] == "FAIL"]
        if not bad and _case_only_failure(r):  # each trial passed; the case failed on a check across trials (determinism)
            line = f"- {i}: {short(r.get('detail')) or 'failed'} (case-level, across {len(_trials(r))} trials)."
            if changes and i in changes:
                line += f" To change: {changes[i]}"
            out.append(line)
        if bad:
            staged = sorted({x for t in bad for x in t.get("staged", [])})
            line = f"- {i}: {short(bad[0].get('detail')) or 'failed'} ({len(bad)} of {len(_trials(r))} trials)." + (f" Staged in the failing trials: {', '.join(staged)}." if staged else "")
            if changes and i in changes:
                line += f" To change: {changes[i]}"
            out.append(line)
    return out


def speed_cost_line(results: dict[str, dict]) -> str:
    sp = [r["speed"] for r in results.values() if r.get("speed")]
    if not sp:
        return "speed and cost: not measured in this run"
    first = [s["first_step_ms"] for s in sp if s.get("first_step_ms") is not None]
    wall = [s["wall_ms"] for s in sp if s.get("wall_ms") is not None]
    cost = sum(s.get("cost_usd") or 0 for s in sp)
    runs = sum(r.get("runs", len(r.get("trials") or [1])) for r in results.values() if r.get("speed"))
    avg = lambda xs: f"{sum(xs) / len(xs) / 1000:.1f} s" if xs else "not measured"  # noqa: E731
    return f"first step avg {avg(first)} · total avg {avg(wall)} · cost {cost:.2f} USD over {runs} live runs"


def rounds_table(path: Path) -> str:
    if not path.exists():
        return ""
    rounds = yaml.safe_load(path.read_text()) or []
    if not rounds:
        return ""
    rows = ["| round | passed | what changed |", "|---|---|---|"]
    rows += [f"| {r['round']} | {r['passed']} | {r['changed']} |" for r in rounds]
    return "\n".join(rows)


def glance(results: dict[str, dict], cases: dict[str, dict]) -> list[str]:
    """The whole run in a handful of lines: pass counts with intervals, what the live trials support, the kinds of failure, speed and cost."""
    score = []
    for cat in ORDER:
        if cat == "control":
            continue  # reported by controls_headline, not as a rate
        rows = [(i, results[i]) for i, c in cases.items() if c["category"] == cat and i in results]
        done = [r for _, r in rows if r["status"] not in ("BLOCKED", "SKIPPED")]
        if done:
            passed = sum(_case_passed(r) for r in done)
            lo, hi = stats.wilson(passed, len(done))
            score.append(f"{cat} {passed}/{len(done)} [{lo:.2f}–{hi:.2f}]")
    modes = taxonomy.tally(results, cases)
    kinds = ", ".join(f"{m} {n}" for m, n in sorted(modes.items(), key=lambda kv: -kv[1])) or "none"
    lines = [controls_headline(results, cases), "At a glance: " + " · ".join(score), "Failure modes (failed trials): " + kinds, speed_cost_line(results)]
    oc = [(i, r["overcaution"]) for i, r in results.items() if r.get("overcaution") and r["overcaution"]["runs"]]
    if oc:
        runs, extra = sum(o["runs"] for _, o in oc), sum(o["extra"] for _, o in oc)
        top = ", ".join(f"{i} {o['extra']}" for i, o in sorted(oc, key=lambda kv: -kv[1]["extra"]) if o["extra"])[:160]
        lines.append(f"Questions beyond what the sheets require (an upper bound on over-caution): {extra} across {runs} runs" + (f" ({top})" if top else ""))
    lines += [f"Reliability, {x}" for x in reliability_lines(results, cases)]
    return lines


def calibration_lines(path: Path) -> list[str]:
    """How far the product's Reviewer can be trusted, from packets a labeller read blind (evals/judge/calibration.json)."""
    import json
    if not path.exists():
        return []
    c = json.loads(path.read_text())
    f = lambda t: f"{t[0]:.2f} [{t[1][0]:.2f}–{t[1][1]:.2f}]"  # noqa: E731
    weak = sorted(c["agreement_by_check"].items(), key=lambda kv: kv[1]["rate"])[:3]
    return [f"Reviewer vs the labeller ({c['labeller']}), {c['strict']['labels']} labels:",
            f"- scoring a check 'met' only at 2: agreement {f(c['strict']['agreement'])}, kappa {c['strict']['kappa']}; rejects what the labeller rejects {f(c['strict']['reviewer_rejects_when_human_no'])}",
            f"- scoring it met at 1 or 2: agreement {f(c['lenient']['agreement'])}, kappa {c['lenient']['kappa']}; rejects what the labeller rejects {f(c['lenient']['reviewer_rejects_when_human_no'])}",
            f"- of {c['damaged_check_caught']['reviewer']['of']} checks broken on purpose, the Reviewer flagged {c['damaged_check_caught']['reviewer']['caught']} (95% {c['damaged_check_caught']['reviewer']['wilson'][0]:.2f}–{c['damaged_check_caught']['reviewer']['wilson'][1]:.2f})",
            "- weakest checks: " + "; ".join(f"{n} {v['agree']}/{v['of']}" for n, v in weak),
            "- reading: the 0-2 scale did not separate met from not met (a 1 is used for both); use it to flag, not to pass"] + _binary_lines(path.parent / "calibration_binary.json")


def _binary_lines(path: Path) -> list[str]:
    import json
    if not path.exists():
        return []
    c = json.loads(path.read_text())
    b = c["binary"]
    f = lambda t: f"{t[0]:.2f} [{t[1][0]:.2f}–{t[1][1]:.2f}]"  # noqa: E731
    weak = sorted(c["agreement_by_check"].items(), key=lambda kv: kv[1]["rate"])[:3]
    return [f"Today's binary Reviewer (pass or fail per check, re-graded on the same packets, {b['labels']} labels): agreement {f(b['agreement'])}, kappa {b['kappa']}; passes what the labeller passes {f(b['reviewer_meets_when_human_yes'])}; rejects what the labeller rejects {f(b['reviewer_rejects_when_human_no'])}; "
            f"flagged {c['damaged_check_caught']['reviewer']['caught']} of {c['damaged_check_caught']['reviewer']['of']} checks broken on purpose; weakest: " + "; ".join(f"{n} {v['agree']}/{v['of']}" for n, v in weak)]


def not_run_note(all_cases: dict[str, dict]) -> str:
    stale = {i: c["stale"] for i, c in all_cases.items() if c.get("stale")}
    if not stale:
        return ""
    return "\n\nSheets kept but not run, and why (python -m evals.run --all runs them):\n" + "\n".join(f"- {i}: {why}" for i, why in sorted(stale.items()))


def render(cfg: dict, results: dict[str, dict], cases: dict[str, dict], mode: str,
           changes: dict[str, str] | None = None, rounds_path: Path | None = None, calibration: bool = True) -> str:
    cases = {i: c for i, c in cases.items() if i in results}  # a sheet that was not run (a parked one) is not a case in this report
    head = (f"Lookout evals · {cfg['date']} · model {cfg['model']} · prompt {cfg['prompt_hash']} · "
            f"data {cfg['data_hash']} · sheets {cfg.get('sheets_hash', 'not recorded')} · sdk {cfg['sdk']} · git {cfg['git_sha']} · {mode}")
    core = {i: c for i, c in cases.items() if c.get("core")}
    ext = {i: c for i, c in cases.items() if not c.get("core")}
    lines = [head, ""]
    if core:
        lines += [f"THE ANSWER SHEET: {len(core)} cases, written from the raw files before any agent ran, each with its source and reason", *glance({i: r for i, r in results.items() if i in core}, core), ""]
        lines += controls_block(results, core)
        for cat in ORDER[1:]:
            rows = [(i, results[i]) for i, c in core.items() if c["category"] == cat and i in results]
            if rows:
                lines.append(category_line(cat, rows))
        lines += [""]
    heading = f"EXTENDED SUITE: {len(ext)} cases added after (stages, readiness, the steward, the Inbox analyst, model-level injection), same rules" if core else f"SHEETS RUN: {len(ext)} cases"
    lines += [heading, *glance({i: r for i, r in results.items() if i in ext}, ext), ""]
    lines += controls_block(results, ext)
    for cat in ORDER[1:]:
        rows = [(i, results[i]) for i, c in ext.items() if c["category"] == cat and i in results]
        if rows:
            lines.append(category_line(cat, rows))
    lines += ["", "Pipeline controls vs model controls: control-fraud and control-injection run on trust items that code answers before any model reads them, so their three trials test the code's stop, not the model. The model-level injection controls (injected text in front of the Inbox analyst and the clerk) are control-injection-model-*."]
    if results.get("_baselines"):
        b = results["_baselines"]
        lines += ["", f"Baselines (a do-nothing agent and an always-refuse agent, same graders): {b['status']}. {b['detail']}."]
    cal = calibration_lines(Path(__file__).parent / "judge" / "calibration.json") if calibration else []
    if cal:
        lines += ["", *cal]
    fails = failures(results, changes)
    if fails:
        lines += ["", "Failures, kept in:"] + fails
    rt = rounds_table(rounds_path) if rounds_path else ""
    if rt:
        lines += ["", rt]
    return "\n".join(lines)



def unmeasured_facts(results: dict[str, dict], cases: dict[str, dict]) -> dict[str, int]:
    """Per case, how many facts its sheet expects that no tool gives a number id: checks that could not be made. Counted once per case (the first trial that says so)."""
    out = {}
    for i in cases:
        r = results.get(i) or {}
        for t in report_trials(r):
            n = (t.get("detail") or "").count("no number id agreed yet")
            if n:
                out[i] = n
                break
    return out


def report_trials(r: dict) -> list[dict]:
    return _trials(r)


def agent_headline(results: dict[str, dict], cases: dict[str, dict]) -> str:
    """Passed, failed and not measured, apart: a fact nobody could check is not a wrong fact."""
    passed = sum(_case_passed(results[i]) for i in cases if i in results)
    failed = sum(1 for i in cases if i in results and not _case_passed(results[i]))
    um = unmeasured_facts(results, cases)
    tail = f"; facts not measured (no tool gives them an id yet): {sum(um.values())} across {len(um)} cases ({', '.join(f'{i} {n}' for i, n in um.items())})" if um else "; no fact is unmeasured"
    held_only = sum(1 for i in cases if i in results and not _case_passed(results[i]) and _case_held(results[i]))
    failed = sum(1 for i in cases if i in results and not _case_held(results[i]))
    return (f"Agent cases: {passed} passed every check in every trial, {held_only} more held every check that could be made, {failed} failed" + tail)


def facts_headline(results: dict[str, dict], cases: dict[str, dict]) -> str:
    """The commercial facts the sheets expect, right / wrong / not measured, over every trial, apart from behaviour, conditions and prose.
    By id is the strong check; 'found in the answer' (the figure is in the answer's own words) is weaker and counted as right but named."""
    t = {"right": 0, "wrong": 0, "not measured": 0}
    weak = 0
    seen = False
    for i in cases:
        for tr in _trials(results.get(i) or {}):
            for row in tr.get("facts") or []:
                seen = True
                t[row["status"]] += 1
                weak += row["status"] == "right" and row.get("via") == "found in the answer"
    if not seen:
        return "Commercial facts: not recorded in this run (the fact-by-fact record starts with the round that added it)"
    return (f"Commercial facts the sheets expect, over all trials: {t['right']} right ({weak} of them only found in the answer's words, a weaker check), "
            f"{t['wrong']} wrong, {t['not measured']} not measured (no tool returns them as numbers and the answer does not state them)")


def passing_summary(results: dict[str, dict], cases: dict[str, dict], spec: dict) -> list[str]:
    """What passes, said first and plainly: the guardrails that held, the system checks, and for the agent cases each kind of check that held in every trial."""
    ids = bench_ids(spec)
    ctl = {i: cases[i] for i in ids["controls"] if i in results and results[i]["status"] not in ("BLOCKED", "SKIPPED")}
    held = [i for i in ctl if _control_failures(results[i]) == 0]
    out = [f"Guardrails held in every trial: {len(held)} of {len(ctl)} controls ({', '.join(held)})"] if ctl else []
    sysc = [i for i in ids["system"] if i in results]
    if sysc:
        out.append(f"System checks passing: {sum(results[i]['status'] == 'PASS' for i in sysc)} of {len(sysc)}")
    ag = {i: cases[i] for i in ids["agent"] if i in results and results[i]["status"] not in ("BLOCKED", "SKIPPED")}
    for g in ("behaviour", "facts", "conditions", "prose"):
        ok = []
        for i, c in ag.items():
            ts = _trials(results[i])
            if g == "prose":
                ts = [t for t in ts if t.get("prose") in ("met", "failed")]
                if not ts:
                    continue
            if all(g not in trial_groups(t, c.get("expected", {}).get("phrasing_terms") or []) for t in ts):
                ok.append(i)
        out.append(f"Agent cases where {GROUP_LABEL[g]} in every trial: {len(ok)} of {len(ag)}" + (f" ({', '.join(ok)})" if ok else ""))
    full = [i for i in ag if _case_passed(results[i])]
    out.append(f"Agent cases that passed every check in every trial: {len(full)} of {len(ag)}" + (f" ({', '.join(full)})" if full else ""))
    return out


def change_line(text: str, limit: int = 170) -> str:
    """One line of 'what we would change' from a longer note: the part after 'Agent:' (or 'Agent/DOMAIN:'), else the first sentence."""
    m = re.search(r"Agent[/A-Za-z]*:\s*(.+?)(?:\.\s|$)", text or "")
    one = (m.group(1) if m else (text or "").split(". ")[0]).strip()
    return one[:limit] + ("…" if len(one) > limit else "")


def gate_summary(results: dict[str, dict], cases: dict[str, dict], spec: dict) -> str:
    """What `make eval-gate` prints: one number for the answer sheet (the one in the README), what ran without a key and what needs the model, the code controls, the replays.
    The history and the live results are in evals/report.md."""
    ids = bench_ids(spec)
    sheet = ids["controls"] + ids["agent"]
    ran = [i for i in sheet if i in results and results[i]["status"] not in ("SKIPPED", "BLOCKED")]
    need = [i for i in sheet if i not in ran]
    code_ctl = [i for i in ids["controls"] if i in ran and _kind(cases[i]) == "code"]
    code_bad = [i for i in code_ctl if _control_failures(results[i])]
    replayed = [i for i in ids["agent"] if i in ran]
    rep_ok = [i for i in replayed if _case_passed(results[i])]
    sysc = [i for i in ids["system"] if i in results]
    lines = ["make eval-gate: no key. It runs the code controls for real and replays the shipped recordings through the graders; it tests the graders and the code, not the agent.", "",
             f"The answer sheet: {len(sheet)} cases ({len(ids['controls'])} controls, {len(ids['agent'])} agent cases). {len(ran)} ran without a key, {len(need)} need the model" + (f" ({', '.join(need)})" if need else "") + ".",
             f"  Code guardrails: {len(code_ctl) - len(code_bad)} of {len(code_ctl)} held" + (f" (failed: {', '.join(code_bad)})" if code_bad else ""),
             f"  Replayed agent cases: {len(rep_ok)} of {len(replayed)} pass on the shipped recordings" + (f" (fail: {', '.join(i for i in replayed if i not in rep_ok)})" if len(rep_ok) != len(replayed) else ""),
             f"  System checks: {sum(results[i]['status'] == 'PASS' for i in sysc)} of {len(sysc)} pass",
             "  The recordings are from before the last agent changes: a replayed PASS can differ from the live result until they are re-made; the lines below list where the latest live run disagrees."]
    return "\n".join(lines)


def quality_summary(results: dict[str, dict], cases: dict[str, dict], held_path: Path | None = None) -> list[str]:
    """The top of the report in six lines a founder can read: what the agent did on the bench, what it did on sheets written apart, what held and what did not, what it cost."""
    n = len(cases)
    full = sum(1 for i in cases if i in results and _case_passed(results[i]))
    held_ok = sum(1 for i in cases if i in results and _case_held(results[i]))
    beh = sum(1 for i in cases if i in results and groups_ok(results[i], "behaviour", cases[i]))
    pro = sum(1 for i in cases if i in results and groups_ok(results[i], "prose", cases[i]))
    out = [f"QUALITY SUMMARY (this round, the bench's {n} agent cases; every count is over every trial of the case)",
           f"  Passed every check in every trial: {full} of {n}; every check that could be made held: {held_ok} of {n}.",
           f"  What the agent DID (right contact, nothing wrongly staged, no forbidden step) held in {beh} of {n}; what it SAID (prose a buyer can use) held in {pro} of {n}. A gap between the two means the agent does the right thing but does not carry every figure, date and condition into the answer."]
    if held_path and held_path.exists():
        import json
        hr = json.loads(held_path.read_text())
        hres = {k: v for k, v in hr["results"].items() if not k.startswith("_") and v.get("status") not in ("BLOCKED", "SKIPPED")}
        hfull = sum(1 for v in hres.values() if _case_passed(v))
        out.append(f"  Beside it, the held-out sheets (written apart from the cases the builders saw; agent at git {hr['config']['git_sha']}): {hfull} of {len(hres)} passed every trial. A bench that rose while this stayed flat would mean fitting to the bench.")
    sp = [r["speed"] for r in results.values() if r.get("speed")]
    if sp:
        cost = sum(s.get("cost_usd") or 0 for s in sp) + sum(s.get("judge_cost_usd") or 0 for s in sp)
        wall = sum(s.get("wall_ms") or 0 for s in sp) / 1000
        out.append(f"  Cost and time of this round (the agent cases, agent plus judge; controls and the held-out run are in the ledger): {cost:.2f} USD, {wall / 60:.0f} minutes of agent time. The per-round cost is in the rounds table below and in evals/spend.yaml.")
    out.append("  Why each case failed, in one line each: the 'Failures, kept in' section below (what the agent did, why, the general fix).")
    return out


def groups_ok(r: dict, group: str, case: dict) -> bool:
    ts = _trials(r)
    return bool(ts) and all(group not in trial_groups(t, case.get("expected", {}).get("phrasing_terms") or []) for t in ts)


def bench_ids(spec: dict) -> dict[str, list[str]]:
    return {"controls": [i for ids in spec["controls"].values() for i in ids], "agent": list(spec["agent"]), "system": list(spec["system_checks"]), "live": list(spec.get("live_findings") or [])}


def render_bench(cfg: dict, results: dict[str, dict], cases: dict[str, dict], spec: dict, mode: str,
                 changes: dict[str, str] | None = None, rounds_path: Path | None = None, calibration: bool = True, corrections: list[dict] | None = None,
                 notes: list[str] | None = None) -> str:
    """The one screen: controls (hard stops), the agent's cases (ordinary and hard apart), the system checks, and what is not in the bench."""
    ids = bench_ids(spec)
    n_bench = len(ids["controls"]) + len(ids["agent"])
    pick = lambda keys: {i: cases[i] for i in keys if i in cases and i in results}  # noqa: E731
    head = (f"Lookout evals · {cfg['date']} · model {cfg['model']} · prompt {cfg['prompt_hash']} · "
            f"data {cfg['data_hash']} · sheets {cfg.get('sheets_hash', 'not recorded')} · sdk {cfg['sdk']} · git {cfg['git_sha']} · {mode}")
    ctl, ag, sysc = pick(ids["controls"]), pick(ids["agent"]), pick(ids["system"])
    lines = [head, "", *quality_summary({i: results[i] for i in ids["agent"] if i in results}, {i: cases[i] for i in ids["agent"] if i in cases}, Path(__file__).parent / "report_heldout.json"), "", f"THE ANSWER SHEET: {n_bench} cases ({len(ids['controls'])} controls, {len(ids['agent'])} agent cases), written from the raw files; the sheets and what each tests are in evals/bench.yaml", ""]
    lines += ["WHAT PASSES", *[f"  {x}" for x in passing_summary(results, cases, spec)], ""]
    lines += [controls_headline(results, ctl), "", *controls_block(results, ctl), ""]
    lines += ["THE AGENT'S CASES (ordinary and hard apart)", agent_headline(results, ag), facts_headline(results, ag), *glance({i: results[i] for i in ag}, ag)[1:]]
    for cat in ORDER[1:]:
        rows = [(i, results[i]) for i, c in ag.items() if c["category"] == cat]
        if rows:
            lines.append(category_line(cat, rows))
    if ag:
        lines += ["", "AGENT CASES BY KIND OF CHECK (each over the case's own trials; live single runs vary: a case that fails in one run may pass in the next, and the reverse)"]
        lines += [f"  {i:24} passed {sum(t['status'] == 'PASS' for t in _trials(results[i]))} of {len(_trials(results[i]))} trials · "
                  + groups_line(results[i], c.get("expected", {}).get("phrasing_terms") or []) for i, c in ag.items()]
    live = {i: cases[i] for i in ids["live"] if i in cases and i in results}
    if live:
        lines += ["", "LIVE FINDINGS (not part of the answer sheet: written after the feedback lane found these failures in live use; graded on behaviour; run once per round, judge off)"]
        lines += [f"  {i:24} " + (f"not run ({results[i]['status'].lower()}): {short(results[i].get('detail', ''))}" if results[i]["status"] in ("BLOCKED", "SKIPPED") else
                  f"passed {sum(t['status'] == 'PASS' for t in _trials(results[i]))} of {len(_trials(results[i]))} trials · " + (short(results[i].get('detail', '')) or 'every check held')) for i in live]
    if sysc:
        ok = sum(results[i]["status"] == "PASS" for i in sysc)
        lines += ["", f"SYSTEM CHECKS (code against the built records; tests, not agent cases): {ok} of {len(sysc)} pass", "  " + " · ".join(f"{i} {results[i]['status']}" for i in sysc)]
    lines += ["", "Not in the answer sheet: the other sheets (python -m evals.run --full), the held-out set (evals/report_heldout.md), and `make eval-gate`, which replays shipped recordings and so tests the graders and the code, not the agent."]
    if results.get("_baselines"):
        b = results["_baselines"]
        lines += ["", f"Baselines (a do-nothing agent and an always-refuse agent, same graders): {b['status']}. {b['detail']}."]
    cal = calibration_lines(Path(__file__).parent / "judge" / "calibration.json") if calibration else []
    if cal:
        lines += ["", *cal]
    if notes:
        lines += ["", "HISTORY AND NOTES (moved here from the README)", *[f"- {x}" for x in notes]]
    for c in corrections or []:
        lines += ["", f"Correction, {c['date']} ({c['what']}): {c['note']}. {c['trials_re_judged']} trials re-judged; {c['trials_whose_status_changed']} changed status."]
    fails = failures({i: r for i, r in results.items() if i in ctl or i in ag}, changes)
    if fails:
        lines += ["", "Failures, kept in:"] + fails
    rt = rounds_table(rounds_path) if rounds_path else ""
    if rt:
        lines += ["", rt]
    return "\n".join(lines)
