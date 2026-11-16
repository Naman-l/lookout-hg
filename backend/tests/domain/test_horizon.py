"""Hindsight: the same recipe rebuilds the database as it stood on an earlier day, and nothing that happened after that day is in it."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
RECIPE = BACKEND.parent / "recipes" / "hg"
HORIZON = "2026-09-01"      # before the MFC fell due, the October mail, the fund sheets and the vendor's rename

# Columns that record something that happened (not a plan, a due date or a validity): none may be later than the data date.
HAPPENED = {"created", "released", "changed_on", "doc_date", "posting_date", "clearing_date", "date", "rfq_sent", "first_quote", "quote_date", "approved_on",
            "issued_on", "mfc_requested", "mfc_issued", "inspection_call", "inspection_done", "dispatch_clearance", "delivered", "commissioned", "created_on", "built_on"}


@pytest.fixture(scope="module")
def early(tmp_path_factory):
    db = tmp_path_factory.mktemp("horizon") / "early.db"
    env = {**os.environ, "LOOKOUT_AS_OF": HORIZON, "LOOKOUT_DB": str(db)}
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(RECIPE), "--db", str(db)], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    con = sqlite3.connect(db)
    yield con
    con.close()


def test_nothing_that_happened_after_the_horizon_is_in_the_database(early):
    assert early.execute("select value from build_meta where key = 'as_of'").fetchone()[0] == HORIZON
    late = []
    for (table,) in early.execute("select name from sqlite_master where type = 'table' and name not like 'raw_%'"):
        for col in [r[1] for r in early.execute(f"pragma table_info({table})")]:
            if col in HAPPENED:
                n = early.execute(f"select count(*) from {table} where substr({col}, 1, 10) > ?", (HORIZON,)).fetchone()[0]
                late += [f"{table}.{col}: {n}"] if n else []
    assert late == []


def test_sheets_built_after_the_horizon_are_not_read_and_trackers_are_read_row_by_row(early):
    one = lambda sql: early.execute(sql).fetchone()[0]      # noqa: E731
    assert one("select count(*) from fund_lines") == 0 and one("select count(*) from requirement_lines") == 0 and one("select count(*) from payment_projection") == 0
    assert one("select count(*) from messages") == 0 and one("select count(*) from events") == 0      # every mail is from October
    assert 0 < one("select count(*) from quotes") < 2124 and 0 < one("select count(*) from vendor_library") < 351
    assert one("select count(*) from supplier_records") == 88      # the renamed firm's new code was created on 10 Sep


def test_what_the_mfc_story_looked_like_on_the_horizon(early):
    """The traction transformers' PO was already open, its validity already 31 Oct, the MFC asked for and not yet given: visible, not yet urgent."""
    po = early.execute("select po_line_id from milestones where mfc_requested is not null and mfc_issued is null").fetchall()
    assert po, "an MFC asked for and not issued"
    validity = {r[0] for p in po for r in early.execute("select validity_end from po_lines where id = ?", p)}
    assert "2026-10-31" in validity


def test_every_gate_check_passes_on_the_horizon(early):
    failed = early.execute('select "check", detail from load_gate where passed = 0').fetchall()
    assert failed == []
