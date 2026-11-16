"""Where the work on a case stands: found, worked, decision ready, drafted, signed (waits for the countersign), approved, sent, answered.

Derived on every request from what runs and people leave behind, never stored: the runs on the case and the ledger of drafts and decisions. Each
stage comes with the one next act in plain words and whose move it is. Once a note to someone inside the company is out, the case reads "With
Projects", "With Finance" or "With QA" until they answer; a letter out to a vendor waits on the vendor.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.actions import ledger
from app.domain.attention.schema import Stage
from app.domain.common import AS_OF
from app.domain.fmt import local_date, md
from app.domain.inbox.model import Message
from app.domain.values import ref

LABELS = {"found": "Found", "worked": "Worked", "decision_ready": "Decide", "drafted": "Needs your OK", "signed": "Countersign", "approved": "Approved",
          "sent": "Sent", "answered": "Replied"}
OUTWARD = ("supplier_request", "internal_note", "supplier_alias")
FUNCTION_SIDE = {"project_head": "Projects", "planner": "Projects", "finance_treasury": "Finance", "finance_funds": "Finance", "vendor_master": "Finance",
                 "qa": "QA", "qa_inspection": "QA", "md_office": "Management", "ho_stores": "Projects"}


def side_of(action) -> str | None:
    """Whose move a sent internal note leaves the case with (Projects, Finance, QA, Management), from the function of its recipient on file."""
    fn = (action.change or {}).get("function") or ""
    return FUNCTION_SIDE.get(fn.split(":")[0])


def _runs(db_path) -> dict[str, list[tuple[str, str]]]:
    try:
        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute("SELECT item_key, status, started_at FROM runs ORDER BY started_at DESC").fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for key, status, at in rows:
        out.setdefault(key, []).append((status, at))
    return out


def _replies(session: Session) -> dict[str, datetime]:
    """{sender address: the newest message's time}: a vendor's or a colleague's answer, simulated replies included."""
    from app.domain.inbox.service import _dt  # noqa: PLC0415

    out: dict[str, datetime] = {}
    for addr, d in session.execute(select(Message.from_email, Message.date)):
        t = _dt(d)
        if addr and t and (addr.lower() not in out or t > out[addr.lower()]):
            out[addr.lower()] = t
    return out


def derive(item, runs: list[tuple[str, str]], actions: list, replies: dict[str, str]) -> Stage:
    chosen = {(a.change or {}).get("action_id") for a in actions if a.type == "note" and (a.change or {}).get("kind") == "choice"}
    # a draft a run prepared waits for the owner's choice of its route; until then the case is theirs to decide, not to sign
    prepared = [a for a in actions if a.state == "proposed" and a.run_id and a.action_id not in chosen]
    actions = [a for a in actions if a not in prepared]
    live = [a for a in actions if a.type in OUTWARD and a.state != "rejected"]
    staged = [a for a in actions if a.type == "note" and (a.change or {}).get("kind") in ("note", "record", "erp_update")]
    sent = sorted([a for a in live if a.type in ("supplier_request", "internal_note") and a.state == "executed"], key=lambda a: a.confirmed_at or "", reverse=True)
    if sent:
        a = sent[0]
        from app.domain.inbox.service import _dt  # noqa: PLC0415

        out_at = _dt(a.confirmed_at or a.decided_at)
        who = a.recipient_name or a.recipient
        got = replies.get((a.recipient or "").lower())
        if got and out_at and got > out_at:
            return Stage(key="answered", label=LABELS["answered"], step=7, at=got.isoformat(), waiting_on="you", action=ref("action", a.action_id),
                         next_act=f"{who} has answered: read the reply and decide what is left.")
        side = side_of(a) if a.type == "internal_note" else None
        chase = f" Chase if nothing comes by {md(item.act_by)}." if item.act_by and item.act_by >= AS_OF.isoformat() else ""
        return Stage(key="sent", label=f"With {side}" if side else LABELS["sent"], step=6, at=a.confirmed_at, waiting_on=side or "the vendor", action=ref("action", a.action_id),
                     next_act=f"Sent to {who} (simulated). Waiting for {who} to answer.{chase}")
    signed = next((a for a in live + staged if a.state == "signed"), None)
    if signed:
        return Stage(key="signed", label=LABELS["signed"], step=5, at=signed.signed_at, waiting_on=signed.countersign, action=ref("action", signed.action_id),
                     next_act=f"Signed by {(signed.signed_by or '').split()[0]}; waits for {signed.countersign}'s countersign before it is sent.")
    done = next((a for a in live if a.state in ("approved", "executed")), None)
    if done:
        return Stage(key="approved", label=LABELS["approved"], step=5, at=done.decided_at, waiting_on=None, action=ref("action", done.action_id),
                     next_act="Approved. Nothing is waiting on you for this one.")
    recorded = next((a for a in staged if a.state in ("approved", "executed")), None)
    waiting = next((a for a in live if a.state == "proposed"), None) or next((a for a in staged if a.state == "proposed"), None)
    if recorded and not waiting:
        return Stage(key="approved", label="Recorded", step=5, at=recorded.decided_at, waiting_on=None, action=ref("action", recorded.action_id),
                     next_act=f"Recorded: {recorded.subject or 'the decision'}. Nothing is sent and nothing is waiting on you.")
    if waiting:
        to = waiting.recipient_name or waiting.recipient
        act = "Sign or reject: it records your decision and sends nothing." if waiting.type == "note" else f"Approve or reject the draft to {to}."
        return Stage(key="drafted", label=LABELS["drafted"], step=4, at=waiting.proposed_at, waiting_on="you", action=ref("action", waiting.action_id), next_act=act)
    rejected = next((a for a in actions if a.type in OUTWARD and a.state == "rejected"), None)
    note = f" You rejected the draft on {md(local_date(rejected.decided_at))}: {rejected.reason}." if rejected and rejected.reason else ""
    ok = next((r for r in runs if r[0] in ("ok", "did_not_pass")), None)
    if ok:
        ready = f" Lookout prepared the draft for its recommended route ({(prepared[0].change or {}).get('option_kind', '').replace('_', ' ')})." if prepared else ""
        return Stage(key="decision_ready", label=LABELS["decision_ready"], step=3, at=ok[1], waiting_on="you",
                     next_act=("Read the analysis, then choose a route." + ready + note).strip())
    if runs:
        status, at = runs[0]
        return Stage(key="worked", label=LABELS["worked"], step=2, at=at, waiting_on=None if status == "running" else "you",
                     next_act="Lookout is working on it." if status == "running" else "The last run did not finish. Run it again.")
    return Stage(key="found", label=LABELS["found"], step=1, waiting_on="you", next_act=("Open the case: the routes are ready to choose from." + note).strip())


def _with_names(session: Session, actions: list) -> list:
    """Each draft with its recipient's name on file (a vendor's contact or a person inside the company)."""
    by_mail = {(c.email or "").lower(): c.name for c in lookups.contacts(session).values() if c.email}
    by_mail.update({(r.contact_email or "").lower(): r.contact_name for r in lookups.records(session).values() if r.contact_email})
    return [a.model_copy(update={"recipient_name": by_mail.get((a.recipient or "").lower())}) if a.recipient else a for a in actions]


def actions_by_item(session: Session, db_path) -> dict[str, list]:
    by_item: dict[str, list] = {}
    all_ = _with_names(session, ledger.list_actions(db_path))
    by_id = {a.action_id: a for a in all_}
    for a in all_:
        for k in ledger.asks_of(a) or ([a.item_key] if a.item_key else []):
            by_item.setdefault(k, []).append(a)
    for k, acts in by_item.items():      # a draft the owner chose for this case moves it, even when another case wrote it (one letter per contact)
        picked = {(a.change or {}).get("action_id") for a in acts if a.type == "note" and (a.change or {}).get("kind") == "choice"}
        acts += [by_id[p] for p in picked if p in by_id and by_id[p] not in acts]
    return by_item


def attach(session: Session, db_path, items: list) -> list:
    """The same items with their stage set; a sent internal note moves the case's 'waiting on' to that function until it answers."""
    runs = _runs(db_path)
    by_item = actions_by_item(session, db_path)
    replies = _replies(session)
    out = []
    for it in items:
        st = derive(it, runs.get(it.key, []), by_item.get(it.key, []), replies)
        upd = {"stage": st}
        if st.key == "sent":
            side = st.label.removeprefix("With ") if st.label.startswith("With ") else "Vendor"
            upd["waiting_on"] = side if side in ("Projects", "Finance", "QA", "Management", "Vendor") else it.waiting_on
            upd["next_action"] = st.next_act
        elif st.key == "signed":
            upd["waiting_on"] = "Management"
        elif st.key in ("answered", "drafted"):
            upd["waiting_on"] = "SCM"
        out.append(it.model_copy(update=upd))
    return out
