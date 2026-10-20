from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.consignments import service
from app.domain.consignments.schema import Consignment

router = APIRouter()


@router.get("/consignments", response_model=list[Consignment], summary="Material the company owns at a contract manufacturer, what it becomes there, its open orders' dates now and the products a slip reaches")
def consignments(session: Session = Depends(get_session)):
    return service.list_consignments(session)
