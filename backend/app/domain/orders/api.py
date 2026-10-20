from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.orders import service
from app.domain.orders.schema import PoLine, PoLineView

router = APIRouter()


@router.get("/orders", response_model=list[PoLine], response_model_exclude_none=True, summary="The open PO report (open and partial lines; filter by buyer)")
def orders(buyer: str | None = None, supplier: str | None = None, status: str | None = None, past_due: bool | None = None, include_stale: bool = True,
           session: Session = Depends(get_session)):
    """Filters: `buyer`, `supplier` (an identity id), `status` (OPEN or PARTIAL) and `past_due` (true: only lines behind their promise; false: only the rest)."""
    rows = service.open_orders(session, buyer, include_stale=include_stale)
    return [l for l in rows if (not supplier or l.supplier.id == supplier) and (not status or l.status.lower() == status.lower())
            and (past_due is None or bool(l.days_past_due and l.days_past_due > 0 and not l.stale) == past_due)]


@router.get("/orders/{po_line_id:path}", response_model=PoLineView, summary="One PO line, the clean values beside the source row (inferred values say so)")
def order(po_line_id: str, session: Session = Depends(get_session)):
    v = service.line_view(session, po_line_id)
    if v is None:
        raise HTTPException(404, "no such PO line")
    return v
