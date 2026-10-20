"""The per-run state every hook and tool closes over: the recorder, the evidence register, the plan."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..domain.common import Unknown
from .runs.events import Recorder
from .schemas import Handoff, Number


@dataclass
class RunContext:
    run_id: str
    item_key: str
    db_path: str
    recorder: Recorder
    plan: list[str]  # specialists Lookout may delegate to; empty = delegation refused
    allow: dict[str | None, set[str]]  # agent_type (None = Lookout's own thread) -> permitted tool names
    max_calls_per_agent: int = 24
    groups: list = field(default_factory=list)  # the plan as ordered groups; members of a group work independently, together
    evidence: dict[str, Number] = field(default_factory=dict)
    unknowns: list[Unknown] = field(default_factory=list)
    handoffs: dict[str, Handoff] = field(default_factory=dict)
    action_ids: list[str] = field(default_factory=list)
    delegated: list[str] = field(default_factory=list)
    calls: Counter = field(default_factory=Counter)
    # Agent tool_use_id -> {"specialist", "task"}; agent_id -> child Recorder
    pending: dict[str, dict] = field(default_factory=dict)
    children: dict[str, Recorder] = field(default_factory=dict)
    child_by_tool_use: dict[str, Recorder] = field(default_factory=dict)
    numbers_by_agent: dict = field(default_factory=dict)  # agent_type -> number ids its tools returned
    unknowns_by_agent: dict = field(default_factory=dict)
    actions_by_agent: dict = field(default_factory=dict)
    tools_called: set = field(default_factory=set)  # short tool names that ran, for the verifier's evidence check
    item_number_ids: list = field(default_factory=list)  # ids of the item's own numbers, registered by code before the model ran
    say_forms: set = field(default_factory=set)  # rounded dollar phrases the tools offered ("$1.54M")
    seen_dates: set = field(default_factory=set)  # (month, day) of every date any tool returned, or the item states
    seen_days_left: set = field(default_factory=set)  # the days left a tool returned for this item (days_left, days_to_effective): the only "N days left" the answer may state
    seen_day_counts: set = field(default_factory=set)  # every "N days" a tool or the item itself stated: the only day counts the answer may state
    seen_numerals: set = field(default_factory=set)  # every numeral that appeared in any tool output (descriptions, dates, quantities)
    running: set = field(default_factory=set)  # agent ids of teammates started and not yet stopped
    handoffs_seen: set = field(default_factory=set)  # the specialists whose handoffs Lookout had read when it last called get_handoffs
    finding_facts: dict = field(default_factory=dict)  # key -> the fact code found on the case: what `findings` may pick
    option_kinds: list = field(default_factory=list)  # the kinds of the ways through code laid out for this item: what `recommended` may name
    action_item_key: str | None = None  # Ask on an Action-list case: what it stages belongs to that case (its Approval card, its owner)
    is_case: bool = False  # an Action-list case: its finding is the Situation (no action word needed) and it carries no points (the page shows the case's blocks)
    coded: bool = False  # the answer is written by code, not by a model (a trust item): its rows keep the item's full text
    owner_for: dict = field(default_factory=dict)  # supplier id -> the buyer who owns all the lines being chased there: the request is owned, and signed, by that buyer
    pending_calls: object = None  # a function giving the (tool, part) calls this kind of item must have had before it is answered; the gate asks it at the write
    handoff_reads: int = 0  # how many times Lookout has read the handoffs: a re-read with nothing new is refused
    required_suppliers: set = field(default_factory=set)  # supplier ids that must each get a request (staged, amended or covered) before the clerk may hand off
    suppliers_asked: set = field(default_factory=set)  # supplier ids whose request this run staged, amended or found covering the ask
    reads_ok: Counter = field(default_factory=Counter)  # specialist -> tools that returned a result (a handoff that read nothing is refused)
    results_seen: set = field(default_factory=set)  # tool_use_ids that already have a tool.result event
    site_text: dict = field(default_factory=dict)  # supplier name (lower) -> the origin and conditions text offers returned for it: where its site can be named
    conditions: dict = field(default_factory=dict)  # id -> {text, tokens}: the conditions the offer tools returned (carry-through)
    calls_made: set = field(default_factory=set)  # (short tool name, first argument value): which part was actually examined
    steward: dict = field(default_factory=dict)  # the Data steward's workspace for this run: the incoming file, attempts, findings, the best step
    optional: set = field(default_factory=set)  # specialists in the plan that Lookout may skip when nothing is needed from them
    open_plan: bool = False  # Ask: no fixed plan; Lookout decides whom to ask, within max_delegations
    max_delegations: int = 3
    tool_caps: dict = field(default_factory=dict)  # short tool name -> most calls a run may make: bounded fan-out
    tool_counts: Counter = field(default_factory=Counter)
    stage_allowed: bool = True  # false on trust items: nothing may be drafted
    nonce: str = field(default_factory=lambda: __import__("secrets").token_hex(4))  # marks untrusted text in this run, unguessable by the text
    injection_signals: set = field(default_factory=set)  # why a message read like an instruction to an AI (flag, never block)
    tokens_by_agent: dict = field(default_factory=dict)  # specialist -> {tokens, tool_uses, duration_ms}, as the SDK reports its task

    asked_numerals: set = field(default_factory=set)  # numerals the buyer typed in an Ask ('a bridge order of 200'): a decision they asked for may restate them
    asked_buyers: set = field(default_factory=set)  # buyers this run has already logged a question for: one note each

    def __post_init__(self):
        if not self.groups:
            self.groups = [[p] for p in self.plan]

    def register(self, numbers: list[Number]) -> None:
        from .toolkit import money_words  # noqa: PLC0415

        for n in numbers:
            if n.unit == "USD" and n.say is None and n.value:  # every dollar figure has the form a buyer says it (cents under $10,000, K and M above)
                n.say = money_words(n.value)
            self.evidence[n.id] = n
            if n.say:
                self.say_forms.add(n.say)
