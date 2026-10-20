from __future__ import annotations

from pydantic import BaseModel

from app.domain.bom.schema import WhereUsedRow
from app.domain.common import EntityRef, Money, Quantity, Unknown
from app.domain.tariffs.schema import CooStatus, PartExposure, TariffStatus


class Part(BaseModel):
    """The item master as the company uses it. A blank origin or code is an Unknown with an owner, not an empty string."""

    ref: EntityRef
    description: str
    category: str
    coo: str | Unknown
    hts: str | Unknown
    preferred_supplier: EntityRef | None = None
    open_supply: Quantity
    robots: list[str] = []  # product ids whose BOM uses the part (a consigned board counts where the part it becomes is used)


class Shortage(BaseModel):
    """The first month with a shortfall that the records assert (supply under a force-majeure notice): what is needed, what is covered, what is short."""

    month: str  # YYYY-MM
    requirement: Quantity
    covered: Quantity
    short: Quantity


class SupplyState(BaseModel):
    """The worst state among the part's open orders, as the stage ladder reads it, with the record it comes from."""

    state: str  # disrupted | late | unknown | expected
    date: str | None = None
    detail: str
    source: EntityRef | None = None


class LeadTimeActual(BaseModel):
    """How long the part's closed lines really took, order to receipt, beside the ERP's planned lead time (code-computed from the receipts)."""

    planned_days: int | None
    median_days: int
    receipts: int  # closed lines with an order and a receipt date
    later: int  # of those, how many took longer than the planned lead time (0 without one)
    lines: list[EntityRef]  # the closed lines it was computed from
    rule: str = "median of (received date - order date) over the part's closed PO lines"


class PartDetail(BaseModel):
    """Everything the part page needs, each fact with its source: the item master row beside what the other records say about the part."""

    part: Part
    kind: str  # purchased | subassembly | finished
    mpn: str | None
    manufacturer: str | None
    uom: str
    status: str  # Active | Obsolete
    buyer: str | None
    buyer_method: str | None  # 'inferred': the buyer on most of its PO lines, or its category's buyer
    planned_lead_time: Quantity | Unknown
    raw: dict[str, str | None]  # the item master row as exported
    where_used: list[WhereUsedRow]
    tariff: TariffStatus
    origin: CooStatus
    reference_price: Money | None
    open_lines: int
    linked_parts: list[EntityRef]  # possible duplicates (same manufacturer part number)
    exposure: PartExposure | None  # the duty, net and gross, when the part can owe it
    shortage: Shortage | None = None  # None: no shortfall is asserted (with no stock data most parts would look short)
    supply_state: SupplyState | None = None  # None: no open order
    lead_time_actual: LeadTimeActual | None = None  # None: no closed line with both dates
