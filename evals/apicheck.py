"""No-model checks over the app's own routes: GET a path, pick a row, compare fields to the answer sheet.

A check is {id, get, params?, rows?, pick?, expect}. `rows` names the list inside a dict response (e.g.
`columns`); `pick` selects one row by dotted-path equality; `expect` maps a dotted path to a value or to
{approx, tol}. Money objects are compared by their `amount`. A route that is not mounted is BLOCKED; a row
or field that is absent where the sheet expects it is a wrong answer.
"""
from __future__ import annotations

from typing import Any

import httpx

from . import graders

MISSING = object()


def dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return MISSING
    return obj


def _num(v: Any) -> Any:
    if isinstance(v, dict) and "amount" in v:
        v = v["amount"]
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def _match(got: Any, want: Any) -> bool:
    if isinstance(want, dict) and "all_true" in want:  # every item of a list has this field true
        return isinstance(got, list) and bool(got) and all(isinstance(i, dict) and i.get(want["all_true"]) is True for i in got)
    if isinstance(want, dict) and "contains" in want:  # a list that holds at least these
        return isinstance(got, list) and set(want["contains"]) <= set(got)
    if isinstance(want, dict) and "in" in want:
        return got in want["in"]
    got = _num(got)
    if isinstance(want, dict) and "approx" in want:
        return isinstance(got, (int, float)) and graders.within(got, want["approx"], want.get("tol", 0.0))
    if isinstance(want, list):
        return isinstance(got, list) and sorted(map(str, got)) == sorted(map(str, want))
    return got == want


def evaluate(check: dict, body: Any) -> dict:
    """One dimension for one check, from a response body."""
    rows = body
    if check.get("rows"):
        rows = dig(body, check["rows"])
    if check.get("pick"):
        hits = [r for r in (rows if isinstance(rows, list) else []) if all(_match(dig(r, k), v) for k, v in check["pick"].items())]
        if not hits:
            return graders._dim(check["id"], False, f"no row where {check['pick']}", [], 1)
        rows = hits[0]
    bad, missing = [], []
    for path, want in check["expect"].items():
        got = dig(rows, path)
        if got is MISSING:
            missing.append(path)
        elif not _match(got, want):
            bad.append(f"{path}: expected {want}, got {_num(got)}")
    return graders._dim(check["id"], not bad and not missing, "; ".join(bad + [f"{p}: not in the response" for p in missing]) or "as expected", [], len(bad) + len(missing))


def run(base: str, checks: list[dict]) -> list[dict]:
    dims = []
    with httpx.Client(base_url=base, timeout=30) as http:
        for c in checks:
            r = http.get(c["get"], params=c.get("params"))
            if r.status_code == 404 and "detail" in (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}) \
                    and r.json()["detail"] == "Not Found":
                dims.append(graders._dim(c["id"], False, f"{c['get']} is not mounted", [c["get"]], 0))
            elif r.status_code != 200:
                dims.append(graders._dim(c["id"], False, f"{c['get']} returned {r.status_code}", [], 1))
            else:
                dims.append(evaluate(c, r.json()))
    return dims
