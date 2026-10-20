from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.imports import service
from app.domain.imports import flow
from app.domain.imports.schema import BuildStamp, BuildStep, DataIssue, ImportAnswers, ImportApproval, ImportDeck, ImportDryRun, ImportLoaded

router = APIRouter()


@router.get("/data-issues", response_model=list[DataIssue], summary="Defects found in the company's files and how each was handled")
def data_issues(session: Session = Depends(get_session)):
    return service.list_issues(session)


@router.get("/data/steps", response_model=list[BuildStep], summary="The recipe's steps in the order they ran, with rows in and out")
def steps(session: Session = Depends(get_session)):
    return service.list_steps(session)


@router.get("/data/stamp", response_model=BuildStamp, summary="When the database was built, from which recipe, and the gate result")
def stamp(session: Session = Depends(get_session)):
    return service.build_stamp(session)


@router.get("/imports/questions", response_model=ImportDeck, response_model_by_alias=True, summary="The current import's questions as a short deck (grouped entries, a proposed answer each)")
def questions():
    return flow.deck()


@router.post("/imports/answers", response_model=ImportDeck, response_model_by_alias=True, summary="Accept, change or skip questions (one or many)")
def answers(body: ImportAnswers):
    try:
        return flow.answer(body)
    except KeyError as e:
        raise HTTPException(404, f"no such question: {e.args[0]}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/imports/dry-run", response_model=ImportDryRun, summary="The recipe run on a copy with the current answers; before and after per file, the load checks")
def dry_run():
    return flow.dry_run()


@router.post("/imports/approve", response_model=ImportLoaded, summary="Load what the dry run showed. Refused if the answers changed since that dry run.")
def approve(body: ImportApproval):
    try:
        return flow.approve(body)
    except flow.AnswersChanged:
        raise HTTPException(409, "the answers changed since the dry run")
