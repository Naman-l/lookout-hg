"""The owner chooses a route; the draft follows the choice. `choose` records the choice (append-only: who, when), then returns the route's draft: one
already waiting for that route, else one written now in code from the route's template, to the route's recipient on file, in house style, staged
`proposed` for the owner's signature like any draft. A route that commits money carries the DoA's countersigner, so it waits as `signed` after the
owner signs until that person countersigns the same text.

- request: a letter to the vendor's contact on file (one per vendor when the route goes to several). One open thread per contact: a letter still
  waiting to that address gets this route's ask as a paragraph (its owner must own this case too).
- internal_note: a short memo to the person on file who owns the function (the project head or planner, Treasury, QA, a member of SCM); sent
  (simulated), and the case waits on that function until they answer.
- note: an entry to make in SAP or a note on record, signed and sent nowhere.
- record: the owner's decision on record, with the reason they give.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import routes as table
from app.domain.attention import service
from app.domain.inbox.model import Message

from . import ledger
from .letters import DraftRefused, add_paragraph, internal_ask, memo, reply_by, vendor_ask, vendor_letter


class RouteError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _route(session: Session, key: str, kind: str, by: str) -> table.Route:
    for r in table.routes(session, key, by):
        if r.kind == kind:
            return r
    raise RouteError(404, f"this case has no route '{kind}'")


def _check_owner(session: Session, key: str, by: str):
    if key.startswith("trust:"):
        raise RouteError(409, "nothing is drafted on a held message: record the controls instead")
    d = service.item_detail(session, key)
    if d is None:
        raise RouteError(404, "no such case")
    import os  # noqa: PLC0415

    if by not in d.owner.split(" · ") and os.environ.get("LOOKOUT_ALLOW_DELEGATION") != "1":
        raise RouteError(403, f"This case belongs to {d.owner.replace(' · ', ' and ')}: only they can choose for it, and you are {by}.")
    return d


def _change(route: table.Route, kind: str, member, extra: dict | None = None) -> dict:
    ch = {"owner": member.name, "option_kind": kind, "option_kinds": [kind]}
    if route.commits is not None:
        ch.update(commits_inr=float(route.commits.amount), document=route.document, doa_line=route.doa_line)
    if route.countersign and route.countersign != member.name:
        ch["countersign"] = route.countersign
    return {**ch, **(extra or {})}


def draft_route(session: Session, db_path, key: str, kind: str, by: str, reason: str = "", run_id: str | None = None) -> tuple[list[ledger.Action], str]:
    """Draft route `kind` of case `key` for its owner `by` (a full name). Returns the drafts and how: drafted, amended (the ask added to the letter
    waiting to that contact) or covered (that letter already asks it)."""
    d = _check_owner(session, key, by)
    member = lookups.member_of(session, by)
    route = _route(session, key, kind, by)
    company = lookups.answers().get("company") or "the company"
    msgs = {m.id: m for m in session.query(Message).filter(Message.id.in_([x.id for x in d.messages]))} if d.messages else {}
    out, how = [], "drafted"
    try:
        if route.leads_to == "request":
            if not route.to or not any(r.email for r in route.to):
                raise RouteError(409, "no contact on file for this vendor, so nothing can be drafted")
            for rcp in route.to:
                if not rcp.email:
                    continue
                vendor = lookups.vendor_name(session, rcp.vendor.id) if rcp.vendor else rcp.role
                subject, refs, paras, reserve = vendor_ask(kind, d, route, vendor=vendor, msgs=msgs)
                held = ledger.open_thread(db_path, rcp.email)
                needs = bool(route.countersign and route.countersign != member.name)
                if held is not None and held.state == "proposed" and (held.change or {}).get("owner") == member.name and bool((held.change or {}).get("countersign")) == needs:
                    # one open letter per contact, when both need the same signatures: an ask that commits nothing never waits behind a countersign
                    done = set((held.change or {}).get("option_kinds") or [])
                    if kind in done:
                        out.append(held)
                        how = "covered"
                        continue
                    para = " ".join(paras)
                    po = d.po_lines[0].po if d.po_lines else None
                    if po and po not in (held.body or ""):      # the added ask names its own PO, so the vendor reads which order it is about
                        para = f"Regarding PO No. {po}" + (f" ({d.projects[0].label})" if d.projects else "") + f": {para}"
                    body = add_paragraph(held.body or "", para)
                    asks = ledger.asks_of(held)
                    ch = {**(held.change or {}), "option_kinds": sorted(done | {kind}), "asks": asks + ([key] if key not in asks else [])}
                    out.append(ledger.update_draft(db_path, held.action_id, subject=held.subject or subject, body=body, edited_by=by, change=ch, run_id=run_id))
                    how = "amended"
                    continue
                body = vendor_letter(contact=rcp.name, vendor=vendor, subject=subject, refs=[r for r in refs if r], paras=paras, confirm_by=reply_by(d.act_by),
                                     member=member, company=company, reserve=reserve)
                out.append(ledger.propose(db_path, type="supplier_request", item_key=key, run_id=run_id, target=rcp.vendor, recipient=rcp.email, subject=subject, body=body,
                                          change=_change(route, kind, member)))
        elif route.leads_to == "internal_note":
            if not route.to:
                raise RouteError(409, "nobody on file owns this function, so nothing can be drafted")
            for rcp in route.to:
                subject, paras = internal_ask(kind, d, route, to=rcp)
                body = memo(to_name=rcp.name or rcp.role, to_role=rcp.role, member=member, subject=subject, paras=paras)
                out.append(ledger.propose(db_path, type="internal_note", item_key=key, run_id=run_id, target=None, recipient=rcp.email, subject=subject, body=body,
                                          change=_change(route, kind, member, {"function": rcp.function, "to": f"{rcp.name}, {rcp.role}"})))
        elif route.leads_to == "record":
            if not reason.strip():
                raise RouteError(422, "a decision on record needs a reason")
            text = f"{route.label}." + (f" {route.changes}." if route.changes else "") + (f" Cost: {route.cost_basis}." if route.cost_basis else "")
            out.append(ledger.propose(db_path, type="note", item_key=key, run_id=None, target=None, recipient=None, subject="Decision", body=text,
                                      change=_change(route, kind, member, {"kind": "record", "reason": reason.strip()})))
        else:
            lines = [dict(po_line=l.ref.id, was=l.delivery_date, now=max(r.date for r in l.revised)) for l in d.po_lines if l.revised] if kind == "accept_new_date" else None
            erp = "SAP" in route.label
            text = f"{route.label}." + (f" {route.changes}." if route.changes else "")
            if lines:
                text += " " + "; ".join(f"{x['po_line']}: {x['was']} → {x['now']}" for x in lines) + "."
            if kind == "ask_why" or kind == "ask_owner":
                text += " " + " ".join(u.question for u in d.unknowns[:12])
            out.append(ledger.propose(db_path, type="note", item_key=key, run_id=run_id, target=None, recipient=None,
                                      subject="To enter in SAP" if erp else "Note", body=text,
                                      change=_change(route, kind, member, {"kind": "erp_update" if erp else "note", "lines": lines, "reason": reason.strip() or None})))
    except DraftRefused as e:
        raise RouteError(422, str(e)) from e
    except ledger.LedgerError as e:
        raise RouteError(409, e.message) from e
    return out, how


def choose(session: Session, db_path, key: str, kind: str, by: str, reason: str = "") -> tuple[ledger.Action, str, list[ledger.Action]]:
    """Record that `by` chose route `kind` on case `key`; return (the first draft, how it came: prepared | drafted | amended | covered, all its drafts)."""
    _check_owner(session, key, by)
    _route(session, key, kind, by)
    mine = [a for a in ledger.list_actions(db_path) if a.state in ("proposed", "signed") and (a.item_key == key or key in ledger.asks_of(a))
            and (a.change or {}).get("owner") == by and kind in ((a.change or {}).get("option_kinds") or [(a.change or {}).get("option_kind")])]
    if mine:
        drafts, how = mine, "prepared"
    else:
        drafts, how = draft_route(session, db_path, key, kind, by, reason)
    for a in drafts:
        ledger.record_app_action(db_path, type="note", item_key=key, target=None, body=f"Chose: {_route(session, key, kind, by).label}", by=by,
                                 change={"kind": "choice", "option_kind": kind, "action_id": a.action_id, "how": how})
    return ledger.get(db_path, drafts[0].action_id), how, [ledger.get(db_path, a.action_id) for a in drafts]
