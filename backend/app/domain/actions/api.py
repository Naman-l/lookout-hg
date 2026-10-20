"""Approvals and the simulated outbox (api/openapi.yaml). ORCH mounts this router under /api.

These routes are the only way to approve, reject or execute an action; no agent tool reaches them."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ... import db as _db
from .. import naming
from ..annotate import service as annotate
from . import approvers, ledger
from .schema import Action, ActionState, OutboxMessage

router = APIRouter(tags=["approvals"])
log = logging.getLogger(__name__)


class Approve(BaseModel):
    payload_hash: str
    approved_by: str
    confirm_unverified: bool = False  # required when the run that wrote the draft did not pass its code checks


class Reject(BaseModel):
    reason: str
    rejected_by: str


def _buyer(name: str) -> str:
    """The deciding person must be one of the company's buyers; the ledger records the full name."""
    who = approvers.resolve(_db.DB_PATH, name)
    if who is None:
        raise HTTPException(422, "the person deciding must be one of the company's buyers")
    return who


def _only_the_owner(action: Action | None, who: str) -> None:
    """A draft is signed or edited by the buyer who owns its item. Another buyer is refused (403), and so is everyone when the owner cannot be found (409), unless LOOKOUT_ALLOW_DELEGATION=1 says a team may sign for each other."""
    if action is None or os.environ.get("LOOKOUT_ALLOW_DELEGATION") == "1":
        return
    try:
        owners = approvers.owners_of_action(_db.DB_PATH, action)
    except approvers.NoOwner as e:
        raise HTTPException(409, f"Nobody can sign this: {e}. Set LOOKOUT_ALLOW_DELEGATION=1 if the team signs for each other.") from e
    except approvers.OwnerLookupError as e:
        raise HTTPException(409, f"Nobody can sign this now: {e} (the error is logged). Try again, or ask the administrator.") from e
    if owners and who not in owners:
        raise HTTPException(403, f"This belongs to {' and '.join(sorted(owners))}: only they can sign it, and you are {who}. (A team that signs for each other sets LOOKOUT_ALLOW_DELEGATION=1.)")


def _entities(a: Action) -> dict:
    """What the draft's subject and body mention, matched against the records. A nicety for the screen: if the records cannot be read, the draft is shown without it."""
    try:
        with Session(create_engine(f"sqlite:///{_db.DB_PATH}", future=True)) as s:
            out = {"subject_entities": annotate.annotate(s, a.subject), "body_entities": annotate.annotate(s, a.body)}
            if a.target is not None and a.target.type == "supplier":      # the name a buyer says (the short form), for the queue and the heading
                out["target"] = a.target.model_copy(update={"label": naming.supplier_name(s, a.target.id)})
            return out
    except Exception:  # noqa: BLE001
        log.warning("could not annotate action %s", a.action_id, exc_info=True)
        return {}


def _picks() -> dict:
    """The buyer's choices: a route chosen on Decision (the ledger's choice notes), and a draft she asked Lookout for in Ask (her own words chose it)."""
    out = {}
    try:
        import sqlite3  # noqa: PLC0415

        con = sqlite3.connect(f"file:{_db.DB_PATH}?mode=ro", uri=True)
        try:
            asked = dict(con.execute("SELECT run_id, COALESCE(asked_by, '') FROM runs WHERE workflow = 'ask' OR item_key LIKE 'ask:%'").fetchall())
            for aid, run, at in con.execute("SELECT action_id, run_id, proposed_at FROM actions WHERE run_id IS NOT NULL"):
                if run in asked:
                    out[aid] = {"option_kind": "ask", "routes": [], "by": asked[run] or "the buyer (in Ask)", "at": at}      # a replayed Ask run keeps no asker
        finally:
            con.close()
    except Exception:  # noqa: BLE001  no runs table: only the ledger's choices
        log.warning("could not read Ask runs for choices", exc_info=True)
    return {**out, **ledger.choices(_db.DB_PATH)}


def _shown(a: Action, chosen: dict | None = None) -> Action:
    update = _entities(a)
    c = (chosen if chosen is not None else _picks()).get(a.action_id)
    if c:
        update.update(chosen=True, chosen_route=c["option_kind"], chosen_routes=c.get("routes") or [c["option_kind"]], chosen_by=c["by"], chosen_at=c["at"])
    if a.state == "proposed":
        update["unverified_checks"] = approvers.unverified_checks_of(_db.DB_PATH, a)
    return a.model_copy(update=update) if update else a


def _refuse(e: ledger.LedgerError) -> HTTPException:
    return HTTPException(404 if e.code == "no_such_action" else 409, e.message)


@router.get("/actions", response_model=list[Action], operation_id="listActions")
def list_actions(state: ActionState | None = None, item_key: str | None = None, run_id: str | None = None, chosen: bool | None = None):
    """The drafts, newest first; `item_key` keeps the drafts of one Action list item and `run_id` those of one run (both exact); `chosen=true` only the
    drafts whose route the buyer chose."""
    picks = _picks()
    return [_shown(a, picks) for a in ledger.list_actions(_db.DB_PATH, state) if (item_key is None or a.item_key == item_key) and (run_id is None or a.run_id == run_id)
            and (chosen is None or (a.action_id in picks) == chosen)]


@router.get("/actions/{action_id}", response_model=Action, operation_id="getAction")
def get_action(action_id: str):
    a = ledger.get(_db.DB_PATH, action_id)
    if a is None:
        raise HTTPException(404, "no such action")
    return _shown(a)


@router.post("/actions/{action_id}/approve", response_model=Action, operation_id="approveAction")
def approve(action_id: str, body: Approve):
    """Approve exactly what was shown, then execute (simulated send). 409 on a stale hash or a non-proposed state."""
    who = _buyer(body.approved_by)
    current = ledger.get(_db.DB_PATH, action_id)
    _only_the_owner(current, who)
    if current is not None and current.state == "proposed":
        failed = approvers.unverified_checks_of(_db.DB_PATH, current)
        if failed and not body.confirm_unverified:
            raise HTTPException(409, "the run that wrote this draft did not pass its checks (" + "; ".join(failed[:3]) + "); confirm to approve it anyway")
    try:
        return _shown(ledger.approve(_db.DB_PATH, action_id, body.payload_hash, who))
    except ledger.LedgerError as e:
        raise _refuse(e) from e


class EditDraft(BaseModel):
    subject: str
    body: str
    edited_by: str
    reason: str | None = None  # a staged decision only: its reason and re-check date are part of what the owner signs (F101)
    recheck_on: str | None = None


@router.patch("/actions/{action_id}", response_model=Action, operation_id="editAction")
def edit_action(action_id: str, body: EditDraft):
    """Change the subject and text of a draft still waiting. The payload hash changes, so the buyer approves the edited text, not the old one. 409 once decided."""
    who = _buyer(body.edited_by)
    held = ledger.get(_db.DB_PATH, action_id)
    _only_the_owner(held, who)
    change = None
    if body.reason is not None or body.recheck_on is not None:
        staged = (held.change or {}) if held and held.type == "note" else {}
        if staged.get("kind") != "record":
            raise HTTPException(422, "only a staged decision has a reason and a re-check date")
        if body.reason is not None and not body.reason.strip():
            raise HTTPException(422, "a decision needs a reason")
        change = {**staged, **({"reason": body.reason.strip()} if body.reason is not None else {}), **({"recheck_on": body.recheck_on or None} if body.recheck_on is not None else {})}
    try:
        return _shown(ledger.update_draft(_db.DB_PATH, action_id, subject=body.subject, body=body.body, edited_by=who, change=change))
    except ledger.LedgerError as e:
        raise _refuse(e) from e


@router.post("/actions/{action_id}/reject", response_model=Action, operation_id="rejectAction")
def reject(action_id: str, body: Reject):
    who = _buyer(body.rejected_by)
    _only_the_owner(ledger.get(_db.DB_PATH, action_id), who)
    try:
        return _shown(ledger.reject(_db.DB_PATH, action_id, body.reason, who))
    except ledger.LedgerError as e:
        raise _refuse(e) from e


class LineChange(BaseModel):
    po_line: str
    was: str | None = None  # the promise or quantity on the line today
    now: str  # what it should become, to enter in the ERP


class StageAction(BaseModel):
    """What the owner chose on a case that is not an email: a note to someone inside the company, a decision on record, or PO lines to update in the ERP.
    Staged for the owner's signature like a draft; approving it records it and sends nothing (no outbox row)."""

    kind: Literal["note", "record", "erp_update"]
    staged_by: str
    text: str
    to: str = ""  # a note: who reads it ("planning", "Accounts Payable", a buyer)
    reason: str = ""  # a decision on record must say why
    lines: list[LineChange] = []  # an ERP update: each line, was -> now
    recheck_on: str | None = None  # a decision to wait: the date to look again
    option_kind: str | None = None  # the option on the case this came from (OPTION_KINDS)


_KIND_SUBJECT = {"note": "Note to {to}", "record": "Decision", "erp_update": "PO lines to update · enter in the ERP"}


@router.post("/action-items/{key}/actions", response_model=Action, status_code=201, operation_id="stageCaseAction")
def stage_case_action(key: str, body: StageAction):
    """Stage a note, a decision or an ERP update on a case for its owner's signature (F101: Approvals hold everything that needs a signature).
    Only an owner of the case may stage it, and only that person may approve it. Never on a trust item: nothing is acted on from a message that failed the checks."""
    if key.startswith("trust:"):
        raise HTTPException(409, "nothing is staged on a trust item: phone the contact on file")
    who = _buyer(body.staged_by)
    if not body.text.strip():
        raise HTTPException(422, "say what the note or decision is")
    if body.kind == "record" and not body.reason.strip():
        raise HTTPException(422, "a decision on record needs a reason")
    if body.kind == "erp_update" and not body.lines:
        raise HTTPException(422, "an ERP update lists the PO lines it changes")
    if body.kind == "note" and not body.to.strip():
        raise HTTPException(422, "a note says who it is for")
    try:
        owners = approvers.owners_of(_db.DB_PATH, key)
    except (approvers.NoOwner, approvers.OwnerLookupError) as e:
        raise HTTPException(409, f"Nobody can sign this now: {e}") from e
    if not owners:
        raise HTTPException(404, "no case with an owner on the Action list has this key")
    if who not in owners and os.environ.get("LOOKOUT_ALLOW_DELEGATION") != "1":
        raise HTTPException(403, f"This case belongs to {' and '.join(sorted(owners))}: only they can stage and sign for it, and you are {who}.")
    change = {"kind": body.kind, "to": body.to or None, "reason": body.reason or None, "lines": [l.model_dump() for l in body.lines] or None,
              "recheck_on": body.recheck_on, "option_kind": body.option_kind, "owner": who}
    try:
        return _shown(ledger.propose(_db.DB_PATH, type="note", item_key=key, run_id=None, target=None, recipient=None,
                                     subject=_KIND_SUBJECT[body.kind].format(to=body.to), body=body.text, change=change))
    except ledger.LedgerError as e:
        raise _refuse(e) from e


class ChooseRoute(BaseModel):
    by: str
    reason: str = ""  # a decision on record must say why


@router.post("/action-items/{key}/routes/{kind}/choose", response_model=Action, operation_id="chooseRoute")
def choose_route(key: str, kind: str, body: ChooseRoute):
    """The buyer chooses a route on a case (the main one, or each "Also start"): the choice is recorded with who and when, and its draft is returned:
    the one the morning run prepared for that route, or one drafted now in code from the route's template, to its recipient on file. Owner only; no model;
    nothing is sent until the owner approves the draft."""
    from sqlalchemy.orm import Session as _S  # noqa: PLC0415

    from .routes import RouteError, choose  # noqa: PLC0415

    who = _buyer(body.by)
    with _S(create_engine(f"sqlite:///{_db.DB_PATH}", future=True)) as s:
        try:
            a, how = choose(s, _db.DB_PATH, key, kind, who, body.reason)
        except RouteError as e:
            raise HTTPException(e.status, e.message) from e
        except ledger.LedgerError as e:
            raise _refuse(e) from e
    return _shown(a).model_copy(update={"change": {**(a.change or {}), "how": how}})


class HeldControl(BaseModel):
    control: str  # one of the held message's required actions, as the case page words it
    by: str


@router.post("/action-items/{key}/controls", response_model=Action, status_code=201, operation_id="recordHeldControl")
def record_held_control(key: str, body: HeldControl):
    """A held message's required action, done: recorded on the case at once with who and when (BUYER 02: ticks kept only in the browser were gone in a
    new tab). Nothing is staged or sent; the record is append-only, so a done control stays done."""
    if not key.startswith("trust:"):
        raise HTTPException(409, "only a held message has required actions")
    who = _buyer(body.by)
    control = body.control.strip()
    if not control:
        raise HTTPException(422, "say which required action was done")
    return _shown(ledger.record_app_action(_db.DB_PATH, type="note", item_key=key, target=None, body=f"Done: {control}", by=who, change={"kind": "control", "control": control}))


@router.get("/outbox", response_model=list[OutboxMessage], operation_id="listOutbox")
def outbox():
    return ledger.outbox(_db.DB_PATH)
