import re
from collections.abc import Callable

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db as _db
from app.db import get_session
from types import SimpleNamespace

from app.domain.attention import decisions, findings, option_kinds, options, service, stage
from app.domain import naming
from app.domain.attention.schema import ActionItem, ActionItemDetail, FireOption, LinkedCase
from app.organism.context_packet import linked_items
from app.domain.imports import service as imports_service
from app.domain.inbox.model import Message
from app.domain.orders.model import PoLine
from app.domain.suppliers.service import open_summary
from app.domain.parts.model import Part
from app.domain.suppliers.model import SupplierIdentity

router = APIRouter()

# Counts that other parts of the system own (approvals, runs): they register a function here, so this module never imports them.
COUNT_PROVIDERS: dict[str, Callable[[Session], int]] = {}
# The runs table is the agent's: it registers what an item page needs of it (the newest finished run and its answer, and the item's runs) so this module never imports it.
LATEST_RUN_PROVIDER: Callable[[str], tuple[dict | None, dict | None]] | None = None
RUNS_PROVIDER: Callable[[str], list] | None = None


class Counts(BaseModel):
    action_items: int = 0
    inbox: int = 0
    suppliers: int = 0
    parts: int = 0
    open_po_lines: int = 0  # open and partial lines, stale ones left out (they are counted in stale_po_lines)
    stale_po_lines: int = 0
    open_po_summary: str = ""  # "182 open · 3 may not really be open": the Orders header, equal to its rows
    approvals_pending: int = 0
    waiting_all: int = 0  # every draft waiting for a signature, whoever owns it (the sidebar's 'waiting', labelled 'all')
    to_sign_mine: int | None = None  # the waiting drafts the asking buyer owns and can sign (give `buyer`); None when no buyer is asked about
    runs_running: int = 0
    data_issues: int = 0


@router.get("/counts", response_model=Counts, summary="Live counts for the sidebar")
def counts(buyer: str | None = None, session: Session = Depends(get_session)):
    """`waiting_all` is every draft waiting; `to_sign_mine` (with `buyer`) the ones that buyer owns, the one number Today and Approvals' "To sign" show."""
    c = Counts(
        action_items=len(service.what_needs_attention(session)),
        inbox=session.scalar(select(func.count()).select_from(Message)),
        suppliers=session.scalar(select(func.count()).select_from(SupplierIdentity)),
        parts=session.scalar(select(func.count()).select_from(Part)),
        open_po_lines=session.scalar(select(func.count()).select_from(PoLine).where(PoLine.status.in_(("OPEN", "PARTIAL")), PoLine.flags.not_like("%stale_open%"))),
        stale_po_lines=session.scalar(select(func.count()).select_from(PoLine).where(PoLine.flags.like("%stale_open%"))),
        data_issues=len(imports_service.list_issues(session)))
    c.open_po_summary = open_summary(c.open_po_lines, c.stale_po_lines)
    for name, fn in COUNT_PROVIDERS.items():
        setattr(c, name, fn(session))
    c.waiting_all = c.approvals_pending
    if buyer:
        from app.domain.actions import approvers, ledger

        who = approvers.resolve(_db.DB_PATH, buyer)
        mine = 0
        for a in ledger.list_actions(_db.DB_PATH, "proposed"):
            try:
                mine += bool(who) and who in (approvers.owners_of_action(_db.DB_PATH, a) or {who})
            except approvers.OwnerLookupError:
                pass
        c.to_sign_mine = mine
    return c


@router.get("/action-items", response_model=list[ActionItem], summary="The Action list, ranked inside each group (fire, deadline, tariff, unknown)")
def action_items(owner: str | None = None, kind: Literal["disruption", "trust", "deadline", "tariff", "unknown"] | None = None, category: str | None = None,
                 act_by_from: str | None = None, act_by_to: str | None = None, session: Session = Depends(get_session)):
    """Filters: `owner` (a name), `kind` (the group), `category` (the stage), and an act-by window (`act_by_from`, `act_by_to`; an item with no date is outside a window)."""
    for name, value in (("act_by_from", act_by_from), ("act_by_to", act_by_to)):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise HTTPException(422, f"{name} must be an ISO date (YYYY-MM-DD), not {value!r}")
    items = [i for i in service.what_needs_attention(session, owner) if (not kind or i.group == kind) and (not category or i.category == category)
             and (not act_by_from or (i.act_by and i.act_by >= act_by_from)) and (not act_by_to or (i.act_by and i.act_by <= act_by_to))]
    return stage.attach(session, _db.DB_PATH, items)


@router.get("/action-items/{key:path}/options", response_model=list[FireOption], summary="The ways through a supplier's disruption, as fields: needs, earliest date, cost, the unknown that decides")
def action_item_options(key: str, owner: str | None = None, session: Session = Depends(get_session)):
    """Every case with routes: a disruption's ways through computed from the records (needs, earliest, cost, what decides), with what each covers; any other
    kind's routes with Covers, Earliest and Cost from the case's own figures, empty with the reason where the records hold none (FINAL-SPEC §2)."""
    from app.domain.attention import route_figures  # noqa: PLC0415

    out = options.fire_options(session, key)
    table = {o.kind for o in option_kinds.option_kinds(session, key, owner)}
    if out is not None and table:  # the case's kind decides which ways through it has (a supplier at risk has nothing that 'survived'); the records fill the ones it shares
        out = route_figures.disruption_rows(session, key, [o for o in out if o.kind in table], owner)
    if out is None:
        item = service.item_context(session, key)
        if item is not None and item[0].group == "disruption" and not table:
            return []      # a disruption with no way through to offer: nothing to show, not a missing page
        if item is None:
            raise HTTPException(404, "no such item")
        if not table:
            return []      # a case whose kind has no routes yet (a trust item has controls instead): an empty table, not a missing page
        return route_figures.figures(session, key, owner)
    return out


@router.get("/action-items/{key:path}/option-kinds", response_model=list[option_kinds.OptionKind], summary="The options of the item's kind of case, from the code table: label, button, where each leads and to whom")
def action_item_option_kinds(key: str, owner: str | None = None, session: Session = Depends(get_session)):
    """`owner` (a buyer's name): where an option names records across buyers (the duty's alternate origins), the viewer's own lead."""
    if service.item_context(session, key) is None:
        raise HTTPException(404, "no such item")
    return option_kinds.option_kinds(session, key, owner)


@router.get("/action-items/{key:path}/findings", response_model=list[findings.FindingCandidate], summary="What the records show on this case, as code facts with a template meaning; the run's own meanings are on its Recommendation")
def action_item_findings(key: str, session: Session = Depends(get_session)):
    if service.item_context(session, key) is None:
        raise HTTPException(404, "no such item")
    return findings.candidates(session, key)


@router.get("/action-items/{key:path}/runs", summary="The runs on one item, newest first")
def action_item_runs(key: str):
    return RUNS_PROVIDER(key) if RUNS_PROVIDER else []


def two_step_duty(key: str, answer: dict | None) -> dict | None:
    """The duty roll-up's broker exclusion, recommended for the duty owed on lines that cannot ship before the duty starts, says both steps the case's
    next step names: budget that duty, and ask the broker for an exclusion (BUYER 02: the reason alone read as an argument for budgeting)."""
    rec = (answer or {}).get("recommended") or {}
    if key != "tariff:all" or rec.get("kind") != "broker_exclusion" or not any("duty_owed_fire" in n for n in rec.get("number_ids") or []):
        return answer
    reason = (rec.get("reason") or "").rstrip(". ")
    if not reason or "budget" in reason.lower():
        return answer
    return {**answer, "recommended": {**rec, "reason": f"{reason}: budget it, and ask the broker for an exclusion"}}


_NO_DATE = re.compile(r"[;,]?\s*no (?:new |revised )?dates? (?:given|stated)", re.I)


def dated_reason(d, answer: dict | None) -> dict | None:
    """A recommended reason that says no date was given, on a case whose every open line carries the supplier's new date, drops that clause (AI-UI-SYNC M5):
    the screen never says what the records contradict."""
    rec = (answer or {}).get("recommended") or {}
    reason = rec.get("reason") or ""
    lines = d.po_lines or []
    if not _NO_DATE.search(reason) or not lines or not all(getattr(l, "revised_date", None) for l in lines):
        return answer
    kept = _NO_DATE.sub("", reason).strip(" ;,")
    return {**answer, "recommended": {**rec, "reason": kept}} if kept else answer


@router.get("/action-items/{key:path}", response_model=ActionItemDetail, summary="One action item with its evidence and the latest Recommendation")
def action_item(key: str, owner: str | None = None, session: Session = Depends(get_session)):
    d = service.item_detail(session, key)
    if d is None:
        raise HTTPException(404, "no such item")
    if owner:      # the viewer's slice of a team case (Today's "Yours", BUYER #1): their title, figure, lines; the team total stays in the summary
        mine = next((i for i in service.what_needs_attention(session, owner) if i.key == key), None)
        if mine is not None:
            team = " · " in (d.owner or "")
            mine_lines = [l for l in (d.po_lines or []) if getattr(l, "buyer", None) == owner] if team else None      # a team roll-up keeps the viewer's own lines
            d = d.model_copy(update={"title": mine.title, "summary": mine.summary, "at_stake": mine.at_stake, "owner": mine.owner, "robots": mine.robots, "robot_notes": mine.robot_notes,
                                     **({"po_lines": mine_lines, "lines_in_scope": len(mine_lines)} if mine_lines else {})})
    d = stage.attach(session, _db.DB_PATH, [d])[0]
    latest, answer = LATEST_RUN_PROVIDER(key) if LATEST_RUN_PROVIDER else (None, None)
    answer = dated_reason(d, two_step_duty(key, answer))
    from app.organism.answer_rules import correct_answer  # noqa: PLC0415

    answer = correct_answer(answer, d)      # a recorded answer that predates a claim rule is served with it applied (planned vs short, the stake's scope, robots hit)
    team = service.what_needs_attention(session)
    linked = [LinkedCase(key=o.key, title=o.title, why=why, owner=o.owner) for o, why in linked_items(d, SimpleNamespace(attention=SimpleNamespace(list_items=lambda: team)))]
    # The messages that move this case, as the Inbox links them (a supplier's reply to the case's request included, LOOKOUT #65): one list, newest first.
    from app.domain.inbox import service as inbox_service
    from app.domain.inbox.api import _with_cases
    have = {m.ref.id for m in (d.messages or [])}
    moving = [m for m in _with_cases(session, inbox_service.list_messages(session)) if m.related_item == key and m.ref.id not in have]
    messages = sorted([*(d.messages or []), *moving], key=lambda m: m.date or "", reverse=True)
    return d.model_copy(update={"decisions": decisions.decisions_for(_db.DB_PATH, key), "latest_run": latest, "recommendation": answer, "linked": linked, "messages": messages,
                              "short_names": {r.id: naming.supplier_name(session, r.id) for r in d.refs if r.type == "supplier" and r.id}})
