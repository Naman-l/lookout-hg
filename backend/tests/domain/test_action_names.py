"""Approvals (FINAL 03): a draft names its supplier the way a buyer says it, for the queue and the heading."""

import shutil

from app import db as app_db
from app.domain.actions import api, ledger
from app.domain.common import EntityRef


def test_a_draft_to_a_supplier_carries_its_short_name(db_path, tmp_path, monkeypatch):
    copy = tmp_path / "names.db"
    shutil.copy(db_path, copy)
    monkeypatch.setattr(app_db, "DB_PATH", copy)
    a = ledger.propose(copy, type="supplier_request", item_key="disruption:SUP-0001", run_id="r1", target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Revised dates", body="Dear Li Wei,\nHPO-26-00450/10, HR-40110, 355 EA, confirmed 26 August")
    shown = api._shown(a)
    assert shown.target.label == "Yunzhan" and shown.target.id == "SUP-0001"
    assert {e.type for e in shown.body_entities} >= {"po_line", "part", "quantity", "date"}      # the marks the email shows
