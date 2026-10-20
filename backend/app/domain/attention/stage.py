"""Where the work on an item stands: found, worked, decision ready, drafted, approved, sent, answered.

Derived on every request from two records people and runs leave behind, never stored: the runs of the organism on the item and the
ledger of drafts and decisions. Each stage comes with the one next act, in plain words. The same ladder is what the agent is told, so it
and the screen say the same thing about the same item.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.actions import ledger
from app.domain.attention.schema import ActionItem, Stage
from app.domain.common import AS_OF
from app.domain.fmt import local_date, md
from app.domain.suppliers import service as suppliers
from app.domain.suppliers.model import SupplierIdentity
from app.domain.values import ref
from app.domain.inbox.model import Message

ORDER = ("found", "worked", "decision_ready", "drafted", "approved", "sent", "answered")
LABELS = {"found": "Found", "worked": "Worked", "decision_ready": "Decision ready", "drafted": "Needs your OK", "approved": "Approved", "sent": "Sent",
          "answered": "Answered"}
OUTWARD = ("supplier_request", "supplier_alias")      # the actions that change something outside the item; a note does not move the stage


def _runs(db_path) -> dict[str, list[tuple[str, str]]]:
    """{item key: [(status, started_at), ...]} newest first; empty if the organism has never run."""
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


def _supplier(item: ActionItem) -> str:
    r = next((r for r in item.refs if r.type == "supplier"), None)
    return (r.label or r.id) if r else "the supplier"


def _requests_line(sent: list, waiting: list, approved: list, name) -> str:
    """One sentence for an item with several requests in different states, each supplier named: '1 of 3 sent (Alpha); 2 wait for your OK'."""
    total = len(sent) + len(waiting) + len(approved)
    parts = [f"{len(sent)} of {total} sent ({', '.join(name(a) for a in sent)})"]
    if approved:
        parts.append(f"{len(approved)} approved, not yet sent ({', '.join(name(a) for a in approved)})")
    if waiting:
        parts.append(f"{len(waiting)} wait{'s' if len(waiting) == 1 else ''} for your OK ({', '.join(name(a) for a in waiting)})")
    return "; ".join(parts) + "."


def derive(item: ActionItem, runs: list[tuple[str, str]], actions: list, answered_since: dict[str, str], names: dict[str, str] | None = None, contact: str | None = None) -> Stage:
    """The stage of one item from its runs (newest first), its ledger actions and the latest message from its supplier. `names` maps a supplier id to its name,
    so a line names the supplier of the request it is about, which on an item with several quotes is not the item's first supplier."""
    who = _supplier(item)
    names = names or {}

    def supplier_id(a) -> str | None:
        t = getattr(a, "target", None)
        return t.id if t and t.type == "supplier" else None

    def name(a) -> str:      # the supplier the request went to
        return names.get(supplier_id(a)) or who
    live = [a for a in actions if a.type in OUTWARD and a.state != "rejected"]
    choices = sorted((a for a in actions if a.type == "note" and (getattr(a, "change", None) or {}).get("kind") == "choice"), key=lambda a: a.decided_at or a.proposed_at or "")
    chosen_ids = [(a.change or {}).get("action_id") for a in reversed(choices)]      # the buyer's choices, newest first: the draft she chose is the one waiting on her
    rejected = [a for a in actions if a.type in OUTWARD and a.state == "rejected"]
    requests = [a for a in live if a.type == "supplier_request"]
    all_sent = [a for a in requests if a.state == "executed"]
    sent = all_sent[0] if all_sent else None
    if sent:
        sent_on = local_date(sent.confirmed_at or sent.decided_at)      # the buyers' day, not UTC's
        asked = supplier_id(sent) or next((r.id for r in item.refs if r.type == "supplier"), None)      # the supplier whose answer ends the wait
        by = name(sent)
        if asked and answered_since.get(asked, "") > sent_on:
            return Stage(key="answered", label=LABELS["answered"], step=7, at=answered_since[asked], waiting_on="you",
                         next_act=f"{by} has answered: read the new message and decide what is left.")
        chase = f" Chase if nothing comes by {md(item.act_by)}." if item.act_by and item.act_by >= AS_OF.isoformat() else ""
        if len(requests) > 1 and len({a.state for a in requests}) > 1 or len(all_sent) > 1:
            then = _requests_line(all_sent, [a for a in requests if a.state == "proposed"], [a for a in requests if a.state == "approved"], name)
            return Stage(key="sent", label=LABELS["sent"], step=6, at=sent.confirmed_at or sent.decided_at, waiting_on="the supplier", action=ref("action", sent.action_id),
                         next_act=f"{then}{chase}")
        return Stage(key="sent", label=LABELS["sent"], step=6, at=sent.confirmed_at or sent.decided_at, waiting_on="the supplier", action=ref("action", sent.action_id),
                     next_act=f"Sent to {contact or by} on {md(AS_OF.isoformat())} (simulated). Waiting for {contact or by} to answer.{chase}")      # a name and the data date, never an address or the wall clock
    done = next((a for a in live if a.state in ("approved", "executed")), None)
    if done:
        what = "The supplier link is recorded." if done.type == "supplier_alias" else "Approved."
        return Stage(key="approved", label=LABELS["approved"], step=5, at=done.decided_at, waiting_on=None, action=ref("action", done.action_id), next_act=f"{what} Nothing is waiting on you for this one.")
    # A note, a decision or an ERP update staged on the case (P7) moves it too: signed, it is Recorded (nothing is sent); waiting, it needs the owner's OK.
    staged = [a for a in actions if a.type == "note" and (getattr(a, "change", None) or {}).get("kind") in ("note", "record", "erp_update")]
    recorded = next((a for a in staged if a.state in ("approved", "executed")), None)
    email_waiting = next((a for a in live if a.state == "proposed"), None)
    if recorded and not email_waiting:      # an email still waiting keeps the case open: "Recorded" never hides it (LOOKOUT P2)
        return Stage(key="approved", label="Recorded", step=5, at=recorded.decided_at, waiting_on=None, action=ref("action", recorded.action_id),
                     next_act=f"Recorded {md(AS_OF.isoformat())}: {recorded.subject or 'the decision'}. Nothing is sent and nothing is waiting on you.")
    waiting = (next((a for cid in chosen_ids for a in live + staged if a.action_id == cid and a.state == "proposed"), None)
               or next((a for a in live if a.state == "proposed"), None) or next((a for a in staged if a.state == "proposed"), None))
    if waiting:
        to = f" to {waiting.recipient}" if waiting.recipient else f" for {who}"
        act = "Sign or reject the note: it records your decision and sends nothing." if waiting.type == "note" else f"Approve or reject the draft{to}."      # a note goes to no supplier
        return Stage(key="drafted", label=LABELS["drafted"], step=4, at=waiting.proposed_at, waiting_on="you", action=ref("action", waiting.action_id), next_act=act)
    note = ""
    if rejected:
        r = rejected[0]
        note = f" You rejected the draft on {md(local_date(r.decided_at))}" + (f": {r.reason.strip().rstrip('. ')}." if r.reason and r.reason.strip().rstrip(". ") else ".") + " Revise it with the agent."
    ok = next((r for r in runs if r[0] == "ok"), None)
    if ok:
        return Stage(key="decision_ready", label=LABELS["decision_ready"], step=3, at=ok[1], waiting_on="you",
                     next_act=("Read the Recommendation, then draft the request or record your decision." + note).strip())
    if runs:
        status, at = runs[0]
        act = "Lookout is working on it." if status == "running" else "The last run did not finish. Run it again."
        return Stage(key="worked", label=LABELS["worked"], step=2, at=at, waiting_on=None if status == "running" else "you", next_act=(act + note).strip())
    return Stage(key="found", label=LABELS["found"], step=1, waiting_on="you", next_act="Work this item: Lookout reads the records and prepares what to decide.")


def attach(session: Session, db_path, items: list) -> list:
    """The same items with their stage set (works for ActionItem and ActionItemDetail)."""
    runs = _runs(db_path)
    by_item: dict[str, list] = {}
    by_id: dict[str, object] = {}
    for a in ledger.list_actions(db_path):
        by_id[a.action_id] = a
        if a.item_key:
            by_item.setdefault(a.item_key, []).append(a)
    latest: dict[str, str] = {}
    for ident, date in session.execute(select(Message.identity_id, Message.date).where(Message.identity_id.is_not(None))):
        latest[ident] = max(latest.get(ident, ""), date)
    names = {i.id: i.name for i in session.execute(select(SupplierIdentity)).scalars()}
    out = []
    for it in items:
        # Only a draft made for this item moves its stage (B4): a request on another item to the same supplier is that item's, and may not cover these lines.
        own = by_item.get(it.key, [])
        picked = {(a.change or {}).get("action_id") for a in own if a.type == "note" and (getattr(a, "change", None) or {}).get("kind") == "choice"}
        own = own + [a for a in by_id.values() if a.action_id in picked and a not in own]      # a draft the buyer chose for this case moves it, even when another case wrote it (one email per contact)
        sup = next((r for r in it.refs if r.type == "supplier"), None)
        contact = suppliers.contact_on_file(session, sup.id).name if sup and any(a.state == "executed" for a in own) else None
        st = derive(it, runs.get(it.key, []), own, latest, names, contact)
        update = {}
        if st.key == "sent":      # once a request is out, what is next comes from the ledger, not from the detector
            update["next_action"] = f"Waiting on {contact or _supplier(it)}" + (f"; chase {md(it.act_by)} if no dates." if it.act_by and it.act_by >= AS_OF.isoformat() else ".")
        out.append(it.model_copy(update={"stage": st, **update}))
    return out
