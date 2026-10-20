"""The organism's typed shapes: the run event, the specialist handoff and the Recommendation.

These models are the contract. FastAPI derives the OpenAPI from them and the UI renders the Recommendation
from its typed fields, so nothing here is free text that a screen has to parse.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..domain.common import EntityRef, Provenance, Unknown

# ---- numbers ---------------------------------------------------------------------------------------------


class Number(BaseModel):
    """One figure a tool computed. `id` is stable (shortage:PN-12345:2026-10:short) and is how the
    Recommendation and the handoffs cite it; the verifier matches by id."""

    id: str
    name: str  # in the buyer's words: "Units short, October"
    value: Decimal
    unit: str  # "EA", "USD", "days"
    provenance: Provenance | None = None
    say: str | None = None  # how a buyer says it ("$1.54M"): rounded by code, and the only rounding the prose may use

    @field_validator("value")
    @classmethod
    def _whole_numbers_read_whole(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal(1)) if v == v.to_integral_value() else v.normalize()


# ---- the handoff a specialist ends with ---------------------------------------------------------------------


class Handoff(BaseModel):
    findings: list[str] = Field(min_length=1)
    number_ids: list[str] = Field(default_factory=list, description="ids of tool numbers the findings rely on")
    unknowns: list[Unknown] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)


# ---- the Recommendation (matches api/openapi.yaml) ----------------------------------------------------------


class VerifierResult(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)  # soft checks: worth a look, never a failure
    numbers_checked: int
    numbers_from_tools: int
    open_questions_with_owner: int
    reasons: list[str] = Field(default_factory=list)  # each failure in words a buyer reads, never an id or a check's name
    unchecked: list[str] = Field(default_factory=list)  # figures in the answer's sentences that no tool returned: shown marked, the answer is still delivered (a draft with one is blocked)
    open_questions: int = 0  # every open question the Recommendation carries: the model's own, the item's and the tools'
    failures: list[str] = Field(default_factory=list)


class RecommendedNumber(BaseModel):
    """What the model writes: the id of a tool number and the value it read. Code resolves name and unit."""

    id: str
    value: float = Field(description="The number only, exactly as the tool gave it: no unit, no text")


class NextStepDraft(BaseModel):
    who: str = Field(default="", description="The person who does the next thing: a buyer or owner by name, or 'Lookout' only when it will run again")
    what: str = Field(default="", description="The next thing, in one short line")
    by: str = Field(default="", description="The date it is needed by, only if a tool returned it; otherwise empty")


class PointDraft(BaseModel):
    label: str = Field(description="Two or three words naming the row: Short, Recovery, Asked of the supplier, Needs you")
    text: str = Field(description="One short line, at most 20 words")


class FindingDraft(BaseModel):
    """One of the facts code found on the case, picked by Lookout, with what it means for the buyer. The fact itself is code's."""

    key: str = Field(description="The key of a fact the context lists under 'What the records show'")
    meaning: str = Field(description="What it means for the buyer, at most 8 words; a figure only as the fact states it")


class RecommendedDraft(BaseModel):
    """The one way through Lookout recommends (rule B): the buyer still chooses and the owner signs. Code drops it when it fails its check."""

    kind: str = Field(description="The kind of the option, exactly as the ways through list it (for example allocation)")
    reason: str = Field(description="Why this one, at most 8 words, numbers first, no subject ('covers all 10 lines, rights reserved'); every figure cited in number_ids")
    number_ids: list[str] = Field(default_factory=list, description="The ids of every figure the reason states (option or item numbers)")


class RecommendationDraft(BaseModel):
    """The `output_format` schema Lookout fills."""

    finding: str = Field(description="The decision in one sentence of at most 20 words, in a buyer's words")
    points: list[PointDraft] = Field(default_factory=list, description="At most 4 short rows that carry the detail: {label, text}; at most 3 when answering a question")
    next_step: NextStepDraft = Field(default_factory=NextStepDraft, description="Who does what next, and by when: every answer ends with one")
    numbers: list[RecommendedNumber]
    assumptions: list[str] = Field(default_factory=list)
    would_change: list[str] = Field(default_factory=list, description="What would change the answer")
    open_questions: list[Unknown] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    findings: list[FindingDraft] = Field(default_factory=list, description="Only on a case whose context lists what the records show: the 3-4 facts a buyer most needs, most important first")
    recommended: RecommendedDraft | None = Field(default=None, description="Only when the ways through are listed: the one you recommend; otherwise leave it out")


def draft_schema(ask: bool = False) -> dict:
    """The schema the model writes to: the shape limits are in it (words become a character ceiling, rows a count), so the first write fits instead of costing a rewrite turn.
    The model class itself stays loose: an answer written by code, with a row longer than a model's, still parses."""
    import copy  # noqa: PLC0415

    s = copy.deepcopy(RecommendationDraft.model_json_schema())
    s["properties"]["finding"]["maxLength"] = 150
    pts = s["properties"]["points"]
    pts["maxItems"] = 3 if ask else 4
    point = s["$defs"]["PointDraft"]["properties"]
    point["label"]["maxLength"], point["text"]["maxLength"] = 40, 260
    s["$defs"]["RecommendedDraft"]["properties"]["reason"]["maxLength"] = 60
    s["$defs"]["FindingDraft"]["properties"]["meaning"]["maxLength"] = 60
    s["properties"]["findings"]["maxItems"] = 4
    return s


class RecommendationNumber(BaseModel):
    id: str
    value: str
    unit: str
    name: str | None = None  # extra to the contract: the buyer-words label, for the screen
    headline: bool = False  # extra: code guarantees these for the item's kind; the determinism check compares them
    say: str | None = None  # extra: how a buyer says a dollar figure ($188.99, $1.54M); the exact value stays in `value`
    provenance: Provenance | None = None  # extra: the click-through


class FailedCheck(BaseModel):
    """A Reviewer check that failed, in plain words."""

    name: str
    reason: str


class Grade(BaseModel):
    """The quiet strip under a Recommendation: the Reviewer's score and whether it was revised."""

    reviewer_score: int | None = None  # share of checks passed, 0-100; None when the Reviewer could not run (shown as ungraded, never as a pass)
    checks_passed: int | None = None  # "5 of 6 checks passed"
    checks_total: int | None = None
    summary: str = ""
    revised: bool = False  # Lookout revised once after the review or a failed check
    failed_checks: list[FailedCheck] = Field(default_factory=list)  # what the Reviewer failed, so the strip can name it


class RecommendationFinding(BaseModel):
    """A defect or difference the Data steward found, with a count a tool returned: written by the steward's tool, not by Lookout."""

    issue: str
    count: int
    consequence: str
    example: str
    handling: str = "fix"


class Point(BaseModel):
    label: str
    text: str
    entities: list[dict] = Field(default_factory=list)  # spans over `text`, attached by code (the annotate module)
    added_by_code: bool = False  # a row code added because the answer left out what a tool returned (the Conditions row)


class DoneLine(BaseModel):
    """One thing the run did, written by code from the ledger: the UI lists these under the answer."""

    text: str
    action_id: str
    stage: str  # proposed | approved | executed | ...


class Recommendation(BaseModel):
    finding: str
    next_step: NextStepDraft = Field(default_factory=NextStepDraft)
    done: list[DoneLine] = Field(default_factory=list)  # what the run did, each with its action id and stage (from the ledger, never from the model)
    points: list[Point] = Field(default_factory=list)  # the skimmable rows under the finding
    answer_entities: list[dict] = Field(default_factory=list)  # spans over `finding` (the annotate module's shape, UTF-16 offsets), attached on read
    recommendation_entities: list[list[dict]] = Field(default_factory=list)  # spans over each assumption, then each would_change line, in that order
    numbers: list[RecommendationNumber]
    assumptions: list[str] = Field(default_factory=list)
    would_change: list[str] = Field(default_factory=list)
    open_questions: list[Unknown] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    unchecked: list[str] = Field(default_factory=list)  # figures in the sentences that no tool returned, for the screen to mark
    findings: list[RecommendationFinding] = Field(default_factory=list)  # a data import's findings, attached by code
    grade: Grade | None = None
    case_findings: list[FindingDraft] = Field(default_factory=list)  # the facts Lookout picked on a case, in its order, each kept only if its key is code's and its meaning passes (verifier)
    recommended: RecommendedDraft | None = None  # the way through Lookout recommends, kept only if its kind is one laid out and every figure in its reason is cited (verifier)
    corrections: list[str] = Field(default_factory=list)  # "corrected by a rule: <why>" when code corrected a recorded finding that broke a claim rule (answer_rules): the words are code's, not the agent's


# ---- run events ---------------------------------------------------------------------------------------------

EventType = Literal[
    "run.started", "step.text", "step.delta", "child.started", "child.finished", "tool.called",
    "tool.result", "action.staged", "verifier.result", "review.result", "revision.started", "run.finished", "run.failed", "run.status",
]


class RunEvent(BaseModel):
    """One row of How we got here. Written to SQLite first, then pushed over SSE and emitted to the Watcher.
    `step.delta` is SSE-only and never stored."""

    run_id: str
    parent_run_id: str | None = None
    seq: int
    ts: str
    t_ms: int
    type: EventType
    agent: str  # lookout | supply_planner | buyers_clerk | verifier
    agent_label: str  # "Lookout", "Supply planner", "Buyer's clerk", "Verifier"
    tool_use_id: str | None = None
    summary: str  # one plain sentence in the buyer's words
    refs: list[EntityRef] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    stage: str | None = None  # overview · analysis · draft · decision: derived when the run is read (runs/stages.py), never stored


RunStatus = Literal["running", "ok", "failed", "refused", "did_not_pass"]


class RunRef(BaseModel):
    run_id: str
    status: RunStatus


class Run(BaseModel):
    run_id: str
    item_key: str
    asked_by: str | None = None
    status: RunStatus
    started_at: str
    first_step_ms: int | None = None
    duration_ms: int | None = None
    tool_calls: int = 0
    denied_calls: int = 0
    cost_usd: str | None = None
    original_cost_usd: str | None = None  # a replay's cost_usd is 0; this is what the run it replays cost
    original_tokens_in: int | None = None  # likewise: what the recorded run read and wrote (a replay's own tokens are 0)
    original_tokens_out: int | None = None
    title: str | None = None  # an Ask run's question, so a list can name it in words
    model: str = ""
    prompt_hash: str = ""
    recorded: bool = False  # true when this is a replay of a real run recorded at build time, not a live run
    recorded_at: str | None = None
    # the operator's row: what happened in one line (all read from what the run already stored)
    workflow: str = ""  # work_item | ask | import
    specialists: list[dict[str, str]] = Field(default_factory=list)  # [{agent, label}] in the order they started
    first_token_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    verifier_passed: bool | None = None
    reviewer_score: int | None = None  # share of checks passed, 0-100
    checks_passed: int | None = None
    checks_total: int | None = None
    revised: bool = False


class StageSummary(BaseModel):
    """One step of a run as its card shows it: how many lookups and figures read, when it started and ended (ms from the run's start)."""

    stage: str
    lookups: int = 0
    figures_read: int = 0
    started_ms: int = 0
    ended_ms: int = 0


class TableCell(BaseModel):
    say: str  # the figure as a buyer reads it
    id: str  # the evidence id of the number a tool returned in this run: the cell is cited, and is what the verifier checks the answer against


class TableRow(BaseModel):
    label: str
    ref: dict = Field(default_factory=dict)  # {type, id}: what the row is (a part, a PO line, a quote), so the UI can name and link it
    part: str | None = None  # the part a PO line or a quote is for
    note: str | None = None  # code's own words for the row (a late line: supplier, days past due, buyer, the robot it feeds), never the model's
    cells: list[TableCell | None] = Field(default_factory=list)  # one per column; null where the run read no figure


class AskTable(BaseModel):
    """One of an Ask answer's tables (F100): built by code from the run's tool results, never by the agent."""

    kind: str  # shortfall | po_lines | exposure | quotes
    title: str
    by: str  # the specialist whose lookup returned the figures
    columns: list[str] = Field(default_factory=list)
    rows: list[TableRow] = Field(default_factory=list)  # at most 6
    more: int = 0  # rows left out: "+N in Analysis ›"
    more_what: str | None = None  # what the left-out rows are, when they are not simply more of the same ("other lines read": the answer named the rows shown)


class RunDetail(Run):
    events: list[RunEvent] = Field(default_factory=list)
    stages: list[StageSummary] = Field(default_factory=list)  # in run order; "figures checked" stays the verifier's
    open_questions_first: int | None = None  # an Ask answer: how many of recommendation.open_questions (ordered first) are about the answer's own parts; the UI folds the rest as "+N other open questions" (display only: every question is still carried)
    tables: list[AskTable] = Field(default_factory=list)  # an Ask answer's tables, from its own tool results (empty on any other run)
    recommendation: Recommendation | None = None
    verifier: VerifierResult | None = None
