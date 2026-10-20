"""Who may decide a draft, and whether the run that wrote it passed its own checks.

An approver is a buyer in the buyers table (matched by first name or full name, any case); anything else is refused, and the
canonical full name is what the ledger records. An empty or missing table refuses everyone: the check fails closed.
A draft from a run that ended `did_not_pass` can still be approved, but only with an explicit confirmation.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3

log = logging.getLogger(__name__)


class OwnerLookupError(RuntimeError):
    """The owner of an item could not be determined. Nobody may sign on a guess: the caller refuses."""


def resolve(db_path, name: str | None) -> str | None:
    """The buyer's full name for what the person typed or the screen sent, or None when no such buyer exists."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        rows = con.execute("SELECT id, name FROM buyers").fetchall()
    except sqlite3.OperationalError:  # no buyers table yet: nobody can decide
        return None
    finally:
        con.close()
    for bid, full in rows:
        if wanted in (str(bid).lower(), str(full).lower()):
            return full
    return None


class NoOwner(OwnerLookupError):
    """A draft that answers a message, and nothing ties the message to a buyer. Nobody may sign it: an outward email with no owner is not signed by whoever is nearest."""


def _reply_owners(session, message_id: str) -> set[str]:
    """Who owns the draft that answers (or triages) a message. In order: the owner of the Action-list item that links the message; else the buyer on the
    PO lines the message names; else the buyer of the parts it names; else the buyer on most of the sender supplier's lines; else the buyer it is addressed to; else NoOwner."""
    from collections import Counter  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from ..attention import service  # noqa: PLC0415
    from ..inbox.model import Message, MessageRef  # noqa: PLC0415
    from ..orders.model import PoLine  # noqa: PLC0415
    from ..ownership import buyer_ids  # noqa: PLC0415

    ids = buyer_ids(session)

    def named(buyer_ids_: list[str]) -> set[str]:
        c = Counter(b for b in buyer_ids_ if b in ids)
        top = max(c.values()) if c else 0
        return {ids[b] for b, n in c.items() if n == top} if c else set()

    for item in service.what_needs_attention(session):                        # ranked: the most urgent linked item decides
        if any(r.type == "message" and r.id == message_id for r in item.refs) and item.owner:
            return {n.strip() for n in item.owner.split("·") if n.strip()}
    lines = [r.ref_id for r in session.scalars(select(MessageRef).where(MessageRef.message_id == message_id, MessageRef.ref_type == "po_line"))]
    if lines and (owners := named(list(session.scalars(select(PoLine.buyer_id).where(PoLine.id.in_(lines)))))):
        return owners
    from ..parts.model import Part  # noqa: PLC0415

    parts = [r.ref_id for r in session.scalars(select(MessageRef).where(MessageRef.message_id == message_id, MessageRef.ref_type == "part"))]
    if parts and (owners := named(list(session.scalars(select(Part.buyer_id).where(Part.part_number.in_(parts)))))):      # the buyer the build assigned to the parts it names (the one on their PO lines)
        return owners
    msg = session.get(Message, message_id)
    if msg is not None and msg.identity_id and (owners := named(list(session.scalars(select(PoLine.buyer_id).where(PoLine.identity_id == msg.identity_id))))):
        return owners
    if msg is not None and (to := (msg.to_addrs or "").lower()):      # the buyer the mail is addressed to
        addressed = {ids[b] for b in ids if re.search(rf"(?<![a-z]){re.escape(b.lower())}(?![a-z])", to)}
        if addressed:
            return addressed
    raise NoOwner(f"no buyer owns this message: it links to no item, names no PO line with a buyer, and its sender has no orders ({message_id})")


def owners_of(db_path, item_key: str | None) -> set[str] | None:
    """The buyers who own an item (full names), or None when the item is not on the Action list: nobody is then excluded. A draft that answers a message
    (`reply:` or `triage:`) is owned by the item that links the message, else the buyer on its PO lines, else its sender's buyer, else NoOwner.

    An error while looking is not "no owner": it is logged and raised as OwnerLookupError, so the check fails closed."""
    if not item_key:
        return None
    try:
        from sqlalchemy import create_engine  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415

        from ..attention import service  # noqa: PLC0415

        eng = create_engine(f"sqlite:///{db_path}")
        try:
            with Session(eng) as s:
                if item_key.startswith(("reply:", "triage:")):               # a draft answering a message: it has an owner, or nobody signs it
                    return _reply_owners(s, item_key.split(":", 1)[1])
                item = service.item_detail(s, item_key)
        finally:
            eng.dispose()
    except NoOwner:
        log.warning("no owner for %s", item_key)
        raise
    except Exception as e:  # noqa: BLE001  any failure to find the owner refuses the signature
        log.exception("owner lookup failed for item %s", item_key)
        raise OwnerLookupError(f"could not find who owns {item_key}") from e
    if item is None or not item.owner:
        return None
    return {resolve(db_path, n.strip()) or n.strip() for n in item.owner.split("·") if n.strip()} or None


def owners_of_action(db_path, action) -> set[str] | None:
    """Who may sign this draft. The buyer it names (`owner`) when it names one; else the owner of its Action-list item; a draft that answers a message is owned as `owners_of` says. A draft tied to no item (an answer from Ask, or an
    item the list cannot name) is owned by the asker who started the run, else the buyer on most of the target supplier's PO lines, else nobody (NoOwner: 409 unless delegation is on)."""
    named = (getattr(action, "change", None) or {}).get("owner") or getattr(action, "owner", None)      # the buyer the draft was written for (the buyer of its PO lines): a shared item has several owners, a draft has one
    if named:
        return {resolve(db_path, named) or named}
    owners = owners_of(db_path, action.item_key)
    if owners:
        return owners
    if action.item_key and action.item_key.startswith(("reply:", "triage:")):
        return owners
    names: dict[str, str] = {}
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        try:
            names = {str(i): n for i, n in con.execute("SELECT id, name FROM buyers")}
        except sqlite3.OperationalError:
            pass
        asker = None
        if action.run_id:
            try:
                row = con.execute("SELECT asked_by FROM runs WHERE run_id = ?", (action.run_id,)).fetchone()
                asker = row[0] if row else None
            except sqlite3.OperationalError:
                pass
        who = resolve(db_path, asker) if asker else None
        if who:
            return {who}
        if action.target and action.target.type == "supplier":
            try:
                top = con.execute("SELECT buyer_id, count(*) c FROM po_lines WHERE identity_id = ? AND buyer_id IS NOT NULL GROUP BY buyer_id ORDER BY c DESC, buyer_id LIMIT 1", (action.target.id,)).fetchone()
            except sqlite3.OperationalError:
                top = None
            if top and top[0] in names:
                return {names[top[0]]}
    finally:
        con.close()
    raise NoOwner(f"nobody owns this draft: it is tied to no item, no asker started it, and its supplier has no buyer on file ({action.action_id})")


def unverified_checks(db_path, run_id: str | None) -> list[str]:
    """The failed code checks of the run that staged this draft; empty when the run passed or there is no run to ask."""
    if not run_id:
        return []
    from ...organism.runs import store  # noqa: PLC0415

    row = store.read_run(db_path, run_id)
    if not row or row["status"] != "did_not_pass":
        return []
    try:
        return list(json.loads(row["verifier_json"] or "{}").get("failures") or ["a code check failed"])
    except ValueError:
        return ["a code check failed"]


def unverified_checks_of(db_path, action) -> list[str]:
    """The failed code checks of every run that wrote this draft's current text (the staging run and each run that amended it), once each."""
    from . import ledger  # noqa: PLC0415

    out: list[str] = []
    for run_id in ledger.writer_runs(db_path, action.action_id):
        out += [f for f in unverified_checks(db_path, run_id) if f not in out]
    return out
