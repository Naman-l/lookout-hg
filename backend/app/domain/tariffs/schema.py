from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.common import EntityRef, Money, Unknown


class TariffRuleView(BaseModel):
    id: int
    tranche: int
    hts_prefix: str
    description: str
    rate: float
    effective_date: str
    origin: str
    in_transit: str | None
    exported_before: str | None = None  # goods exported before this date and entered before `entered_before` owe nothing
    entered_before: str | None = None
    source_line: str | None = None  # the row of the advisory this rule was read from, as written
    advisory_no: str | None = None
    issued: str | None = None


class TariffStatus(BaseModel):
    """Does the new duty apply to this part? By code (HTS prefix) and origin, never by supplier country."""

    part: EntityRef
    status: Literal["listed", "excluded", "not_listed", "unknown_hts"]
    rule: TariffRuleView | None = None
    excluded_by: str | None = None
    unknown: Unknown | None = None


class CooStatus(BaseModel):
    part: EntityRef
    status: Literal["china", "other", "unknown"]
    coo: str | None
    unknown: Unknown | None = None


class ExposureLine(BaseModel):
    po_line: EntityRef
    open_value: Money
    exposed: bool  # in the exposure at all: owed or conditional
    bucket: Literal["owed", "conditional", "not_owed", "pass_through", "out"] = "not_owed"  # owed: certain; conditional: owed unless it ships in time; out: probably not open
    importer: Literal["company", "supplier"]  # the importer of record pays the duty: the company for FOB/FCA/EXW/DAP, the supplier for DDP
    incoterm: str | None = None  # the supplier record's term and place, as the ERP has it: "FOB Shenzhen", "DDP Reno"
    incoterm_says: str | None = None  # what that term means for the duty, in words: "FOB: the company clears the goods and pays the duty"
    why: str  # why this line is or is not counted in the net figure
    under_force_majeure: EntityRef | None = None  # the notice, when the supplier cannot ship before the duty date and so the line is owed


class LineDuty(BaseModel):
    """The new duty on one open PO line."""

    po_line: EntityRef
    status: Literal["owed", "pass_through", "before_effective_date", "not_applicable", "unknown"]
    duty: Money | None  # what the company pays if the line enters after the effective date; None when unknown or not applicable
    importer: Literal["company", "supplier"] | None
    incoterm: str | None = None
    incoterm_says: str | None = None
    why: str
    unknown: Unknown | None = None


class PartExposure(BaseModel):
    """New duty on one part: net first (the figure to act on), gross beside it, both with their rule."""

    part: EntityRef
    tariff: TariffStatus
    coo: CooStatus
    status: Literal["china_listed", "unknown_origin", "unknown_hts", "not_applicable"]
    rate: float | None
    net: Money | None  # the headline: duty owed (= `owed`); for a part of unknown origin, what it would owe if China (= `if_china`)
    owed: Money | None = None  # duty certain to be paid: confirmed China origin, entering on/after the date
    conditional: Money | None = None  # duty on open orders that owe nothing if the supplier ships them in time (in transit); beside the headline, never in it
    if_china: Money | None = None  # parts whose origin is unknown: what they would owe if made in China; never in the headline
    rule_sentences: dict[str, str] = {}  # bucket -> the one-sentence rule, as shown beside the figure
    gross: Money | None
    open_lines: list[ExposureLine]
    uncovered_qty: float  # 12-month requirement not covered by open supply
    reference_price: Money | None
    unpriced: bool  # demand exists but the part has no reference price
    effective_date: str | None
    open_value_total: Money | None = None  # open value of the lines that have an exchange rate; a line without one is in no total
    open_duty_total: Money | None = None
    lines_without_rate: list[EntityRef] = []
    pass_through: Money | None = None  # duty on DDP lines and requirement: the supplier is importer of record; expect it in the price
    unknown: Unknown | None = None
