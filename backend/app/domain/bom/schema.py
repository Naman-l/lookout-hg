from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.domain.common import EntityRef, Quantity


class BomExplosionRow(BaseModel):
    """One part inside a finished product, with the quantity per robot multiplied down every level."""

    product: EntityRef
    part: EntityRef
    qty_per_robot: Quantity
    path: list[str]  # part numbers from the product down to this part
    level: int
    flags: list[str] = []


class WhereUsedRow(BaseModel):
    product: EntityRef
    part: EntityRef
    qty_per_robot: Decimal
    paths: list[list[str]]  # every route the part takes to the product (a shared sub-assembly gives several products)


class BomTreeRow(BaseModel):
    """One line of the indented BOM, in drawing order: the part, how many sit in its parent and in the whole robot, and anything wrong with the line."""

    part: EntityRef  # label: the part's description
    parent: EntityRef
    level: int
    find_no: str | None
    qty_per: Quantity  # in its parent
    qty_per_robot: Quantity
    is_assembly: bool
    in_master: bool  # False: the item master does not know this part (an orphan)
    obsolete: bool
    defects: list[str]  # orphan_child | obsolete_child | second_placement | unit_converted


class BomTree(BaseModel):
    product: EntityRef
    rows: list[BomTreeRow]
    defects: dict[str, int]  # how many lines carry each defect, so the page can say "3 lines need a look"
