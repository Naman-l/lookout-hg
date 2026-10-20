from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.demand import service
from app.domain.demand.schema import ForecastRow, ProductOut

router = APIRouter()


@router.get("/forecast", response_model=list[ForecastRow], summary="Robots to build per month, by product")
def forecast(session: Session = Depends(get_session)):
    return service.forecast(session)


@router.get("/products", response_model=list[ProductOut], summary="The finished robots the company builds: the roots of the BOM views")
def products(session: Session = Depends(get_session)):
    return service.products(session)
