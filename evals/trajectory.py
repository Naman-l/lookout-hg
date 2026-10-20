"""Grade the path, not only the answer: which specialists ran and in what order, which tools they called with which arguments, and the waste.

A right answer reached by a forbidden route (an analyst staging a request, a tool asked about the wrong supplier) is still a wrong run. All of it is
read from the run's stored events. A sheet's `trajectory` block may say:

  specialists:            [a, b]     each must have been started
  specialists_forbidden:  [c]
  order:                  [a, b]     a starts before b
  tools:                  - {tool: find_suppliers, by: inbox_analyst, args_any: {name: [Baycrest, BCX]}}     called at least once, with a matching argument
  tools_forbidden_by:     {inbox_analyst: [draft_supplier_request]}                                        a tool a given specialist must never call
  max_tool_calls: 30       a budget, not a correctness claim
  max_repeat: 3            the same tool with the same arguments more than this many times is a loop
  max_tool_errors: 3       tool results that came back not ok
"""
from __future__ import annotations

import json

from . import graders


def _name(raw: str) -> str:
    return (raw or "").split("__")[-1].split(".")[-1].strip().lower()


def _calls(events: list[dict]) -> list[dict]:
    return [{"tool": _name(p.get("name") or p.get("tool") or ""), "by": ev.get("agent") or "", "args": p.get("args") or {}}
            for ev in events if ev.get("type") == "tool.called" for p in [ev.get("payload") or {}]]


def _contains(value, needles) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return any(str(n).lower() in text for n in (needles if isinstance(needles, list) else [needles]))


def grade(spec: dict, events: list[dict]) -> dict:
    bad = []
    started = [(ev.get("payload") or {}).get("specialist") or ev.get("agent") for ev in events if ev.get("type") == "child.started"]
    for s in spec.get("specialists", []):
        if s not in started:
            bad.append(f"specialist {s} never started")
    for s in spec.get("specialists_forbidden", []):
        if s in started:
            bad.append(f"specialist {s} started")
    order = [s for s in spec.get("order", []) if s in started]
    if len(order) == len(spec.get("order", [])) and [started.index(s) for s in order] != sorted(started.index(s) for s in order):
        bad.append(f"specialists started out of order: {started}, wanted {spec['order']}")
    calls = _calls(events)
    for want in spec.get("tools", []):
        tool = _name(want["tool"])
        hits = [c for c in calls if c["tool"] == tool and (not want.get("by") or c["by"] == want["by"])]
        if not hits:
            bad.append(f"{tool} not called" + (f" by {want['by']}" if want.get("by") else ""))
            continue
        for key, needles in (want.get("args_any") or {}).items():
            if not any(_contains(c["args"].get(key, ""), needles) for c in hits):
                bad.append(f"{tool} never asked about {needles} in {key}")
    for who, tools in (spec.get("tools_forbidden_by") or {}).items():
        bad += [f"{who} called {c['tool']}" for c in calls if c["by"] == who and c["tool"] in {_name(t) for t in tools}]
    if "max_tool_calls" in spec and len(calls) > spec["max_tool_calls"]:
        bad.append(f"{len(calls)} tool calls, budget {spec['max_tool_calls']}")
    if "max_repeat" in spec:
        seen: dict[str, int] = {}
        for c in calls:
            k = f"{c['by']}:{c['tool']}:{json.dumps(c['args'], sort_keys=True)}"
            seen[k] = seen.get(k, 0) + 1
        bad += [f"{k.split(':', 2)[1]} repeated {n} times with the same arguments" for k, n in seen.items() if n > spec["max_repeat"]]
    if "max_tool_errors" in spec:
        errs = sum(1 for ev in events if ev.get("type") == "tool.result" and (ev.get("payload") or {}).get("ok") is False)
        if errs > spec["max_tool_errors"]:
            bad.append(f"{errs} tool calls failed, at most {spec['max_tool_errors']}")
    return graders._dim("trajectory", not bad, "; ".join(bad) or f"{len(started)} specialists, {len(calls)} tool calls, as expected")
