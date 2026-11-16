from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.phases.ladder import ladder
from app.domain.phases.schema import Ladder

router = APIRouter()


@router.get("/ladder", response_model=Ladder, summary="The PR-to-payment ladder of one PR line or PO line: each rung's date, source row and whose move it was")
def get_ladder(pr_line: str | None = None, po_line: str | None = None, session: Session = Depends(get_session)):
    if not pr_line and not po_line:
        raise HTTPException(422, "give pr_line or po_line")
    out = ladder(session, pr_line_id=pr_line, po_line_id=po_line)
    if out is None:
        raise HTTPException(404, "no such PR line or PO line")
    return out
