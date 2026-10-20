from typing import Literal

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.inbox import service
from app.domain.inbox.model import Message, MessageEvent
from app.domain.orders.model import PoLine
from app.domain.quotes.model import Offer
from app.domain.inbox.schema import Classification, MessageDetail, MessageSummary, RelatedStage

router = APIRouter()

CASE_ORDER = ("disruption:", "incident:", "risk:", "deadline:")      # the case a supplier's or a part's message moves: a stopped line first, then a supplier's risk, then a date


def _parts_of(session: Session, m: Message) -> list[str]:
    """The parts a message is about: on the PO lines its events name, in its offers, else named in its text."""
    lines = [e.ref_id for e in session.scalars(select(MessageEvent).where(MessageEvent.message_id == m.id, MessageEvent.ref_type == "po_line"))]
    parts = list(session.scalars(select(PoLine.part_number).where(PoLine.id.in_(lines)))) if lines else []
    parts += [o.part_number for o in session.scalars(select(Offer).where(Offer.message_id == m.id)) if o.part_number]
    parts += re.findall(r"\bHR-\d{5}\b", m.body or "") if not parts else []
    return list(dict.fromkeys(parts))


def _case_of(session: Session, m: Message, items: list) -> tuple[str | None, str | None]:
    """The open case a message moves: the one that names the message, else the case of its supplier, else the case of a part it names (FINAL 04 §6b)."""
    own = next((i.key for i in items if any(r.type == "message" and r.id == m.id for r in i.refs)), None)
    if own:
        return own, "message"
    ranked = lambda k: next((n for n, p in enumerate(CASE_ORDER) if k.startswith(p)), None)  # noqa: E731
    cands = sorted((i for i in items if ranked(i.key) is not None), key=lambda i: ranked(i.key))
    if m.identity_id:
        sup = next((i.key for i in cands if any(r.type == "supplier" and r.id == m.identity_id for r in i.refs)), None)
        if sup:
            return sup, "supplier"
    parts = set(_parts_of(session, m))
    by_part = next((i.key for i in cands if parts & {r.id for r in i.refs if r.type == "part"}), None)
    return (by_part, "part") if by_part else (None, None)


def _unlisted(session: Session, m: Message) -> str | None:
    """A company not on file, named the way naming.supplier_name names one on file (its first two words), from what its own quote says it is."""
    name = session.scalar(select(Offer.supplier_name).where(Offer.message_id == m.id, Offer.supplier_name.is_not(None)))
    return " ".join(name.replace(",", " ").split()[:2]) if name else None


def _with_cases(session: Session, rows: list[MessageSummary]) -> list[MessageSummary]:
    """Each row with what the Inbox list shows (FINAL 04 §6a): the owner, the supplier's short name, the robots, and the case it moves with where that stands."""
    from app.db import DB_PATH
    from app.domain import naming
    from app.domain.actions import ledger
    from app.domain.attention import service as attention, stage

    items = stage.attach(session, DB_PATH, attention.what_needs_attention(session))
    owner_of = {a.action_id: getattr(a, "owner", None) for a in ledger.list_actions(DB_PATH)}
    out = []
    for r in rows:
        m = session.get(Message, r.ref.id)
        if m is None:
            out.append(r)
            continue
        key, link = _case_of(session, m, items)
        it = next((i for i in items if i.key == key), None)
        st = it.stage if it else None
        parts = [] if r.trust == "suspicious" else _parts_of(session, m)
        if not parts and r.trust != "suspicious" and m.identity_id:      # a message that names no part stands for its supplier's open lines
            parts = list(dict.fromkeys(session.scalars(select(PoLine.part_number).where(PoLine.identity_id == m.identity_id, PoLine.status == "OPEN"))))
        out.append(r.model_copy(update={
            "owner": service._owner_text(session, m.id), "supplier_short": naming.supplier_name(session, m.identity_id) if m.identity_id else _unlisted(session, m),
            "robots": attention._robots_of(session, parts), "related_item": key, "link": link, "changes": service.message_changes(session, m.id),
            "related_stage": RelatedStage(key=st.key, label=st.label, waiting_on=st.waiting_on,
                                          draft_owner=owner_of.get(st.action.id) if st.action else None) if st else None,
        }))
    return out


@router.get("/messages", response_model=list[MessageSummary], summary="The shared inbox, one row per message, trust computed before any model reads it; searched with q (sender, company, subject, body, facts, part and PO numbers) and filtered")
def messages(q: str | None = None, kind: str | None = None, supplier: str | None = None, trust: Literal["on_file", "new_sender", "suspicious"] | None = None,
             date_from: str | None = None, date_to: str | None = None, session: Session = Depends(get_session)):
    """Every word of `q` must be found; each row says where (subject, from, supplier, refs, facts, body) with the text around the match and its span. Best match first, then newest."""
    return _with_cases(session, service.search_messages(session, q, kind=kind, supplier=supplier, trust=trust, date_from=date_from, date_to=date_to))


@router.get("/messages/review", response_model=list[Classification], summary="The messages the code would not act on alone: blocked, unknown sender, sender not on file, or several kinds fit")
def review(session: Session = Depends(get_session)):
    return service.check_these(session)


@router.get("/messages/{message_id}", response_model=MessageDetail, summary="One message as quoted data, its trust flags, the lines it rests on and what it changes")
def message(message_id: str, session: Session = Depends(get_session)):
    from app.domain.attention import service as attention

    items = attention.what_needs_attention(session)
    m = session.get(Message, message_id)
    related, link = _case_of(session, m, items) if m is not None else (None, None)
    d = service.message_detail(session, message_id, related)
    if d is None:
        raise HTTPException(404, "no such message")
    return d.model_copy(update={"link": link})


