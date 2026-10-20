from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.suppliers import service
from app.domain.suppliers.schema import Supplier, SupplierDetail

router = APIRouter()


@router.get("/suppliers", response_model=list[Supplier], summary="Suppliers, one row per company, vendor records counted")
def suppliers(country: str | None = None, risk: bool | None = None, session: Session = Depends(get_session)):
    """Filters: `country` (its country code) and `risk` (true: only suppliers whose quotes or news carry a warning; false: the rest)."""
    return [s for s in service.list_suppliers(session) if (not country or s.country.lower() == country.lower()) and (risk is None or bool(s.risk) == risk)]


@router.get("/suppliers/{supplier_id}", response_model=SupplierDetail, summary="One company: its records, contact on file, open exposure")
def supplier(supplier_id: str, session: Session = Depends(get_session)):
    p = service.profile(session, supplier_id)
    if p is None:
        raise HTTPException(404, "no such supplier")
    return p
