from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.domain.common import EntityRef


class MaterialLine(BaseModel):
    po_line: EntityRef
    promised: str | None  # the date in the ERP
    now: str | None  # the date now expected (the supplier's revision when there is one)
    days_later: int | None  # now minus promised, when both are known


class ProductReached(BaseModel):
    product: EntityRef
    qty_per_robot: Decimal  # of the part the material is built into


class Consignment(BaseModel):
    """Material that the company owns at a contract manufacturer, the part it becomes there, and what a slip in it reaches."""

    id: int
    material: EntityRef
    holder: EntityRef  # the contract manufacturer that holds it and builds it in
    into: EntityRef  # the part built from it
    evidence: str
    method: str
    material_lines: list[MaterialLine]  # open orders for the material, with their dates now
    slip_days: int | None  # the longest slip among them; None when none has slipped
    reaches: list[ProductReached]  # the finished products that contain the part built from it
