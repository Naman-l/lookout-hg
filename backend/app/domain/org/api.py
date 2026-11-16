"""The organisation chart (the SCM organogram) and the edits people make to it. A refused edit answers 403, 404 or 422 with the reason."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ... import db as _db
from . import service
from .schema import OrgBy, OrgChart, OrgFields

router = APIRouter(tags=["organisation"])


def _do(fn, *args):
    try:
        return fn(_db.DB_PATH, *args)
    except service.OrgError as e:
        raise HTTPException(e.status, e.message) from None


@router.get("/org", response_model=OrgChart, summary="The SCM organogram: every person and open post, whom they report to and their work, with the edits made here")
def org():
    return service.chart(_db.DB_PATH)


@router.post("/org/people", response_model=OrgChart, summary="Add a person or an open post under someone on the chart")
def add_person(body: OrgFields):
    return _do(service.add, body)


@router.patch("/org/people/{person_id}", response_model=OrgChart, summary="Change a box: name, designation, whom they report to, desk, work, or fill / open the post")
def change_person(person_id: str, body: OrgFields):
    return _do(service.update, person_id, body)


@router.delete("/org/people/{person_id}", response_model=OrgChart, summary="Take a box off the chart; anyone under it moves up to its lead")
def remove_person(person_id: str, by: str):
    return _do(service.remove, person_id, by)


@router.post("/org/undo", response_model=OrgChart, summary="Undo the latest edit")
def undo(body: OrgBy):
    return _do(service.undo, body.by)


@router.post("/org/reset", response_model=OrgChart, summary="Undo every edit: the chart as the sheet draws it")
def reset(body: OrgBy):
    return _do(service.undo, body.by, True)
