"""The material requirement against supply: what the 3-month sheets ask per project, material and month, beside what open POs bring by their
(revised) delivery dates and what MB51 has received; and the work fronts that stop when a material lands late, is under a disruption or has no PO.
Site stock is not in the data, so every shortfall is "up to"."""

from __future__ import annotations

import calendar
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.funds.model import FundCheck, FundLine
from app.domain.orders.service import all_lines as po_lines, revisions
from app.domain.receipts.model import Receipt
from app.domain.requirements.model import RequirementLine


class MonthRow(BaseModel):
    month: str  # YYYY-MM
    required: float | None  # the requirement sheet's quantity for the month (None: the sheet has no row for it)
    required_value: float | None
    on_order: float  # open PO quantity due in the month (by the vendor's revised date where one is on file)
    received: float  # net received in the month
    late_into: float  # open quantity due earlier but moved by the vendor into a later month
    gap: float | None  # required - on order - received, never below 0 ("up to": site stock is not in the data)


class SupplyByMonth(BaseModel):
    project: str
    project_name: str
    materials: list[str]
    uom: str | None
    months: list[MonthRow]
    note: str


class FrontStatus(BaseModel):
    front: str
    month: str
    lines: int  # requirement lines for the front's material groups in the month
    in_time: int  # covered by a PO due in or before the month
    late: int  # covered only by a PO due after the month
    disrupted: int  # covered, but the supply sits under a closure or strike window
    no_po: int  # no open PO: covered only by stock nobody has counted (unknown)
    stops_on: str | None  # the earliest need date a late or missing supply misses (the 1st of the month), "up to"
    materials: list[str]


def month_end(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


@memo
def all_lines(session: Session) -> list[RequirementLine]:
    return list(session.scalars(select(RequirementLine).order_by(RequirementLine.project_id, RequirementLine.month)))


def lines_for(session: Session, project: str | None = None, material: str | None = None) -> list[RequirementLine]:
    return [r for r in all_lines(session) if (not project or r.project_id == project) and (not material or material in (r.material_codes or "").split(","))]


def _due(l, rev) -> list[tuple[str, float]]:
    """(date, qty) the open quantity of a PO line is due on: the vendor's revised splits where its mail moved them, else the line's own date."""
    if rev:
        total = sum(r.qty or 0 for r in rev) or l.open_base
        return [(r.date, (r.qty or 0) * l.open_base / total if total else 0) for r in rev]
    return [(l.delivery_date or AS_OF.isoformat(), l.open_base)]


def supply_by_month(session: Session, project: str, materials: list[str], months: list[str] | None = None) -> SupplyByMonth:
    req = [r for r in all_lines(session) if r.project_id == project and set((r.material_codes or "").split(",")) & set(materials)]
    lines = [l for l in po_lines(session).values() if l.project_id == project and l.material in materials]
    rev = revisions(session)
    keys = sorted(set(months or []) | {r.month for r in req} | {AS_OF.isoformat()[:7]})
    on_order: dict[str, float] = {}
    moved: dict[str, float] = {}
    for l in lines:
        if l.status != "open" or l.open_base <= 0:
            continue
        for when, q in _due(l, rev.get(l.id, [])):
            on_order[when[:7]] = on_order.get(when[:7], 0) + q
            if rev.get(l.id) and l.delivery_date and l.delivery_date[:7] < when[:7]:
                moved[when[:7]] = moved.get(when[:7], 0) + q
    received: dict[str, float] = {}
    ids = [l.id for l in lines]
    if ids:
        for r in session.scalars(select(Receipt).where(Receipt.po_line_id.in_(ids))):
            received[r.posting_date[:7]] = received.get(r.posting_date[:7], 0) + float(r.qty_base or 0)
    keys = sorted(set(keys) | {k for k in on_order if keys and k <= max(keys)})
    rows = []
    for k in keys:
        q = sum(r.qty for r in req if r.month == k) if any(r.month == k for r in req) else None
        v = sum(r.amount or 0 for r in req if r.month == k) if q is not None else None
        oo, rc = on_order.get(k, 0.0), received.get(k, 0.0)
        rows.append(MonthRow(month=k, required=q, required_value=v, on_order=round(oo, 3), received=round(rc, 3), late_into=round(moved.get(k, 0.0), 3),
                             gap=max(0.0, round(q - oo - rc, 3)) if q is not None else None))
    m0 = lookups.materials(session).get(materials[0]) if materials else None
    return SupplyByMonth(project=project, project_name=lookups.project_name(session, project), materials=materials, uom=m0.base_uom if m0 else None, months=rows,
                         note="Up to: site stock is not in the data. Requirement from the 3-month sheet; on order by the delivery date (the vendor's revised date where its mail moved it); received net of reversals.")


def fronts_for(session: Session, project: str | None, materials: list[str]) -> list[str]:
    """The work fronts of a project that consume any of the materials' groups."""
    groups = {lookups.materials(session)[m].group for m in materials if m in lookups.materials(session)}
    return [w.name for w in lookups.work_fronts(session).get(project or "", []) if groups & set((w.material_groups or "").split(","))]


def disruption_windows(session: Session) -> list[dict]:
    """Closures and strikes read from mail: (projects, from, to or None for indefinite, message)."""
    from app.domain.inbox.model import MessageEvent  # noqa: PLC0415

    out = []
    for e in session.scalars(select(MessageEvent).where(MessageEvent.kind.in_(("closure", "strike")))):
        out.append(dict(projects=[p for p in (e.ref_id or "").split(",") if p], start=e.date_from, end=e.date_to, message=e.message_id, kind=e.kind))
    return out


def readiness(session: Session, project: str) -> list[FrontStatus]:
    """Per work front and month of the requirement sheet: how its requirement lines are covered. Worst first (most lines not covered in time)."""
    mats = lookups.materials(session)
    lines = [l for l in po_lines(session).values() if l.project_id == project and l.status == "open" and l.open_base > 0]
    rev = revisions(session)
    windows = [w for w in disruption_windows(session) if project in w["projects"]]
    out = []
    for w in lookups.work_fronts(session).get(project, []):
        groups = set((w.material_groups or "").split(","))
        for month in sorted({r.month for r in lines_for(session, project)}):
            req = [r for r in lines_for(session, project) if r.month == month and any(mats.get(c) and mats[c].group in groups for c in (r.material_codes or "").split(","))]
            if not req:
                continue
            st = dict(in_time=0, late=0, disrupted=0, no_po=0)
            stops = None
            for r in req:
                codes = set((r.material_codes or "").split(","))
                cover = [l for l in lines if l.material in codes]
                dues = [d for l in cover for d, _ in _due(l, rev.get(l.id, []))]
                if not cover:
                    st["no_po"] += 1
                    stops = min(filter(None, [stops, f"{month}-01"]))
                elif any(w0["start"] and w0["start"] <= month_end(month) and (w0["end"] is None or w0["end"] >= f"{month}-01") for w0 in windows):
                    st["disrupted"] += 1
                    stops = min(filter(None, [stops, max(f"{month}-01", min(w0["start"] for w0 in windows))]))
                elif min(dues) <= month_end(month):
                    st["in_time"] += 1
                else:
                    st["late"] += 1
                    stops = min(filter(None, [stops, f"{month}-01"]))
            out.append(FrontStatus(front=w.name, month=month, lines=len(req), stops_on=stops, materials=sorted({c for r in req for c in (r.material_codes or "").split(",") if c}), **st))
    return sorted(out, key=lambda f: (-(f.late + f.disrupted + f.no_po), f.month, f.front))


@memo
def fund_checks(session: Session) -> list[FundCheck]:
    return list(session.scalars(select(FundCheck).order_by(FundCheck.month, FundCheck.column_as_printed)))


def fund_lines(session: Session, project: str | None = None) -> list[FundLine]:
    return [f for f in session.scalars(select(FundLine).order_by(FundLine.month)) if not project or project in (f.project_ids or "").split(",")]


def months_ahead(n: int = 3) -> list[str]:
    y, m = AS_OF.year, AS_OF.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def first_of(ym: str) -> date:
    return date(int(ym[:4]), int(ym[5:7]), 1)
