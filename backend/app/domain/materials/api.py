from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.materials import service
from app.domain.materials.service import MaterialDetail, MaterialRow

router = APIRouter()


@router.get("/materials", response_model=list[MaterialRow], summary="The material master with what is open and the last rate paid")
def materials(session: Session = Depends(get_session)):
    return service.list_materials(session)


@router.get("/materials/{code}", response_model=MaterialDetail, summary="One material: rate history by site and vendor, where used, open PRs and POs, quotes against the last PO and the budget")
def material(code: str, session: Session = Depends(get_session)):
    d = service.detail(session, code)
    if d is None:
        raise HTTPException(404, "no such material")
    return d
