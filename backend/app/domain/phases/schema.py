from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from decimal import Decimal

from app.domain.common import EntityRef, Provenance, Quantity, Unknown

RungState = Literal["done", "expected", "late", "disrupted", "unknown", "na"]  # late: the promised date has passed; disrupted: named on a force-majeure notice


class Rung(BaseModel):
    """One step in the life of an order or a part. `done` and `expected` carry the date and the record they come from; `unknown` carries who to ask."""

    key: str  # need | quote | ordered | promised | acknowledged | at_supplier | shipped | in_transit | customs | received | inspected | stocked | kitted | closed
    label: str
    state: RungState
    date: str | None = None
    detail: str
    source: EntityRef | None = None  # the PO line, message or forecast the state comes from
    unknown: Unknown | None = None  # state == unknown: what is missing, why it blocks, who to ask
    flag: Literal["disrupted", "past_due", "slipped"] | None = None


class LinePromise(BaseModel):
    """The date an open line is now expected, and the ERP date when it differs (the supplier moved it)."""

    date: str
    erp_date: str | None = None


class Ladder(BaseModel):
    """GET /api/phases: the rungs of one PO line, or of one part (with the ladders of its open lines inside)."""

    subject: EntityRef
    kind: Literal["po_line", "part"]
    rungs: list[Rung]
    counts: dict[str, int]  # one count per state
    verdict: str  # "3 known from records, 2 expected, 8 unknown (no data)"; never a percent
    qty: Quantity | None = None  # an open line: what is still to arrive, in the part's unit
    promised: LinePromise | None = None  # an open line with a date: the current date by the stage rules, and the ERP date if it differs
    lines: list[Ladder] = []  # a part: its open order lines


class Qty(BaseModel):
    """A plain quantity for a row whose provenance is said once for the whole build (`need_source`) or by its ladder."""

    value: Decimal
    uom: str


class Ask(BaseModel):
    owner: str  # who to ask: Ana, Ben, Cy, Di, Eve, supplier or broker
    question: str


class ReadyPart(BaseModel):
    part: EntityRef  # the label is the description
    state: str  # covered | after_build | short | past_due | disrupted | undated | no_order | in_house | in_stock | short_after_stock
    detail: str
    need: Qty  # for the build: units x quantity per robot (BuildReadiness.need_source says how)
    open_qty: Qty | None = None
    po_lines: list[str] = []  # the open lines behind open_qty; GET /api/phases?part= cites each
    arrives: str | None = None  # the date the open supply lands (the supplier's revised date when there is one)
    supplier: EntityRef | None = None
    cause: EntityRef | None = None  # the notice behind `disrupted`
    on_hand: Qty | None = None  # the stock count, when one was given
    ask: Ask | None = None  # unknown: who to ask and what
    cases: list[str] | None = None  # the open cases (Today's rows) that hold this part or one of its lines; set by the readiness route only


class ReadyGroup(BaseModel):
    assembly: EntityRef  # a sub-assembly of the product, or the product itself for parts that go straight into it
    parts: list[ReadyPart]
    counts: dict[str, int]


class BuildReadiness(BaseModel):
    """GET /api/builds/{product}/{month}/readiness: every part of a build, its state, rolled up by sub-assembly, with a verdict in counts."""

    product: EntityRef
    month: str
    units: int
    verdict: str
    need_source: Provenance  # how every row's `need` was computed, said once
    counts: dict[str, int]  # distinct parts per state; assemblies counted as `in_house`
    groups: list[ReadyGroup]
    stock_counted: int  # parts with a stock count
    stock_note: str


Ladder.model_rebuild()


class BuildSummary(BaseModel):
    """GET /api/builds: one row per product, for its next build month: small enough to load on every screen."""

    product: EntityRef
    month: str
    units: int
    counts: dict[str, int]  # covered, after_build, past_due, disrupted, no_order, in_house always present (0 when none); other states when they occur
    verdict: str
