"""The typed handoff. A specialist submits only its findings; code attaches what its tools actually returned
(number ids, open questions with owners) and what it staged. The model writes prose, the system keeps the
facts, so a handoff is short to generate and cannot cite a number no tool returned."""

from __future__ import annotations

import json

from claude_agent_sdk import tool
from pydantic import BaseModel, Field, ValidationError

from ..context import RunContext
from ..schemas import Handoff
from ..toolkit import refuse


class HandoffInput(BaseModel):
    findings: list[str] = Field(min_length=1, max_length=4, description="Two or three short sentences in a buyer's words")


def make_handoff_tool(ctx: RunContext, specialist: str):
    @tool(
        "submit_handoff",
        "Finish your work: submit your findings (two or three short sentences). The numbers your tools returned, "
        "the open questions they raised and any draft you staged are attached for you. Call it once, last.",
        HandoffInput.model_json_schema(),
    )
    async def submit_handoff(args):
        try:
            given = HandoffInput.model_validate(args)
        except ValidationError as e:
            return refuse(f"handoff rejected: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}")
        if specialist in ("inbox_analyst", "supply_planner", "tariff_analyst", "sourcing_analyst") and ctx.reads_ok[specialist] == 0:
            return refuse("you have read nothing yet: look up what the task needs with your tools, then hand off what you found")
        if specialist == "supply_planner" and callable(ctx.pending_calls):  # the parts the notice affects must have had their shortage run: the planner finishes it, nobody can after its handoff
            missing_calls = sorted(c for c in (ctx.pending_calls() or []) if c not in ctx.calls_made)
            if missing_calls:
                names = {"shortage": "shortage_for_parts", "where_used": "where_used_for_parts"}
                return refuse("not finished: " + "; ".join(f"run {names.get(t, t)} for {a}" for t, a in missing_calls) + " (the notice affects them), then hand off")
        owed = sorted(ctx.required_suppliers - ctx.suppliers_asked) if specialist == "buyers_clerk" else []
        if owed:  # code made the list of who needs asking from the item's lines; the clerk writes each request, it cannot skip one
            return refuse("not finished: no request yet for " + ", ".join(owed) + ". Draft one for each (one per supplier contact), then hand off.")
        ctx.handoffs[specialist] = Handoff(
            findings=given.findings, number_ids=list(ctx.numbers_by_agent.get(specialist, [])),
            unknowns=list(ctx.unknowns_by_agent.get(specialist, [])), action_ids=list(ctx.actions_by_agent.get(specialist, [])),
        )
        return {"content": [{"type": "text", "text": json.dumps({"summary": "handoff accepted"})}]}

    return submit_handoff
