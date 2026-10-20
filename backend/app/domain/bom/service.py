"""BOM explosion and where-used. Derived on demand from bom_lines; never stored by hand."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.bom.model import BomLine
from app.domain.cache import memo
from app.domain.bom.schema import BomExplosionRow, BomTree, WhereUsedRow
from app.domain.demand.model import Product
from app.domain.parts.model import Part
from app.domain.values import prov, qty, ref


def _children(session: Session) -> dict[str, list[BomLine]]:
    kids: dict[str, list[BomLine]] = defaultdict(list)
    for line in session.scalars(select(BomLine).order_by(BomLine.id)):
        kids[line.parent_part].append(line)
    return kids


@memo
def explode_bom(session: Session, product: str) -> list[BomExplosionRow]:
    """Every part inside `product` (a finished-good part number) with its quantity per robot.

    Quantities multiply down the tree; a part that sits in two places (second placements, shared sub-assemblies) appears
    once per route. The rule is recorded in each row's provenance."""
    kids = _children(session)
    uom = {p.part_number: p.uom for p in session.scalars(select(Part))}
    pname = session.scalar(select(Product.name).where(Product.part_number == product))
    root = ref("product", product, pname)
    rows: list[BomExplosionRow] = []

    def walk(parent: str, mult: Decimal, path: list[str], level: int) -> None:
        for line in kids.get(parent, []):
            q = mult * Decimal(str(line.qty_per))
            p = path + [line.child_part]
            rows.append(BomExplosionRow(
                product=root, part=ref("part", line.child_part), level=level, path=p,
                flags=(line.flags or "").split(",") if line.flags else [],
                qty_per_robot=qty(q, uom.get(line.child_part, line.uom), prov(
                    "computed", "bom_lines", row=str(line.id), rule="quantity per parent multiplied down the bill of materials",
                    by="bom.explode_bom"))))
            walk(line.child_part, q, p, level + 1)

    walk(product, Decimal(1), [product], 1)
    return rows


def where_used(session: Session, part: str) -> list[WhereUsedRow]:
    """Which finished products contain `part`, how many per robot, by which routes."""
    names = {p.part_number: p.name for p in session.scalars(select(Product))}
    products = list(names)
    from app.domain.consignments.model import Consignment  # noqa: PLC0415

    into = [c.into_part for c in session.scalars(select(Consignment).where(Consignment.material_part == part))]  # a board the company consigns to a maker is used wherever the part it becomes is
    out = []
    for product in products:
        hits = [r for r in explode_bom(session, product) if r.part.id == part]
        paths = [r.path for r in hits]
        qty_sum = sum((r.qty_per_robot.value for r in hits), Decimal(0))
        for parent in into:  # the consigned material reaches the robot through the part it is built into: the route ends with the material
            via = [r for r in explode_bom(session, product) if r.part.id == parent]
            paths += [[*r.path, part] for r in via]
            qty_sum += sum((r.qty_per_robot.value for r in via), Decimal(0))  # one board per built part: the count is the parent's
        if paths:
            out.append(WhereUsedRow(product=ref("product", product, names.get(product)), part=ref("part", part), qty_per_robot=qty_sum, paths=paths))
    return out


@memo
def requirements_per_robot(session: Session) -> dict[str, dict[str, Decimal]]:
    """{product: {part: qty per robot}}, summed over routes. The demand service multiplies this by the forecast."""
    out: dict[str, dict[str, Decimal]] = {}
    for p in session.scalars(select(Product)):
        acc: dict[str, Decimal] = defaultdict(Decimal)
        for r in explode_bom(session, p.part_number):
            acc[r.part.id] += r.qty_per_robot.value
        out[p.part_number] = dict(acc)
    return out


@memo
def bom_tree(session: Session, product: str) -> BomTree | None:
    """The indented BOM of a product in drawing order (find number, then part), every line once, with the defects the recipe found marked on the line."""
    from app.domain.bom.schema import BomTreeRow, BomTree
    from app.domain.demand.model import Product as ProductRow

    prod = session.get(ProductRow, product)
    if prod is None:
        return None
    parts = {p.part_number: p for p in session.scalars(select(Part))}
    kids = _children(session)
    rows: list[BomTreeRow] = []

    def key(line: BomLine):
        return (int(line.find_no) if (line.find_no or "").isdigit() else 10**6, line.child_part)

    def walk(parent: str, mult: Decimal, level: int) -> None:
        for line in sorted(kids.get(parent, []), key=key):
            q = mult * Decimal(str(line.qty_per))
            p = parts.get(line.child_part)
            uom = p.uom if p else line.uom
            defects = [f for f in (line.flags or "").split(",") if f]
            rows.append(BomTreeRow(
                part=ref("part", line.child_part, p.description if p else None), parent=ref("part", parent, parts[parent].description if parent in parts else None), level=level,
                find_no=line.find_no, in_master=p is not None, obsolete=bool(p and p.status == "Obsolete"), is_assembly=line.child_part in kids, defects=defects,
                qty_per=qty(line.qty_per, uom, prov("stated", "bom_lines", row=str(line.id), raw=f"{line.qty_per_raw} {line.uom_raw}") if "unit_converted" not in defects
                         else prov("computed", "bom_lines", row=str(line.id), raw=f"{line.qty_per_raw} {line.uom_raw}", rule="the BOM's quantity converted to the part's own unit", by="bom.bom_tree")),
                qty_per_robot=qty(q, uom, prov("computed", "bom_lines", row=str(line.id), rule="quantity per parent multiplied down the bill of materials", by="bom.bom_tree"))))
            walk(line.child_part, q, level + 1)

    walk(product, Decimal(1), 1)
    count: dict[str, int] = {}
    for r in rows:
        for d in r.defects:
            count[d] = count.get(d, 0) + 1
    return BomTree(product=ref("product", product, prod.name), rows=rows, defects=count)


@memo
def robots_by_part(session: Session) -> dict[str, list[str]]:
    """{part: [product ids]} for every part in a robot's BOM, in product order; a consigned board counts wherever the part it becomes is used."""
    from app.domain.consignments.model import Consignment

    out: dict[str, list[str]] = {}
    for p in session.scalars(select(Product).order_by(Product.part_number)):
        for r in explode_bom(session, p.part_number):
            ids = out.setdefault(r.part.id, [])
            if p.part_number not in ids:
                ids.append(p.part_number)
    for c in session.scalars(select(Consignment)):
        for pid in list(out.get(c.into_part, [])):
            ids = out.setdefault(c.material_part, [])
            if pid not in ids:
                ids.append(pid)
    return out
