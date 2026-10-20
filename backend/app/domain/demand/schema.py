from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import EntityRef, Quantity, Unknown


class MonthQty(BaseModel):
    month: str  # YYYY-MM
    qty: Quantity
    by_product: dict[str, int]  # robots forecast per product that month


class MonthBucket(BaseModel):
    """One month of the MRP-style view. `short` is asserted only where supply is under force majeure and recovery has not
    arrived; otherwise it is None, because with no stock data every part would look short."""

    month: str
    requirements: Quantity
    scheduled_receipts: Quantity
    under_disruption: Quantity
    short: Quantity | None  # units this month's builds are short: at most what the month needs
    uncovered_before: Quantity | None = None  # of the shortage, the part the promised dates did not cover either (no notice caused it)
    backlog: Quantity | None = None  # unmet need carried in from earlier months plus this month's: cumulative, never a month's own figure


class TimePhased(BaseModel):
    part: EntityRef
    per_unit: str  # "2 per Alpha A1"
    past_due_receipts: Quantity
    buckets: list[MonthBucket]
    on_hand: Unknown
    first_short_month: str | None = None
    unmet_after_all_open_orders: Quantity | None = None  # a part a notice moved: need still not covered once every open order has landed (the end of the horizon); more must be ordered
    disrupted: bool = False
    recovery_by: str | None = None  # the latest date the supplier's own estimate allows (the notice date plus its longest figure)
    recovery_text: str | None = None  # the supplier's own words, verbatim: '6 to 8 weeks'. Say the range, not a date.
    recovery_line: str | None = None  # the line of the notice they come from
    recovery_source: EntityRef | None = None  # ... and the message that holds it


class ForecastMonth(BaseModel):
    month: str
    units: int


class ForecastRow(BaseModel):
    product: str
    months: list[ForecastMonth]


class SlipImpact(BaseModel):
    """Supply that a supplier's notice pushed past a month in which it was needed: the shortage the slip itself causes."""

    part: EntityRef
    slipped_lines: list[EntityRef]
    months: list[str]  # months that were covered by the promised dates and are not covered by the revised ones
    first_month: str
    first_month_qty: Quantity  # units the first month's builds are short because of the new dates: at most what that month needs
    first_month_backlog: Quantity  # cumulative requirement not covered at the revised dates, beyond what was already uncovered
    by_month: dict[str, float]  # each hit month's own shortage (at most that month's requirement)
    backlog_by_month: dict[str, float]  # the cumulative figure behind it


class ProductOut(BaseModel):
    part_number: str
    name: str
    family: str
