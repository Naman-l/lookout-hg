from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.search import service
from app.domain.search.schema import Hit

router = APIRouter()


@router.get("/search", response_model=list[Hit], operation_id="search",
            summary="Search across action items, messages, suppliers (names, former names, domains), parts (number, name), PO lines (the full number and the short 'PO 450/10' form are both found) and people; deterministic, no model")
def search(q: str = Query(..., min_length=1), types: str | None = Query(None, description="comma-separated: item, message, supplier, part, po_line, person"),
           limit: int = Query(30, ge=1, le=100), session: Session = Depends(get_session)):
    return service.search(session, q, [t.strip() for t in types.split(",")] if types else None, limit)
