from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.projects import service
from app.domain.projects.service import ProjectRow

router = APIRouter()


@router.get("/projects", response_model=list[ProjectRow], summary="Every project by vertical: plants, aliases, people on file, what is open")
def projects(session: Session = Depends(get_session)):
    return service.list_projects(session)
