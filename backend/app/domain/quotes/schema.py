from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from decimal import Decimal

from app.domain.common import Conditional, EntityRef, Money, Provenance, Unknown


class OfferView(BaseModel):
    """One supplier price for one part at one quantity break, with everything that comes with it."""

    offer_id: int
    supplier: EntityRef | None  # None: the sender is not in the supplier master
    supplier_name: str
    message: EntityRef
    quote_no: str | None
    part: EntityRef
    qty_break: int | None
    price: Money  # as quoted, in the quote's currency (the raw text is in the provenance)
    price_basis: Literal["each", "per_1000"]
    unit_price_usd: Money  # per piece, converted at the latest month's rate
    incoterm: str | None
    origin_claim: str | None
    origin: str | None  # ISO when the supplier's claim settles it; None when it is a customs-broker question
    origin_source: str | None = None  # 'the quote' | 'stated in the part master' (when the quote says nothing); None when undetermined
    lead_time: Conditional | None
    valid_until: str | None
    days_left: int | None
    expired: bool
    moq: int | None
    tooling_usd: float | None
    payment_terms: str | None
    conditions: str | None
    trust: str
    # The conditions beside the price as named fields (also kept in `incoterm`, `lead_time` and `conditions`).
    incoterm_term: str | None = None  # "EXW"
    incoterm_place: str | None = None  # "Hannover"
    lead_time_days: int | None = None
    surcharge_pct: float | None = None
    surcharge_included: bool | None = None  # True: the quoted price already contains the surcharge
    prepayment: str | None = None  # what must be paid before the goods ship, as the document states it
    site: str | None = None  # the plant or site the goods come from, as the quote names it in the origin claim (Huizhou, Dongguan, Georgetown); not the port in the Incoterm
    line_ref: str | None = None  # the line of the quote or mail the price was read from
    available_from: str | None = None  # ISO date this offer (an alternative origin, a new site) can start, when the document gives one


class DutyRule(BaseModel):
    """The tariff rule the part falls under, with the in-transit window the notice gives (None where it gives none)."""

    tranche: int
    rate: float
    effective_date: str
    exported_before: str | None = None
    entered_before: str | None = None


class LandedCost(BaseModel):
    """Unit cost incl. surcharge and duty, with what is not known kept apart. Code does the sum."""

    offer: OfferView
    unit_price_usd: Money
    surcharge_usd: Money | None
    duty_status: Literal["owed", "at_cost_on_top", "none", "unknown_origin", "no_rule"]
    duty_usd: Money | None  # known duty per piece (None when unknown)
    duty_if_china_usd: Money | None  # what it would be if the goods are ruled China-origin
    tooling_per_unit_usd: Money | None
    total_known_usd: Money  # price + surcharge + known duty + tooling per unit
    total_if_china_usd: Money | None
    last_paid_usd: Money | None = None  # the current-order column only: what was paid on the last PO line, with no duty
    with_new_duty_usd: Money | None = None  # ... and that price plus the new duty its origin would bring; None when no duty applies
    unknowns: list[Unknown]
    notes: list[str]
    duty_rule: DutyRule | None = None  # the rule for this part; None when it is not on the list


class BidColumn(BaseModel):
    label: str
    landed: LandedCost
    is_current: bool = False  # the last PO line, for reference


class QuoteFigure(BaseModel):
    """One quoted or derived figure with a stable id, a unit and where it comes from (the quote's line, or the rule that computed it), so an answer can cite it."""

    id: str
    name: str
    amount: Decimal
    unit: str  # a currency code, or '%'
    provenance: Provenance


class BidTab(BaseModel):
    part: EntityRef
    qty: int | None
    columns: list[BidColumn]  # cheapest known total first
    figures: list[QuoteFigure] = []  # every quoted price at every break, the order totals, prepayment, change on the last PO, and the quote's other lines and 2027 duty
    note: str
