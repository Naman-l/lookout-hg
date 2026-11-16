from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.requirements import service
from app.domain.requirements.service import FrontStatus, SupplyByMonth

router = APIRouter()


class RequirementRow(BaseModel):
    id: str
    project: str | None
    project_name: str
    sheet: str
    row: str  # the material row as the sheet writes it
    materials: list[str]
    unit: str | None
    month: str
    qty: float
    rate: float | None
    amount: float | None
    fund: float | None  # the fund sheet's figure for the same project, head and month (its head covers several rows; shown on the head's first row)
    fund_head: str | None
    src: str  # sheet cell reference


@router.get("/requirements", response_model=list[RequirementRow], summary="The 3-month requirement sheets as long form, with the fund sheet's figure beside each head")
def requirements(project: str | None = None, session: Session = Depends(get_session)):
    pid = lookups.resolve_project(session, project) if project else None
    heads = lookups.answers().get("fund_heads") or {}
    head_of = {row: h for h, rows in heads.items() for row in rows}
    checks = {(c.project_ids, c.head, c.month): c for c in service.fund_checks(session)}
    seen: set = set()
    out = []
    for r in service.lines_for(session, pid):
        h = head_of.get(r.row_as_printed)
        c = next((x for (pids, head, month), x in checks.items() if head == h and month == r.month and r.project_id in (pids or "").split(",")), None) if h else None
        first = c is not None and (c.id not in seen)
        if c is not None:
            seen.add(c.id)
        out.append(RequirementRow(id=r.id, project=r.project_id, project_name=lookups.project_name(session, r.project_id) or r.column_as_printed, sheet=r.sheet, row=r.row_as_printed,
                                  materials=[m for m in (r.material_codes or "").split(",") if m], unit=r.unit, month=r.month, qty=r.qty, rate=r.rate, amount=r.amount,
                                  fund=c.fund if first else None, fund_head=h, src=f"{r.file} r{r.src_row} c{r.src_col}"))
    return out


@router.get("/supply", response_model=SupplyByMonth, summary="Requirement against supply by month for a project and material(s)")
def supply(project: str, material: str, session: Session = Depends(get_session)):
    pid = lookups.resolve_project(session, project)
    if pid is None:
        raise HTTPException(404, "no such project")
    return service.supply_by_month(session, pid, material.split(","), service.months_ahead())


@router.get("/workfronts", response_model=list[FrontStatus], summary="Work-front readiness per project and month, worst first ('up to': site stock is not in the data)")
def workfronts(project: str, session: Session = Depends(get_session)):
    pid = lookups.resolve_project(session, project)
    if pid is None:
        raise HTTPException(404, "no such project")
    return service.readiness(session, pid)
