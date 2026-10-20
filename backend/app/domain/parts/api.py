from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.parts import service
from app.domain.parts.schema import Part, PartDetail

router = APIRouter()


@router.get("/parts", response_model=list[Part], response_model_exclude_none=True, summary="The item master as the company uses it")
def parts(session: Session = Depends(get_session)):
    return service.list_parts(session)


@router.get("/parts/{part}", response_model=PartDetail, summary="One part: master row beside raw, where used, tariff and origin status, reference price")
def part(part: str, session: Session = Depends(get_session)):
    d = service.part_detail(session, part)
    if d is None:
        raise HTTPException(404, "no such part")
    return d
