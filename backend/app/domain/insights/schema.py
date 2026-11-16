"""Insights shapes: Team, Projects, Pricing, Estimates and the Daily brief. Every figure is a `Figure`: the number, how a buyer reads it, the rule that
computed it, and the records it rests on ("pr_line:<PR>/<item>", "po_line:<PO>/<item>", "item:<case key>"), so a screen can open each one."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.requirements.service import FrontStatus

Unit = Literal["inr", "days", "count", "pct", "ratio", "rate", "text"]


class Figure(BaseModel):
    value: float | None  # None: nothing to measure (the text says why)
    text: str  # as a buyer reads it: "₹1.4 Cr", "12 days", "7 lines"
    unit: Unit = "count"
    rule: str  # the rule that computed it, in plain words
    refs: list[str] = []  # "<type>:<id>" of every record it rests on
    note: str | None = None  # a condition it holds under ("where a previous rate exists")


# ------------------------------------------------------------------------------------------------------------------------------------ Team
class VerticalTurnaround(BaseModel):
    """PR -> PO days on one vertical: the member's median against the vertical's own median (every buyer's lines on it). No other comparison."""

    vertical: str
    name: str
    mine: Figure
    vertical_median: Figure


class Saving(BaseModel):
    """PO rate against a reference rate x the PO quantity, on the lines where the reference exists. Positive: bought below it."""

    net: Figure
    below: Figure  # lines bought below the reference: what that saved
    above: Figure  # lines bought above it: what that cost
    lines: int  # lines with a reference
    of_lines: int  # every PO line of the member


class CancelledEffort(BaseModel):
    """Work spent on PR lines that were later deleted or short-closed: the RFQs sent and the quotes received on them."""

    lines: Figure
    prs: int
    rfq_lines: Figure  # cancelled lines an RFQ went out on
    enquiries: Figure  # comparative statements (enquiries) behind them
    vendors_asked: Figure
    quotes: Figure  # priced quotes received on them


class FunctionWait(BaseModel):
    """Days the member's items were held by one function over their ladders (PLAN 6.2), and the lines waiting on it now."""

    function: str  # SCM | Projects | Vendor | QA | Finance | Management
    days: Figure
    per_line: Figure  # those days over the lines it held
    lines: int  # ladders with any days held by this function
    now: Figure  # lines whose move it is now


class Workload(BaseModel):
    open_pr_lines: Figure
    open_po_lines: Figure
    open_po_value: Figure
    cases: Figure  # Today cases the member owns
    cases_on_you: Figure  # ... of them, the move is SCM's (theirs)


class OpenPr(BaseModel):
    ref: str  # pr_line:<id>
    pr: str
    item: int
    text: str
    project: str | None
    project_name: str | None
    age_days: int
    since: str  # release (else creation) date
    needed_by: str | None
    rfq_sent: str | None
    quotes_in: int
    waiting_on: str | None  # whose move it is now, from the ladder
    rung: str | None  # the rung it waits for


class AgeBucket(BaseModel):
    label: str
    lines: Figure


class MemberSummary(BaseModel):
    id: str
    name: str
    initials: str
    role: str
    groups: list[str]
    verticals: list[str]
    group: str  # whose team the organogram puts the member in: a lead's member id | head | none
    group_name: str
    group_note: str | None = None  # the lead's portfolio (what their team buys), or the head's designation
    designation: str | None = None  # as the organogram writes it, and in full
    designation_full: str | None = None
    reports_to: str | None = None  # the member id of whom they report to, and the name
    reports_to_name: str | None = None
    category: str | None = None  # the desk label the organogram writes beside them
    responsibilities: str | None = None  # their work, as the organogram words it
    portfolio: str | None = None  # a lead's line of what their team buys
    open_prs: Figure
    oldest_open: Figure  # days
    pos_30: Figure
    pos_30_value: Figure
    pos_90: Figure
    pos_90_value: Figure
    turnaround: list[VerticalTurnaround]
    saving_last: Figure
    saving_budget: Figure
    cancelled: Figure
    cancelled_quotes: Figure
    waited_scm: Figure
    waited_others: Figure
    waited_scm_line: Figure  # the same days over every line of the member's with a ladder: what a line waits, which a sum of line-days does not say
    waited_others_line: Figure
    workload: Workload


class MemberPage(MemberSummary):
    email: str | None
    ageing: list[AgeBucket]
    oldest: list[OpenPr]  # the oldest open PR lines first
    saving_last_detail: Saving
    saving_budget_detail: Saving
    cancelled_detail: CancelledEffort
    waits: list[FunctionWait]  # SCM first, then the others in the ladder's order
    period: str
    as_of: str
    viewer_note: str | None = None


class TeamResponse(BaseModel):
    viewer: str | None  # the viewer's member id
    viewer_name: str | None
    scope: Literal["all", "team", "self", "none"]
    note: str  # who sees what, and why
    order: str  # "the organogram's order": never a performance figure
    period: str
    as_of: str
    members: list[MemberSummary]


# -------------------------------------------------------------------------------------------------------------------------------- Projects
class ProjectFigures(BaseModel):
    id: str
    name: str
    vertical: str
    vertical_name: str
    stage: str
    plants: list[str]
    head: str | None
    planner: str | None
    open_prs: Figure
    turnaround: Figure  # median PR -> PO days, same-day PRs left out
    target_days: int | None  # the vertical's turnaround target (answers.yaml)
    cancelled: Figure
    budget: Figure  # Σ PO qty x the project's budget rate, on lines with one
    actual: Figure  # Σ PO value on the same lines
    budget_cover: Figure  # share of the project's PO value that has a budget rate
    requirement: Figure  # the 3-month sheets
    fund: Figure  # the fund sheets, same months
    received: Figure  # MB51 net received value, the same number of months just past
    longlead: Figure  # look-ahead items ordered of all
    longlead_open: Figure  # value of the look-ahead items not yet ordered
    at_risk: Figure  # Today cases on this project alone
    at_risk_shared: Figure  # Today cases this project shares with others, each counted in full
    held_by_projects: Figure  # days its lines were held by Projects
    waiting_on_projects: Figure  # its lines whose move is Projects' now


class VerticalCount(BaseModel):
    id: str
    name: str
    projects: int


class ProjectsResponse(BaseModel):
    as_of: str
    period: str
    sheet_months: list[str]
    received_months: list[str]
    verticals: list[VerticalCount]
    rows: list[ProjectFigures]
    notes: list[str]


class RungCount(BaseModel):
    key: str
    label: str
    waiting: Figure | None  # lines waiting for this rung now
    standing: Figure | None  # lines whose last step is this rung, nothing waiting (closed, cancelled, paid but not closed)
    who: dict[str, int]  # whose move, for the lines waiting at this rung


class MoveRow(BaseModel):
    """The lines waiting now on one function, and the days they have waited between them."""

    function: str
    lines: Figure
    days: Figure


class OldWait(BaseModel):
    ref: str  # the ladder's subject
    text: str
    rung: str  # the rung it waits for
    waiting_on: str
    since: str | None
    days: int


class TopMaterial(BaseModel):
    code: str
    description: str
    value: Figure
    qty: float
    uom: str
    lines: int


class CaseRow(BaseModel):
    key: str
    title: str
    tab: str
    waiting_on: str
    owner: str
    act_by: str | None
    at_stake: Figure | None  # the case's own figure, whatever its label
    label: str  # at stake | claimed | if those sites paid the median | ...
    at_risk: bool  # the figure counts as ₹ at risk (money at stake or claimed)
    shared: bool  # the case names other projects too


class EstimateMonth(BaseModel):
    month: str  # YYYY-MM
    past: bool  # the whole month is before the data date
    partial: bool  # the month the data date falls in
    requirement: Figure | None
    fund: Figure | None
    fund_shared_with: list[str] = []  # the other projects a fund column covers
    received: Figure | None
    over: bool | None  # the requirement exceeds the project's best month of the past twelve by both the recipe's amount and share


class ProjectPage(BaseModel):
    row: ProjectFigures
    state: str | None
    aliases: list[str]
    work_fronts: list[str]
    ladder: list[RungCount]  # where its lines stand now, in ladder order
    whose_move: list[MoveRow]
    oldest_waits: list[OldWait]
    fronts: list[FrontStatus]
    top_materials: list[TopMaterial]
    cases: list[CaseRow]
    months: list[EstimateMonth]


# --------------------------------------------------------------------------------------------------------------------------------- Pricing
class SitePrice(BaseModel):
    project: str
    project_name: str
    vertical: str | None
    rate: Figure  # the project's last PO rate
    date: str
    vendor: str
    vendor_name: str
    buyer: str | None
    buyer_name: str | None
    budget: Figure | None
    quote: Figure | None  # the newest priced quote for this material on this project
    vs_median_pct: float | None
    lines: int


class VendorRate(BaseModel):
    vendor: str
    vendor_name: str
    lines: int
    last: Figure
    low: float
    high: float
    last_date: str
    projects: list[str]


class MonthRate(BaseModel):
    month: str
    rate: Figure | None  # Σ value / Σ quantity of the month's PO lines; None: nothing bought


class PvItem(BaseModel):
    ref: str  # po_line:<id> or lookahead:<id>
    kind: Literal["po", "lookahead"]
    project: str | None
    project_name: str | None
    vendor_name: str | None
    index: str
    base_month: str | None
    base_index: float | None
    latest_month: str | None
    latest_index: float | None
    change_pct: float | None  # the index since the base month
    share: float | None
    pv: Figure | None  # what the clause moves on the ordered quantity at the latest index; a look-ahead item: a month's wait


class IndexPoint(BaseModel):
    month: str
    value: float


class SpreadUnknown(BaseModel):
    project: str
    project_name: str
    rate: float
    what: str  # what is unknown
    ask: str | None  # member id of the buyer of that site's lines
    ask_name: str | None
    question: str
    refs: list[str]


class QuoteRow(BaseModel):
    ref: str
    vendor_name: str
    project: str | None
    project_name: str | None
    date: str | None
    rate: float | None  # as quoted, per `uom`
    uom: str | None
    rate_base: float | None  # per the material's base unit (None: a unit the master cannot convert)
    source: str
    cs: str | None
    basis: str | None


class PricingRow(BaseModel):
    code: str
    description: str
    group: str
    category: str
    uom: str
    index: str | None
    sites: int
    spread: Figure | None  # highest site rate over the lowest
    low: SitePrice | None
    high: SitePrice | None
    median: float | None
    last: Figure | None  # the newest PO rate anywhere
    last_project: str | None
    last_budget: Figure | None  # the budget rate of that line's project
    latest_quote: Figure | None
    latest_quote_project: str | None
    trend: list[MonthRate]
    trend_change: Figure | None  # the last month bought against the first, over the twelve months
    pv_lines: int
    flagged: str | None  # the Today case on this spread, if any
    unexplained: bool  # a site materially above the median, for reasons the records do not hold


class PricingDetail(PricingRow):
    by_site: list[SitePrice]
    by_vendor: list[VendorRate]
    pv: list[PvItem]
    index_series: list[IndexPoint]  # the twelve months of the material's index
    unknowns: list[SpreadUnknown]
    quotes: list[QuoteRow]


class PricingResponse(BaseModel):
    as_of: str
    months: list[str]
    rows: list[PricingRow]
    notes: list[str]


# ------------------------------------------------------------------------------------------------------------------------------- Estimates
class EstimateRow(BaseModel):
    project: str
    project_name: str
    vertical: str
    on_sheet: bool  # a 3-month requirement sheet covers it
    months: list[EstimateMonth]
    usual: Figure | None  # received a month (same materials), averaged over the months of the past twelve it received anything
    peak: Figure | None  # the most it received in one of those months: an over-ask is judged against it
    bias: Figure | None  # requirement over the usual month, averaged over the sheet's months
    accuracy: Figure | None  # 1 - |requirement - received| / requirement over the sheet's months already past
    over_months: int
    repeat: bool  # over in more than one month
    fund_disagrees: list[str]  # fund_check ids that disagree (the build's own comparison)
    ask: str | None  # the project's planner, who builds its requirement


class Unresolved(BaseModel):
    name: str
    source: str
    amount: Figure | None  # what the fund lines under this name carry
    ask: str | None  # member id who builds that sheet
    ask_name: str | None


class EstimatesResponse(BaseModel):
    as_of: str
    sheet_months: list[str]
    year_months: list[str]  # the twelve full months the project's record is read over
    threshold: str  # the rule an over-ask is judged by, in words
    rows: list[EstimateRow]
    over_askers: list[str]
    unresolved: list[Unresolved]
    notes: list[str]


# ----------------------------------------------------------------------------------------------------------------------------------- Brief
class BriefLine(BaseModel):
    text: str  # one plain line, every figure from the records
    ref: str | None = None  # "<type>:<id>": what the line links to
    figure: str | None = None  # the figure at the end of the line ("₹1.4 Cr", "42 days")


class BriefSection(BaseModel):
    key: str
    title: str
    lines: list[BriefLine]
    more: int = 0  # lines left out of the email (the screen links to the rest)
    empty: str  # what the section says when it has nothing


class Brief(BaseModel):
    person: str
    name: str
    role: str
    sender: str  # "Lookout <lookout@...>"
    to: str  # "Name <email>"
    date: str  # the data date (ISO)
    subject: str
    greeting: str
    intro: str
    sections: list[BriefSection]
    sign_off: str
    sent: bool = False  # never: Lookout does not send it
