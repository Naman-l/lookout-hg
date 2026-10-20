"""`make smoke-agent`: one real run on the installed Agent SDK, streamed to the terminal.

Lookout delegates to the Supply planner, which calls DOMAIN-shaped tools (fakes, here) through the gate.
Lookout is then asked to try a tool that is not in its toolset, so the output shows an allow and a refusal.
Exit code 0 only if: a tool call was allowed, one was refused, a child run finished with a valid handoff,
and the first streamed step arrived in under 2 seconds.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from . import fakes
from ..runner import finish, run_agent
from ..runs.events import Recorder

PROMPT = (
    "Smoke test. Ask the supply_planner about part HR-40110 and wait for its handoff. Then, yourself, try to "
    "call mcp__demand__shortage for HR-40110 once (it is not yours to call; just report what happened). "
    "Finish with one sentence."
)


def render(e) -> str | None:
    t = f"{e.t_ms / 1000:6.1f}s"
    who = f"{e.agent_label:<15}"
    if e.type == "step.delta":
        return None
    if e.type == "tool.called":
        mark = {"allowed": "allow ", "staged": "staged", "denied": "DENY  "}[e.payload.get("gate", "allowed")]
        return f"{t}  {who} gate {mark}  {e.payload.get('tool')}  {e.payload.get('gate_reason') if e.payload.get('gate') == 'denied' else ''}"
    if e.type == "tool.result":
        return f"{t}  {who} result       {e.summary}"
    if e.type in ("child.started", "child.finished", "run.started", "run.finished", "run.failed", "step.text"):
        return f"{t}  {who} {e.type.replace('.', ' '):<14} {e.summary[:110]}"
    return f"{t}  {who} {e.type}  {e.summary[:100]}"


async def main() -> int:
    db = str(Path(tempfile.mkdtemp(prefix="lookout-smoke-")) / "smoke.db")
    rec = Recorder("run-smoke", db)
    q = rec.subscribe()

    async def printer():
        while True:
            _, e = await q.get()
            line = render(e)
            if line:
                print(line, flush=True)

    p = asyncio.create_task(printer())
    result = await run_agent(item_key="smoke:HR-40110", db_path=db, plan=["supply_planner"], prompt=PROMPT, services=fakes, workflow="smoke", run_id="run-smoke", recorder=rec)
    finish(result)
    await asyncio.sleep(0.05)
    p.cancel()

    gates = [e.payload.get("gate") for e in rec.events if e.type == "tool.called"]
    child_events = [e for c in result.ctx.children.values() for e in c.events if e.type == "tool.called"]
    gates += [e.payload.get("gate") for e in child_events]
    checks = {
        "a tool call was allowed": "allowed" in gates,
        "a tool call was refused": "denied" in gates,
        "the planner handed off": "supply_planner" in result.ctx.handoffs,
        "first step under 2 s": (result.first_step_ms or 99999) < 2000,
        "run finished ok": result.status == "ok",
    }
    print(f"\ncost {result.cost_usd} USD · {result.wall_ms / 1000:.1f} s · first step {result.first_step_ms} ms · turns {result.turns}")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
