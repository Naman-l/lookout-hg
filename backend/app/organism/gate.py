"""The gate: one PreToolUse hook for the whole tree, keyed by agent_type, failing closed.

Lookout's own thread is agent_type None. A call is allowed only if the caller's allow-list names the tool;
everything else is denied with a reason the model sees. The gate also enforces the item type's delegation
plan (which specialist, in which order), a per-agent call budget, and "no drafting on a trust item". Every
decision becomes a `tool.called` run event. Returning an explicit allow matters: a hook that returns nothing
falls through to the CLI's permission check, which denies.

The delegation plan, which `decide` reads from `ctx.groups` (see `workflows/work_item.plan_for`):

    one step per group, in order          Lookout may ask only the next unasked group, and only once each member has handed off
    members of one group (independent)    asked together, in the same turn
    optional specialists (`ctx.optional`) the plan may move past them if Lookout does not use them
    Ask (`ctx.open_plan`)                 no fixed order: any registered specialist, once each, `ctx.max_delegations` at most
    trust item (empty plan)               no delegation at all; the answer is written by code
"""

from __future__ import annotations

from typing import Any

from .context import RunContext
from .purposes import status, why as _why

STRUCTURED_OUTPUT = "StructuredOutput"  # the SDK's own tool for output_format; Lookout's thread only
STAGING_TOOLS = {"mcp__actions__draft_supplier_request", "mcp__actions__log_buyer_question", "mcp__actions__propose_supplier_alias", "mcp__actions__amend_draft"}


CASE_SITUATION_WORDS = 14  # F105: the Situation sentence on a case page

def decide(ctx: RunContext, agent_type: str | None, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
    """Pure decision (testable without a model): returns (allowed, reason)."""
    if tool_name == "Agent":
        if agent_type is not None:
            return False, "a teammate does not pass work on; Lookout asks"
        if (tool_input or {}).get("run_in_background"):
            return False, "ask a teammate and wait for the answer: do not send the work to the background"
        wanted = (tool_input or {}).get("subagent_type")
        if ctx.open_plan:  # Ask: any registered specialist, once each, a few at most
            if wanted not in ctx.plan:
                return False, f"{wanted} is not a colleague I can ask here"
            if wanted in ctx.delegated:
                return False, f"{wanted} has already been asked"
            if len(ctx.delegated) >= ctx.max_delegations:
                return False, f"at most {ctx.max_delegations} teammates may be asked for one question"
            return True, "asked for this question"
        for gi, group in enumerate(ctx.groups):
            if all(m in ctx.delegated or m in ctx.optional for m in group) and not any(m in ctx.delegated for m in group) and wanted not in group:
                continue  # an optional step Lookout has not used: the plan may move past it
            if all(m in ctx.delegated for m in group):
                continue  # this group has been asked already
            waiting = [m for earlier in ctx.groups[:gi] for m in earlier if m not in ctx.handoffs]
            if waiting:
                return False, f"wait for {', '.join(_label(w) for w in waiting)} to finish before the next step of the plan"
            todo = [m for m in group if m not in ctx.delegated]
            if wanted in todo:
                return True, "the next step of the plan"
            return False, f"the plan for this item asks {' and '.join(todo)} next, not {wanted}"
        return False, "the plan for this item has no further step"
    if tool_name == STRUCTURED_OUTPUT:
        if agent_type is not None:
            return False, "only Lookout writes the Recommendation"
        expected = ctx.delegated if ctx.open_plan else [m for m in ctx.plan if m not in ctx.optional or m in ctx.delegated]
        unasked = [m for m in expected if m not in ctx.delegated]
        pending = [m for m in expected if m in ctx.delegated and m not in ctx.handoffs]
        unread = [m for m in expected if m in ctx.handoffs and m not in ctx.handoffs_seen]
        if unasked or pending:
            return False, f"wait for {', '.join(_label(m) for m in unasked + pending)} to hand off before you write the Recommendation"
        if unread:
            return False, f"read {', '.join(_label(m) + chr(39) + 's' for m in unread)} handoff first (get_handoffs), then write the Recommendation"
        from types import SimpleNamespace  # noqa: PLC0415

        from .verifier import REASON_WORDS, shape_failures  # noqa: PLC0415

        if callable(ctx.pending_calls) and "supply_planner" not in ctx.handoffs:  # told at the write while the planner can still run them; once it has handed off, nobody can, so Lookout writes and the verifier records the gap (R2b: a run looped here to its turn limit with no answer)
            owed = sorted(c for c in (ctx.pending_calls() or []) if c not in ctx.calls_made)
            if owed:
                names = {"shortage": "shortage_for_parts", "where_used": "where_used_for_parts"}
                return False, "before you write: " + "; ".join(f"run {names.get(t, t)} for {a}" for t, a in owed) + " (the notice affects them), then write the Recommendation"
        ti = tool_input or {}
        shaped = SimpleNamespace(finding=str(ti.get("finding") or ""), points=[SimpleNamespace(label=str(p.get("label", "")), text=str(p.get("text", ""))) for p in ti.get("points") or [] if isinstance(p, dict)])
        too_long = shape_failures(shaped, ask=ctx.open_plan)
        if not ctx.open_plan and not ctx.coded and shaped.finding.strip():  # an item's headline carries what is at stake and what to do, so the buyer can act on it alone
            from .verifier import headline_gaps  # noqa: PLC0415

            too_long += [f"shape: {g}" for g in headline_gaps(shaped.finding, action=not ctx.is_case)]
            n = len(shaped.finding.split())
            if ctx.is_case and n > CASE_SITUATION_WORDS:  # F105: a case's Situation is short; the page shows the facts beside it
                too_long.append(f"shape: the Situation has {n} words; at most {CASE_SITUATION_WORDS} on a case")
        from .verifier import before_notice_claim  # noqa: PLC0415

        if before_notice_claim(shaped.finding):
            too_long.append("shape: say 'past due on <the data date>' (the date the records count it on); a count before the notice is not a tool figure")
        rec = ti.get("recommended") if isinstance(ti.get("recommended"), dict) else None
        if rec and rec.get("reason"):  # G1: a figure in the reason must be one it cites, or the verifier drops the mark after the run: ask for the rewrite now
            from .verifier import _same, numerals  # noqa: PLC0415

            cited = [ctx.evidence[i] for i in rec.get("number_ids") or [] if i in ctx.evidence]
            text = str(rec.get("reason"))
            for ev in cited:
                if ev.say:
                    text = text.replace(ev.say, " ")
            loose = sorted({str(v) for v in numerals(text) if not any(_same(v, ev.value, ev.unit) for ev in cited)})
            if loose:
                too_long.append(f"shape: the recommended reason states {', '.join(loose)}: cite the id of each figure in its number_ids, or drop the figure")
        if rec and rec.get("kind") == "extend" and "buy_ahead" in ctx.option_kinds:  # a price lock's letter acknowledges the open lines at today's price and never asks to extend (BUYER R2b, the deadline case)
            too_long.append("shape: the letter asks the supplier to acknowledge the open lines at today's price: recommend buy_ahead, the option it acts on")
        if rec and len(str(rec.get("reason") or "").split()) > REASON_WORDS:  # the verifier would drop the mark: ask for the rewrite now, in the same turn
            too_long.append(f"shape: the recommended reason has {len(str(rec.get('reason')).split())} words; at most {REASON_WORDS}")
        for f in ti.get("findings") or []:
            if isinstance(f, dict) and len(str(f.get("meaning") or "").split()) > REASON_WORDS:
                too_long.append(f"shape: the meaning of {f.get('key')} has {len(str(f.get('meaning')).split())} words; at most {REASON_WORDS}")  # the shape is checked before the answer is written, so the rewrite happens in the same turn, not as a failed run
        if too_long:
            return False, "rewrite it to fit: " + "; ".join(f.removeprefix("shape: ") for f in too_long)
        return True, "Recommendation"
    allowed = ctx.allow.get(agent_type, set())
    who = agent_type or "lookout"
    if tool_name not in allowed:
        return False, f"{_short(tool_name)} is not part of {_label(who)}'s work"
    if tool_name in STAGING_TOOLS and not ctx.stage_allowed:
        return False, "nothing is drafted or logged from this message: its sender is not a supplier on file, and the item already tells the buyer"
    cap = ctx.tool_caps.get(_short(tool_name))
    if cap is not None and ctx.tool_counts[_short(tool_name)] >= cap:
        return False, f"{_short(tool_name)} has been used {cap} times for this item, which is enough: work with what you have"
    if ctx.calls[agent_type] >= ctx.max_calls_per_agent:
        return False, f"{who} has used its {ctx.max_calls_per_agent} tool calls; wrap up with what you have"
    return True, "part of this role's work"


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def _allow(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": reason}}


def recorder_for(ctx: RunContext, inp: dict):
    return ctx.children.get(inp.get("agent_id") or "", ctx.recorder)


def make_gate(ctx: RunContext):
    async def gate(inp, tool_use_id, _hook_ctx):
        agent_type = inp.get("agent_type")
        name = inp["tool_name"]
        allowed, reason = decide(ctx, agent_type, name, inp.get("tool_input") or {})
        rec = recorder_for(ctx, inp)
        agent = agent_type or "lookout"
        if allowed:
            ctx.calls[agent_type] += 1
            ctx.tool_counts[_short(name)] += 1
            if name == "Agent":
                ti = inp["tool_input"]
                ctx.delegated.append(ti["subagent_type"])
                ctx.pending[inp["tool_use_id"]] = {"specialist": ti["subagent_type"], "task": ti.get("description") or ti.get("prompt", "")[:120]}
            elif name != STRUCTURED_OUTPUT and not name.endswith("__submit_handoff"):
                gate_state = "staged" if name in STAGING_TOOLS else "allowed"
                rec.emit("tool.called", f"{_label(agent)} calls {_short(name)}", agent=agent, tool_use_id=inp["tool_use_id"], tool=_short(name), name=_short(name), args=inp.get("tool_input"), gate=gate_state,
                         gate_reason=_why(_short(name), inp.get("tool_input"), ctx.db_path))  # what the step is for, not "part of this role's work": the log's reason is a purpose
                rec.emit("run.status", status(_label(agent), _short(name)), agent=agent, tool_use_id=inp["tool_use_id"])  # the one live line: who is doing what now
            return _allow(reason)
        what = "asking a teammate" if name == "Agent" else _short(name)  # the Agent tool is delegation, not a lookup: say what was tried, not the tool's name
        rec.emit("tool.called", f"{_label(agent)} was refused {what}: {reason}", agent=agent, tool_use_id=inp["tool_use_id"], tool=_short(name), name=_short(name), args=inp.get("tool_input"), gate="denied", gate_reason=reason)
        return _deny(reason)

    return gate


def _short(tool_name: str) -> str:
    return tool_name.rsplit("__", 1)[-1]


def _label(agent: str) -> str:
    from .runs.events import LABELS

    return LABELS.get(agent, agent)
