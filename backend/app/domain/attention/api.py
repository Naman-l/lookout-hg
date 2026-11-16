"""Today and the case page (api/openapi.yaml): the list of cases, one case in full, its routes, and the live counts for the sidebar."""

import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db as _db
from app.db import get_session
from app.domain import lookups
from app.domain.attention import decisions, routes, service, stage
from app.domain.attention.schema import ActionItem, ActionItemDetail, LinkedCase
from app.domain.imports import service as imports_service
from app.domain.inbox.model import Message
from app.domain.orders.model import PoLine
from app.domain.prs.model import PrLine

router = APIRouter()

COUNT_PROVIDERS: dict[str, Callable[[Session], int]] = {}
LATEST_RUN_PROVIDER: Callable[[str], tuple[dict | None, dict | None]] | None = None
RUNS_PROVIDER: Callable[[str], list] | None = None


class Counts(BaseModel):
    action_items: int = 0
    inbox: int = 0
    held: int = 0
    open_prs: int = 0
    open_po_lines: int = 0
    approvals_pending: int = 0
    waiting_all: int = 0
    to_sign_mine: int | None = None  # drafts the asking member owns and can sign (give `buyer`)
    countersign_mine: int | None = None  # signed drafts waiting for the asking member's countersign
    runs_running: int = 0
    data_issues: int = 0


@router.get("/counts", response_model=Counts, summary="Live counts for the sidebar")
def counts(buyer: str | None = None, session: Session = Depends(get_session)):
    from app.domain.actions import approvers, ledger  # noqa: PLC0415

    c = Counts(action_items=len(service.what_needs_attention(session)), inbox=session.scalar(select(func.count()).select_from(Message)),
               held=session.scalar(select(func.count()).select_from(Message).where(Message.trust == "blocked")),
               open_prs=session.scalar(select(func.count()).select_from(PrLine).where(PrLine.status == "open")),
               open_po_lines=session.scalar(select(func.count()).select_from(PoLine).where(PoLine.status == "open")),
               data_issues=len(imports_service.list_issues(session)))
    for name, fn in COUNT_PROVIDERS.items():
        setattr(c, name, fn(session))
    waiting = ledger.list_actions(_db.DB_PATH, "proposed")
    signed = ledger.list_actions(_db.DB_PATH, "signed")
    c.approvals_pending = c.waiting_all = len(waiting) + len(signed)
    from app.domain.actions.api import _picks  # noqa: PLC0415

    picks = _picks()
    waiting = [a for a in waiting if a.action_id in picks or not a.run_id]      # a draft a run prepared counts once its owner chooses its route
    c.approvals_pending = c.waiting_all = len(waiting) + len(signed)
    if buyer:
        who = approvers.resolve(_db.DB_PATH, buyer)
        mine = 0
        for a in waiting:
            try:
                mine += bool(who) and who in (approvers.owners_of_action(_db.DB_PATH, a) or {who})
            except approvers.OwnerLookupError:
                pass
        c.to_sign_mine = mine
        c.countersign_mine = sum(1 for a in signed if a.countersign == who)
    return c


@router.get("/action-items", response_model=list[ActionItem], summary="Today: one row per cause, ranked by code")
def action_items(owner: str | None = None, tab: str | None = None, vertical: str | None = None, project: str | None = None, waiting_on: str | None = None,
                 act_by_from: str | None = None, act_by_to: str | None = None, session: Session = Depends(get_session)):
    """Filters: `owner` (a member's id or name: their share of each case they own), `tab`, `vertical`, `project` (id or any alias), `waiting_on`,
    and an act-by window (ISO dates; a case with no date is outside a window)."""
    for name, value in (("act_by_from", act_by_from), ("act_by_to", act_by_to)):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise HTTPException(422, f"{name} must be an ISO date (YYYY-MM-DD), not {value!r}")
    pid = lookups.resolve_project(session, project) if project else None
    if project and pid is None:
        raise HTTPException(422, f"no project is called {project!r}")
    items = stage.attach(session, _db.DB_PATH, service.what_needs_attention(session, owner))
    if owner:      # a draft waiting for this person's countersign puts its case on their list too (the Head of SCM's Yours)
        who = lookups.member_of(session, owner)
        have = {i.key for i in items}
        extra = [i for i in stage.attach(session, _db.DB_PATH, service.what_needs_attention(session)) if i.key not in have and i.stage and i.stage.key == "signed"
                 and who and i.stage.waiting_on == who.name]
        items = sorted(items + extra, key=service.rank_key)
    return [i for i in items if (not tab or i.tab == tab) and (not vertical or vertical in i.verticals) and (not pid or any(p.id == pid for p in i.projects))
            and (not waiting_on or i.waiting_on == waiting_on) and (not act_by_from or (i.act_by and i.act_by >= act_by_from))
            and (not act_by_to or (i.act_by and i.act_by <= act_by_to))]


@router.get("/action-items/{key:path}/routes", response_model=list[routes.Route], summary="The case's routes, from the code table, with their figures")
def action_item_routes(key: str, owner: str | None = None, session: Session = Depends(get_session)):
    if service.item_detail(session, key) is None:
        raise HTTPException(404, "no such item")
    return routes.routes(session, key, owner)


@router.get("/action-items/{key:path}/runs", summary="The runs on one case, newest first")
def action_item_runs(key: str):
    return RUNS_PROVIDER(key) if RUNS_PROVIDER else []


def linked(session: Session, d: ActionItemDetail) -> list[LinkedCase]:
    """Other cases that share a PO, a PR, a vendor, a project or a material with this one (the IEEMA claim and the MFC case on the same vendor)."""
    mine = {(r.type, r.id) for r in d.refs}
    mine |= {("po", l.po) for l in d.po_lines} | {("pr", l.pr) for l in d.pr_lines}
    out = []
    order = ["po_line", "po", "pr_line", "pr", "supplier", "material", "project"]
    for o in service.what_needs_attention(session):
        if o.key == d.key or o.key in {x.key for x in d.dated}:
            continue
        theirs = {(r.type, r.id) for r in o.refs}
        common = mine & theirs
        if not common:
            continue
        t, i = sorted(common, key=lambda x: ["po_line", "po", "pr_line", "pr", "supplier", "material", "project"].index(x[0]) if x[0] in
                      ["po_line", "po", "pr_line", "pr", "supplier", "material", "project"] else 9)[0]
        label = next((r.label for r in d.refs if r.type == t and r.id == i), None) or i
        why = {"po_line": "the same PO line", "po": "the same PO", "pr": "the same PR", "pr_line": "the same PR line", "supplier": f"the same vendor: {label}",
               "material": f"the same material: {label}", "project": f"the same project: {label}"}.get(t, f"the same {t}")
        out.append((order.index(t) if t in order else 9, LinkedCase(key=o.key, title=o.title, why=why, owner=o.owner)))
    return [x for _, x in sorted(out, key=lambda p: p[0])][:8]


@router.get("/action-items/{key:path}", response_model=ActionItemDetail, summary="One case in full: its evidence, findings, panels and history")
def action_item(key: str, owner: str | None = None, session: Session = Depends(get_session)):
    d = service.item_detail(session, key, owner)
    if d is None:
        raise HTTPException(404, "no such item")
    d = stage.attach(session, _db.DB_PATH, [d])[0]
    latest, answer = LATEST_RUN_PROVIDER(key) if LATEST_RUN_PROVIDER else (None, None)
    held = d.held
    if held is not None:
        from app.domain.actions import ledger  # noqa: PLC0415

        done = [dict(control=(a.change or {}).get("control"), by=a.decided_by, at=a.decided_at) for a in ledger.list_actions(_db.DB_PATH)
                if a.item_key == key and (a.change or {}).get("kind") == "control"]
        held = held.model_copy(update={"done": done})
    return d.model_copy(update={"decisions": decisions.decisions_for(_db.DB_PATH, key), "latest_run": latest, "recommendation": answer, "linked": linked(session, d),
                                "held": held})
