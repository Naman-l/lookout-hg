"""Names before ids: how a buyer says a vendor, a project, a material, a PR or PO line, and the label every reference carries. Nothing here knows a
customer: every name comes from the vendor master, the project directory, the material master and the order lines."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.common import EntityRef

LEGAL = (" Pvt Ltd", " Private Limited", " Ltd", " Limited", " Co., Ltd.", " Co.")


def supplier_name(session: Session, supplier_id: str) -> str:
    """The name a buyer says: the newest record's name."""
    return lookups.vendor_name(session, supplier_id)


def firm_name(name: str) -> str:
    """The name without its legal form: '<Name> Pvt Ltd' -> '<Name>'."""
    for suffix in LEGAL:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def label_for(session: Session, r: EntityRef) -> str | None:
    if r.type == "supplier":
        return lookups.vendor_name(session, r.id)
    if r.type == "project":
        return lookups.project_name(session, r.id)
    if r.type == "material":
        m = lookups.materials(session).get(r.id)
        return m.description if m else None
    if r.type in ("po_line", "pr_line"):
        from app.domain.orders.service import line  # noqa: PLC0415
        from app.domain.prs.service import all_lines  # noqa: PLC0415

        l = line(session, r.id) if r.type == "po_line" else all_lines(session).get(r.id)
        return l.short_text if l else None
    if r.type == "person":
        b = lookups.team(session).get(r.id) or lookups.contacts(session).get(r.id)
        return b.name if b else None
    return r.label


def labelled(session: Session, refs: list[EntityRef]) -> list[EntityRef]:
    return [r if r.label else r.model_copy(update={"label": label_for(session, r)}) for r in refs]
