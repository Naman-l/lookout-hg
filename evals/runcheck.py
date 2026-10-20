"""Determinism and speed, read from a run's events (the run_events rows, whole or mirrored by the Watcher).

Determinism: two runs of the same workflow on the same data must agree on the (number id, value) set, the
tool-call (name, args) multiset and the staged (type, recipient) set. Prose is ignored.
Speed: first streamed step and total wall time, from `run.finished` (server) or a client-side stamp.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter

TARGETS_MS = {"first_step": 2000, "fire_total": 30000, "page_p95": 200}


def _body(e: dict) -> dict:
    return e.get("payload") or e.get("body") or {}


def _type(e: dict) -> str:
    return e.get("type") or e.get("kind") or ""


def signature(events: list[dict]) -> dict:
    numbers, calls, actions = set(), Counter(), set()
    for e in events:
        b, t = _body(e), _type(e)
        if t == "tool.result":
            numbers |= {(n["id"], n["value"]) for n in b.get("numbers", [])}
        elif t == "tool.called":
            calls[(b.get("name"), json.dumps(b.get("args"), sort_keys=True, default=str))] += 1
        elif t == "action.staged":
            actions.add((b.get("type"), b.get("recipient")))
    return {"numbers": numbers, "tool_calls": calls, "actions": actions}


def compare(a: list[dict], b: list[dict]) -> dict:
    """{identical, differences}: every difference named, so a failure says what moved."""
    sa, sb = signature(a), signature(b)
    diffs = []
    if sa["numbers"] != sb["numbers"]:
        diffs.append(f"numbers differ: only in run 1 {sorted(sa['numbers'] - sb['numbers'])}, "
                     f"only in run 2 {sorted(sb['numbers'] - sa['numbers'])}")
    if sa["tool_calls"] != sb["tool_calls"]:
        d1, d2 = sa["tool_calls"] - sb["tool_calls"], sb["tool_calls"] - sa["tool_calls"]
        diffs.append(f"tool calls differ: run 1 extra {dict(d1)}, run 2 extra {dict(d2)}")
    if sa["actions"] != sb["actions"]:
        diffs.append(f"staged actions differ: {sorted(sa['actions'] ^ sb['actions'])}")
    return {"identical": not diffs, "differences": diffs}


def speed(events: list[dict]) -> dict:
    fin = [e for e in events if _type(e) == "run.finished" and not e.get("parent_run_id")
           and not _body(e).get("parent_run_id")]
    if not fin:
        return {"first_step_ms": None, "wall_ms": None, "status": "no run.finished"}
    b = _body(fin[-1])
    return {"first_step_ms": b.get("first_step_ms"), "wall_ms": b.get("wall_ms"), "status": b.get("status"),
            "cost_usd": b.get("cost_usd"), "tool_calls": b.get("tool_calls"),
            "tokens_in": b.get("tokens_in"), "tokens_out": b.get("tokens_out"), "tokens_cache_read": b.get("tokens_cache_read")}


def speed_verdict(s: dict, workflow: str = "fire") -> list[str]:
    """Targets missed, as sentences (empty = all met). A missing measurement is a miss, not a pass."""
    out = []
    if s.get("first_step_ms") is None:
        out.append("first step not measured")
    elif s["first_step_ms"] >= TARGETS_MS["first_step"]:
        out.append(f"first step {s['first_step_ms']} ms (target < {TARGETS_MS['first_step']})")
    if workflow == "fire":
        if s.get("wall_ms") is None:
            out.append("total time not measured")
        elif s["wall_ms"] >= TARGETS_MS["fire_total"]:
            out.append(f"total {s['wall_ms']} ms (target < {TARGETS_MS['fire_total']})")
    return out


def page_latency(get, paths: list[str], n: int = 20) -> dict:
    """p50/p95 in ms over n requests per path; `get(path)` performs one request (httpx client or a stub)."""
    out = {}
    for p in paths:
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            get(p)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        out[p] = {"p50": round(statistics.median(times), 1), "p95": round(times[max(0, int(len(times) * .95) - 1)], 1)}
    return out


def compare_headline(rec_a: dict, actions_a: list, rec_b: dict, actions_b: list) -> dict:
    """Determinism as the product guarantees it: the numbers code marks `headline`, the staged (type,
    recipient) set and the recommended way through must be identical across two runs; other cited numbers and prose may vary."""
    heads = lambda r: {(n["id"], str(n["value"])) for n in r.get("numbers", []) if n.get("headline")}  # noqa: E731
    ha, hb, diffs = heads(rec_a), heads(rec_b), []
    if not ha:
        diffs.append("run 1 has no headline numbers to compare")
    if ha != hb:
        diffs.append(f"headline numbers differ: only in run 1 {sorted(ha - hb)}, only in run 2 {sorted(hb - ha)}")
    if set(actions_a) != set(actions_b):
        diffs.append(f"staged actions differ: {sorted(set(actions_a) ^ set(actions_b), key=str)}")
    pick = lambda r: (r.get("recommended") or {}).get("kind")  # noqa: E731  the way through Lookout recommends: the same data must pick the same one
    if pick(rec_a) != pick(rec_b):
        diffs.append(f"recommended differs: {pick(rec_a)} in run 1, {pick(rec_b)} in run 2")
    return {"identical": not diffs, "differences": diffs, "headline_count": len(ha)}
