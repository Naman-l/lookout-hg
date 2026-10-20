from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef, Money


class Contact(BaseModel):
    name: str | None
    email: str | None  # the only valid recipient for anything Lookout drafts


class RiskFlag(BaseModel):
    """One warning the records carry about a supplier (insolvency, prepayment demanded, payment terms cut, a quote far above the last PO), with the words it was read from."""

    kind: Literal["insolvency", "prepayment", "terms_cut", "price_jump", "late_delivery", "cash_in_advance", "undated_open", "news_risk"]
    severity: Literal["high", "medium"]
    text: str
    evidence: str | None = None
    sources: list[EntityRef] = []


class LateStreak(BaseModel):
    """The supplier's recent record when it is getting worse (F105: shown only then): its last receipts, all late, and this year's late share against last year's.
    Receipts in the order they arrived; late = received after the promise, the rule of `delivery_performance`."""

    late_in_row: int  # the current run of late receipts, counted back from the latest one
    first: str  # the receipt date of the first late one in the run
    last: str  # ... and of the latest
    min_days_late: int
    max_days_late: int
    year: int  # the data date's year
    late_this_year: int
    n_this_year: int
    late_pct_this_year: float
    late_last_year: int
    n_last_year: int
    late_pct_last_year: float | None = None  # None with no receipt last year
    line: str  # "Last 9 receipts late · 65% late in 2026 (12% in 2025)": the one line a screen shows in place of the all-time on-time share


class DeliveryPerformance(BaseModel):
    """How a supplier has delivered, from its closed lines that have both a promise and a receipt date."""

    n: int  # closed lines counted
    on_time: int  # received on or before the promise
    on_time_pct: float
    late: int
    avg_days_late: float | None = None  # over the late ones
    last10_on_time: int | None = None  # on time among its latest 10 receipts (or fewer, when it has fewer)
    last10_n: int | None = None
    streak: LateStreak | None = None  # a run of at least STREAK_MIN late receipts; None otherwise (the screens then show the plain on-time share)


class Supplier(BaseModel):
    ref: EntityRef
    short: str = ""  # the name a buyer says (the brand word, not the legal form), the one Today, the Inbox and the cases use; the legal name is ref.label
    country: str
    terms: str
    incoterms: str
    status: Literal["active", "hold", "inactive"]
    open_value: Money
    past_due_lines: int
    records: int  # vendor records for this company (aliases kept)
    delivery: DeliveryPerformance | None = None  # None when it has no closed line with both dates
    risk: list[RiskFlag] = []  # warnings read from its quotes and the news: for the banner on its page


class SupplierDetail(Supplier):
    """One company: its records, the contact on file, its open lines (stale ones counted apart) and the messages and news about it."""

    contact: Contact
    tier: int | None
    record_ids: list[str]
    open_lines: int  # open and partial lines, stale ones left out
    open_summary: str = ""  # "10 open · 2 may not really be open": the header over the order rows, which are open + stale
    stale_lines: int = 0  # old orders that may not really be open: shown as an unknown, not as supply or as late
    messages: list[EntityRef]
    news: list[EntityRef]
