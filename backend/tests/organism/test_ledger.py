"""The ledger's guarantees, with no model: hash-bound approval, execution re-checks, exactly one send."""

import sqlite3

import pytest

from app.domain.actions import ledger
from app.domain.common import EntityRef

SUP = EntityRef(type="supplier", id="SUP-0001")


def draft(db, body="Please confirm revised promise dates for HPO-26-00614 line 10.", item="disruption:SUP-0001"):
    return ledger.propose(db, type="supplier_request", item_key=item, run_id="run-1", target=SUP, recipient="li.wei@yunzhan-motor.example", subject="Revised promise dates", body=body)


def test_a_draft_waits_and_the_outbox_is_empty(db):
    a = draft(db)
    assert a.state == "proposed" and a.recipient == "li.wei@yunzhan-motor.example" and len(a.payload_hash) == 64
    assert ledger.outbox(db) == []


def test_the_same_draft_is_staged_once(db):
    assert draft(db).action_id == draft(db).action_id
    assert len(ledger.list_actions(db)) == 1


def test_no_contact_on_file_means_no_draft(db):
    with pytest.raises(ledger.LedgerError) as e:
        ledger.propose(db, type="supplier_request", item_key="k", run_id="r", target=SUP, recipient=None, subject="s", body="b")
    assert e.value.code == "no_recipient"


def test_approving_a_wrong_hash_is_refused_and_sends_nothing(db):
    a = draft(db)
    with pytest.raises(ledger.LedgerError) as e:
        ledger.approve(db, a.action_id, "0" * 64, "Dana Reyes")
    assert e.value.code == "hash"
    assert ledger.get(db, a.action_id).state == "proposed" and ledger.outbox(db) == []


def test_approving_the_shown_hash_executes_exactly_one_send(db):
    a = draft(db)
    done = ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert done.state == "executed" and done.decided_by == "Dana Reyes" and done.outbox_id
    assert done.attempted_at and done.confirmed_at
    out = ledger.outbox(db)
    assert len(out) == 1 and out[0].to == "li.wei@yunzhan-motor.example" and out[0].status == "sent_simulated"


def test_a_second_approval_is_refused(db):
    a = draft(db)
    ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    with pytest.raises(ledger.LedgerError) as e:
        ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert e.value.code == "state" and len(ledger.outbox(db)) == 1


def test_rejected_drafts_cannot_be_approved(db):
    a = draft(db)
    ledger.reject(db, a.action_id, "wrong supplier", "Dana Reyes")
    with pytest.raises(ledger.LedgerError):
        ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert ledger.outbox(db) == []


def test_editing_a_draft_voids_the_hash_that_was_shown(db):
    a = draft(db)
    b = ledger.update_draft(db, a.action_id, subject=a.subject, body="Different text.", edited_by="Dana Reyes")
    assert b.payload_hash != a.payload_hash and b.state == "proposed"
    with pytest.raises(ledger.LedgerError) as e:
        ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert e.value.code == "hash"


def test_a_row_changed_outside_the_ledger_is_caught_at_approval_and_at_execution(db):
    a = draft(db)
    con = sqlite3.connect(db)
    con.execute("UPDATE actions SET recipient = 'attacker@evil.example' WHERE action_id = ?", (a.action_id,))
    con.commit()
    with pytest.raises(ledger.LedgerError) as e:
        ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert e.value.code == "tampered" and ledger.outbox(db) == []
    # even an action already marked approved is not sent if its payload no longer matches the approved hash
    con.execute("UPDATE actions SET state = 'approved' WHERE action_id = ?", (a.action_id,))
    con.commit()
    with pytest.raises(ledger.LedgerError) as e:
        ledger.execute(db, a.action_id)
    assert e.value.code == "tampered" and ledger.outbox(db) == []


def test_execute_needs_an_approved_action(db):
    a = draft(db)
    with pytest.raises(ledger.LedgerError) as e:
        ledger.execute(db, a.action_id)
    assert e.value.code == "state" and ledger.outbox(db) == []


def test_app_actions_are_logged_as_executed_and_never_reach_the_outbox(db):
    a = ledger.record_app_action(db, type="note", item_key="disruption:SUP-0001", target=None, body="Called Li Wei", by="Dana Reyes")
    assert a.state == "executed" and ledger.outbox(db) == []


def test_a_rerun_links_to_the_waiting_draft_instead_of_staging_a_second_one(db):
    first = ledger.propose(db, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-1", target=SUP, recipient="li.wei@yunzhan-motor.example", subject="s", body="b")
    again = ledger.propose(db, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-2", target=SUP, recipient="li.wei@yunzhan-motor.example", subject="s", body="b")
    assert again.action_id == first.action_id and len(ledger.list_actions(db)) == 1
    assert ledger.in_run(db, first.action_id, "run-1") and ledger.in_run(db, first.action_id, "run-2") and not ledger.in_run(db, first.action_id, "run-3")
    assert [a.action_id for a in ledger.for_run(db, "run-2")] == [first.action_id]


def test_the_same_question_for_a_buyer_is_logged_once_however_often_the_item_is_worked(db):
    kw = dict(type="note", item_key="deadline:SUP-0001:2026-10-13", target=EntityRef(type="item", id="deadline:SUP-0001:2026-10-13"), body="Is the Vinh Phuc motor a drop-in?", by="Lookout")
    a, b = ledger.record_app_action(db, run_id="run-1", **kw), ledger.record_app_action(db, run_id="run-2", **kw)
    assert a.action_id == b.action_id and len(ledger.list_actions(db)) == 1 and ledger.in_run(db, a.action_id, "run-2")
    other = ledger.record_app_action(db, run_id="run-2", **{**kw, "body": "A different question"})
    assert other.action_id != a.action_id


def test_approving_a_supplier_alias_records_a_link_and_merges_nothing(db):
    a = ledger.propose(db, type="supplier_alias", item_key="triage:m1", run_id="run-1", target=EntityRef(type="supplier", id="SUP-0061"), recipient=None,
                       subject="Link SUP-0061 and V10560 as one supplier", body="Baycrest says it is now BCX.", change={"link": ["V10560", "SUP-0061"], "merge": False})
    assert ledger.supplier_links(db) == []  # proposing records nothing
    done = ledger.approve(db, a.action_id, a.payload_hash, "Priya Nair")
    assert done.state == "executed" and done.outbox_id is None and ledger.outbox(db) == []  # nothing is sent
    (link,) = ledger.supplier_links(db)
    assert (link["supplier_a"], link["supplier_b"], link["linked_by"], link["action_id"]) == ("SUP-0061", "V10560", "Priya Nair", a.action_id)
    assert link["evidence"] == "Baycrest says it is now BCX."


def test_a_rejected_alias_leaves_no_link(db):
    a = ledger.propose(db, type="supplier_alias", item_key="triage:m1", run_id="run-1", target=EntityRef(type="supplier", id="SUP-0061"), recipient=None,
                       subject="s", body="b", change={"link": ["V10560", "SUP-0061"], "merge": False})
    ledger.reject(db, a.action_id, "not the same company", "Priya Nair")
    assert ledger.supplier_links(db) == []
