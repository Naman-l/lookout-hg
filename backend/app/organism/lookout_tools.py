"""Lookout's own tool: read what the specialists handed off, with every number resolved from the run's
evidence register. The orchestrator cites these ids; it never relays a figure from memory."""

from __future__ import annotations

import asyncio
import os

from claude_agent_sdk import tool

from .context import RunContext
from .toolkit import READ, _unk, refuse, reply


HANDOFF_WAIT_S = float(os.environ.get("LOOKOUT_HANDOFF_WAIT_S", "60"))  # how long a repeat read waits for a running teammate's handoff


def _line(n) -> str:
    return f"{n.id} = {n.value} {n.unit} ({n.name})" + (f" - say \"{n.say}\"" if n.say else "")


def make_tools(ctx: RunContext):
    @tool(
        "get_handoffs",
        "What the specialists have handed off so far: their findings, the numbers they relied on (id, name, value, "
        "unit) and their open questions with owners. Call it once after a specialist finishes; cite these ids and "
        "copy open questions exactly.",
        {},
        annotations=READ,
    )
    async def get_handoffs(args):
        if ctx.handoff_reads and set(ctx.handoffs) == ctx.handoffs_seen and ctx.running:  # a teammate is still working: wait here for its handoff (bounded) instead of refusing, so polling costs one turn, not the run's turn budget (live Ask run-5cd3e9d2 hit max turns polling)
            for _ in range(int(HANDOFF_WAIT_S / 0.5)):
                await asyncio.sleep(0.5)
                if set(ctx.handoffs) != ctx.handoffs_seen or not ctx.running:
                    break
        if ctx.handoff_reads and set(ctx.handoffs) == ctx.handoffs_seen:  # nothing new since the last read: a repeat costs a turn and says nothing
            return refuse("no new handoffs since you last read them: what they said is above. " + ("A teammate is still working and has not handed off: call get_handoffs again, it waits for the teammate." if ctx.running else "Write the Recommendation."))
        ctx.handoff_reads += 1
        ctx.handoffs_seen = set(ctx.handoffs)
        out = {}
        if ctx.item_number_ids:  # the item's own computed figures, read by the system before the model ran
            out["item"] = {"numbers": [_line(ctx.evidence[i]) for i in ctx.item_number_ids if i in ctx.evidence]}
        for name, h in ctx.handoffs.items():
            out[name] = {
                "findings": h.findings,
                "numbers": [_line(ctx.evidence[i]) for i in h.number_ids if i in ctx.evidence],
                "unknowns": [_unk(u) for u in h.unknowns],
                "action_ids": h.action_ids,
            }
        from .runs.events import LABELS  # noqa: PLC0415

        who = [LABELS.get(n, n) for n in out if n != "item"]
        say = " and ".join(who) if len(who) < 3 else ", ".join(who[:-1]) + " and " + who[-1]
        return reply(ctx, f"{say} handed back their findings" if who else "No specialist has handed back yet", out, capped=False)  # the team's answers are what Lookout writes from: never cut

    return [get_handoffs]
