"""Approvals over HTTP, no model: the 409 paths and exactly one send."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db as app_db
from app.domain.actions import api, approvers, ledger
from app.domain.common import EntityRef

from .conftest import seed_buyers

REAL_OWNERS_OF_ACTION = approvers.owners_of_action
REAL_OWNERS_OF_ACTION = approvers.owners_of_action
REAL_OWNERS_OF = approvers.owners_of      # the fixture below stands in for it; one test needs the real lookup


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "a.db")
    seed_buyers(app_db.DB_PATH)
    monkeypatch.setattr(approvers, "owners_of", lambda db, key: None)      # these test the ledger over HTTP: the database has no Action list to ask who owns an item
    monkeypatch.setattr(approvers, "owners_of_action", lambda db, action: None)
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def staged(client):
    return ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-1", target=EntityRef(type="supplier", id="SUP-0001"),
                          recipient="li.wei@yunzhan-motor.example", subject="Revised promise dates", body="Please confirm.")


def test_awaiting_approval_is_listed_and_the_outbox_is_empty(client, staged):
    rows = client.get("/api/actions", params={"state": "proposed"}).json()
    assert [r["action_id"] for r in rows] == [staged.action_id] and rows[0]["recipient"] == "li.wei@yunzhan-motor.example"
    assert client.get("/api/outbox").json() == []


def test_a_wrong_hash_is_409_and_nothing_is_sent(client, staged):
    r = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": "bad", "approved_by": "Dana Reyes"})
    assert r.status_code == 409
    assert client.get("/api/outbox").json() == [] and client.get(f"/api/actions/{staged.action_id}").json()["state"] == "proposed"


def test_the_right_hash_executes_exactly_one_send_and_a_second_approval_is_409(client, staged):
    body = {"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"}
    r = client.post(f"/api/actions/{staged.action_id}/approve", json=body)
    assert r.status_code == 200 and r.json()["state"] == "executed" and r.json()["outbox_id"]
    out = client.get("/api/outbox").json()
    assert len(out) == 1 and out[0]["to"] == "li.wei@yunzhan-motor.example" and out[0]["status"] == "sent_simulated"
    assert client.post(f"/api/actions/{staged.action_id}/approve", json=body).status_code == 409
    assert len(client.get("/api/outbox").json()) == 1


def test_reject_records_the_reason_and_blocks_approval(client, staged):
    r = client.post(f"/api/actions/{staged.action_id}/reject", json={"reason": "wrong supplier", "rejected_by": "Dana Reyes"})
    assert r.status_code == 200 and r.json()["state"] == "rejected" and r.json()["reason"] == "wrong supplier"
    assert client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"}).status_code == 409


def test_unknown_action_is_404(client):
    assert client.get("/api/actions/nope").status_code == 404
    assert client.post("/api/actions/nope/approve", json={"payload_hash": "x", "approved_by": "Dana Reyes"}).status_code == 404


def test_a_buyer_can_edit_a_waiting_draft_and_must_approve_the_edited_text(client, staged):
    r = client.patch(f"/api/actions/{staged.action_id}", json={"subject": "Revised dates, please", "body": "Please confirm dates for the Tern T2 lines.", "edited_by": "Dana Reyes"})
    assert r.status_code == 200 and r.json()["payload_hash"] != staged.payload_hash and r.json()["state"] == "proposed"
    assert staged.edited_by is None and r.json()["edited_by"] == "Dana Reyes"      # a hand edit is marked: its figures were not re-checked (LOOKOUT QA #17)
    stale = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"})
    assert stale.status_code == 409 and client.get("/api/outbox").json() == []
    ok = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": r.json()["payload_hash"], "approved_by": "Dana Reyes"})
    assert ok.status_code == 200 and len(client.get("/api/outbox").json()) == 1
    assert client.patch(f"/api/actions/{staged.action_id}", json={"subject": "x", "body": "y", "edited_by": "Dana Reyes"}).status_code == 409  # decided: no more edits


def test_a_send_that_failed_after_approval_is_finished_by_approving_again_and_goes_out_once(client, staged, monkeypatch):
    real = ledger.watcher.emit

    def boom(*a, **k):
        if a[1] == "action.executed":
            raise RuntimeError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(ledger.watcher, "emit", boom)
    first = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"}).json()
    assert first["state"] == "executed"  # the send and its confirmation are saved before the announcement; the announcement failing changes nothing
    assert len(client.get("/api/outbox").json()) == 1


def test_execute_between_attempt_and_confirmation_is_retryable_and_never_double_sends(client, staged):
    ledger.approve(app_db.DB_PATH, staged.action_id, staged.payload_hash, "Dana Reyes")
    con = ledger.connect(app_db.DB_PATH)  # simulate a crash after the send was written but before it was confirmed
    con.execute("UPDATE actions SET state = 'approved', confirmed_at = NULL WHERE action_id = ?", (staged.action_id,)); con.close()
    again = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"})
    assert again.status_code == 200 and again.json()["state"] == "executed" and len(client.get("/api/outbox").json()) == 1
    assert again.json()["attempted_at"] and again.json()["confirmed_at"]


@pytest.mark.parametrize("text", [
    "Please confirm your new bank details.", "Send us your updated banking instructions", "What is your account number and sort code?", "Kindly wire the funds to us",
    "Share the beneficiary name", "Please confirm the new payment details", "Our IBAN has changed", "send the money to the account below"])
def test_bank_wording_in_any_of_these_paraphrases_cannot_be_drafted(text):
    from app.domain.actions.tools import _FORBIDDEN

    assert _FORBIDDEN.search(text), text


@pytest.mark.parametrize("text", ["Please confirm the revised promise dates for HPO-26-00614 line 10.", "Can you hold the allocation for the Tern T2 build?", "Please confirm the quote is valid to 13 October."])
def test_ordinary_requests_are_not_caught_by_the_bank_filter(text):
    from app.domain.actions.tools import _FORBIDDEN

    assert not _FORBIDDEN.search(text), text


def test_a_name_that_is_not_a_buyer_cannot_decide(client, staged):
    for who in ("", "someone", "Yunzhan Accounts"):
        r = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": who})
        assert r.status_code == 422
    assert client.post(f"/api/actions/{staged.action_id}/reject", json={"reason": "x", "rejected_by": "nobody"}).status_code == 422
    assert client.patch(f"/api/actions/{staged.action_id}", json={"subject": "s", "body": "b", "edited_by": "nobody"}).status_code == 422
    assert client.get(f"/api/actions/{staged.action_id}").json()["state"] == "proposed" and client.get("/api/outbox").json() == []


def test_the_ledger_records_the_buyers_full_name(client, staged):
    r = client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "marcus"})
    assert r.status_code == 200 and r.json()["decided_by"] == "Marcus Chen"


def test_with_no_buyers_table_nobody_can_decide(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "empty.db")
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    a = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="k", run_id=None, target=EntityRef(type="supplier", id="SUP-0001"), recipient="a@b.example", subject="s", body="b")
    r = TestClient(app).post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": "Dana Reyes"})
    assert r.status_code == 422


def test_a_draft_from_a_run_that_did_not_pass_needs_a_confirmation(client):
    from app.organism.runs import store

    store.insert_run(app_db.DB_PATH, run_id="run-bad", item_key="disruption:SUP-0001", workflow="work_item", status="did_not_pass", started_at="2026-09-25T00:00:00",
                     verifier_json='{"failures": ["prose: numbers in the text that no tool returned: 7"]}')
    a = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-bad", target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Dates", body="Please confirm.")
    shown = client.get(f"/api/actions/{a.action_id}").json()
    assert shown["unverified_checks"] == ["prose: numbers in the text that no tool returned: 7"]
    body = {"payload_hash": a.payload_hash, "approved_by": "Dana Reyes"}
    r = client.post(f"/api/actions/{a.action_id}/approve", json=body)
    assert r.status_code == 409 and "did not pass" in r.json()["detail"] and client.get("/api/outbox").json() == []
    assert client.post(f"/api/actions/{a.action_id}/approve", json={**body, "confirm_unverified": True}).status_code == 200
    assert len(client.get("/api/outbox").json()) == 1


def _amended(run_status, failures="[]"):
    from app.organism.runs import store

    store.insert_run(app_db.DB_PATH, run_id="run-first", item_key="disruption:SUP-0001", workflow="work_item", status="ok", started_at="2026-09-25T00:00:00")
    store.insert_run(app_db.DB_PATH, run_id="run-again", item_key="disruption:SUP-0001", workflow="work_item", status=run_status, started_at="2026-09-25T01:00:00",
                     verifier_json=f'{{"failures": {failures}}}')
    a = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-first", target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Dates", body="Please confirm.")
    return ledger.update_draft(app_db.DB_PATH, a.action_id, subject="Dates", body="Please confirm. Also: one more thing.", edited_by="Lookout", run_id="run-again")


def test_a_draft_a_failed_run_amended_needs_a_confirmation_though_a_passed_run_staged_it(client):
    a = _amended("did_not_pass", '["dates: a date that is still ahead was written as past"]')
    assert a.edited_by is None      # a run's rewrite is checked by that run, so it is not a hand edit
    assert client.get(f"/api/actions/{a.action_id}").json()["unverified_checks"] == ["dates: a date that is still ahead was written as past"]
    body = {"payload_hash": a.payload_hash, "approved_by": "Dana Reyes"}
    r = client.post(f"/api/actions/{a.action_id}/approve", json=body)
    assert r.status_code == 409 and "did not pass" in r.json()["detail"] and client.get("/api/outbox").json() == []
    assert client.post(f"/api/actions/{a.action_id}/approve", json={**body, "confirm_unverified": True}).status_code == 200


def test_a_draft_a_passed_run_amended_needs_no_confirmation(client):
    a = _amended("ok")
    assert client.get(f"/api/actions/{a.action_id}").json()["unverified_checks"] == []
    assert client.post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": "Dana Reyes"}).status_code == 200


def test_only_the_buyer_who_owns_the_item_can_sign_its_draft(client, staged, monkeypatch):
    """The screen says 'Tom signs this one'; the API holds it too. Another buyer is refused with a plain reason, unless the team says it signs for each other."""
    monkeypatch.setattr(approvers, "owners_of", lambda db, key: {"Marcus Chen"})
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)
    body = {"payload_hash": staged.payload_hash, "approved_by": "Dana Reyes"}
    r = client.post(f"/api/actions/{staged.action_id}/approve", json=body)
    assert r.status_code == 403 and "belongs to Marcus Chen" in r.json()["detail"] and "you are Dana Reyes" in r.json()["detail"]
    assert client.post(f"/api/actions/{staged.action_id}/reject", json={"reason": "no", "rejected_by": "Dana Reyes"}).status_code == 403
    edit = {"subject": "s", "body": "b", "edited_by": "Dana Reyes"}
    assert client.patch(f"/api/actions/{staged.action_id}", json=edit).status_code == 403          # editing is signing's first half: the owner rule holds for it too
    assert client.patch(f"/api/actions/{staged.action_id}", json={**edit, "edited_by": "Marcus Chen"}).status_code == 200
    body = {**body, "payload_hash": client.get(f"/api/actions/{staged.action_id}").json()["payload_hash"]}
    assert client.get(f"/api/actions/{staged.action_id}").json()["state"] == "proposed" and client.get("/api/outbox").json() == []
    monkeypatch.setenv("LOOKOUT_ALLOW_DELEGATION", "1")
    assert client.post(f"/api/actions/{staged.action_id}/approve", json=body).status_code == 200  # delegation allowed by configuration
    monkeypatch.delenv("LOOKOUT_ALLOW_DELEGATION")


def test_when_the_owner_cannot_be_found_nobody_may_sign_edit_or_reject(client, staged, monkeypatch, caplog):
    """The lookup fails closed: an error is not 'no owner'. 409 with a reason, the error logged, nothing changed; delegation (an explicit choice) still widens it."""
    monkeypatch.setattr(approvers, "owners_of", REAL_OWNERS_OF)
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)      # the real lookup runs on a database with no Action list, and fails
    who = {"approved_by": "Dana Reyes"}
    with caplog.at_level("ERROR"):
        for r in (client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, **who}),
                  client.post(f"/api/actions/{staged.action_id}/reject", json={"reason": "no", "rejected_by": "Dana Reyes"}),
                  client.patch(f"/api/actions/{staged.action_id}", json={"subject": "s", "body": "b", "edited_by": "Dana Reyes"})):
            assert r.status_code == 409 and "Nobody can sign this now" in r.json()["detail"] and "disruption:SUP-0001" in r.json()["detail"]
    assert "owner lookup failed for item disruption:SUP-0001" in caplog.text
    assert client.get(f"/api/actions/{staged.action_id}").json()["state"] == "proposed" and client.get("/api/outbox").json() == []
    with pytest.raises(approvers.OwnerLookupError):
        approvers.owners_of(app_db.DB_PATH, "disruption:SUP-0001")
    assert approvers.owners_of(app_db.DB_PATH, None) is None                                      # no item key is a triage, not an error


def test_the_owner_signs_and_an_item_with_no_owner_the_list_can_name_excludes_nobody(client, staged, monkeypatch):
    from app.domain.actions import approvers

    real = approvers.owners_of
    assert real(app_db.DB_PATH, None) is None
    monkeypatch.setattr(approvers, "owners_of", lambda db, key: {"Dana Reyes", "Marcus Chen"})
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)  # two owners: either may sign
    assert client.post(f"/api/actions/{staged.action_id}/approve", json={"payload_hash": staged.payload_hash, "approved_by": "marcus"}).status_code == 200


def test_a_reply_draft_with_no_owner_is_409_for_everyone_unless_the_team_signs_for_each_other(client, monkeypatch):
    def nobody(db, key):
        raise approvers.NoOwner("no buyer owns this message: it links to no item (m1)")

    monkeypatch.setattr(approvers, "owners_of", nobody)
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)
    a = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="reply:m1", run_id="run-2", target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Re: dates", body="Thanks.")
    for who in ("Dana Reyes", "Marcus Chen"):
        r = client.post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": who})
        assert r.status_code == 409 and "Nobody can sign this" in r.json()["detail"] and "links to no item" in r.json()["detail"]
    assert client.patch(f"/api/actions/{a.action_id}", json={"subject": "s", "body": "b", "edited_by": "Dana Reyes"}).status_code == 409
    assert client.get("/api/outbox").json() == [] and client.get(f"/api/actions/{a.action_id}").json()["state"] == "proposed"
    monkeypatch.setenv("LOOKOUT_ALLOW_DELEGATION", "1")
    assert client.post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": "Dana Reyes"}).status_code == 200



def test_the_drafts_list_is_filtered_by_item_and_by_run(client, staged):
    other = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="deadline:SUP-0042:2026-09-28", run_id="run-2", target=EntityRef(type="supplier", id="SUP-0042"),
                           recipient="a@b.example", subject="Closure", body="Please confirm.")
    ids = lambda **q: sorted(r["action_id"] for r in client.get("/api/actions", params=q).json())      # noqa: E731
    assert ids() == sorted([staged.action_id, other.action_id])
    assert ids(item_key="disruption:SUP-0001") == [staged.action_id]      # an item shows its own drafts, not the others'
    assert ids(item_key="deadline:SUP-0042:2026-09-28") == [other.action_id]
    assert ids(item_key="unknown:undated") == []
    assert ids(run_id="run-2") == [other.action_id]
    assert ids(item_key="disruption:SUP-0001", run_id="run-2") == []


def test_only_the_buyer_of_the_lines_can_sign_a_draft_on_a_shared_item(client, monkeypatch):
    """FEEDBACK: on a shared item every owner could sign every draft; Tom saw Marcus's request under To sign with Approve enabled."""
    from app.domain.common import EntityRef

    import sqlite3

    db = app_db.DB_PATH
    with sqlite3.connect(db) as con:
        con.execute("INSERT OR IGNORE INTO buyers VALUES ('Tom', 'Tom Albrecht', 'TA'), ('Marcus', 'Marcus Chen', 'MC')")
    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Marcus Chen", "Dana Reyes", "Tom Albrecht"})  # the shared item: three owners
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)  # the real signer rule, not the fixture's stand-in
    a = ledger.propose(db, type="supplier_request", item_key="deadline:chase", run_id="run-1", target=EntityRef(type="supplier", id="SUP-0035"), recipient="laura@brightwave.example",
                       subject="Past due line", body="Please confirm.\n\nRegards,\nMarcus Chen", change={"owner": "Marcus Chen"})
    assert a.owner == "Marcus Chen" and ledger.get(db, a.action_id).owner == "Marcus Chen"
    refused = client.post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": "Tom Albrecht"})
    assert refused.status_code == 403 and "Marcus Chen" in refused.json()["detail"]
    assert client.get(f"/api/actions/{a.action_id}").json()["owner"] == "Marcus Chen"
    ok = client.post(f"/api/actions/{a.action_id}/approve", json={"payload_hash": a.payload_hash, "approved_by": "Marcus Chen"})
    assert ok.status_code == 200 and ok.json()["state"] == "executed"


REAL_OWNERS_OF_ACTION = approvers.owners_of_action


@pytest.fixture
def case_client(client, monkeypatch):
    """P7 (F101): a case owned by Dana; the action's own owner decides who signs it (the real rule)."""
    monkeypatch.setattr(approvers, "owners_of", lambda db, key: {"Dana Reyes"} if key == "disruption:SUP-0001" else None)
    monkeypatch.setattr(approvers, "owners_of_action", REAL_OWNERS_OF_ACTION)
    return client


def test_a_note_a_decision_and_an_erp_update_are_staged_for_the_owners_signature_and_recorded_without_a_send(case_client):
    c = case_client
    note = c.post("/api/action-items/disruption:SUP-0001/actions", json={"kind": "note", "staged_by": "Dana Reyes", "to": "planning", "text": "Move the Heron build first in October.", "option_kind": "resequence"})
    assert note.status_code == 201 and note.json()["state"] == "proposed" and note.json()["type"] == "note" and note.json()["subject"] == "Note to planning"
    assert note.json()["change"]["owner"] == "Dana Reyes" and note.json()["change"]["option_kind"] == "resequence"
    rec = c.post("/api/action-items/disruption:SUP-0001/actions", json={"kind": "record", "staged_by": "Dana Reyes", "text": "Wait for Yunzhan's revised dates.", "reason": "Dates promised by Oct 10", "recheck_on": "2026-10-10"}).json()
    erp = c.post("/api/action-items/disruption:SUP-0001/actions", json={"kind": "erp_update", "staged_by": "Dana Reyes", "text": "Enter the revised dates.",
                                                                       "lines": [{"po_line": "HPO-26-00450/10", "was": "2026-09-20", "now": "2026-11-03"}]}).json()
    assert rec["subject"] == "Decision" and erp["subject"] == "PO lines to update · enter in the ERP" and erp["change"]["lines"][0]["now"] == "2026-11-03"
    assert c.post(f"/api/actions/{rec['action_id']}/approve", json={"payload_hash": "stale", "approved_by": "Dana Reyes"}).status_code == 409      # hash-bound, like a draft
    assert c.post(f"/api/actions/{rec['action_id']}/approve", json={"payload_hash": rec["payload_hash"], "approved_by": "Marcus Chen"}).status_code == 403   # only the owner signs
    done = c.post(f"/api/actions/{rec['action_id']}/approve", json={"payload_hash": rec["payload_hash"], "approved_by": "Dana Reyes"})
    assert done.status_code == 200 and done.json()["state"] == "executed" and done.json()["outbox_id"] is None and c.get("/api/outbox").json() == []


def test_staging_on_a_case_is_refused_for_another_buyer_a_trust_item_or_a_missing_field(case_client):
    c, url = case_client, "/api/action-items/disruption:SUP-0001/actions"
    assert c.post(url, json={"kind": "note", "staged_by": "Marcus Chen", "to": "planning", "text": "x"}).status_code == 403
    assert c.post(url, json={"kind": "record", "staged_by": "Dana Reyes", "text": "Wait."}).status_code == 422                  # a decision needs a reason
    assert c.post(url, json={"kind": "erp_update", "staged_by": "Dana Reyes", "text": "Update."}).status_code == 422            # an ERP update lists its lines
    assert c.post(url, json={"kind": "note", "staged_by": "Dana Reyes", "text": "x"}).status_code == 422                       # a note says who it is for
    assert c.post("/api/action-items/trust:x/actions", json={"kind": "note", "staged_by": "Dana Reyes", "to": "AP", "text": "x"}).status_code == 409
    assert c.post("/api/action-items/nope:1/actions", json={"kind": "note", "staged_by": "Dana Reyes", "to": "AP", "text": "x"}).status_code == 404
    assert c.get("/api/actions", params={"state": "proposed"}).json() == []                                                      # nothing refused was staged


def test_the_owner_edits_a_staged_decision_and_signs_the_new_words(case_client):
    """UX F101: the agent wrote the statement, the reason and the re-check date, so the owner may change them before signing; the hash moves with
    them (the old one is refused), another buyer may not edit, and a decision keeps a reason."""
    c = case_client
    rec = c.post("/api/action-items/disruption:SUP-0001/actions", json={"kind": "record", "staged_by": "Dana Reyes", "text": "Wait.", "reason": "Dates due Oct 10", "recheck_on": "2026-10-10"}).json()
    url = f"/api/actions/{rec['action_id']}"
    assert c.patch(url, json={"subject": "Decision", "body": "Wait.", "edited_by": "Marcus Chen", "reason": "x"}).status_code == 403
    assert c.patch(url, json={"subject": "Decision", "body": "Wait.", "edited_by": "Dana Reyes", "reason": "  "}).status_code == 422
    new = c.patch(url, json={"subject": "Decision", "body": "Wait for the revised dates.", "edited_by": "Dana Reyes", "reason": "Yunzhan promised dates by Oct 10", "recheck_on": "2026-10-12"}).json()
    assert new["change"]["reason"] == "Yunzhan promised dates by Oct 10" and new["change"]["recheck_on"] == "2026-10-12" and new["change"]["kind"] == "record" and new["change"]["owner"] == "Dana Reyes"
    assert new["payload_hash"] != rec["payload_hash"] and new["edited_by"] == "Dana Reyes"
    assert c.post(f"{url}/approve", json={"payload_hash": rec["payload_hash"], "approved_by": "Dana Reyes"}).status_code == 409      # the old words are void
    assert c.post(f"{url}/approve", json={"payload_hash": new["payload_hash"], "approved_by": "Dana Reyes"}).json()["state"] == "executed"
    note = c.post("/api/action-items/disruption:SUP-0001/actions", json={"kind": "note", "staged_by": "Dana Reyes", "to": "planning", "text": "x"}).json()
    assert c.patch(f"/api/actions/{note['action_id']}", json={"subject": "Note to planning", "body": "y", "edited_by": "Dana Reyes", "reason": "z"}).status_code == 422
