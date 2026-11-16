"""Today's items: one per cause that will cost money or a date if nobody acts, raised by a detector in code. Each carries its tab, the ₹ at stake
with the rule that computed it, the date to act by, the SCM owners, whose move it is (SCM, Projects, Finance, QA, Vendor, Management), the verticals
and projects it touches, and the work fronts that stop if nothing is done ("up to": site stock is not in the data)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef, Money, Provenance, Quantity, Unknown
from app.domain.doa.service import DoaLine
from app.domain.orders.schema import PoLineView
from app.domain.phases.schema import Ladder
from app.domain.prs.service import PrLineView
from app.domain.quotes.schema import CsView
from app.domain.requirements.service import SupplyByMonth

Tab = Literal["requirement", "after_po", "price", "payments", "vendor_risk", "trust", "unknown"]
WaitingOn = Literal["SCM", "Projects", "Finance", "QA", "Vendor", "Management"]
TAB_NAMES = {"requirement": "Requirement", "after_po": "After PO", "price": "Price", "payments": "Payments", "vendor_risk": "Vendor risk", "trust": "Trust",
             "unknown": "Unknowns"}


class DateValue(BaseModel):
    date: str
    provenance: Provenance


class SiteImpact(BaseModel):
    """A work front that stops if nothing is done: from the date its material is needed, when the supply covering it lands later, sits under a
    disruption, or does not exist. "Up to": site stock is not in the data."""

    project: EntityRef
    front: str
    month: str  # YYYY-MM
    stops_on: str | None = None
    why: str  # "masts land 20 Nov; needed from 12 Nov"


StageKey = Literal["found", "worked", "decision_ready", "drafted", "signed", "approved", "sent", "answered"]


class Stage(BaseModel):
    """Where the work on an item stands, read from the runs and the ledger on every request (never stored), with the one next act and whose move it is."""

    key: StageKey
    label: str
    step: int  # 1..7
    of: int = 7
    next_act: str
    at: str | None = None
    waiting_on: str | None = None  # "you", "the vendor", "Projects", "Finance", "QA", "the Head of SCM", or None when nothing is owed
    action: EntityRef | None = None


class DatedRow(BaseModel):
    """A dated fact folded under its cause (a vendor's revised schedule under its late streak, a quote's lapse under the long-lead decision)."""

    key: str  # still resolvable at /api/action-items/<key>
    title: str
    act_by: str | None = None
    days_left: int | None = None
    at_stake: Money | Unknown | None = None


class ActionItem(BaseModel):
    key: str
    kind: str  # the detector: pr-late, pr-stuck, mfc-validity, ...
    tab: Tab
    severity: Literal["high", "medium", "low"]
    title: str
    summary: str  # the row's line of facts under the title
    at_stake: Money | Quantity | Unknown | None = None
    at_stake_label: str = "at stake"  # at stake | covers | claimed | if those sites paid the median
    at_stake_rule: str = ""  # the rule, for the tooltip
    act_by: str | None = None
    days_left: int | None = None
    owner: str  # full names, " · " between them
    owner_ids: list[str] = []
    waiting_on: WaitingOn = "SCM"
    verticals: list[str] = []
    projects: list[EntityRef] = []
    site_impact: list[SiteImpact] = []
    next_action: str = ""
    refs: list[EntityRef] = []
    dated: list[DatedRow] = []
    team_total: Money | None = None  # on a viewer's share of a team case: the whole case's figure
    stage: Stage | None = None


class Number(BaseModel):
    id: str
    label: str
    value: Money | Quantity | Unknown | DateValue


class Decision(BaseModel):
    action_id: str
    type: str
    state: str
    by: str
    at: str
    reason: str | None = None
    text: str


class LinkedCase(BaseModel):
    key: str
    title: str
    why: str  # "the same vendor: <name>", "the same PO", "the same project"
    owner: str | None = None


class Finding(BaseModel):
    key: str
    fact: str  # code's sentence, every figure from the records
    meaning: str  # what it means, when no run has given a reading of its own
    refs: list[EntityRef] = []


class Deadline(BaseModel):
    what: str
    date: str
    source: str  # "message <id> L5", "po_lines row 362"
    days_left: int


class VendorPanel(BaseModel):
    ref: EntityRef
    name: str
    codes: list[str]
    gstin: str | None
    msme: bool
    msme_due_45: int  # invoices of an MSME vendor that fall due within 45 days
    on_time: str  # "on time 60% (6/10)"
    avg_days_late: float | None
    streak_line: str
    terms: list[str]
    library: list[str]  # approved verticals; empty: not in the library
    contact: str | None
    contact_email: str | None


class ProjectPanel(BaseModel):
    ref: EntityRef
    vertical: str
    stage: str
    plants: list[str]
    head: str | None
    planner: str | None
    median_pr_po_days: float | None  # this project's PR -> PO turnaround, same-day PRs left out


class HeldMessage(BaseModel):
    """What the trust check found on a held message, and the controls a person must record before anything else happens."""

    message: EntityRef
    sender: str
    imitates: str | None
    flags: list[str]  # plain words
    claimed: Money | None
    controls: list[str]
    done: list[dict] = []  # each control done: who, when


class ActionItemDetail(ActionItem):
    finding: str = ""
    findings: list[Finding] = []
    numbers: list[Number] = []
    unknowns: list[Unknown] = []
    evidence: list[EntityRef] = []
    deadlines: list[Deadline] = []
    pr_lines: list[PrLineView] = []
    po_lines: list[PoLineView] = []
    messages: list[EntityRef] = []
    vendor: VendorPanel | None = None
    project: ProjectPanel | None = None
    supply: SupplyByMonth | None = None
    ladder: Ladder | None = None
    cs: CsView | None = None
    doa: DoaLine | None = None
    held: HeldMessage | None = None
    linked: list[LinkedCase] = []
    decisions: list[Decision] = []
    latest_run: dict | None = None
    recommendation: dict | None = None
    sheet_cells: list[dict] = []  # requirement / fund sheet cells the case rests on, with their cell reference
