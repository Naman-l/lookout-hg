"""The demo loop: a sent request, a simulated reply from the contact on file, the item Answered, the reply in the Inbox."""
from __future__ import annotations

import shutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.actions import ledger
from app.domain.attention import service, stage
from app.domain.common import EntityRef
from app.domain.inbox import service as inbox
from app.domain.inbox import simulate_reply

ITEM = "disruption:SUP-0001"
CONTACT = "li.wei@yunzhan-motor.example"


@pytest.fixture()
def copy(db_path, tmp_path):
    out = tmp_path / "loop.db"
    shutil.copy(db_path, out)
    return out


@pytest.fixture()
def session(copy):
    with Session(create_engine(f"sqlite:///{copy}", connect_args={"check_same_thread": False})) as s:
        yield s


def _send(copy, session):
    line = session.execute(__import__("sqlalchemy").text("select id from po_lines where identity_id = 'SUP-0001' limit 1")).scalar()
    a = ledger.propose(copy, type="supplier_request", item_key=ITEM, run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient=CONTACT,
                       subject="Revised promise dates", body=f"Please confirm the new date for {line}.")
    ledger.approve(copy, a.action_id, a.payload_hash, "Dana Reyes")
    return ledger.get(copy, a.action_id), line


def _stage(copy, session):
    return stage.attach(session, copy, [service.item_detail(session, ITEM)])[0].stage


def test_a_sent_request_is_answered_by_a_simulated_reply_that_the_inbox_lists(copy, session):
    sent, line = _send(copy, session)
    assert sent.state == "executed" and _stage(copy, session).key == "sent"
    msg = simulate_reply.write(session, sent)
    assert msg and "[simulated reply]" in msg.subject and msg.from_email == CONTACT and msg.trust == "ok" and msg.sender_match == "record"
    assert _stage(copy, session).key == "answered"
    listed = {m.ref.id: m for m in inbox.search_messages(session, None)}
    assert msg.id in listed and listed[msg.id].trust == "on_file"
    detail = inbox.message_detail(session, msg.id)
    assert any(c.ref.id == line for c in detail.changes) and "Revised promise dates" in detail.summary.summary + msg.subject


def test_a_request_is_answered_once_and_an_unsent_one_not_at_all(copy, session):
    sent, _ = _send(copy, session)
    assert simulate_reply.write(session, sent) is not None
    assert simulate_reply.write(session, sent) is None
    draft = ledger.propose(copy, type="supplier_request", item_key=ITEM, run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient=CONTACT, subject="Another", body="Please confirm.")
    assert simulate_reply.write(session, draft) is None



def test_a_reply_that_re_dates_the_fires_lines_keeps_one_case_per_key(copy, session):
    """LOOKOUT QA #66 (pre-existing since b9e08cd): the reply's new dates made the slip detector add a second disruption:SUP-0001 row. A slip on a
    supplier that already has an open disruption case folds into it."""
    from sqlalchemy import text
    lines = [r[0] for r in session.execute(text("select id from po_lines where identity_id = 'SUP-0001' and status in ('OPEN', 'open')"))]
    a = ledger.propose(copy, type="supplier_request", item_key=ITEM, run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient=CONTACT,
                       subject="Revised promise dates", body="Please confirm the new dates for " + ", ".join(lines) + ".")
    ledger.approve(copy, a.action_id, a.payload_hash, "Dana Reyes")
    assert simulate_reply.write(session, ledger.get(copy, a.action_id)) is not None
    simulate_reply.memo_clear()
    keys = [i.key for i in service.what_needs_attention(session)]
    assert len(keys) == len(set(keys)) and keys.count(ITEM) == 1
    assert service.item_detail(session, ITEM).title.startswith("Yunzhan fire")      # the fire keeps its case; the slip does not replace it


def test_the_reply_is_among_the_cases_messages(copy, session, monkeypatch):
    """LOOKOUT QA #65: after a simulated reply, the case's messages include it (newest first), so the Response step shows the reply, not the notice."""
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app.main import app

    sent, _ = _send(copy, session)
    msg = simulate_reply.write(session, sent)
    simulate_reply.memo_clear()
    monkeypatch.setattr(app_db, "DB_PATH", copy)
    from app.db import get_session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as S
    eng = create_engine(f"sqlite:///{copy}", connect_args={"check_same_thread": False})

    def _s():
        with S(eng) as s:
            yield s
    app.dependency_overrides[get_session] = _s
    try:
        ids = [m["ref"]["id"] for m in TestClient(app).get(f"/api/action-items/{ITEM}").json()["messages"]]
    finally:
        app.dependency_overrides.clear()
    assert ids and ids[0] == msg.id


def test_a_reply_that_only_re_dates_shows_each_lines_open_qty(copy, session):
    """LOOKOUT QA #65 P2: the Response table's Open qty was "—" because the reply's lines state no quantity; the row then shows the PO line's open quantity."""
    from sqlalchemy import text
    open_qty = {r[0]: r[1] for r in session.execute(text("select id, open_qty_ea from po_lines where identity_id = 'SUP-0001' and status in ('OPEN', 'open', 'PARTIAL')"))}
    a = ledger.propose(copy, type="supplier_request", item_key=ITEM, run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient=CONTACT,
                       subject="Revised promise dates", body="Please confirm the new dates for " + ", ".join(open_qty) + ".")
    ledger.approve(copy, a.action_id, a.payload_hash, "Dana Reyes")
    msg = simulate_reply.write(session, ledger.get(copy, a.action_id))
    rows = [c for c in inbox.message_changes(session, msg.id) if c.ref.type == "po_line"]
    assert rows and all(c.qty == round(open_qty[c.ref.id]) for c in rows if open_qty.get(c.ref.id) is not None)
    assert any(c.ref.id == "HPO-26-00450/10" and c.qty == 355 for c in rows)
