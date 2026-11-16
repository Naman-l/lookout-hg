from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.quotes import service
from app.domain.quotes.schema import CsView, QuoteView

router = APIRouter()


@router.get("/cs/{cs_no:path}", response_model=CsView, summary="One comparative statement: quotes in, L1 against the last PO rate and the budget rate")
def cs(cs_no: str, session: Session = Depends(get_session)):
    out = service.cs(session, cs_no)
    if out is None:
        raise HTTPException(404, "no such comparative statement")
    return out


@router.get("/materials/{code}/quotes", response_model=list[QuoteView], summary="Every quote on file for a material, newest first")
def material_quotes(code: str, session: Session = Depends(get_session)):
    return service.quotes_for_material(session, code)
