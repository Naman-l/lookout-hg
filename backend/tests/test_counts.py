"""The sidebar's live counts: drafts awaiting approval and runs in flight come from the ledger and the run store."""
from app import db as app_db
from app.domain.actions import ledger
from app.domain.attention.api import COUNT_PROVIDERS
from app.domain.common import EntityRef
from app import main  # noqa: F401  (registers the providers)


def test_approvals_pending_counts_proposed_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "a.db")
    assert COUNT_PROVIDERS["approvals_pending"](None) == 0
    a = ledger.propose(app_db.DB_PATH, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-1",
                       target=EntityRef(type="supplier", id="SUP-0001"), recipient="li.wei@yunzhan-motor.example",
                       subject="Revised promise dates", body="Please confirm.")
    assert COUNT_PROVIDERS["approvals_pending"](None) == 1
    ledger.reject(app_db.DB_PATH, a.action_id, "not now", "Dana Reyes")
    assert COUNT_PROVIDERS["approvals_pending"](None) == 0


def test_runs_running_reads_an_empty_store(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "a.db")
    assert COUNT_PROVIDERS["runs_running"](None) == 0
