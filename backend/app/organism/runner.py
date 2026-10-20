"""Runs Lookout once: builds the options, streams the SDK's messages into run events, finishes the run row.

One fresh SDK session per run (measured: first token 1.4-1.7 s on Sonnet, and a kept-open client would carry
one run's conversation into the next). Everything per-run (tool servers, hooks, evidence) closes over a
RunContext, so runs never share state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import claude_agent_sdk as sdk
from claude_agent_sdk import (
    AgentDefinition, AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage,
    StreamEvent, TaskNotificationMessage, TaskProgressMessage, TextBlock, create_sdk_mcp_server,
)

from ..domain.actions import tools as actions_tools
from ..domain.attention import tools as attention_tools
from ..domain.bom import tools as bom_tools
from ..domain.demand import tools as demand_tools
from ..domain.imports.steward import tools as steward_tools
from ..domain.inbox import tools as inbox_tools
from ..domain.orders import tools as orders_tools
from ..domain.phases import tools as phases_tools
from ..domain.quotes import tools as quotes_tools
from ..domain.tariffs import tools as tariffs_tools
from .context import RunContext
from . import lookout_tools
from .gate import STRUCTURED_OUTPUT, make_gate
from .lifecycle import make_post_tool, make_post_tool_failure, make_subagent_start, make_subagent_stop
from .prompts import build_system_prompt
from .runs import store
from .runs.events import LABELS, Recorder
from .specialists.handoff import make_handoff_tool
from .specialists.registry import SPECIALISTS, prompt_hash

DEFAULT_MODEL = os.environ.get("LOOKOUT_MODEL", "claude-sonnet-5-5")
MAX_BUDGET = float(os.environ.get("LOOKOUT_MAX_BUDGET_USD_PER_RUN", "1"))
FAST_MODEL = os.environ.get("LOOKOUT_FAST_MODEL", "claude-haiku-5-5")
LOOKOUT_MAX_TURNS = int(os.environ.get("LOOKOUT_MAX_TURNS", "12"))
# Thinking and effort are measured, not assumed: the tools do the reasoning-heavy work, so these default low.
THINKING = os.environ.get("LOOKOUT_THINKING", "disabled")  # disabled | adaptive
EFFORT = os.environ.get("LOOKOUT_EFFORT", "low")


@dataclass
class RunResult:
    run_id: str
    status: str
    ctx: RunContext
    structured_output: Any = None
    cost_usd: float | None = None
    wall_ms: int = 0
    first_step_ms: int | None = None
    turns: int | None = None
    error: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cache_read: int | None = None
    tokens_cache_creation: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tool_lists(ctx: RunContext, services) -> dict[str, list]:
    """Every domain tool server's tools, by server name: the one list that registration and the version hash are both built from."""
    return {
        "orders": orders_tools.make_tools(ctx, services.orders), "demand": demand_tools.make_tools(ctx, services.demand), "bom": bom_tools.make_tools(ctx, services.bom),
        "attention": attention_tools.make_tools(ctx, services.attention), "steward": steward_tools.make_tools(ctx), "phases": phases_tools.make_tools(ctx, services.phases),
        "quotes": quotes_tools.make_tools(ctx, services.quotes), "tariffs": tariffs_tools.make_tools(ctx, services.tariffs), "inbox": inbox_tools.make_tools(ctx, services.inbox),
        "actions": actions_tools.make_tools(ctx, services.suppliers), "lookout": lookout_tools.make_tools(ctx),
    }


def build_servers(ctx: RunContext, services, plan: list[str], lists: dict[str, list] | None = None) -> dict:
    """Every tool server, registered at the top level (the SDK only routes in-process servers from there).
    Which agent may call what is the gate's job, not the registration's."""
    servers = {name: create_sdk_mcp_server(name, "1.0", tools) for name, tools in (lists or tool_lists(ctx, services)).items()}
    for name in plan:
        servers[name] = create_sdk_mcp_server(name, "1.0", [make_handoff_tool(ctx, name)])
    return servers


def versions(system_prompt: str, plan: list[str], lists: dict[str, list], output_schema: dict | None, db_path=None) -> dict:
    """What this run was made of, hashed: Lookout's prompt, each specialist's instructions, and every tool's name, description and input schema. Any of them changing changes the hash."""
    import json  # noqa: PLC0415

    specialists = {n: prompt_hash(SPECIALISTS[n].instructions_for(db_path), SPECIALISTS[n].description, " ".join(sorted(SPECIALISTS[n].qualified_tools()))) for n in plan}
    tools = {f"{srv}.{t.name}": prompt_hash(t.name, t.description, json.dumps(t.input_schema, sort_keys=True, default=str)) for srv, ts in lists.items() for t in ts}
    return {"prompt_hash": prompt_hash(system_prompt, *[specialists[n] for n in plan], json.dumps(output_schema or {}, sort_keys=True)),
            "toolset_hash": prompt_hash(*[f"{k}:{v}" for k, v in sorted(tools.items())]), "specialist_prompts": specialists, "tool_count": len(tools)}


def allow_map(plan: list[str]) -> dict[str | None, set[str]]:
    allow: dict[str | None, set[str]] = {None: {"Agent", STRUCTURED_OUTPUT, "mcp__lookout__get_handoffs", "mcp__attention__get_item", "mcp__attention__list_items", "mcp__attention__requests_for"}}
    for name in plan:
        allow[name] = SPECIALISTS[name].qualified_tools()
    return allow


async def run_agent(
    *,
    item_key: str,
    db_path: str,
    plan: list[str],
    prompt: str,
    services,
    workflow: str = "work_item",
    model: str | None = None,
    output_schema: dict | None = None,
    stage_allowed: bool = True,
    run_id: str | None = None,
    recorder: Recorder | None = None,
    asked_by: str | None = None,
    preface: tuple[str, dict, list] | None = None,
    tool_caps: dict | None = None,
    open_plan: bool = False,
    max_budget: float | None = None,
    started: dict | None = None,
    preload=None,
    judge=None,
    optional=(),
    turns: dict | None = None,
    action_item_key: str | None = None,
) -> RunResult:
    model = model or DEFAULT_MODEL
    groups = [[g] if isinstance(g, str) else list(g) for g in plan]  # a plan is ordered groups; members of a group work together
    plan = [m for g in groups for m in g]
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    rec = recorder or Recorder(run_id, db_path)
    ctx = RunContext(run_id=run_id, item_key=item_key, db_path=db_path, recorder=rec, plan=plan, groups=[] if open_plan else groups, open_plan=open_plan, optional=set(optional), allow=allow_map(plan), stage_allowed=stage_allowed, tool_caps=tool_caps or {}, action_item_key=action_item_key)
    if preload:  # the system's own reading of the item, registered before any model runs
        preload(ctx)
    if judge is not None and getattr(judge, "required_calls_fn", None):
        ctx.pending_calls = lambda: judge.required_calls_fn(ctx)
    system_prompt = build_system_prompt(db_path)
    lists = tool_lists(ctx, services)
    servers = build_servers(ctx, services, plan, lists)
    ver = versions(system_prompt, plan, lists, output_schema, db_path)
    label_of = lambda n: SPECIALISTS[n].label if n in SPECIALISTS else LABELS.get(n, n)

    agents = {
        n: AgentDefinition(
            description=SPECIALISTS[n].description,
            prompt=SPECIALISTS[n].instructions_for(db_path),
            tools=sorted(SPECIALISTS[n].qualified_tools()),
            model=FAST_MODEL if SPECIALISTS[n].fast and model == DEFAULT_MODEL else model,
            maxTurns=max(SPECIALISTS[n].max_turns, (turns or {}).get(n, 0)),  # a run that owes more requests than the default turns allow gets enough of them
            background=False,
            effort=EFFORT,
        )
        for n in plan
    }
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        tools=["Agent"],
        mcp_servers=servers,
        agents=agents,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[make_gate(ctx)])],
            "PostToolUse": [HookMatcher(hooks=[make_post_tool(ctx)])],
            "PostToolUseFailure": [HookMatcher(hooks=[make_post_tool_failure(ctx)])],
            "SubagentStart": [HookMatcher(hooks=[make_subagent_start(ctx, label_of)])],
            "SubagentStop": [HookMatcher(hooks=[make_subagent_stop(ctx, label_of)])],
        },
        setting_sources=[],
        strict_mcp_config=True,
        cwd=tempfile.mkdtemp(prefix="lookout-"),
        thinking={"type": THINKING},
        effort=EFFORT,
        include_partial_messages=True,
        forward_subagent_text=True,
        max_budget_usd=min(MAX_BUDGET, max_budget) if max_budget else MAX_BUDGET,
        max_turns=LOOKOUT_MAX_TURNS,
        env={"CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"},
        output_format={"type": "json_schema", "schema": output_schema} if output_schema else None,
    )

    store.insert_run(db_path, run_id=run_id, item_key=item_key, workflow=workflow, status="running", started_at=_now(), model=model, asked_by=asked_by,
                     prompt_hash=ver["prompt_hash"], toolset_hash=ver["toolset_hash"], sdk_version=sdk.__version__)
    rec.emit("run.started", f"Working {item_key}" if not started else started.pop("summary", f"Working {item_key}"), workflow=workflow, item_key=item_key, **(started or {}), model=model,
             prompt_hash=ver["prompt_hash"], toolset_hash=ver["toolset_hash"], specialist_prompts=ver["specialist_prompts"], tool_count=ver["tool_count"], sdk_version=sdk.__version__)

    if preface:  # the system's own first step: it reads the item in code before any model is asked anything
        summary, data, refs = preface
        rec.emit("tool.called", "Lookout reads the item", agent="lookout", tool="get_item", name="get_item", args={}, gate="allowed", gate_reason="system step before the model runs")
        rec.emit("tool.result", summary, agent="lookout", refs=refs, tool="get_item", name="get_item", ok=True, numbers=[], unknowns=[], **data)
    result = RunResult(run_id=run_id, status="failed", ctx=ctx)
    t0 = time.perf_counter()
    try:
        async with ClaudeSDKClient(options) as client:
            next_prompt, nudges = prompt, 0
            while True:
                await client.query(next_prompt)
                async for m in client.receive_response():
                    _handle(m, ctx, rec, result)
                if result.status != "ok":
                    break
                # Lookout sometimes ends its turn while a teammate is still working (or never asks them). Wait for whoever is running, then tell it
                # once or twice what is outstanding; the verifier still fails the run if the answer does not rest on every handoff.
                await _wait_for_running(ctx)
                expected = ctx.delegated if ctx.open_plan else [m for m in ctx.plan if m not in ctx.optional or m in ctx.delegated]
                missing = [m for m in expected if m not in ctx.handoffs]
                unread = [m for m in expected if m in ctx.handoffs and m not in ctx.handoffs_seen]
                if (missing or unread) and nudges < 2:
                    nudges += 1
                    if missing:
                        rec.emit("step.text", "Still waiting for " + " and ".join(LABELS.get(m, m) for m in missing) + " to finish", agent="lookout", system=True)
                        next_prompt = (f"Not everyone in your plan has answered yet ({', '.join(missing)}). If you have not asked them, ask them now. "
                                       "Then read their answers and write the Recommendation.")
                    else:
                        next_prompt = "Your teammates have all finished. Read their answers now, then write the Recommendation."
                    continue
                if judge is not None:  # verify and review the answer; a prompt back means "revise once"
                    again = await judge(result)
                    if again:
                        next_prompt = again
                        continue
                break
    except Exception as e:  # noqa: BLE001  a failed run is recorded, never hidden
        result.status, result.error = "failed", f"{type(e).__name__}: {e}"
        rec.emit("run.failed", f"The run failed: {result.error}", agent="lookout", error_kind=type(e).__name__, message=str(e))
    result.wall_ms = round((time.perf_counter() - t0) * 1000)
    result.first_step_ms = rec.first_step_ms
    return result


def _handle(m, ctx: RunContext, rec: Recorder, result: RunResult) -> None:
    """One SDK message -> run events and the result fields."""
    if isinstance(m, StreamEvent):
        ev = m.event
        if m.parent_tool_use_id is None and ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            rec.emit("step.delta", ev["delta"]["text"], agent="lookout")
    elif isinstance(m, AssistantMessage):
        child = ctx.child_by_tool_use.get(m.parent_tool_use_id or "")
        agent = ctx.pending.get(m.parent_tool_use_id or "", {}).get("specialist", "lookout")
        for b in m.content:
            if isinstance(b, TextBlock) and b.text.strip():
                (child or rec).emit("step.text", b.text.strip(), agent=agent)
    elif isinstance(m, (TaskProgressMessage, TaskNotificationMessage)) and m.usage:  # what each teammate used, as the SDK reports it for its task
        who = ctx.pending.get(m.tool_use_id or "", {}).get("specialist")
        if who:
            ctx.tokens_by_agent[who] = {"tokens": m.usage["total_tokens"], "tool_uses": m.usage["tool_uses"], "duration_ms": m.usage["duration_ms"]}
    elif isinstance(m, ResultMessage):
        result.structured_output = m.structured_output
        result.cost_usd = m.total_cost_usd
        result.turns = m.num_turns
        result.status = "ok" if m.subtype == "success" and not m.is_error else "failed"
        result.error = m.subtype if result.status == "failed" else None
        usage = m.model_usage or {}
        result.tokens_cache_read = sum(u.get("cacheReadInputTokens", 0) for u in usage.values())
        result.tokens_cache_creation = sum(u.get("cacheCreationInputTokens", 0) for u in usage.values())
        result.tokens_in = sum(u.get("inputTokens", 0) for u in usage.values()) + result.tokens_cache_read + result.tokens_cache_creation  # everything the model read, cached or not
        result.tokens_out = sum(u.get("outputTokens", 0) for u in usage.values())


async def _wait_for_running(ctx: RunContext, timeout: float = 45.0) -> None:
    """A teammate Lookout asked may still be working when Lookout ends its turn: give it time to finish before anything is judged."""
    t0 = time.perf_counter()
    while ctx.running and time.perf_counter() - t0 < timeout:
        await asyncio.sleep(0.25)


def finish(result: RunResult, *, status: str | None = None, recommendation_json: str | None = None, verifier_json: str | None = None) -> None:
    """Close the run: one run.finished event (always written) and the run row."""
    ctx, rec = result.ctx, result.ctx.recorder
    status = status or result.status
    total_calls = rec.tool_calls + sum(c.tool_calls for c in ctx.children.values())
    denied = rec.denied_calls + sum(c.denied_calls for c in ctx.children.values())
    store.update_run(ctx.db_path, ctx.run_id, status=status, cost_usd=result.cost_usd, wall_ms=result.wall_ms, first_step_ms=result.first_step_ms,
                     turns=result.turns, tool_calls=total_calls, denied_calls=denied, recommendation_json=recommendation_json,
                     verifier_json=verifier_json)
    # the row says the final status before the stream says the run is over, so a page that reads the run when the
    # stream ends never sees "running"
    rec.emit("run.finished", f"Run {status}", agent="lookout", status=status, turns=result.turns, tool_calls=total_calls,
             cost_usd=None if result.cost_usd is None else round(result.cost_usd, 4), wall_ms=result.wall_ms, first_step_ms=result.first_step_ms, first_token_ms=rec.first_token_ms, recommendation_id=ctx.run_id, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
             tokens_cache_read=result.tokens_cache_read, tokens_cache_creation=result.tokens_cache_creation, tokens_by_agent=ctx.tokens_by_agent)


async def run_without_model(*, item_key: str, db_path: str, services, workflow: str = "work_item", run_id: str | None = None, recorder: Recorder | None = None,
                            asked_by: str | None = None, preface=None, preload=None) -> RunResult:
    """A run the system answers alone: the same run record, events and verifier, no model and no cost. Used where
    the right answer is fixed by code (a trust item: do not act)."""
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    rec = recorder or Recorder(run_id, db_path)
    ctx = RunContext(run_id=run_id, item_key=item_key, db_path=db_path, recorder=rec, plan=[], allow={}, stage_allowed=False)
    if preload:
        preload(ctx)
    store.insert_run(db_path, run_id=run_id, item_key=item_key, workflow=workflow, status="running", started_at=_now(), model="none (written by code)",
                     prompt_hash="", toolset_hash="", sdk_version=sdk.__version__, asked_by=asked_by)
    rec.emit("run.started", f"Working {item_key}", workflow=workflow, item_key=item_key, model="none (written by code)", prompt_hash="", toolset_hash="", sdk_version=sdk.__version__)
    if preface:
        summary, data, refs = preface
        rec.emit("tool.called", "Lookout reads the item", agent="lookout", tool="get_item", name="get_item", args={}, gate="allowed", gate_reason="system step")
        rec.emit("tool.result", summary, agent="lookout", refs=refs, tool="get_item", name="get_item", ok=True, numbers=[], unknowns=[], **data)
    result = RunResult(run_id=run_id, status="ok", ctx=ctx, cost_usd=0.0, turns=0, wall_ms=0)
    result.first_step_ms = rec.first_step_ms
    return result
