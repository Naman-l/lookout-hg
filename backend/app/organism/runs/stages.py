"""The step each run event belongs to, derived when a run is read (agent-spec-steps Rev 4, F94 names): overview · analysis · draft · decision, in run order.
Derived, never stored, so every stored run and every recording gets it with no re-record. "approval" is the buyer's step, never a run's."""

from __future__ import annotations

from ..schemas import RunEvent, StageSummary
from ..specialists.registry import SPECIALISTS

ORDER = ("overview", "analysis", "draft", "decision")
_DRAFTERS = {"buyers_clerk"}
_ANALYSTS = set(SPECIALISTS) - _DRAFTERS
_DECIDE_TOOLS = {"get_handoffs", "StructuredOutput"}


def stage_of(e: RunEvent, current: str) -> str:
    name = (e.payload or {}).get("name")
    if e.agent in _ANALYSTS:
        return "analysis"
    if e.agent in _DRAFTERS:
        return "draft"
    if e.agent in ("verifier", "reviewer") or e.type in ("verifier.result", "review.result", "revision.started"):
        return "decision"
    if e.agent == "lookout" and (name in _DECIDE_TOOLS or (e.type == "run.finished" and e.parent_run_id is None)):
        return "decision"
    return current  # Lookout's own reading and delegating stays in the step it is in


def attach(events: list[RunEvent]) -> tuple[list[RunEvent], list[StageSummary]]:
    """Each event with its stage, and one summary per stage that ran: lookups (tools called), figures read (numbers the tools returned), when it started and ended."""
    current, out, sums = "overview", [], {}
    for e in sorted(events, key=lambda e: (e.t_ms, e.seq)):
        current = stage_of(e, current)
        out.append(e.model_copy(update={"stage": current}))
        s = sums.setdefault(current, StageSummary(stage=current, started_ms=e.t_ms, ended_ms=e.t_ms))
        s.started_ms, s.ended_ms = min(s.started_ms, e.t_ms), max(s.ended_ms, e.t_ms)
        if e.type == "tool.called" and (e.payload or {}).get("name") != "StructuredOutput":
            s.lookups += 1
        if e.type == "tool.result":
            s.figures_read += len((e.payload or {}).get("numbers") or [])
    staged = {(e.run_id, e.seq): e.stage for e in out}
    return [e.model_copy(update={"stage": staged[(e.run_id, e.seq)]}) for e in events], [sums[k] for k in ORDER if k in sums]
