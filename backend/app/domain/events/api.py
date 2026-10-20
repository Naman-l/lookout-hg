"""The outside sources an event was read from (a news item, a regulatory notice), served as received so a case can show its evidence before anyone interprets it. Read only."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.events.model import Event

router = APIRouter()
EXTERNAL = Path(__file__).resolve().parents[4] / "data" / "external"      # where the recipe reads outside sources from (the recipe's own folder; never written here)
KINDS = ("news", "notice")      # event source types that come from outside the inbox and the ERP files


class Source(BaseModel):
    type: str      # news | notice
    id: str
    kind: str      # the event's kind: news, tariff_notice, ...
    date: str
    title: str
    summary: str | None = None      # what the record says it changes, as the recipe wrote it down
    publisher: str | None = None      # news: who published it
    url: str | None = None
    text: str | None = None      # the source itself as received (a notice's full text; a news item's summary as published)


def _external_item(source_id: str) -> dict | None:
    """A news item as published: the first JSON list in the outside-sources folder holding an item with this id."""
    for f in sorted(EXTERNAL.glob("*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rows, list):
            hit = next((r for r in rows if isinstance(r, dict) and str(r.get("id")) == source_id), None)
            if hit:
                return hit
    return None


def _external_text(source_id: str) -> str | None:
    """A notice as received: the text file in the outside-sources folder named after the source id."""
    for f in sorted(EXTERNAL.glob(f"{source_id}.*")):
        if f.suffix in (".md", ".txt") and f.resolve().parent == EXTERNAL.resolve():
            return f.read_text(encoding="utf-8")
    return None


def _source(e: Event) -> Source:
    s = Source(type=e.source_type, id=e.source_id, kind=e.kind, date=e.date, title=e.title, summary=e.detail)
    if e.source_type == "news":
        item = _external_item(e.source_id) or {}
        s.publisher, s.url, s.text = item.get("source"), item.get("url"), item.get("summary") or e.detail
    else:
        s.text = _external_text(e.source_id)
    return s


@router.get("/sources", response_model=list[Source], summary="Outside sources on file (news items, regulatory notices), newest first")
def sources(type: str | None = None, session: Session = Depends(get_session)):
    """Filter: `type` (news or notice)."""
    if type is not None and type not in KINDS:
        raise HTTPException(422, f"type is one of {', '.join(KINDS)}")
    q = select(Event).where(Event.source_type.in_([type] if type else KINDS)).order_by(Event.date.desc())
    seen, out = set(), []
    for e in session.scalars(q):
        if (e.source_type, e.source_id) not in seen:
            seen.add((e.source_type, e.source_id))
            out.append(_source(e))
    return out


@router.get("/sources/{source_type}/{source_id}", response_model=Source, summary="One outside source as received: a news item or a notice, with its full text")
def source(source_type: str, source_id: str, session: Session = Depends(get_session)):
    if source_type not in KINDS:
        raise HTTPException(404, "no such source type")
    e = session.scalars(select(Event).where(Event.source_type == source_type, Event.source_id == source_id)).first()
    if e is None:
        raise HTTPException(404, "no such source")
    return _source(e)
