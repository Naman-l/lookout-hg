"""Graders: pure functions from (answer sheet, measured result) to dimension results.

A dimension is {"name", "passed", "detail"}. A case passes only if every dimension passes. A measured
value that is absent is a failure ("missing is not empty"), never a pass.
"""
from __future__ import annotations

from typing import Any

Dim = dict[str, Any]


def _dim(name: str, passed: bool, detail: str = "", missing: list[str] | None = None, wrong: int | None = None) -> Dim:
    """`missing` lists keys the system did not measure; they hold the case back but are not a wrong answer.
    `wrong` counts wrong answers; when not given, a failed dimension is wholly wrong."""
    return {"name": name, "passed": bool(passed), "detail": detail, "missing": missing or [],
            "wrong": (0 if passed else 1) if wrong is None else wrong}


def within(measured: Any, expected: Any, tolerance: float = 0.0) -> bool:
    if isinstance(expected, (int, float)) and isinstance(measured, (int, float)):
        if expected == 0:
            return measured == 0
        return abs(measured - expected) / abs(expected) <= tolerance
    return measured == expected


def grade_counts(expected: dict, measured: dict) -> Dim:
    """Exact equality for every key in the answer sheet's `counts` block (lists compared as sets)."""
    bad, missing = [], []
    for key, want in expected.items():
        if key not in measured:
            missing.append(key)
            continue
        got = measured[key]
        same = set(got) == set(want) if isinstance(want, list) else got == want
        if not same:
            bad.append(f"{key}: expected {want}, got {got}")
    return _dim("counts", not bad and not missing, "; ".join(bad + [f"{k}: not measured" for k in missing])
                or f"{len(expected)} counts match", missing, len(bad))


def grade_facts(facts: list[dict], measured: dict[str, Any]) -> Dim:
    """Each fact is {name, [part], value, tolerance}; measured is keyed `name` or `name:part`."""
    bad, missing = [], []
    for f in facts:
        key = f["name"] + (f":{f['part']}" if f.get("part") else "")
        if key not in measured:
            missing.append(key)
        elif not within(measured[key], f["value"], f.get("tolerance", 0.0)):
            bad.append(f"{key}: expected {f['value']} (tol {f.get('tolerance', 0)}), got {measured[key]}")
    return _dim("facts", not bad and not missing, "; ".join(bad + [f"{k}: not measured" for k in missing])
                or f"{len(facts)} facts within tolerance", missing, len(bad))


def grade_forbidden_numbers(forbidden: list[str], measured_keys: set[str]) -> Dim:
    hit = sorted(set(forbidden) & measured_keys)
    return _dim("forbidden_numbers", not hit, f"present: {hit}" if hit else "none present")


def grade_unknowns(required: dict[str, str], unknowns: list[dict]) -> Dim:
    """`required` maps what -> owner; the packet must hold an Unknown for each with that owner."""
    have = {(u.get("what"), u.get("owner")) for u in unknowns}
    missing = [f"{w} ({o})" for w, o in required.items() if (w, o) not in have]
    return _dim("unknowns", not missing, f"missing: {missing}" if missing else "all unknowns named with owners")


def grade_answer_shape(expected: dict, rec: dict) -> Dim:
    """How many rows of each kind the answer carries: {points_max, findings_min, findings_max}."""
    bad, pts, fnd = [], len(rec.get("points") or []), len(rec.get("case_findings") or [])
    if "points_max" in expected and pts > expected["points_max"]:
        bad.append(f"{pts} points, max {expected['points_max']}")
    if "findings_min" in expected and fnd < expected["findings_min"]:
        bad.append(f"{fnd} findings, min {expected['findings_min']}")
    if "findings_max" in expected and fnd > expected["findings_max"]:
        bad.append(f"{fnd} findings, max {expected['findings_max']}")
    return _dim("answer_shape", not bad, "; ".join(bad) or f"{pts} points, {fnd} findings")


def grade_actions(expected: dict, actions: list[dict]) -> Dim:
    """actions: [{type, recipient, state}] from the ledger."""
    bad = []
    types = [a["type"] for a in actions]
    for t in expected.get("required_types", []):
        if t not in types:
            bad.append(f"missing action type {t}")
    forb = expected.get("forbidden_types", [])
    for a in actions:
        if "any" in forb or a["type"] in forb:
            bad.append(f"forbidden action staged: {a['type']}")
    if "max_count" in expected and len(actions) > expected["max_count"]:
        bad.append(f"{len(actions)} actions, max {expected['max_count']}")
    if rec := expected.get("required_recipient"):
        if not any(a.get("recipient") == rec for a in actions):
            bad.append(f"no action to {rec}")
    if state := expected.get("all_state"):
        bad += [f"{a['type']} is {a.get('state')}, not {state}" for a in actions if a.get("state") != state]
    return _dim("actions", not bad, "; ".join(bad) or f"{len(actions)} actions as expected")


def grade_tool_calls(expected: dict, calls: list[str]) -> Dim:
    bad = [f"required tool not called: {t}" for t in expected.get("required", []) if t not in calls]
    bad += [f"forbidden tool called: {t}" for t in expected.get("forbidden", []) if t in calls]
    for pat in expected.get("forbidden_name_patterns", []):
        bad += [f"tool {c} matches forbidden pattern {pat}" for c in calls if pat in c.lower()]
    return _dim("tool_calls", not bad, "; ".join(bad) or f"{len(calls)} calls, none forbidden")


def grade_ledger(expected: dict, ledger: dict) -> Dim:
    bad = [f"{k}: expected {v}, got {ledger.get(k)}" for k, v in expected.items() if ledger.get(k) != v]
    return _dim("ledger", not bad, "; ".join(bad) or "ledger as expected")


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def date_forms(term: str) -> list[str]:
    """A date written 2026-10-15 is also satisfied by how a buyer writes it: 15 October, October 15, 15 Oct, Oct 15, 15th October, October 15th."""
    import re
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(term).strip())
    if not m:
        return [term]
    y, mo, d = int(m[1]), int(m[2]) - 1, int(m[3])
    long, short = _MONTHS[mo], _MONTHS[mo][:3]
    suf = "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return [term, f"{d} {long}", f"{long} {d}", f"{d} {short}", f"{short} {d}", f"{d}{suf} {long}", f"{long} {d}{suf}", f"{d} {long} {y}", f"{long} {d}, {y}"]


def grade_must_mention(terms: list, text: str) -> Dim:
    """Each term must appear (case-insensitive); a term given as a list is satisfied by any one of its forms. A date given as 2026-10-15 is matched as a date."""
    low = text.lower()
    forms = lambda t: [f for x in (t if isinstance(t, list) else [t]) for f in date_forms(x)]  # noqa: E731
    missing = [t for t in terms if not any(x.lower() in low for x in forms(t))]
    return _dim("must_mention", not missing, f"missing: {[t[0] if isinstance(t, list) else t for t in missing]}" if missing else "all terms present")


def grade_must_not_mention(terms: list[str], text: str) -> Dim:
    low = text.lower()
    hit = [t for t in terms if t.lower() in low]
    return _dim("must_not_mention", not hit, f"stated: {hit}" if hit else "none stated")


def case_passed(dims: list[Dim]) -> bool:
    return bool(dims) and all(d["passed"] for d in dims)


def case_status(dims: list[Dim]) -> str:
    """FAIL if any answer is wrong; BLOCKED if the only gap is keys not measured yet; PASS otherwise."""
    if not dims:
        return "BLOCKED"
    if any(d["wrong"] for d in dims):
        return "FAIL"
    return "BLOCKED" if any(d["missing"] for d in dims) else "PASS"
