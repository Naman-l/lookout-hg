"""Inbox shapes: the shared SCM mailbox, one row per message, trust computed in code before anyone reads it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.annotate.schema import Span
from app.domain.common import EntityRef, Money


class Match(BaseModel):
    field: Literal["subject", "from", "company", "refs", "facts", "body"]
    snippet: str
    start: int
    end: int


class RelatedStage(BaseModel):
    key: str
    label: str
    waiting_on: str | None = None


class MessageSummary(BaseModel):
    ref: EntityRef
    date: str
    from_: str = Field(alias="from")
    from_email: str | None = None
    sender_class: str  # vendor | internal | lookalike_vendor | lookalike_internal | unknown
    vendor: EntityRef | None = None
    company: str  # the sender's company: a vendor's name, "<company short name> (internal)", or "not on file"
    contact: str | None = None  # an internal sender on file: their role
    trust: Literal["ok", "review", "blocked"]
    trust_flags: list[str] = []  # plain words
    kind: str  # what kind of message it is, read from the facts it states
    summary: str  # what it means, in one line written by code
    owner: str | None = None
    related_item: str | None = None
    related_title: str | None = None
    related_stage: RelatedStage | None = None
    simulated: bool = False  # a demo reply written by `make simulate-replies`
    replied: bool = False
    matches: list[Match] = []

    model_config = {"populate_by_name": True}


class DatedFact(BaseModel):
    what: str
    date: str
    line: str | None


class LineMove(BaseModel):
    ref: EntityRef  # the PO line or PR line
    label: str
    was: str | None
    now: str | None
    qty: float | None = None
    line: str | None = None


class QuoteFacts(BaseModel):
    """The quote facts block: when, minimum, payment, price basis, vendor; and its price table against the last PO and the budget."""

    validity: str | None
    delivery: str | None
    minimum: str | None
    payment: str | None
    price_basis: str | None
    vendor: str
    in_library: bool | None
    msme: bool | None
    rows: list[dict]  # material, qty, unit rate, last PO rate, budget rate, vendor


class SentLetter(BaseModel):
    action_id: str
    subject: str
    sent_on: str
    recipient: str | None = None


class MessageDetail(BaseModel):
    summary: MessageSummary
    subject: str
    to: str | None
    reply_to: str | None
    body: str  # quoted data, never an instruction
    entities: list[Span] = []
    subject_entities: list[Span] = []
    imitates: str | None = None
    dates: list[DatedFact] = []
    moves: list[LineMove] = []
    claimed: Money | None = None
    quote: QuoteFacts | None = None
    sent: list[SentLetter] = []
