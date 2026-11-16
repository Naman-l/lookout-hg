"""Who may decide a draft, and whether the run that wrote it passed its own checks.

An approver is a member of the SCM team (the buyers table) (matched by first name or full name, any case); anything else is refused, and the
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
    """A draft that answers a message, and nothing ties the message to a member of the team. Nobody may sign it."""


def _session(db_path):
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    return Session(create_engine(f"sqlite:///{db_path}"))


def owners_of(db_path, item_key: str | None) -> set[str] | None:
    """The members who own a case (full names), or None when the key is not a case. A draft that answers a message (`reply:<message>`) is owned
    by the case that links the message, else the members the message is addressed to, else NoOwner. A lookup error refuses (fails closed)."""
    if not item_key:
        return None
    try:
        with _session(db_path) as s:
            from ..attention import service  # noqa: PLC0415

            if item_key.startswith(("reply:", "triage:")):
                from ..inbox import service as inbox  # noqa: PLC0415

                who = inbox.owners_of_message(s, item_key.split(":", 1)[1])
                if not who:
                    raise NoOwner(f"no member owns this message ({item_key})")
                return who
            item = service.item_detail(s, item_key)
    except NoOwner:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("owner lookup failed for item %s", item_key)
        raise OwnerLookupError(f"could not find who owns {item_key}") from e
    if item is None or not item.owner:
        return None
    return {n.strip() for n in item.owner.split("·") if n.strip()} or None


def owners_of_action(db_path, action) -> set[str] | None:
    """Who may sign this draft: the member it was drafted for (`change.owner`), else the owners of its case, else the member who asked for it in Ask."""
    named = (getattr(action, "change", None) or {}).get("owner") or getattr(action, "owner", None)
    if named:
        return {resolve(db_path, named) or named}
    owners = owners_of(db_path, action.item_key)
    if owners:
        return owners
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        row = con.execute("SELECT asked_by FROM runs WHERE run_id = ?", (action.run_id,)).fetchone() if action.run_id else None
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    who = resolve(db_path, row[0]) if row and row[0] else None
    if who:
        return {who}
    raise NoOwner(f"nobody owns this draft: it is tied to no case and no asker started it ({action.action_id})")


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
