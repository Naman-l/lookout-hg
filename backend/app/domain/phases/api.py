from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.attention import service as attention
from app.domain.phases import service
from app.domain.phases.schema import BuildReadiness, BuildSummary, Ladder

router = APIRouter()


@router.get("/phases", response_model=Ladder, response_model_exclude_none=True, summary="The stage ladder of one PO line or one part: what the records show, what is expected, what is unknown and who to ask")
def phases(po_line: str | None = None, part: str | None = None, session: Session = Depends(get_session)):
    if bool(po_line) == bool(part):
        raise HTTPException(422, "give exactly one of po_line or part")
    out = service.line_phases(session, po_line) if po_line else service.part_phases(session, part)
    if out is None:
        raise HTTPException(404, "no such PO line" if po_line else "no such part")
    return out


@router.get("/builds", response_model=list[BuildSummary], response_model_exclude_none=True, summary="Each product's next build with its readiness counts and verdict")
def builds(session: Session = Depends(get_session)):
    return service.builds(session)


@router.get("/builds/{product}/{month}/readiness", response_model=BuildReadiness, response_model_exclude_none=True,
            summary="Where each part of a named build stands, rolled up by sub-assembly, with a verdict in counts")
def readiness(product: str, month: str, session: Session = Depends(get_session)):
    out = service.build_readiness(session, product, month)
    if out is None:
        raise HTTPException(404, "no such product or no forecast for that month")
    held = attention.cases_by_part(session)
    for g in out.groups:
        for p in g.parts:
            p.cases = held.get(p.part.id, [])
    return out
