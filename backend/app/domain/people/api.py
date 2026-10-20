from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.people import service
from app.domain.people.schema import Person

router = APIRouter()


@router.get("/people", response_model=list[Person], summary="The buyers: who they are, what they buy, what is open on their desk")
def people(session: Session = Depends(get_session)):
    return service.list_people(session)
