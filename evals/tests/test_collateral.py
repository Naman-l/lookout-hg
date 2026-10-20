"""The collateral check (evals/agent_runner.py): a run may change the ledger and the run store, never the buyer's records.
Harness fix 2026-10-14: payload_runs (the ledger's writer runs of a draft, 7c4f86c) was missing from the allow-list, so every trial that staged
and signed a draft failed 'the records changed' (round fp13). A change to a real record must still fail."""

import sqlite3

from evals.agent_runner import collateral, records_snapshot


def _db(tmp_path):
    db = tmp_path / "c.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE po_lines (id TEXT, qty INTEGER)")
        con.execute("INSERT INTO po_lines VALUES ('HPO-1/10', 5)")
        con.execute("CREATE TABLE payload_runs (action_id TEXT, run_id TEXT)")
        con.execute("CREATE TABLE actions (action_id TEXT)")
    return db


def test_staging_a_draft_is_not_collateral(tmp_path):
    db = _db(tmp_path)
    before = records_snapshot(db)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO actions VALUES ('A-1')")
        con.execute("INSERT INTO payload_runs VALUES ('A-1', 'run-1')")
    assert collateral(before, records_snapshot(db)) == []


def test_a_change_to_a_record_is_still_collateral(tmp_path):   # must FAIL a run that touches the buyer's records
    db = _db(tmp_path)
    before = records_snapshot(db)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE po_lines SET qty = 6")
    assert collateral(before, records_snapshot(db)) == ["po_lines (rows changed)"]
