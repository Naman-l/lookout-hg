"""The shared inbox (api/openapi.yaml): the list (searchable, Yours / Everyone), and one message as quoted data with what it means."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import db as _db
from app.db import get_session
from app.domain.attention import service as attention, stage
from app.domain.inbox import service
from app.domain.inbox.schema import MessageDetail, MessageSummary

router = APIRouter()


def _staged(session: Session, rows: list[MessageSummary]) -> list[MessageSummary]:
    keys = {r.related_item for r in rows if r.related_item}
    items = [attention.item_detail(session, k) for k in keys]
    items = stage.attach(session, _db.DB_PATH, [i for i in items if i is not None])
    return service.with_stage(rows, {i.key: i for i in items})


@router.get("/messages", response_model=list[MessageSummary], summary="The shared inbox, newest first; trust computed before anyone reads; q searches sender, company, subject, facts, PR/PO numbers and body")
def messages(q: str | None = None, owner: str | None = None, kind: str | None = None, trust: str | None = None, session: Session = Depends(get_session)):
    rows = service.list_messages(session)
    if owner:
        from app.domain import lookups  # noqa: PLC0415

        b = lookups.member_of(session, owner)
        rows = [r for r in rows if b and r.owner and b.name in r.owner.split(" · ")]
    if kind:
        rows = [r for r in rows if r.kind == kind]
    if trust:
        rows = [r for r in rows if r.trust == trust]
    if q:
        rows = service.search(session, rows, q)
    return _staged(session, rows)


@router.get("/messages/{message_id}", response_model=MessageDetail, summary="One message as quoted data: trust, what it means, the dates it carries, the lines it moves, the case it feeds")
def message(message_id: str, session: Session = Depends(get_session)):
    d = service.detail(session, message_id)
    if d is None:
        raise HTTPException(404, "no such message")
    return d.model_copy(update={"summary": _staged(session, [d.summary])[0]})
