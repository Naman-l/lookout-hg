"""Hooks that turn the SDK's lifecycle into run events: PostToolUse (tool results), SubagentStart/Stop
(child runs)."""

from __future__ import annotations

import json
import time

from ..domain.common import EntityRef
from .context import RunContext
from .gate import STAGING_TOOLS, _label, _short, recorder_for

_ALIASES = {"shortage_for_parts": "shortage", "where_used_for_parts": "where_used"}  # a batch tool does the single tool's job
DRAFT_TOOLS = STAGING_TOOLS - {"mcp__actions__log_buyer_question"}  # a logged question is not a draft awaiting approval
from .runs import store


def _text_of(tool_response) -> str:
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, list):
            return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    if isinstance(tool_response, list):
        return "".join(b.get("text", "") for b in tool_response if isinstance(b, dict))
    return str(tool_response)


def _handoff_ok(ctx: RunContext, inp: dict) -> bool:
    """True when the handoff was accepted (the tool did not return an error), so ending the specialist loses nothing."""
    return inp.get("agent_type") in ctx.handoffs


def refund(ctx: RunContext, agent_type: str | None, short: str) -> None:
    """A call that failed or was malformed is not a read: it does not count toward the caps."""
    if ctx.tool_counts[short] > 0:
        ctx.tool_counts[short] -= 1
    if ctx.calls[agent_type] > 0:
        ctx.calls[agent_type] -= 1


def make_post_tool(ctx: RunContext):
    async def post_tool(inp, tool_use_id, _hook_ctx):
        name = inp["tool_name"]
        if name.endswith("__submit_handoff"):
            # The handoff is the specialist's last act: end it here instead of paying a model turn to say "Done".
            if inp["tool_use_id"] and _handoff_ok(ctx, inp):
                finish_child(ctx, inp.get("agent_id", ""), inp["agent_type"])
                return {"continue_": False, "stopReason": "handoff received"}
            return {}
        if not name.startswith("mcp__"):
            return {}
        rec = recorder_for(ctx, inp)
        agent = inp.get("agent_type") or "lookout"
        short = _short(name)
        first = next(iter((inp.get("tool_input") or {}).values()), None)
        for part in first if isinstance(first, list) else [first]:  # a batch call counts as one call per part
            ctx.calls_made.add((_ALIASES.get(short, short), part))
        ctx.tools_called.update({short, _ALIASES.get(short, short)})
        from .verifier import dates_in, day_counts, days_left_in, numerals  # noqa: PLC0415

        text = _text_of(inp.get("tool_response"))
        ctx.seen_numerals.update(numerals(text))
        ctx.seen_day_counts.update(day_counts(text))
        ctx.seen_days_left.update(days_left_in(text))
        ctx.seen_dates.update(dates_in(text))
        try:
            body = json.loads(_text_of(inp.get("tool_response")))
        except (ValueError, TypeError):
            body = {}
        if agent != "lookout":  # what this specialist's tools returned is what its handoff relies on; code records it
            ctx.numbers_by_agent.setdefault(agent, []).extend(n["id"] for n in body.get("numbers", []) if n["id"] not in ctx.numbers_by_agent.get(agent, []))
            ctx.unknowns_by_agent.setdefault(agent, []).extend(u for u in ctx.unknowns if u.what in {x["what"] for x in body.get("unknowns", [])} and u not in ctx.unknowns_by_agent.get(agent, []))
            if isinstance(body.get("data"), dict) and body["data"].get("action_id"):
                ctx.actions_by_agent.setdefault(agent, []).append(body["data"]["action_id"])
        ctx.results_seen.add(inp["tool_use_id"])
        if "error" in body:
            refund(ctx, inp.get("agent_type"), _short(name))  # a call that failed does not use up the cap on reads
        elif agent != "lookout":
            ctx.reads_ok[agent] += 1
        if _short(name) == "compare_offers" and isinstance(body.get("data"), dict):
            from .carry import conditions_from_compare  # noqa: PLC0415

            ctx.conditions.update(conditions_from_compare(body["data"]))
            for col in body["data"].get("columns") or []:
                ctx.site_text[str(col.get("supplier") or "").lower()] = ctx.site_text.get(str(col.get("supplier") or "").lower(), "") + " " + " ".join(str(col.get(k) or "") for k in ("origin_claim", "conditions", "origin")).lower()
        extra = {}
        if _short(name) == "try_step" and isinstance(body.get("data"), dict) and body["data"].get("ok"):
            extra = {"script": (inp.get("tool_input") or {}).get("code"), "checks": body["data"].get("checks")}  # the step that passed, shown as code
        rec.emit(
            "tool.result", body.get("summary") or f"{_short(name)} returned", agent=agent, tool_use_id=inp["tool_use_id"],
            tool=_short(name), name=_short(name), ok="error" not in body, numbers=body.get("numbers", []), unknowns=body.get("unknowns", []), **extra,
        )
        if name in DRAFT_TOOLS and isinstance(body.get("data"), dict) and body["data"].get("action_id"):
            d = body["data"]
            rec.emit("action.staged", (f"{_label(agent)} found the draft already waiting ({d['already_waiting']}): " if d.get("already_waiting") else f"{_label(agent)} drafted: ") + str(d.get("subject", "a supplier request")), agent=agent,
                     tool_use_id=inp["tool_use_id"], refs=[EntityRef(type="action", id=d["action_id"], label=d.get("subject"))],
                     action_id=d["action_id"], action_type=d.get("type"), recipient=d.get("recipient"), payload_hash=d.get("payload_hash"), already_waiting=d.get("already_waiting"))
        return {}

    return post_tool


def make_post_tool_failure(ctx: RunContext):
    """A tool that errored (a refusal, a bad argument, an exception) still gets its tool.result event, ok=False, so no call on the page is left without an answer."""
    async def failed(inp, tool_use_id, _hook_ctx):
        name = inp["tool_name"]
        if not name.startswith("mcp__") or inp["tool_use_id"] in ctx.results_seen:
            return {}
        ctx.results_seen.add(inp["tool_use_id"])
        refund(ctx, inp.get("agent_type"), _short(name))
        raw = str(inp.get("error") or "")
        try:
            raw = json.loads(raw).get("error", raw)
        except (ValueError, TypeError, AttributeError):
            pass
        recorder_for(ctx, inp).emit("tool.result", f"{_short(name)} failed: {raw[:300]}", agent=inp.get("agent_type") or "lookout", tool_use_id=inp["tool_use_id"],
                                    tool=_short(name), name=_short(name), ok=False, error=raw[:300], numbers=[], unknowns=[])
        return {}

    return failed


def make_subagent_start(ctx: RunContext, label_of):
    async def start(inp, tool_use_id, _hook_ctx):
        specialist = inp["agent_type"]
        call_id, call = next(((k, v) for k, v in ctx.pending.items() if v["specialist"] == specialist and "child" not in v), (None, None))
        child_id = f"{ctx.run_id}.{len(ctx.children) + 1}"
        child = ctx.recorder.child(child_id)
        ctx.children[inp["agent_id"]] = child
        ctx.running.add(inp["agent_id"])
        if call_id:
            call["child"] = child
            ctx.child_by_tool_use[call_id] = child
        task = (call or {}).get("task", "")
        store.insert_run(ctx.db_path, run_id=child_id, parent_run_id=ctx.run_id, item_key=ctx.item_key, workflow=f"specialist:{specialist}",
                         status="running", started_at=child.events[0].ts if child.events else _now())
        ctx.recorder.emit("child.started", task or f"{label_of(specialist)} started", agent=specialist, tool_use_id=call_id,
                          child_run_id=child_id, specialist=specialist, question=task, task=task, asked_by="lookout")
        child.emit("run.started", f"{label_of(specialist)} started", agent=specialist, workflow=f"specialist:{specialist}", item_key=ctx.item_key)
        return {}

    return start


def finish_child(ctx: RunContext, agent_id: str, specialist: str) -> None:
    """Close a teammate's run: its run.finished, the run row, and the one-line answer on Lookout's run. Idempotent, because a teammate is
    closed either by the SDK's stop hook or at its handoff (we end it there rather than pay a model turn to say 'Done')."""
    from .runs.events import LABELS  # noqa: PLC0415

    child = ctx.children.get(agent_id)
    if child is None or agent_id not in ctx.running:
        return
    ctx.running.discard(agent_id)
    handoff = ctx.handoffs.get(specialist)
    status = "ok" if handoff else "failed"
    child.emit("run.finished", f"{LABELS.get(specialist, specialist)} finished", agent=specialist, status=status, tool_calls=child.tool_calls, first_step_ms=child.first_step_ms)
    store.update_run(ctx.db_path, child.run_id, status=status, tool_calls=child.tool_calls)
    ctx.recorder.emit("child.finished", _answer(ctx, specialist, handoff), agent=specialist, child_run_id=child.run_id, status=status, handoff_ok=handoff is not None)


def make_subagent_stop(ctx: RunContext, label_of):
    async def stop(inp, tool_use_id, _hook_ctx):
        specialist = inp["agent_type"]
        child = ctx.children.get(inp["agent_id"])
        if child is None:
            return {}
        handoff = ctx.handoffs.get(specialist)
        if handoff is None and not inp.get("stop_hook_active"):  # one nudge: it tried to finish without handing off
            return {"decision": "block", "reason": "You have not submitted your handoff. Call submit_handoff with your findings, then reply Done."}
        finish_child(ctx, inp["agent_id"], specialist)
        return {}

    return stop


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _answer(ctx: RunContext, specialist: str, handoff) -> str:
    """The one-line answer the run page shows for a specialist: written by code for the clerk (what it staged),
    the specialist's own first finding otherwise."""
    if handoff is None:
        return "finished without a valid handoff"
    if specialist == "buyers_clerk":
        from ..domain.actions import ledger  # noqa: PLC0415

        acts = [ledger.get(ctx.db_path, a) for a in ctx.actions_by_agent.get(specialist, [])]
        drafts = [a for a in acts if a and a.type == "supplier_request"]
        notes = [a for a in acts if a and a.type == "note"]
        if drafts:
            return "Staged a request to the supplier's contact on file, awaiting approval"
        if any((n.change or {}).get("kind") == "record" for n in notes):
            return "Staged a decision for the owner's signature"
        if any((n.change or {}).get("kind") == "note" and n.state == "proposed" for n in notes):
            return "Staged a note for the owner's signature"
        if notes:
            return f"Logged a question for {notes[0].change.get('owner', 'the owner') if notes[0].change else 'the owner'}"
        return "Staged nothing: no request was needed"
    return handoff.findings[0]
