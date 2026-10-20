from __future__ import annotations

from app.domain.annotate.schema import Span
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.common import EntityRef


class Match(BaseModel):
    """Where a search found its words in a message: the field, the text around the match, and the match inside that text (UTF-16 indices, as a browser counts)."""

    field: Literal["subject", "from", "supplier", "refs", "facts", "tags", "body"]
    snippet: str
    start: int
    end: int


class MessageSummary(BaseModel):
    ref: EntityRef
    date: str
    from_: str = Field(alias="from")
    from_email: str | None = None  # the address it came from, exactly as the message carries it (a look-alike shows as the look-alike)
    supplier: EntityRef | None = None
    company: str = "not on file"  # the sender's company, or "not on file"
    trust: Literal["on_file", "new_sender", "suspicious"]
    trust_flags: list[str] = []
    kind: str | None = None
    summary: str
    matches: list[Match] = []  # only when a search asked: where the words were found, best field first
    replied: bool = False  # a request to this sender's company was sent after this message arrived (set from the ledger on every request, never cached)
    # FINAL 04 (set by the API from the Action list): who owns it, the name a buyer says, the robots it touches, and the case it moves
    owner: str | None = None
    supplier_short: str | None = None
    robots: list[EntityRef] = []  # products whose BOM uses a part the message changes or names; none for a held message
    related_item: str | None = None
    related_stage: "RelatedStage | None" = None
    link: Literal["message", "supplier", "part"] | None = None  # how the case was found: it names the message, its supplier, or a part the message names
    changes: list["MessageChange"] = []  # what it changes, for the row's one-line fact (the same rows as the detail)

    model_config = {"populate_by_name": True}


class RelatedStage(BaseModel):
    """Where the case a message moves stands, with whose draft waits (the screen says it in Today's words)."""

    key: str
    label: str
    waiting_on: str | None = None
    draft_owner: str | None = None  # the owner of the waiting draft, when the case is at "drafted"


class SentRequest(BaseModel):
    action_id: str
    subject: str
    sent_on: str  # the buyers' day it went out (ISO date)
    recipient: str | None = None


class TrustFlag(BaseModel):
    name: str
    words: str  # what a buyer reads


class TrustVerdict(BaseModel):
    message: EntityRef
    verdict: Literal["ok", "review", "blocked"]
    api_trust: Literal["on_file", "new_sender", "suspicious"]
    flags: list[TrustFlag]
    may_act: bool  # False: nothing can be staged from this message


class MessageChange(BaseModel):
    ref: EntityRef
    label: str
    before: str | None = None
    after: str | None = None
    line: str | None = None
    qty: int | None = None  # the quantity the source line gives for this delivery (each partial delivery is its own row)
    ship: str | None = None  # the ship date the source line gives (ISO), when it gives one


class MessageDetail(BaseModel):
    summary: MessageSummary
    subject: str
    to: str | None
    reply_to: str | None
    body: str
    owner: str | None = None  # the buyer who owns what this message is about: the linked item's owner, else the buyer on the PO lines or parts it names, else its sender's buyer, else the buyer it is addressed to
    subject_entities: list[Span] = []  # what the subject and the body mention, matched against the records (offsets in UTF-16 units)
    entities: list[Span] = []  # the body's
    highlights: list[str]
    changes: list[MessageChange]
    related_item: str | None = None
    link: Literal["message", "supplier", "part"] | None = None
    imitates: str | None = None  # the supplier domain on file that the sender's domain imitates (a look-alike), when it does
    sent: list[SentRequest] = []  # the requests we sent to this sender's company after it arrived, newest first (executed supplier requests in the ledger; simulated sends)


class Classification(BaseModel):
    """How a message was understood, and how sure the code is. The ladder stops at the first level that decides; the model (L3) is only for the rest."""

    message: EntityRef
    level: Literal[0, 1, 2, 3]  # 0 sender and trust, 1 a known format parsed by rule, 2 keyword families with anti-patterns, 3 needs the model
    kind: str | None  # force majeure | slip | price change | quote | correction | payment change | spot offer | closure | other
    confidence: float
    evidence: list[str]  # the lines the call rests on
    agrees: bool  # L1 and L2 name the same kind (or only one fired)
    decision: Literal["auto", "review", "blocked"]
    reason: str


class Thread(BaseModel):
    id: str  # the subject with RE:/FW: removed, lower-cased
    subject: str
    supplier: EntityRef | None
    messages: list[MessageSummary]  # oldest first
    corrects: list[str] = []  # "<message> corrects the number quoted in <message>"
    last_date: str
    needs_review: bool


MessageSummary.model_rebuild()
