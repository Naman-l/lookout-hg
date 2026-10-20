"""The Action list: what will cost money if nobody acts, ranked by the four truths. Shapes follow api/openapi.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef, Money, Provenance, Quantity, Unknown
from app.domain.annotate.schema import Span
from app.domain.demand.schema import TimePhased
from app.domain.inbox.schema import MessageSummary
from app.domain.orders.schema import PoLine

Group = Literal["disruption", "deadline", "tariff", "unknown", "trust"]


class DateValue(BaseModel):
    date: str
    provenance: Provenance


class Need(BaseModel):
    """Something an option cannot go ahead without, and who can supply it."""

    what: str
    owner: str
    ref: EntityRef | None = None


class ProductExposure(BaseModel):
    product: EntityRef
    robots: int  # forecast in the first short month
    short_parts: list[EntityRef]  # parts of this product that are short


class FireOption(BaseModel):
    """One way through a supplier's disruption, as fields: what it needs, the earliest date the data supports, what it costs where that can be
    computed, and the one unknown that decides it. No prose: the screen and the agent word it."""

    kind: str  # a disruption's computed ways (allocation, air_freight, resequence, second_source, order_before) or any route of the case's code table
    label: str
    covers: str | None = None  # what the route covers ("10 PO lines", "3 products", "<part> only"), from the records
    cost: Money | None = None  # the route's own figure where it is not a change against today (the duty budgeted, the open value waiting)
    needs: list[Need] = []
    earliest: DateValue | None = None  # the first date the data supports for this option
    earliest_basis: str | None = None  # where that date comes from, or why there is none
    not_before: DateValue | None = None  # a floor when the real date is unknown
    cost_delta: Money | None = None  # versus what is paid today, where it can be computed
    cost_basis: str | None = None
    duty_effect: Money | None = None  # duty owed only if the goods ship late, avoided by shipping in time
    cost_unknowns: list[Unknown] = []
    decided_by: Unknown | None = None  # the unknown that settles whether this option is open (a disruption's ways; other kinds' routes name none)
    products: list[ProductExposure] = []  # resequence: every product with its short parts and forecast, in part-number order (laid out, not ranked)
    moq: int | None = None
    refs: list[EntityRef] = []


StageKey = Literal["found", "worked", "decision_ready", "drafted", "approved", "sent", "answered"]
Category = Literal["Discovery", "RFQ", "Quote & risk", "Purchasing"]   # the standard procurement stage words, where an item belongs to one


class Stage(BaseModel):
    """Where the work on an item stands, read from the runs and the ledger (derived on every request, never stored), and the one next act."""

    key: StageKey
    label: str
    step: int  # 1..7 along found, worked, decision ready, drafted, approved, sent, answered
    of: int = 7
    next_act: str  # the one thing to do now, in plain words
    at: str | None = None  # when it got here, if a record says
    waiting_on: str | None = None  # who has the move: "you", "the supplier", or None when nothing is owed
    action: EntityRef | None = None  # the draft or request this stage is about (always one made for this item)


class DatedRow(BaseModel):
    """One dated step inside a problem, shown under it instead of as a row of its own."""

    key: str  # still resolvable at /api/action-items/<key>
    title: str
    act_by: str | None = None
    days_left: int | None = None
    at_stake: Money | Quantity | Unknown | None = None


class RobotsShort(BaseModel):
    """Robots of one product in one month that a short part stops, as numbers a tile can show (no text to parse)."""

    product: EntityRef
    month: str  # YYYY-MM
    robots: int  # the forecast for that month
    short_parts: list[EntityRef]  # the parts of that product that are short in the month


class ActionItem(BaseModel):
    key: str
    group: Group
    severity: Literal["high", "medium", "low"]
    title: str
    at_stake: Money | Quantity | Unknown | None = None
    at_stake_gross: Money | None = None
    at_stake_note: str | None = None  # what the figure means in builds: "182 Alpha + 40 Beta robots in October"
    act_by: str | None = None
    days_left: int | None = None
    owner: str
    next_action: str = ""
    title_entities: list[Span] = []  # what the title mentions, matched against the records (offsets in UTF-16 units)
    next_action_entities: list[Span] = []
    refs: list[EntityRef] = []
    dated: list[DatedRow] = []  # a disruption's own dates: the supplier's other deadlines (a closure, the promised revised dates, a quote that lapses), folded under it, soonest first
    robots_short: list[RobotsShort] = []  # fire rows: robots per product and month the short parts stop
    robots: list[EntityRef] = []  # every robot (product) whose BOM uses a part this item names, in product order; none when the item names no parts
    robot_notes: dict[str, str] = {}  # product id -> the one fact that ties this item to that robot, where there is one ("<part> 30 d late")
    summary: str | None = None  # the row's one line of facts under the title, in a buyer's words ("182 T2 + 40 P5 short in Oct · 10 lines")
    lines_in_scope: int | None = None  # fire rows: open lines under the notice
    lines_already_late: int | None = None  # fire rows: of those, lines already past their promise date at the data date (not "before the notice")
    waits_until: str | None = None  # a date before which nothing is chased: the supplier promised something by then; the item states this trigger, the agent drafts nothing earlier
    category: Category | None = None  # which of the procurement stages the item belongs to (a quiet tag); None where none applies
    stage: Stage | None = None  # where the work stands; set by the API from the runs and the ledger


class Number(BaseModel):
    id: str
    label: str
    value: Money | Quantity | Unknown | DateValue


class Decision(BaseModel):
    """One decision a person took on an item, from the ledger."""

    action_id: str
    type: str  # supplier_request | supplier_alias | note
    state: str  # approved | rejected | recorded
    by: str
    at: str
    reason: str | None = None
    text: str  # "Ana rejected the request to li.wei@... on Oct 10: wrong contact"


class LinkedCase(BaseModel):
    """Another case on the list that shares an order line, a part, a supplier or a message with this one (the same rule the agent's packet uses)."""
    key: str
    title: str
    why: str  # e.g. "the same supplier: <supplier>"
    owner: str | None = None


class ActionItemDetail(ActionItem):
    finding: str = ""
    finding_entities: list[Span] = []
    numbers: list[Number] = []
    unknowns: list[Unknown] = []
    evidence: list[EntityRef] = []
    latest_run: dict | None = None
    linked: list[LinkedCase] = []  # FINAL 07 §12b: Linked cases in the rail
    short_names: dict[str, str] = {}  # each supplier ref's id -> the name a buyer says (UX SL-7)
    recommendation: dict | None = None
    po_lines: list[PoLine] = []
    messages: list[MessageSummary] = []
    time_phased: TimePhased | None = None
    decisions: list[Decision] = []  # newest first; empty when nobody has decided anything yet
