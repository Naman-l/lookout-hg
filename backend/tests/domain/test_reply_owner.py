"""A draft that answers a message has an owner, or nobody signs it: the linked item's owner, else the buyer on the message's PO lines,
else the sender's buyer, else NoOwner (the API answers 409 with the reason)."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from app.domain.actions import approvers

FIRE_NOTICE = "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"


@pytest.fixture()
def db(db_path, tmp_path):
    copy = tmp_path / "reply.db"
    shutil.copy(db_path, copy)
    return copy


def _message(db, mid, identity=None, refs=()):
    con = sqlite3.connect(db)
    con.execute("insert into messages (id, file, date, kind, subject, body, identity_id, sender_match, trust) values (?, ?, '2026-09-24', 'other', 's', 'b', ?, 'none', 'ok')", (mid, mid + ".eml", identity))
    for r in refs:
        con.execute("insert into message_refs (message_id, ref_type, ref_id, quoted) values (?, 'po_line', ?, 'q')", (mid, r))
    con.commit()
    con.close()


def test_a_message_linked_to_an_item_is_owned_by_that_items_owner(db):
    assert approvers.owners_of(db, f"reply:{FIRE_NOTICE}") == {"Dana Reyes"}
    assert approvers.owners_of(db, f"triage:{FIRE_NOTICE}") == {"Dana Reyes"}


def test_a_message_that_names_po_lines_is_owned_by_the_buyer_on_them(db):
    _message(db, "x-lines", identity=None, refs=["HPO-26-00450/10"])             # a Yunzhan line bought by Dana; no item links this message
    assert approvers.owners_of(db, "reply:x-lines") == {"Dana Reyes"}
    con = sqlite3.connect(db)
    buyer = con.execute("select buyer_id from po_lines where id = 'HPO-26-00450/10'").fetchone()[0]
    assert con.execute("select name from buyers where id = ?", (buyer,)).fetchone()[0] == "Dana Reyes"


def test_a_message_with_no_lines_is_owned_by_its_senders_buyer(db):
    _message(db, "x-sender", identity="SUP-0013")                                 # Jadepeak: no PO lines named, no item links it
    con = sqlite3.connect(db)
    top = con.execute("select b.name from po_lines p join buyers b on b.id = p.buyer_id where p.identity_id = 'SUP-0013' group by b.name order by count(*) desc limit 1").fetchone()[0]
    assert approvers.owners_of(db, "reply:x-sender") == {top}


def test_a_message_that_ties_to_no_buyer_has_no_owner_and_nobody_signs(db):
    _message(db, "x-nobody")
    with pytest.raises(approvers.NoOwner) as e:
        approvers.owners_of(db, "reply:x-nobody")
    assert "x-nobody" in str(e.value) and isinstance(e.value, approvers.OwnerLookupError)
    with pytest.raises(approvers.NoOwner):
        approvers.owners_of(db, "triage:x-nobody")
    with pytest.raises(approvers.OwnerLookupError):                               # a message that does not exist is the same: nobody
        approvers.owners_of(db, "reply:no-such-message")


def _draft(db, **kw):
    from app.domain.actions import ledger
    from app.domain.common import EntityRef

    _draft.n = getattr(_draft, "n", 0) + 1      # one open request per contact: each draft goes to its own address
    base = dict(type="supplier_request", item_key=None, run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient=f"contact{_draft.n}@yunzhan-motor.example", subject="s", body="b")
    return ledger.propose(db, **{**base, **kw})


def _runs(db, run_id, asked_by):
    con = sqlite3.connect(db)
    con.execute("drop table if exists runs")      # this copy is the test's own: only the two columns the owner rule reads
    con.execute("create table runs (run_id text primary key, asked_by text)")
    con.execute("insert into runs values (?, ?)", (run_id, asked_by))
    con.commit()
    con.close()


def test_a_draft_tied_to_no_item_is_owned_by_the_asker_then_the_suppliers_buyer_then_nobody(db):
    """An answer from Ask has no Action-list item. Its owner is the asker who started the run, else the buyer on most of the supplier's lines, else nobody may sign."""
    _runs(db, "run-ask", "Marcus")
    asked = _draft(db, run_id="run-ask")
    assert approvers.owners_of_action(db, asked) == {"Marcus Chen"}                                  # the asker, not the supplier's buyer (Dana)
    nobody_asked = _draft(db, run_id="run-none")
    top = sqlite3.connect(db).execute("select b.name from po_lines p join buyers b on b.id = p.buyer_id where p.identity_id = 'SUP-0001' group by b.name order by count(*) desc limit 1").fetchone()[0]
    assert approvers.owners_of_action(db, nobody_asked) == {top}                                      # no asker: the buyer on the supplier's lines
    from app.domain.common import EntityRef

    loose = _draft(db, target=EntityRef(type="part", id="HR-40110"))
    with pytest.raises(approvers.NoOwner):
        approvers.owners_of_action(db, loose)                                                          # no asker, no supplier: nobody signs
    on_item = _draft(db, item_key="disruption:SUP-0001", run_id="run-ask")
    assert approvers.owners_of_action(db, on_item) == {"Dana Reyes"}                                  # an Action-list item's own owner still decides
    unknown_item = _draft(db, item_key="ask:something", run_id="run-ask")
    assert approvers.owners_of_action(db, unknown_item) == {"Marcus Chen"}                            # an item the list cannot name falls to the asker, not to everybody


def test_the_counts_say_what_is_mine_and_what_waits_for_anyone(db, monkeypatch):
    from app import db as app_db
    from app.domain.actions import ledger
    from app.domain.attention import api as attention_api
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    monkeypatch.setattr(app_db, "DB_PATH", db)
    monkeypatch.setattr(attention_api, "COUNT_PROVIDERS", {"approvals_pending": lambda s: len(ledger.list_actions(db, "proposed"))})      # only the count under test, whatever else the app registered
    _runs(db, "run-m", "Marcus")
    _draft(db, item_key="disruption:SUP-0001")                      # Dana's
    _draft(db, run_id="run-m")                                      # Marcus's (his Ask)
    _draft(db, item_key="reply:x-nobody-ties-this")                 # nobody's: no one can sign it
    with Session(create_engine(f"sqlite:///{db}", future=True)) as s:
        everyone = attention_api.counts(None, s)
        dana, marcus, tom = attention_api.counts("Dana", s), attention_api.counts("Marcus", s), attention_api.counts("Tom", s)
    assert everyone.waiting_all == 3 and everyone.to_sign_mine is None and everyone.approvals_pending == 3
    assert (dana.to_sign_mine, marcus.to_sign_mine, tom.to_sign_mine) == (1, 1, 0) and dana.waiting_all == 3


def test_a_message_detail_names_its_owner_from_the_records(session):
    """'No buyer is named for the battery packs, so the item has no owner': Priya buys them and the mail is addressed to her."""
    from app.domain.inbox import service as inbox

    quenvara = inbox.message_detail(session, "2026-09-21_Quotation_QV-Q-2609-17_battery_packs_2027_Malaysia_option")
    assert quenvara.owner == "Priya Nair"                                            # the parts it names are hers; the mail is to her
    assert inbox.message_detail(session, "2026-09-15_Holiday_notice_National_Day_2026").owner == "Tom Albrecht"             # the supplier's buyer
    assert inbox.message_detail(session, FIRE_NOTICE).owner == "Dana Reyes"          # the linked item's owner
    assert all(inbox.message_detail(session, m.ref.id).owner for m in inbox.list_messages(session))      # no message in the inbox is ownerless


def test_a_mail_that_names_no_line_part_or_supplier_is_owned_by_the_buyer_it_is_addressed_to(db):
    _message(db, "x-to")
    con = sqlite3.connect(db)
    con.execute("update messages set to_addrs = 'Marcus Chen <marcus.chen@haldenrobotics.example>' where id = 'x-to'")
    con.commit()
    con.close()
    assert approvers.owners_of(db, "reply:x-to") == {"Marcus Chen"}
