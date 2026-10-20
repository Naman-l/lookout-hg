"""The gate's decisions, with no model: allow-lists by agent_type, the delegation plan, budgets, trust items."""

import asyncio

from app.organism.gate import decide, make_gate

PLANNER_TOOL = "mcp__orders__open_supply"
DRAFT = "mcp__actions__draft_supplier_request"


def test_lookout_may_delegate_in_plan_order(ctx):
    assert decide(ctx, None, "Agent", {"subagent_type": "supply_planner"})[0]
    ok, why = decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})
    assert not ok and "supply_planner next" in why


def test_delegation_stops_when_plan_is_used(ctx):
    ctx.delegated = ["supply_planner", "buyers_clerk"]
    assert not decide(ctx, None, "Agent", {"subagent_type": "supply_planner"})[0]


def test_specialists_do_not_delegate(ctx):
    assert not decide(ctx, "supply_planner", "Agent", {"subagent_type": "buyers_clerk"})[0]


def test_each_agent_sees_only_its_own_tools(ctx):
    assert decide(ctx, "supply_planner", PLANNER_TOOL, {})[0]
    assert not decide(ctx, "buyers_clerk", PLANNER_TOOL, {})[0]
    assert not decide(ctx, None, PLANNER_TOOL, {})[0]
    assert not decide(ctx, "supply_planner", DRAFT, {})[0]


def test_only_the_clerk_may_draft(ctx):
    assert decide(ctx, "buyers_clerk", DRAFT, {})[0]
    assert not decide(ctx, "supply_planner", DRAFT, {})[0]


def test_unknown_and_builtin_tools_are_refused(ctx):
    for name in ("Bash", "Write", "WebFetch", "mcp__made__up", ""):
        assert not decide(ctx, None, name, {})[0]
        assert not decide(ctx, "supply_planner", name, {})[0]


def test_nothing_is_drafted_on_a_trust_item(ctx):
    ctx.stage_allowed = False
    ok, why = decide(ctx, "buyers_clerk", DRAFT, {})
    assert not ok and "not a supplier on file" in why


def test_call_budget_is_enforced_per_agent(ctx):
    ctx.max_calls_per_agent = 2
    ctx.calls["supply_planner"] = 2
    ok, why = decide(ctx, "supply_planner", PLANNER_TOOL, {})
    assert not ok and "wrap up" in why
    assert decide(ctx, "buyers_clerk", DRAFT, {})[0]


def test_only_lookout_writes_the_recommendation(ctx):
    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)  # the team has answered and Lookout has read it
    assert decide(ctx, None, "StructuredOutput", {})[0]
    assert not decide(ctx, "supply_planner", "StructuredOutput", {})[0]


def test_hook_returns_an_explicit_allow_or_deny_and_records_it(ctx):
    gate = make_gate(ctx)
    allow = asyncio.run(gate({"tool_name": PLANNER_TOOL, "tool_input": {}, "tool_use_id": "t1", "agent_type": "supply_planner", "agent_id": "a1"}, "t1", None))
    deny = asyncio.run(gate({"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "t2"}, "t2", None))
    assert allow["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert deny["hookSpecificOutput"]["permissionDecisionReason"]
    gates = [e.payload["gate"] for e in ctx.recorder.events if e.type == "tool.called"]
    assert gates == ["allowed", "denied"]


def test_delegation_through_the_hook_records_the_pending_call(ctx):
    gate = make_gate(ctx)
    out = asyncio.run(gate({"tool_name": "Agent", "tool_input": {"subagent_type": "supply_planner", "description": "Work HR-40110"}, "tool_use_id": "tu1"}, "tu1", None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert ctx.delegated == ["supply_planner"] and ctx.pending["tu1"]["task"] == "Work HR-40110"


def test_a_specialist_cannot_be_sent_to_the_background(ctx):
    ok, why = decide(ctx, None, "Agent", {"subagent_type": "supply_planner", "run_in_background": True})
    assert not ok and "background" in why


def test_lookout_and_the_clerk_may_read_the_handoffs_and_the_item(ctx):
    assert decide(ctx, None, "mcp__lookout__get_handoffs", {})[0]
    assert decide(ctx, "buyers_clerk", "mcp__lookout__get_handoffs", {})[0]
    assert decide(ctx, None, "mcp__attention__get_item", {})[0]
    assert not decide(ctx, "supply_planner", "mcp__lookout__get_handoffs", {})[0]


def test_logging_a_question_counts_as_drafting_so_a_trust_item_refuses_it(ctx):
    assert decide(ctx, "buyers_clerk", "mcp__actions__log_buyer_question", {})[0]
    ctx.stage_allowed = False
    assert not decide(ctx, "buyers_clerk", "mcp__actions__log_buyer_question", {})[0]


def test_a_specialist_cannot_be_sent_to_the_background(ctx):
    ok, why = decide(ctx, None, "Agent", {"subagent_type": "supply_planner", "run_in_background": True})
    assert not ok and "background" in why


def test_a_tool_cap_bounds_how_many_parts_a_run_examines(ctx):
    ctx.tool_caps = {"exposure_for_part": 2}
    name = "mcp__tariffs__exposure_for_part"
    ctx.allow["tariff_analyst"] = {name}
    assert decide(ctx, "tariff_analyst", name, {})[0]
    ctx.tool_counts["exposure_for_part"] = 2
    ok, why = decide(ctx, "tariff_analyst", name, {})
    assert not ok and "enough" in why


def test_plans_by_item(ctx):
    from app.organism.workflows.work_item import plan_for

    assert plan_for("disruption", "disruption:SUP-0001") == ["supply_planner", "buyers_clerk"]
    assert plan_for("tariff", "tariff:HR-40110") == [["tariff_analyst", "sourcing_analyst"], "buyers_clerk"]  # a part: the duty and, beside it, the offers (an alternative origin is a claim to confirm)
    assert plan_for("tariff", "tariff:all") == ["tariff_analyst"]
    assert plan_for("unknown", "unknown:HR-12120") == ["tariff_analyst", "buyers_clerk"]
    assert plan_for("unknown", "unknown:stale-orders") == ["supply_planner", "buyers_clerk"]
    assert plan_for("unknown", "unknown:undated") == ["supply_planner", "buyers_clerk"]  # an order with no promised date is a supply question, not a duty one
    assert plan_for("unknown", "unknown:HPO-26-00450/10") == ["supply_planner", "buyers_clerk"] == plan_for("unknown", "unknown:PO-10711/1")
    assert plan_for("unknown", "unknown:origin") == ["tariff_analyst", "buyers_clerk"] and plan_for("unknown", "unknown:hts") == ["tariff_analyst"]   # plan-13 item 7: origin gets its letters
    assert plan_for("deadline", "deadline:SUP-0001:2026-10-13") == ["supply_planner", "buyers_clerk"]
    assert plan_for("disruption", "risk:SUP-0002") == ["sourcing_analyst", "buyers_clerk"] == plan_for("deadline", "deadline:quotes")   # plan-13 item 3
    assert plan_for("deadline", "deadline:SUP-0041:2026-10-15") == ["supply_planner", "buyers_clerk"] == plan_for("deadline", "deadline:chase")   # a price lock and a chase stay the planner's
    assert plan_for("trust", "trust:x") == []


def test_independent_specialists_in_one_step_of_the_plan_may_be_asked_together(ctx):
    ctx.plan = ["supply_planner", "sourcing_analyst", "buyers_clerk"]
    ctx.groups = [["supply_planner", "sourcing_analyst"], ["buyers_clerk"]]
    assert decide(ctx, None, "Agent", {"subagent_type": "sourcing_analyst"})[0]  # either order within the group
    ctx.delegated = ["sourcing_analyst"]
    assert decide(ctx, None, "Agent", {"subagent_type": "supply_planner"})[0]
    assert not decide(ctx, None, "Agent", {"subagent_type": "sourcing_analyst"})[0]  # no repeats
    assert not decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})[0]  # not before the group is asked
    ctx.delegated = ["sourcing_analyst", "supply_planner"]
    ok, why = decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})
    assert not ok and "finish" in why  # not until the group has handed off
    ctx.handoffs.update(supply_planner=object(), sourcing_analyst=object())
    assert decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})[0]


def test_compare_quotes_and_the_fire_plans():
    from app.organism.workflows.work_item import plan_for

    assert plan_for("compare", "compare:HR-40110") == ["sourcing_analyst"]
    assert plan_for("disruption", "disruption:SUP-0001") == ["supply_planner", "buyers_clerk"]


def test_the_prompt_states_the_plan_and_which_steps_run_together():
    from types import SimpleNamespace

    from app.organism.workflows.work_item import build_prompt

    item = SimpleNamespace(key="disruption:SUP-0001", group="disruption", title="Fire", owner="Dana", refs=[])
    p = build_prompt(item)
    assert "Step 1: supply_planner" in p and "Step 2: buyers_clerk" in p


def test_ask_lets_lookout_choose_whom_to_ask_within_limits(ctx):
    ctx.open_plan, ctx.groups = True, []
    ctx.plan = ["supply_planner", "tariff_analyst", "sourcing_analyst", "buyers_clerk"]
    assert decide(ctx, None, "Agent", {"subagent_type": "tariff_analyst"})[0]
    ctx.delegated = ["tariff_analyst"]
    assert not decide(ctx, None, "Agent", {"subagent_type": "tariff_analyst"})[0]  # once each
    assert not decide(ctx, None, "Agent", {"subagent_type": "nobody"})[0]
    ctx.delegated = ["tariff_analyst", "supply_planner", "sourcing_analyst"]
    ok, why = decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})
    assert not ok and "at most 3" in why
    ctx.stage_allowed = False
    assert not decide(ctx, "buyers_clerk", "mcp__actions__draft_supplier_request", {})[0]  # a trust context still drafts nothing


def test_a_step_with_two_members_tells_lookout_to_ask_them_together():
    from app.organism.workflows.work_item import describe_plan

    text = describe_plan([["supply_planner", "sourcing_analyst"], "buyers_clerk"])
    assert "Step 1: supply_planner AND sourcing_analyst" in text and "SAME message" in text and "Step 2: buyers_clerk" in text


def test_an_optional_step_may_be_skipped_and_is_not_owed_a_handoff(ctx, db, services):
    from app.organism.verifier import verify

    from .test_verifier import good, seed

    ctx.plan, ctx.groups, ctx.optional = ["inbox_analyst", "buyers_clerk"], [["inbox_analyst"], ["buyers_clerk"]], {"buyers_clerk"}
    ctx.delegated, ctx.handoffs = ["inbox_analyst"], {"inbox_analyst": object()}
    ok, _ = decide(ctx, None, "Agent", {"subagent_type": "buyers_clerk"})
    assert ok  # still allowed if Lookout wants it
    a = seed(ctx, db)
    ctx.handoffs.pop("buyers_clerk", None)
    ctx.action_ids.clear()
    d = good(a)
    d["action_ids"] = []
    assert not any("handoffs" in f for f in verify(ctx, d, services=services)[1].failures)  # an unused optional step owes nothing
    ctx.delegated.append("buyers_clerk")
    assert any("handoffs" in f for f in verify(ctx, d, services=services)[1].failures)  # once asked, it must hand off


def test_triage_and_reply_plans_and_which_clerk_steps_are_optional():
    from types import SimpleNamespace

    from app.domain.common import EntityRef
    from app.organism.workflows.work_item import optional_for, plan_for

    assert plan_for("triage", "triage:x") == ["inbox_analyst", "buyers_clerk"] == plan_for("reply", "reply:x")
    sup = SimpleNamespace(key="reply:x", group="reply", refs=[EntityRef(type="message", id="x"), EntityRef(type="supplier", id="SUP-0001")])
    new = SimpleNamespace(key="reply:y", group="reply", refs=[EntityRef(type="message", id="y")])
    assert optional_for(sup) == set() and optional_for(new) == {"buyers_clerk"}
    assert optional_for(SimpleNamespace(key="triage:x", group="triage", refs=[])) == {"buyers_clerk"}


def test_a_lookup_by_supplier_does_not_demand_a_shortage_run_for_the_supplier(ctx):
    """A slip's open_supply by supplier id writes supply:<supplier>:stuck_qty; only a part number can have a shortage run for it."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.workflows.work_item import required_calls

    ctx.register([Number(id="supply:SUP-0013:stuck_qty", name="stuck", value=Decimal(5), unit="EA"), Number(id="supply:HR-51110:stuck_qty", name="stuck", value=Decimal(3), unit="EA")])
    assert required_calls("disruption", "disruption:SUP-0013", ctx) == [("shortage", "HR-51110")]


def test_a_morning_runs_answer_is_written_to_the_one_buyer_who_will_read_it():
    """P5: the fire said 'logged for Dana Reyes' to Dana. Nobody asked a morning run, so its reader is the item's owner; two owners are named, not addressed."""
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import build_prompt

    item = lambda owner: NS(key="disruption:SUP-0001", group="disruption", title="Fire", owner=owner, refs=[])
    assert "Dana Reyes will read the answer: speak to them as 'you' and 'your'" in build_prompt(item("Dana Reyes"), "Morning run")
    assert "speak to them as 'you'" not in build_prompt(item("Priya Nair · Dana Reyes"), "Morning run")
    assert "name that buyer" in build_prompt(item("Dana Reyes"), "Marcus Chen")  # a different buyer asking: unchanged
    assert "is asking, and this is their own item" in build_prompt(item("Dana Reyes"), "Dana Reyes")


def test_a_sender_who_is_not_a_supplier_on_file_stages_nothing_not_even_a_note(ctx):
    """Round 6 control: the model logged an internal note on an unvetted sender's thread in 19 of 29 trials. Code stops it; no model is asked to behave."""
    ctx.stage_allowed = False
    for tool in ("draft_supplier_request", "log_buyer_question", "propose_supplier_alias"):
        ok, why = decide(ctx, "buyers_clerk", f"mcp__actions__{tool}", {})
        assert not ok and "not a supplier on file" in why and "item already tells the buyer" in why
    assert decide(ctx, "buyers_clerk", "mcp__attention__get_item", {})[0]  # reading is still fine


def test_reading_a_message_from_a_sender_the_master_does_not_vouch_for_closes_staging_for_the_run(ctx):
    import asyncio
    from types import SimpleNamespace as NS

    from app.domain.inbox import tools as inbox_tools

    d = NS(subject="Quote", body="Our quote for the motor is attached.", changes=[], summary=NS(from_="x@new.example", date="2026-09-24", supplier=None, trust="new_sender"))
    mk = lambda api: NS(message_detail=lambda m: d, classify=lambda m: NS(level=1, kind=None, confidence=0, decision="review", reason="", evidence=[]),
                        trust=lambda m: NS(flags=[], may_act=True, api_trust=api, verdict="ok"), thread_for=lambda m: None)
    t = {x.name: x for x in inbox_tools.make_tools(ctx, mk("on_file"))}
    asyncio.run(t["read_message"].handler({"message_id": "m1"}))
    assert ctx.stage_allowed  # a supplier on file: nothing changes
    t = {x.name: x for x in inbox_tools.make_tools(ctx, mk("new_sender"))}
    asyncio.run(t["read_message"].handler({"message_id": "m2"}))
    assert not ctx.stage_allowed and not decide(ctx, "buyers_clerk", "mcp__actions__log_buyer_question", {})[0]


def test_a_triage_or_reply_on_a_new_sender_starts_with_staging_closed():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import sender_is_vetted

    svc = NS(inbox=NS(trust=lambda mid: NS(api_trust="new_sender" if mid == "vpm" else "on_file", verdict="ok")))
    assert not sender_is_vetted("reply:vpm", svc) and not sender_is_vetted("triage:vpm", svc)
    assert sender_is_vetted("reply:yunzhan", svc) and sender_is_vetted("disruption:SUP-0001", svc)


def test_the_clerk_is_never_started_for_an_unvetted_sender_and_the_prompt_says_what_to_do_instead():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import build_prompt, run_plan

    svc = NS(inbox=NS(trust=lambda mid: NS(api_trust="new_sender" if mid == "vpm" else "on_file", verdict="ok")))
    item = lambda key: NS(key=key, group=key.split(":")[0], title="A message", owner="", refs=[NS(type="supplier", id="SUP-0001", label="x")])
    assert run_plan(item("reply:vpm"), svc) == ["inbox_analyst"] and run_plan(item("triage:vpm"), svc) == ["inbox_analyst"]
    assert run_plan(item("reply:yunzhan"), svc) == ["inbox_analyst", "buyers_clerk"] and run_plan(item("disruption:SUP-0001"), svc) == ["supply_planner", "buyers_clerk"]
    p = build_prompt(item("reply:vpm"), None, "", run_plan(item("reply:vpm"), svc))
    assert "nothing is drafted and nothing is logged" in p and "open questions, with its owner" in p and "buyers_clerk" not in p
    assert "Today, in this data, is Friday 25 September 2026" in p and "never from a clock on the machine" in p
    assert "buyers_clerk" in build_prompt(item("reply:yunzhan"), None, "", run_plan(item("reply:yunzhan"), svc))


def test_nothing_is_chased_before_the_date_the_supplier_promised(monkeypatch):
    """O2: the 10 October deadline staged 'we have not yet received them' on a data date of 25 September."""
    from datetime import date
    from types import SimpleNamespace as NS

    from app.organism.workflows import work_item
    from app.organism.workflows.work_item import build_prompt, run_plan, waiting

    item = lambda until: NS(key="deadline:SUP-0001:2026-10-10", group="deadline", title="Yunzhan promised revised dates by Oct 10: chase if they do not come", owner="Dana Reyes", refs=[], waits_until=until)
    assert waiting(item("2026-10-10")) and not waiting(item(None)) and not waiting(item("2026-09-20"))  # the data date is 25 September
    svc = NS()
    assert run_plan(item("2026-10-10"), svc) == ["supply_planner"] and run_plan(item(None), svc) == ["supply_planner", "buyers_clerk"]
    p = build_prompt(item("2026-10-10"), None, "", run_plan(item("2026-10-10"), svc))
    assert "a promise to wait for" in p and "2026-10-10" in p and "Draft nothing and do not chase" in p
    assert "promise to wait for" not in build_prompt(item(None), None, "", run_plan(item(None), svc))
    monkeypatch.setattr("app.domain.common.AS_OF", date(2026, 10, 11))  # after the date the chase is on again
    assert not waiting(item("2026-10-10")) and run_plan(item("2026-10-10"), svc) == ["supply_planner", "buyers_clerk"]


def test_an_ask_is_told_its_answer_stands_alone():
    """O13: an Ask answer said 'the four ways through are laid out below' with nothing below: item-page phrasing in a chat reply."""
    from app.organism.workflows.ask import build_prompt

    p = build_prompt("What should I do about the Yunzhan notice?", None, "Dana Reyes")
    assert "shown in the Ask panel beside the page" in p and "'below'" in p and "laid out" in p and "never point to the layout" in p      # h10: it may name the page, never the layout


def test_the_constitution_makes_lookout_a_system_that_does_not_speak_as_a_person():
    """O20: the agent said 'it is not mine to close' and 'Dana Reyes's colleague'."""


def test_the_constitution_asks_for_a_decision_sentence_points_and_a_next_step():
    from pathlib import Path

    import app.organism as org

    text = (Path(org.__file__).parent / "constitution.md").read_text()
    assert "a system, not a person" in text and "never \"I\"" in text and "not mine to close" in text


def test_the_constitution_says_last_paid_with_the_duty_and_never_counts_a_stale_line_under_the_notice():
    from pathlib import Path

    import app.organism as org

    text = (Path(org.__file__).parent / "constitution.md").read_text()
    assert "`last_paid_usd`" in text and "`with_new_duty_usd`" in text and "Never call the second one what was paid" in text
    assert "A stale line is never counted under the notice" in text and "never say no notice is on file when it returns lines" in text


    assert "ONE sentence of at most 20 words" in text and "`points`" in text and "`next_step`" in text


def test_the_live_status_is_one_line_naming_the_specialist_and_the_step():
    from app.organism.purposes import STATUS, status
    from app.organism.specialists.registry import TOOL_SERVER

    assert status("Supply planner", "open_supply") == "Supply planner: checking the open orders"
    assert status("Supply planner", "unknown_tool") == "Supply planner: working"
    assert not [t for t in TOOL_SERVER if t not in STATUS and t not in ("get_handoffs", "add_finding", "add_question")], "every tool a role can call has a status phrase"


def test_a_tariff_items_rate_owed_conditional_and_uncovered_quantity_are_always_cited_by_code():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import headline_ids

    ev = {i: None for i in ("tariff:HR-50110:rate", "tariff:HR-50110:net", "tariff:HR-50110:conditional", "tariff:HR-50110:uncovered_qty", "tariff:HR-50110:gross", "tariff:HR-50110:reference_price", "item:tariff:HR-50110:at_stake")}
    assert headline_ids("tariff", NS(evidence=ev)) == ["item:tariff:HR-50110:at_stake", "tariff:HR-50110:conditional", "tariff:HR-50110:gross", "tariff:HR-50110:net", "tariff:HR-50110:rate", "tariff:HR-50110:uncovered_qty"]


def test_the_constitution_names_the_fix_pass_rules():
    from pathlib import Path

    import app.organism as org

    text = (Path(org.__file__).parent / "constitution.md").read_text()
    for needle in ("states the decision or the state and why", "at most 3 rows", "origin to confirm", "single-sourced", "do not also log a note"):
        assert needle in text, needle


def test_the_ways_through_are_called_laid_out_below_only_when_the_context_lists_them():
    from pathlib import Path

    import app.organism as org

    text = (Path(org.__file__).parent / "constitution.md").read_text()
    assert 'lists "The ways through"' in text and "do not mention them" in text and "laid out below" not in text and "as a buyer would say it to a colleague" in text and "last paid $100.00 ($125.00 with the duty)" in text
    clerk = (Path(org.__file__).parent / "specialists" / "buyers_clerk" / "instructions.md").read_text()
    assert "SUP-0001" not in clerk


def test_the_recommendation_cannot_be_written_while_a_handoff_is_unread(ctx):
    """3 of the 5 real did_not_pass results were 'written before reading the handoff of buyers_clerk': enforced in code, not in the prompt."""
    from app.organism.gate import decide

    ctx.delegated = ["supply_planner"]
    ok, why = decide(ctx, None, "StructuredOutput", {})
    assert not ok and "wait for" in why and "Buyer's clerk" in why or "clerk" in why.lower()  # the clerk was never asked, the planner has not handed off
    ctx.delegated = ["supply_planner", "buyers_clerk"]
    ctx.handoffs.update(supply_planner=object())
    ok, why = decide(ctx, None, "StructuredOutput", {})
    assert not ok and "wait for" in why  # the clerk was asked and has not handed off
    ctx.handoffs.update(buyers_clerk=object())
    ok, why = decide(ctx, None, "StructuredOutput", {})
    assert not ok and "handoff first (get_handoffs)" in why and "clerk" in why.lower()  # both handed off, none read
    ctx.handoffs_seen = set(ctx.handoffs)
    assert decide(ctx, None, "StructuredOutput", {}) == (True, "Recommendation")
    assert decide(ctx, "supply_planner", "StructuredOutput", {})[0] is False


def test_an_answer_that_is_too_long_is_refused_when_written_so_it_is_rewritten_in_the_same_turn(ctx):
    """Khalid's run ended did_not_pass on a 24-word finding: the shape is checked at the write, not left to fail the run."""
    from app.organism.gate import decide

    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    fine = {"finding": "Order the short parts so 200 robots can ship before the quote lapses.", "points": [{"label": "Short", "text": "Three parts run out."}]}
    assert decide(ctx, None, "StructuredOutput", fine) == (True, "Recommendation")
    long = {"finding": " ".join(["word"] * 24), "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", long)
    assert not ok and why.startswith("rewrite it to fit") and "24 words" in why
    ctx.open_plan = True
    ok, why = decide(ctx, None, "StructuredOutput", {"finding": "Short.", "points": [{"label": "a", "text": "b"}] * 4})
    assert not ok and "at most 3" in why


def test_an_item_spanning_five_suppliers_gets_five_reads_not_three():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import caps_for

    five = NS(refs=[NS(type="supplier", id=f"S{i}") for i in range(5)] + [NS(type="message", id="m")])
    assert caps_for("unknown", "unknown:x", five)["open_supply"] == 6 and caps_for("unknown", "unknown:x", NS(refs=[]))["open_supply"] == 3
    assert caps_for("unknown", "unknown:x", NS(refs=[NS(type="supplier", id=str(i)) for i in range(40)]))["open_supply"] == 12


def test_a_message_the_trust_check_does_not_clear_never_starts_the_clerk_and_a_headline_needs_a_stake_and_an_action(ctx):
    """ROUND 10: control-injection-model-triage started the clerk on the injected mail; QUALITY: the judge wants the headline to say what is at stake and what to do."""
    from types import SimpleNamespace as NS

    from app.organism.gate import decide
    from app.organism.workflows.work_item import sender_is_vetted

    svc = lambda api, verdict: NS(inbox=NS(trust=lambda m: NS(api_trust=api, verdict=verdict)))  # noqa: E731
    assert sender_is_vetted("triage:m", svc("on_file", "ok")) and not sender_is_vetted("triage:m", svc("on_file", "review")) and not sender_is_vetted("reply:m", svc("on_file", "blocked"))
    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ok, why = decide(ctx, None, "StructuredOutput", {"finding": "The supplier sent revised dates.", "points": []})
    assert not ok and "say what is at stake" in why and "say what to do" in why
    assert decide(ctx, None, "StructuredOutput", {"finding": "Ask the supplier to confirm 182 robots' parts by 10 Oct.", "points": []})[0]


def test_the_constitution_gives_the_headline_shape():
    from pathlib import Path

    import app.organism as org

    assert "puts <money or robots> at risk by <date>; <action> (<who> by <date>)" in (Path(org.__file__).parent / "constitution.md").read_text()


def test_the_calls_a_notice_needs_are_owed_by_the_planner_and_never_deadlock_the_write(ctx):
    """The consignment and incident recordings ended did_not_pass ('shortage was not run for HR-…'). R2b: refusing Lookout's write for them after the
    planner had handed off looped a live run to its turn limit with no answer (Lookout cannot run a planner tool, and the plan had no step left).
    Now the planner cannot hand off while they are owed, and Lookout may always write once it has: the verifier records any gap."""
    import asyncio

    from app.organism.gate import decide
    from app.organism.specialists import handoff

    ctx.pending_calls = lambda: [("shortage", "PART-1"), ("shortage", "PART-2")]
    ctx.calls_made.add(("shortage", "PART-1"))
    ctx.reads_ok["supply_planner"] = 1
    submit = handoff.make_handoff_tool(ctx, "supply_planner")
    out = asyncio.run(submit.handler({"findings": ["x"]}))
    assert "run shortage_for_parts for PART-2" in str(out) and "supply_planner" not in ctx.handoffs
    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    assert decide(ctx, None, "StructuredOutput", {"finding": "Approve the request for 200 robots.", "points": []})[0]   # never a dead end


def test_a_quote_messages_prices_and_totals_are_cited_by_id_by_code():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import headline_ids

    ev = {i: None for i in ("quote:HR-12210:q1:price", "quote:HR-12210:q1:total", "quote:HR-12210:q1:duty", "quote:HR-12210:current:price", "item:x:at_stake")}
    assert headline_ids("triage", NS(evidence=ev)) == ["quote:HR-12210:current:price", "quote:HR-12210:q1:price", "quote:HR-12210:q1:total"] == headline_ids("reply", NS(evidence=ev))
    assert headline_ids("compare", NS(evidence=ev)) == headline_ids("triage", NS(evidence=ev))


def test_a_cases_finding_is_its_situation_and_needs_no_action_word(ctx):
    """F74 P1: on an Action-list case the finding says what happened and what it hits; the next step carries the action."""
    from app.organism.gate import decide

    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    situation = {"finding": "Yunzhan's fire stops 10 open lines; 182 Terns and 40 Porters short in October.", "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", situation)
    assert not ok and "say what to do" in why                                    # not a case (Ask, a message): the headline rule holds
    ctx.is_case = True
    assert decide(ctx, None, "StructuredOutput", situation)[0]
    ok, why = decide(ctx, None, "StructuredOutput", {"finding": "Yunzhan had a fire.", "points": []})
    assert not ok and "say what is at stake" in why and "say what to do" not in why  # the stake is still required


def test_a_supplier_at_risk_is_judged_by_its_record_and_quote_not_by_a_notice():
    """plan-13 item 3: risk items are in the disruption group, but sourcing works them; the verifier must not ask for disrupted_supply."""
    from types import SimpleNamespace

    from app.organism.specialists.registry import SPECIALISTS
    from app.organism.workflows.work_item import REQUIRED_TOOLS, judged_as

    assert judged_as(SimpleNamespace(key="risk:SUP-0002", group="disruption")) == "risk" and judged_as(SimpleNamespace(key="disruption:SUP-0001", group="disruption")) == "disruption"
    assert REQUIRED_TOOLS["risk"] == ("supplier_delivery", "compare_offers")
    assert set(REQUIRED_TOOLS["risk"]) <= set(SPECIALISTS["sourcing_analyst"].tools)
    assert {"supplier_delivery", "open_supply", "where_used_for_parts", "get_item"} <= set(SPECIALISTS["sourcing_analyst"].tools)


def test_a_cases_situation_is_at_most_fourteen_words(ctx):
    """F105 (Khalid: clean, only important content): the page shows the facts beside it, so the Situation is short. The gate asks for a rewrite in the same turn."""
    from app.organism.gate import decide

    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ctx.is_case = True
    long = {"finding": "Yunzhan's fire stops 10 open lines, so 182 Terns and 40 Porters are short in October.", "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", long)
    assert not ok and "at most 14 on a case" in why
    ctx.is_case = False
    assert decide(ctx, None, "StructuredOutput", {"finding": long["finding"] + " Ask Li Wei.", "points": []})[0]   # not a case: the 20-word headline rule holds


def test_an_over_long_recommended_reason_or_finding_meaning_is_rewritten_in_the_same_turn(ctx):
    """F108 preview: a 9-word reason and a 9-word meaning were dropped by the verifier after the fact; the gate now asks for the rewrite while it can."""
    from app.organism.gate import decide

    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ctx.is_case = True
    base = {"finding": "Yunzhan's fire leaves 182 Terns and 40 Porters short in October.", "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "allocation", "reason": "fastest answer for all ten lines, keeps our rights reserved", "number_ids": []}})
    assert not ok and "recommended reason has 10 words; at most 8" in why
    ok, why = decide(ctx, None, "StructuredOutput", {**base, "findings": [{"key": "restart_window", "meaning": "Nothing from the burned plant arrives before the third of November"}]})
    assert not ok and "meaning of restart_window has 11 words" in why
    assert decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "allocation", "reason": "covers all open lines, rights reserved"}, "findings": [{"key": "past_due", "meaning": "Late lines predate the fire"}]})[0]


def test_a_recommended_reason_states_only_figures_it_cites(ctx):
    """G1 (PREVIEW 2b): a reason said "100% T/T" with no id behind it; each figure in the reason is one of its number_ids, or it is rewritten."""
    from decimal import Decimal

    from app.organism.schemas import Number

    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ctx.is_case = True
    ctx.register([Number(id="supply:SUP-0013:open_lines", name="open lines", value=Decimal(10), unit="EA")])
    base = {"finding": "Yunzhan's fire leaves 182 Terns and 40 Porters short in October.", "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "allocation", "reason": "covers all 10 lines", "number_ids": []}})
    assert not ok and "the recommended reason states 10" in why                                       # must FAIL: uncited
    ok, why = decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "allocation", "reason": "covers all 12 lines", "number_ids": ["supply:SUP-0013:open_lines"]}})
    assert not ok and "states 12" in why                                                             # must FAIL: cited, but a different figure
    assert decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "allocation", "reason": "covers all 10 lines", "number_ids": ["supply:SUP-0013:open_lines"]}})[0]


def test_a_price_lock_recommends_the_option_its_letter_acts_on(ctx):
    """BUYER R2b (the deadline case): the letter acknowledged the lines at today's price while the mark said extend."""
    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ctx.is_case = True
    ctx.option_kinds = ["buy_ahead", "accept", "extend"]
    base = {"finding": "A price rise from 1 November; open lines keep today's price if acknowledged.", "points": []}
    ok, why = decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "extend", "reason": "more time to decide"}})
    assert not ok and "recommend buy_ahead" in why                                                    # must FAIL
    assert decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "buy_ahead", "reason": "open lines keep today's price"}})[0]
    ctx.option_kinds = ["bridge", "extend"]                                                            # quotes: extend is a real way through
    assert decide(ctx, None, "StructuredOutput", {**base, "recommended": {"kind": "extend", "reason": "the first quote lapses soonest"}})[0]
