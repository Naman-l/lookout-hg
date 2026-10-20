"""Print one run's story end to end.   python -m watcher.correlate <run_id | request_id>

request -> run -> child runs -> tool calls (with the gate's decision) -> staged actions -> verifier -> finish,
read from the event files. Exit code 1 if the id matches nothing, so a scenario can assert on it.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from .store import field, read_all


def collect(key: str) -> list[dict]:
    events = list(read_all())
    runs = {e["run_id"] for e in events if e.get("run_id") and (e["run_id"] == key or e.get("request_id") == key)}
    # pull in child runs, however deep
    grew = True
    while grew:
        children = {e["run_id"] for e in events if e.get("run_id") and field(e, "parent_run_id") in runs}
        grew = not children <= runs
        runs |= children
    picked = [e for e in events if e.get("run_id") in runs or e.get("request_id") == key]
    return sorted(picked, key=lambda e: (e.get("ts") or "", field(e, "seq", 0) or 0))


def render(events: list[dict]) -> str:
    by_run = defaultdict(list)
    for e in events:
        by_run[e.get("run_id")].append(e)
    depth = {}
    for rid in by_run:
        d, cur = 0, rid
        while (p := next((field(e, "parent_run_id") for e in by_run[cur] if field(e, "parent_run_id")), None)) and p in by_run:
            d, cur = d + 1, p
        depth[rid] = d
    out = []
    for e in events:
        ind = "  " * depth.get(e.get("run_id"), 0)
        t = field(e, "t_ms")
        stamp = f"{t / 1000:6.2f}s" if isinstance(t, (int, float)) else (e.get("ts") or "")[11:19].rjust(7)
        gate = field(e, "gate")
        who = field(e, "agent_label") or field(e, "agent") or e.get("source")
        flag = {"denied": " [DENIED]", "staged": " [STAGED]"}.get(gate, "") + (" !!" if e.get("severity") in ("error", "critical") else "")
        out.append(f"{stamp} {ind}{who:<14} {e.get('kind'):<16} {e.get('summary', '')}{flag}")
    return "\n".join(out)


def verdict(events: list[dict]) -> str:
    fin = [e for e in events if e.get("kind") == "run.finished" and not field(e, "parent_run_id")]
    if not fin:
        return "no run.finished event: the run did not end cleanly"
    b = fin[-1].get("body") or {}
    return (f"finished {field(fin[-1], 'status', '?')} · {b.get('tool_calls', '?')} tool calls · "
            f"first step {b.get('first_step_ms', '?')} ms · total {b.get('wall_ms', '?')} ms · cost {b.get('cost_usd', '?')} USD")


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print("usage: python -m watcher.correlate <run_id | request_id>", file=sys.stderr)
        return 2
    events = collect(args[0])
    if not events:
        print(f"no events for {args[0]}", file=sys.stderr)
        return 1
    print(render(events))
    print("-" * 60)
    print(verdict(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
