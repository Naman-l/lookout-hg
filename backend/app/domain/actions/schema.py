"""Action and outbox shapes (api/openapi.yaml)."""

from __future__ import annotations

from app.domain.annotate.schema import Span
from typing import Any, Literal

from pydantic import BaseModel

from ..common import EntityRef

ActionType = Literal["supplier_request", "internal_note", "supplier_alias", "note"]
ActionState = Literal["proposed", "signed", "approved", "rejected", "executed"]


class Action(BaseModel):
    action_id: str
    type: ActionType
    state: ActionState
    payload_hash: str
    item_key: str | None = None
    run_id: str | None = None
    target: EntityRef | None = None
    recipient: str | None = None  # the contact on file (a vendor's, or the function owner's inside the company), never an address taken from a message
    recipient_name: str | None = None  # that person's name on file
    subject: str | None = None
    body: str | None = None
    subject_entities: list[Span] = []  # what the draft mentions, matched against the records (offsets in UTF-16 units)
    body_entities: list[Span] = []
    change: dict[str, Any] | None = None
    proposed_at: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    reason: str | None = None
    attempted_at: str | None = None
    confirmed_at: str | None = None
    outbox_id: str | None = None
    owner: str | None = None  # the one buyer who signs this draft: the buyer of the PO lines it asks about (None on a draft with no lines: the item's owners then)
    unverified_checks: list[str] = []  # the failed code checks of the run that wrote this draft; approving then needs a confirmation
    edited_by: str | None = None  # the buyer who last edited the text by hand: its figures were not re-checked by a run
    signed_by: str | None = None  # the owner's signature (first, when a countersign is needed)
    signed_at: str | None = None
    countersign: str | None = None  # the person whose countersign the DoA requires before it is sent (None: the owner's signature sends it)
    doa_line: str | None = None  # "<amount> <what>: above <threshold>, also needs <name>, <role>" (the DoA rule on file)
    chosen: bool = False  # the buyer chose the route this draft carries (POST /action-items/{key}/routes/{kind}/choose): Approvals lists the chosen ones
    chosen_route: str | None = None  # that route's kind (the latest chosen)
    chosen_routes: list[str] = []  # every route chosen that this draft carries (one email per contact can carry several)
    chosen_by: str | None = None
    chosen_at: str | None = None


class OutboxMessage(BaseModel):
    outbox_id: str
    action_id: str
    to: str
    subject: str
    body: str
    sent_at: str
    status: Literal["sent_simulated"] = "sent_simulated"
