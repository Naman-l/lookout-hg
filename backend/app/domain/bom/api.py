from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.bom import service
from app.domain.bom.schema import BomTree, WhereUsedRow
from app.domain.parts.model import Part

router = APIRouter()


@router.get("/parts/{part}/where-used", response_model=list[WhereUsedRow], summary="Which robots contain the part, how many per robot, by which routes")
def where_used(part: str, session: Session = Depends(get_session)):
    if session.scalar(select(Part.part_number).where(Part.part_number == part)) is None:
        raise HTTPException(404, "no such part")
    return service.where_used(session, part)


@router.get("/products/{product}/bom", response_model=BomTree, response_model_exclude_none=True, summary="The indented BOM of a robot in drawing order, defects marked on the lines")
def bom(product: str, session: Session = Depends(get_session)):
    t = service.bom_tree(session, product)
    if t is None:
        raise HTTPException(404, "no such product")
    return t
