"""The delegation of authority (`doa.csv`): who signs a document of a kind and value, and whether the Head of SCM must countersign it."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.doa.model import DoaRule
from app.domain.fmt import inr

COMMITMENT = "PO / WO / Commitment letter"
MFC = "MFC (manufacturing clearance)"
CS = "CS approval"
REQUEST = "Request or query letter (no commitment)"


class DoaLine(BaseModel):
    document: str
    value: float
    approver: str  # the role the rule names
    countersign: str | None  # the role that signs second, or None
    countersigner: str | None  # that person's full name, from the team table
    threshold: float | None  # the value above which the countersign applies
    rule_row: int
    line: str  # "<value> commitment: above <threshold>, also needs <the Head's name>, <role>"


@memo
def rules(session: Session) -> list[DoaRule]:
    return list(session.scalars(select(DoaRule).order_by(DoaRule.id)))


def decide(session: Session, document: str, value: float) -> DoaLine:
    """The rule that covers a document of this kind and value (the first whose band holds the value)."""
    mine = [r for r in rules(session) if r.document == document] or [r for r in rules(session) if r.document == REQUEST]
    hit = next((r for r in mine if value >= r.from_inr and (r.to_inr is None or value < r.to_inr)), mine[-1])
    counter = lookups.head(session) if hit.countersign else None
    threshold = min((r.from_inr for r in mine if r.countersign), default=None)
    kind = {COMMITMENT: "commitment", MFC: "MFC", CS: "CS"}.get(document, "letter")
    line = (f"{inr(value)} {kind}: above {inr(threshold)}, also needs {counter.name}, {counter.role}" if counter and threshold is not None else
            f"{inr(value)} {kind}: within the owner's authority" if value else "Commits no money: the owner signs alone")
    return DoaLine(document=hit.document, value=value, approver=hit.approver, countersign=hit.countersign, countersigner=counter.name if counter else None,
                   threshold=threshold, rule_row=hit.src_row, line=line)
