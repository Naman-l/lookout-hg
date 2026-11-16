"""The ledger: proposed -> [signed ->] approved | rejected -> executed. Approval is enforced here, in code.

- Delegation of authority: a draft whose `change.countersign` names a person (set when the draft was made, from the DoA rule for the money it
  commits) is signed by its owner first and waits as `signed`; only that person's approval of the same hash sends it. Both signatures are kept.

- A draft's `payload_hash` is the sha256 of its canonical payload (type, target, recipient, subject, body,
  change). The person approves a hash; approve() refuses if the payload no longer hashes to it.
- execute() runs inside approve() and re-reads the row: it needs state == approved and a payload that still
  hashes to the approved value, so an edit between approval and send cannot slip through. It writes the
  simulated outbox row (one per action, enforced by a unique key) and records attempted_at, then confirmed_at.
- No agent tool reaches approve, reject or execute. They exist only behind the API routes a person calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import re
import uuid
from datetime import datetime, timezone

from ... import watcher
from ..common import EntityRef
from .schema import Action, OutboxMessage

_DDL = """
CREATE TABLE IF NOT EXISTS actions (
  action_id TEXT PRIMARY KEY, type TEXT NOT NULL, state TEXT NOT NULL, item_key TEXT, run_id TEXT,
  target_json TEXT, recipient TEXT, subject TEXT, body TEXT, change_json TEXT, payload_hash TEXT NOT NULL,
  proposed_at TEXT, decided_at TEXT, decided_by TEXT, reason TEXT, attempted_at TEXT, confirmed_at TEXT, outbox_id TEXT
);
CREATE TABLE IF NOT EXISTS run_actions (
  run_id TEXT NOT NULL, action_id TEXT NOT NULL, PRIMARY KEY (run_id, action_id)
);
CREATE TABLE IF NOT EXISTS payload_runs (
  action_id TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY (action_id, run_id)
);
CREATE TABLE IF NOT EXISTS supplier_links (
  supplier_a TEXT NOT NULL, supplier_b TEXT NOT NULL, action_id TEXT NOT NULL, linked_by TEXT, linked_at TEXT NOT NULL,
  evidence TEXT, PRIMARY KEY (supplier_a, supplier_b)
);
CREATE TABLE IF NOT EXISTS outbox (
  outbox_id TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE, to_addr TEXT NOT NULL, subject TEXT NOT NULL,
  body TEXT NOT NULL, sent_at TEXT NOT NULL
);
"""


SENT = ("supplier_request", "internal_note")      # the drafts that go out (simulated): a letter to a vendor's contact, a note to a function owner on file


class LedgerError(Exception):
    """A refusal. `code` is one of: no_such_action, state, hash, tampered, no_recipient."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)  # explicit transactions
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    cols = {c[1] for c in con.execute("PRAGMA table_info(actions)")}
    for col in ("edited_by", "signed_by", "signed_at"):      # a db made before hand edits or countersigns were recorded
        if col not in cols:
            con.execute(f"ALTER TABLE actions ADD COLUMN {col} TEXT")
    return con


def payload_hash(type: str, target: EntityRef | dict | None, recipient: str | None, subject: str | None, body: str | None, change: dict | None) -> str:
    t = target.model_dump(include={"type", "id"}) if isinstance(target, EntityRef) else (None if target is None else {"type": target.get("type"), "id": target.get("id")})
    canonical = json.dumps({"type": type, "target": t, "recipient": recipient, "subject": subject, "body": body, "change": change},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _row_hash(r: sqlite3.Row) -> str:
    return payload_hash(r["type"], json.loads(r["target_json"]) if r["target_json"] else None, r["recipient"], r["subject"], r["body"],
                        json.loads(r["change_json"]) if r["change_json"] else None)


def _action(r: sqlite3.Row) -> Action:
    return Action(
        action_id=r["action_id"], type=r["type"], state=r["state"], payload_hash=r["payload_hash"], item_key=r["item_key"], run_id=r["run_id"],
        target=EntityRef.model_validate_json(r["target_json"]) if r["target_json"] else None, recipient=r["recipient"], subject=r["subject"],
        body=r["body"], change=json.loads(r["change_json"]) if r["change_json"] else None, proposed_at=r["proposed_at"], decided_at=r["decided_at"],
        decided_by=r["decided_by"], reason=r["reason"], attempted_at=r["attempted_at"], confirmed_at=r["confirmed_at"], outbox_id=r["outbox_id"],
        owner=(json.loads(r["change_json"]) if r["change_json"] else {}).get("owner"),
        edited_by=r["edited_by"] if "edited_by" in r.keys() else None,
        signed_by=r["signed_by"] if "signed_by" in r.keys() else None, signed_at=r["signed_at"] if "signed_at" in r.keys() else None,
        countersign=(json.loads(r["change_json"]) if r["change_json"] else {}).get("countersign"),
    )


def propose(db_path, *, type: str, item_key: str | None, run_id: str | None, target: EntityRef | None, recipient: str | None,
            subject: str | None, body: str | None, change: dict | None = None, action_id: str | None = None) -> Action:
    """Stage a draft. Idempotent: the same payload for the same item returns the draft already waiting."""
    if type in SENT and not recipient:
        raise LedgerError("no_recipient", "no contact on file for this recipient, so nothing can be drafted")
    h = payload_hash(type, target, recipient, subject, body, change)
    con = connect(db_path)
    try:
        existing = con.execute("SELECT * FROM actions WHERE payload_hash = ? AND item_key IS ? AND state = 'proposed'", (h, item_key)).fetchone()
        if existing:  # the same draft is still waiting: a re-run links to it instead of staging a second copy
            _link(con, run_id, existing["action_id"])
            return _action(existing)
        action_id = action_id or f"A-{uuid.uuid4().hex[:8]}"
        con.execute(
            "INSERT INTO actions (action_id, type, state, item_key, run_id, target_json, recipient, subject, body, change_json, payload_hash, proposed_at)"
            " VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (action_id, type, item_key, run_id, target.model_dump_json() if target else None, recipient, subject, body,
             json.dumps(change) if change is not None else None, h, _now()),
        )
        _link(con, run_id, action_id)
        watcher.emit("actions", "action.proposed", f"{type} proposed to {recipient}", run_id=run_id, action_id=action_id, payload_hash=h)
        return _action(con.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone())
    finally:
        con.close()


def _link(con, run_id: str | None, action_id: str) -> None:
    if run_id:
        con.execute("INSERT OR IGNORE INTO run_actions (run_id, action_id) VALUES (?, ?)", (run_id, action_id))


def link_to_run(db_path, run_id: str, action_id: str) -> None:
    """A run that finds its ask already covered by an earlier action is linked to that action: the run's record says which action covers it."""
    con = connect(db_path)
    try:
        _link(con, run_id, action_id)
    finally:
        con.close()


def open_thread(db_path, recipient: str | None) -> Action | None:
    """The one open thread with a supplier contact: the newest request to that address that is waiting, approved or already sent (a rejected one does not count)."""
    if not recipient:
        return None
    con = connect(db_path)
    try:
        r = con.execute("SELECT * FROM actions WHERE type IN ('supplier_request', 'internal_note') AND recipient = ? AND state IN ('proposed', 'signed', 'approved', 'executed') ORDER BY proposed_at DESC LIMIT 1", (recipient,)).fetchone()
        return _action(r) if r else None
    finally:
        con.close()


def notes_for(db_path, owner: str) -> list[Action]:
    """The questions already logged for one buyer, newest first."""
    return [a for a in list_actions(db_path) if a.type == "note" and (a.change or {}).get("owner") == owner]


def in_run(db_path, action_id: str, run_id: str) -> bool:
    """True when this run staged the action or re-found it still waiting. `Action.run_id` stays the run that first staged it."""
    con = connect(db_path)
    try:
        return con.execute("SELECT 1 FROM run_actions WHERE run_id = ? AND action_id = ?", (run_id, action_id)).fetchone() is not None
    finally:
        con.close()


def writer_runs(db_path, action_id: str) -> list[str]:
    """The runs that wrote the draft's current text: the run that staged it, then each run that amended it."""
    con = connect(db_path)
    try:
        first = con.execute("SELECT run_id FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        later = [r[0] for r in con.execute("SELECT run_id FROM payload_runs WHERE action_id = ? ORDER BY rowid", (action_id,))]
    finally:
        con.close()
    return [r for r in dict.fromkeys([first[0] if first else None, *later]) if r]


def for_run(db_path, run_id: str) -> list[Action]:
    return [a for a in list_actions(db_path) if in_run(db_path, a.action_id, run_id)]


def get(db_path, action_id: str) -> Action | None:
    con = connect(db_path)
    try:
        r = con.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        return _action(r) if r else None
    finally:
        con.close()


def list_actions(db_path, state: str | None = None) -> list[Action]:
    con = connect(db_path)
    try:
        rows = con.execute("SELECT * FROM actions" + (" WHERE state = ?" if state else "") + " ORDER BY proposed_at DESC", (state,) if state else ()).fetchall()
        return [_action(r) for r in rows]
    finally:
        con.close()


def asks_of(action: Action) -> list[str]:
    """The items whose ask this request carries: the item it was drafted for, then each item whose ask was merged into it."""
    return list((action.change or {}).get("asks") or ([action.item_key] if action.item_key else []))


def same_ask(held_text: str | None, new_text: str | None) -> bool:
    """True when the new draft asks what the held request already says: most of its content words are in the held text."""
    words = lambda t: {w for w in re.findall(r"[a-z0-9]{4,}", (t or "").lower())}  # noqa: E731
    new, held = words(new_text), words(held_text)
    return bool(new) and len(new & held) / len(new) >= 0.6


def update_draft(db_path, action_id: str, *, subject: str, body: str, edited_by: str, change: dict | None = None, run_id: str | None = None) -> Action:
    """Edit a draft that is still waiting. The hash changes, so anything approved against the old text is void. A run that edits it is one of the runs
    that wrote its text (`writer_runs`): the checks that run failed hold for the text it wrote."""
    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if r is None:
            raise LedgerError("no_such_action", "no such action")
        if r["state"] != "proposed":
            raise LedgerError("state", f"this action is {r['state']}; only a draft awaiting approval can be edited")
        kept = change if change is not None else (json.loads(r["change_json"]) if r["change_json"] else None)
        h = payload_hash(r["type"], json.loads(r["target_json"]) if r["target_json"] else None, r["recipient"], subject, body, kept)
        con.execute("UPDATE actions SET subject = ?, body = ?, payload_hash = ?, change_json = ?, edited_by = ? WHERE action_id = ?",      # a run's rewrite is checked by that run; a hand edit is not
                    (subject, body, h, json.dumps(kept, sort_keys=True) if kept is not None else None, None if run_id else edited_by, action_id))
        if run_id:
            con.execute("INSERT OR IGNORE INTO payload_runs (action_id, run_id) VALUES (?, ?)", (action_id, run_id))
        con.execute("COMMIT")
        watcher.emit("actions", "action.edited", f"draft edited by {edited_by}", action_id=action_id, payload_hash=h)
    except Exception:
        con.execute("ROLLBACK") if con.in_transaction else None
        raise
    finally:
        con.close()
    return get(db_path, action_id)


def approve(db_path, action_id: str, payload_hash_shown: str, approved_by: str) -> Action:
    """Approve exactly what was shown, then execute. Refuses on a wrong state, a stale hash or a changed payload. A draft that names a countersigner
    (DoA) is only signed by its owner's approval and waits as `signed`; the countersigner's approval of the same hash sends it."""
    con = connect(db_path)
    signed_only = False
    try:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if r is None:
            raise LedgerError("no_such_action", "no such action")
        retry = r["state"] == "approved" and r["confirmed_at"] is None  # approved, but the send did not finish: approving again finishes it
        if r["state"] not in ("proposed", "signed") and not retry:
            raise LedgerError("state", f"this action is already {r['state']}")
        if _row_hash(r) != r["payload_hash"]:
            raise LedgerError("tampered", "the draft no longer matches its recorded hash; it was changed outside the ledger")
        if payload_hash_shown != r["payload_hash"]:
            raise LedgerError("hash", "the draft changed since you were shown it; review it again")
        if retry:
            con.execute("COMMIT")
            con.close()
            return execute(db_path, action_id)
        counter = (json.loads(r["change_json"]) if r["change_json"] else {}).get("countersign")
        if r["state"] == "proposed" and counter and approved_by != counter:
            con.execute("UPDATE actions SET state = 'signed', signed_by = ?, signed_at = ? WHERE action_id = ?", (approved_by, _now(), action_id))
            signed_only = True
        elif r["state"] == "signed":
            if approved_by != counter:
                raise LedgerError("countersign", f"signed by {r['signed_by']}; it waits for {counter}'s countersign, and only {counter} can give it")
            con.execute("UPDATE actions SET state = 'approved', decided_at = ?, decided_by = ? WHERE action_id = ?", (_now(), approved_by, action_id))
        else:
            con.execute("UPDATE actions SET state = 'approved', decided_at = ?, decided_by = ?, signed_by = COALESCE(signed_by, ?), signed_at = COALESCE(signed_at, ?) WHERE action_id = ?",
                        (_now(), approved_by, approved_by, _now(), action_id))
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    if signed_only:
        watcher.emit("actions", "action.signed", f"signed by {approved_by}; waits for {counter}'s countersign", action_id=action_id, payload_hash=payload_hash_shown)
        return get(db_path, action_id)
    watcher.emit("actions", "action.approved", f"approved by {approved_by}", action_id=action_id, payload_hash=payload_hash_shown)
    try:
        return execute(db_path, action_id)
    except LedgerError:
        raise
    except Exception as e:  # noqa: BLE001  the approval stands; the action waits as approved and execute() can be called again
        watcher.emit("actions", "action.execute_failed", f"{type(e).__name__}: {e}", action_id=action_id)
        return get(db_path, action_id)


def execute(db_path, action_id: str) -> Action:
    """Send (simulated) an approved action that still hashes to what was approved. Two steps in two transactions: first the attempt is written, then the send and its
    confirmation. A failure between them leaves the action `approved` with an attempt on record, and calling this again finishes it: the outbox holds one row per action."""
    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if r is None:
            raise LedgerError("no_such_action", "no such action")
        if r["state"] != "approved":
            raise LedgerError("state", f"cannot execute: the action is {r['state']}, not approved")
        if _row_hash(r) != r["payload_hash"]:
            raise LedgerError("tampered", "cannot execute: the payload changed after approval")
        con.execute("UPDATE actions SET attempted_at = ? WHERE action_id = ?", (_now(), action_id))  # the attempt, on record before anything is sent
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        outbox_id = None
        if r["type"] in SENT:
            sent = con.execute("SELECT outbox_id FROM outbox WHERE action_id = ?", (action_id,)).fetchone()  # a retry finds the send that already happened
            outbox_id = sent["outbox_id"] if sent else f"OUT-{uuid.uuid4().hex[:8]}"
            if not sent:
                con.execute("INSERT INTO outbox (outbox_id, action_id, to_addr, subject, body, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (outbox_id, action_id, r["recipient"], r["subject"], r["body"], _now()))
        if r["type"] == "supplier_alias":  # a person approved "these two records are one company": remember the link, never merge the records
            link = sorted(json.loads(r["change_json"] or "{}").get("link") or [])
            a_id, b_id = (link + [None, None])[:2]
            if a_id and b_id:
                con.execute("INSERT OR IGNORE INTO supplier_links (supplier_a, supplier_b, action_id, linked_by, linked_at, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                            (a_id, b_id, action_id, r["decided_by"], _now(), r["body"]))
        con.execute("UPDATE actions SET state = 'executed', confirmed_at = ?, outbox_id = ? WHERE action_id = ?", (_now(), outbox_id, action_id))
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    watcher.emit("actions", "action.executed", "sent (simulated)", action_id=action_id, outbox_id=outbox_id)
    return get(db_path, action_id)


def reject(db_path, action_id: str, reason: str, rejected_by: str) -> Action:
    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT state FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if r is None:
            raise LedgerError("no_such_action", "no such action")
        if r["state"] not in ("proposed", "signed"):
            raise LedgerError("state", f"this action is already {r['state']}")
        con.execute("UPDATE actions SET state = 'rejected', decided_at = ?, decided_by = ?, reason = ? WHERE action_id = ?", (_now(), rejected_by, reason, action_id))
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    watcher.emit("actions", "action.rejected", f"rejected by {rejected_by}: {reason}", action_id=action_id)
    return get(db_path, action_id)


def record_app_action(db_path, *, type: str, item_key: str, target: EntityRef | None, body: str | None, by: str, change: dict | None = None, run_id: str | None = None) -> Action:
    """A note (a question logged for a buyer) is recorded as executed at once; it never reaches a supplier."""
    if type != "note":
        raise LedgerError("state", f"{type} is not an app action")
    # the same question about the same item is logged once; a re-run links to the entry that is there
    con = connect(db_path)
    try:
        old = con.execute("SELECT action_id FROM actions WHERE type = 'note' AND item_key IS ? AND payload_hash = ? AND state = 'executed'",
                          (item_key, payload_hash(type, target, None, None, body, change))).fetchone()
        if old:
            _link(con, run_id, old["action_id"])
            return get(db_path, old["action_id"])
    finally:
        con.close()
    a = propose(db_path, type=type, item_key=item_key, run_id=run_id, target=target, recipient=None, subject=None, body=body, change=change)
    con = connect(db_path)
    try:
        con.execute("UPDATE actions SET state = 'executed', decided_at = ?, decided_by = ?, attempted_at = ?, confirmed_at = ? WHERE action_id = ?",
                    (_now(), by, _now(), _now(), a.action_id))
    finally:
        con.close()
    return get(db_path, a.action_id)


def choices(db_path) -> dict[str, dict]:
    """{action id: the buyer's choice of it} from the choice records (`routes.choose`): the route, who chose it and when; the latest choice wins."""
    out: dict[str, dict] = {}
    for a in sorted((x for x in list_actions(db_path, "executed") if x.type == "note" and (x.change or {}).get("kind") == "choice"), key=lambda x: x.proposed_at or ""):
        ch = a.change or {}
        if ch.get("action_id"):
            prev = out.get(ch["action_id"], {}).get("routes", [])
            out[ch["action_id"]] = {"option_kind": ch.get("option_kind"), "routes": [*[r for r in prev if r != ch.get("option_kind")], ch.get("option_kind")], "by": a.decided_by, "at": a.decided_at}
    return out


def supplier_links(db_path) -> list[dict]:
    """Links a person approved between supplier records, oldest first. Identity resolution reads these; no record is merged or edited."""
    con = connect(db_path)
    try:
        return [dict(x) for x in con.execute("SELECT * FROM supplier_links ORDER BY linked_at")]
    finally:
        con.close()


def outbox(db_path) -> list[OutboxMessage]:
    con = connect(db_path)
    try:
        rows = con.execute("SELECT * FROM outbox ORDER BY sent_at DESC").fetchall()
        return [OutboxMessage(outbox_id=r["outbox_id"], action_id=r["action_id"], to=r["to_addr"], subject=r["subject"], body=r["body"], sent_at=r["sent_at"]) for r in rows]
    finally:
        con.close()
