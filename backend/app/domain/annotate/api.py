from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.annotate import service
from app.domain.annotate.schema import Annotate, Span

router = APIRouter()


@router.post("/annotate", response_model=list[Span], summary="What a text mentions, matched against the records (projects, plants, materials, vendors, people, PRs, POs, rupees, dates, quantities); offsets are UTF-16 indices", operation_id="annotateText")
def annotate(body: Annotate, session: Session = Depends(get_session)):
    return service.annotate(session, body.text, held=body.held)
