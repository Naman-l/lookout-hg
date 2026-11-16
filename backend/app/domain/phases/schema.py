"""The PR-to-payment ladder: one rung per step a purchase passes through, each with its date, the source row it is read from, and whose move the
time before it was."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef

RungState = Literal["done", "now", "todo", "na", "unknown"]
Who = Literal["SCM", "Projects", "Vendor", "QA", "Finance", "Management"]


class Rung(BaseModel):
    key: str  # needed | pr_raised | pr_released | rfq_sent | quotes_in | cs_approved | po_released | mfc_issued | inspected | dispatched | received | invoiced | paid | closed
    label: str
    state: RungState
    date: str | None = None
    source: str | None = None  # "pr_lines row 412", "message:<id> L3", "milestones row 8"
    ref: EntityRef | None = None
    held_by: Who | None = None  # whose move the time before this rung was (for a rung not reached: whose move it is now)
    days: int | None = None  # the days from the previous dated rung to this one (to the data date while it waits)
    why: str | None = None  # the rule that attributed the wait, in a sentence
    unknown: str | None = None  # a rung the data cannot show: what is missing and who could say


class Ladder(BaseModel):
    subject: EntityRef  # the PR line or PO line
    pr_line: EntityRef | None
    po_line: EntityRef | None
    rungs: list[Rung]
    waiting_on: Who | None  # whose move it is now (None: closed)
    waiting_since: str | None
    days_waiting: int | None
    held: dict[str, int]  # days held by each function over the whole ladder so far
