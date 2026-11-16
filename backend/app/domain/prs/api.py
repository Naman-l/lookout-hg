from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.phases.ladder import ladder
from app.domain.phases.schema import Ladder
from app.domain.prs import service
from app.domain.prs.service import PrLineView

router = APIRouter()


class PrDetail(BaseModel):
    pr: str
    lines: list[PrLineView]
    ladders: list[Ladder]


@router.get("/prs", response_model=list[PrLineView], summary="PR lines (ME5A) with status, age, turnaround and plain-word flags")
def prs(status: str | None = None, buyer: str | None = None, project: str | None = None, flag: str | None = None, session: Session = Depends(get_session)):
    b = lookups.member_of(session, buyer) if buyer else None
    pid = lookups.resolve_project(session, project) if project else None
    rows = service.list_lines(session, status=status, buyer=b.id if b else None, project=pid)
    return [r for r in rows if not flag or flag in r.flags]


@router.get("/prs/{pr_no}", response_model=PrDetail, summary="One PR: its lines and each line's PR-to-payment ladder")
def pr(pr_no: str, session: Session = Depends(get_session)):
    lines = service.lines_of_pr(session, pr_no)
    if not lines:
        raise HTTPException(404, "no such PR")
    return PrDetail(pr=pr_no, lines=[service.view(session, l) for l in lines], ladders=[x for x in (ladder(session, pr_line_id=l.id) for l in lines) if x])
