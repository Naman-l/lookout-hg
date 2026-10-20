"""Two agents that do nothing useful, held to the same graders as the real one.

A null agent finishes "ok" with an empty answer; an over-refuser declines everything. A case that either of them passes is not measuring
the work: agentic benchmarks have been found crediting empty responses. Ordinary and hard cases must fail both. A stop case (nothing may
be staged) can legitimately pass a refusal; it says so in its sheet with `baseline_ok` and is paired with a case that needs the work done.
Free: no model, no app."""
from __future__ import annotations

from . import agent_runner, graders

EMPTY = {"finding": "", "numbers": [], "assumptions": [], "would_change": [], "open_questions": [], "action_ids": []}


def trial(kind: str) -> dict:
    """What the harness would read back from an app whose agent did nothing (null) or declined (refuse)."""
    sent = {"filename": "baseline.csv", "text": ""}
    base = {"events": [], "actions": [], "outbox": [], "ledger_mounted": True, "item_days_left": None, "sent": sent}
    if kind == "null":
        return {**base, "detail": {"status": "ok", "recommendation": dict(EMPTY), "verifier": {"passed": True}}}
    return {**base, "detail": {"status": "refused", "recommendation": None, "verifier": None}}


def run(cases: dict[str, dict]) -> dict:
    """Per baseline, the agent cases it passes; a pass is expected only where the sheet lists it under `baseline_ok`."""
    out, offenders = {}, []
    for kind in ("null", "refuse"):
        passes = []
        for cid, c in cases.items():
            if c["kind"] != "agent":
                continue
            dims = agent_runner.grade_trial(c, trial(kind))
            if graders.case_status(dims) == "PASS":
                passes.append(cid)
        out[kind] = passes
        offenders += [f"{kind} agent passes {cid}" for cid in passes if kind not in (cases[cid].get("baseline_ok") or [])]
    ran = sum(c["kind"] == "agent" for c in cases.values())
    allowed = sorted({cid for kind, ids in out.items() for cid in ids if kind in (cases[cid].get("baseline_ok") or [])})
    detail = "; ".join(offenders) or (f"neither passes any of {ran} agent cases" + (f" except {', '.join(allowed)} (stop cases, listed in their sheets)" if allowed else ""))
    return {"status": "FAIL" if offenders else "PASS", "detail": detail, "baselines": out, "agent_cases": ran}
