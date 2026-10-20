"""The buyer chooses a route; the draft follows (Khalid 2026-10-14). POST /api/action-items/{key}/routes/{kind}/choose records the choice and returns the
route's prepared draft, or one drafted in code from the route's template to its recipient on file. Proved on the seed (with the morning run's drafts) and on a
perturbed build (no drafts, a renamed supplier, another company)."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.domain.perturb import BACKEND, perturb

SEED = BACKEND / "demo-seed.db"


def _client(db, monkeypatch):
    from app import db as _db
    from app.domain.actions.api import router

    monkeypatch.setattr(_db, "DB_PATH", db)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


@pytest.fixture()
def seed(tmp_path, monkeypatch):
    if not SEED.exists():
        pytest.skip("no demo seed in this checkout (make demo-state writes one)")
    db = tmp_path / "seed.db"
    shutil.copy(SEED, db)
    monkeypatch.setenv("LOOKOUT_DB", str(db))
    return db


def _choose(c, key, kind, by, **kw):
    return c.post(f"/api/action-items/{key}/routes/{kind}/choose", json={"by": by, **kw})


def _draft_to(db, recipient):
    """The waiting request to a contact on file (ids change with every seed re-make, the contact does not)."""
    return sqlite3.connect(db).execute("SELECT action_id, body FROM actions WHERE type = 'supplier_request' AND state = 'proposed' AND recipient = ? ORDER BY proposed_at DESC",
                                       (recipient,)).fetchone()


def _count(db, sql):
    return sqlite3.connect(db).execute(sql).fetchone()[0]


def test_choosing_the_prepared_route_returns_the_runs_draft_and_records_who(seed, monkeypatch):
    c = _client(seed, monkeypatch)
    before = _count(seed, "SELECT count(*) FROM actions WHERE type = 'supplier_request'")
    fire_id, _ = _draft_to(seed, "li.wei@yunzhan-motor.example")
    slip_id, _ = _draft_to(seed, "lin.yuting@jadepeak.example")
    r = _choose(c, "disruption:SUP-0001", "allocation", "Dana Reyes")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["action_id"] == fire_id and a["state"] == "proposed" and a["chosen"] and a["chosen_by"] == "Dana Reyes" and a["change"]["how"] == "prepared"
    assert _count(seed, "SELECT count(*) FROM actions WHERE type = 'supplier_request'") == before                      # no new draft: instant
    again = _choose(c, "disruption:SUP-0001", "allocation", "Dana Reyes").json()
    assert again["action_id"] == a["action_id"] and _count(seed, "SELECT count(*) FROM actions WHERE body = 'Chose: Allocation request · Yunzhan'") == 1
    chosen = c.get("/api/actions", params={"chosen": "true"}).json()
    assert [x["action_id"] for x in chosen] == [fire_id] and slip_id not in {x["action_id"] for x in chosen}


def test_an_unprepared_route_is_drafted_in_code_to_its_own_recipient(seed, monkeypatch):
    c = _client(seed, monkeypatch)
    a = _choose(c, "disruption:SUP-0001", "alternate_on_file", "Dana Reyes").json()          # Also start: the other supplier on file for HR-40120
    assert a["change"]["how"] == "drafted" and a["type"] == "supplier_request" and a["recipient"] == "somchai.wongsa@siammotion.example"
    assert a["body"].startswith("Dear Somchai Wongsa,") and "Motor, DC gearmotor (HR-40120)" in a["body"] and "Please reply by 30 September." in a["body"]
    assert a["body"].rstrip().endswith("Dana Reyes\nHalden Robotics") and a["payload_hash"] and a["chosen_route"] == "alternate_on_file"
    note = _choose(c, "disruption:SUP-0001", "resequence", "Dana Reyes").json()
    assert note["type"] == "note" and note["change"]["to"] == "planning" and note["change"]["option_kind"] == "resequence" and note["state"] == "proposed"


def test_one_thread_per_contact_a_second_route_joins_the_waiting_email_and_a_covered_one_is_not_asked_twice(seed, monkeypatch):
    c = _client(seed, monkeypatch)
    first = _choose(c, "consignment:HR-30110", "cm_partial", "Marcus Chen").json()
    second = _choose(c, "consignment:HR-30110", "cm_stock", "Marcus Chen").json()
    assert second["action_id"] == first["action_id"] and second["change"]["how"] == "amended" and second["chosen_routes"] == ["cm_partial", "cm_stock"]
    paras = second["body"].split("\n\n")
    assert paras.index(next(p for p in paras if "consigned material you hold" in p)) < paras.index(next(p for p in paras if p.startswith("Please reply by")))
    gp_id, held = _draft_to(seed, "heather.lindqvist@gpextrusion.example")
    gp = _choose(c, "deadline:SUP-0041:2026-10-15", "buy_ahead", "Tom Albrecht").json()     # the chase email to the same contact already asks for today's price
    assert gp["action_id"] == gp_id and gp["change"]["how"] in ("covered", "prepared") and gp["body"] == held      # prepared once the letter records it carries this case's ask


def test_only_the_owner_chooses_and_a_decision_needs_its_reason(seed, monkeypatch):
    c = _client(seed, monkeypatch)
    assert _choose(c, "disruption:SUP-0001", "allocation", "Priya Nair").status_code == 403
    assert _choose(c, "disruption:SUP-0001", "no_such_route", "Dana Reyes").status_code == 404
    assert _choose(c, "disruption:SUP-0001", "wait", "Dana Reyes").status_code == 422
    rec = _choose(c, "disruption:SUP-0001", "wait", "Dana Reyes", reason="revised dates promised by Oct 10").json()
    assert rec["subject"] == "Decision" and rec["change"]["kind"] == "record" and rec["change"]["reason"] == "revised dates promised by Oct 10"
    trust = next(k for (k,) in sqlite3.connect(seed).execute("SELECT DISTINCT item_key FROM actions WHERE item_key LIKE 'trust:%'")) if _count(seed, "SELECT count(*) FROM actions WHERE item_key LIKE 'trust:%'") else "trust:x"
    assert _choose(c, trust, "allocation", "Dana Reyes").status_code in (404, 409)


@pytest.fixture(scope="module")
def changed(tmp_path_factory):
    import os

    root = tmp_path_factory.mktemp("choice-perturbed")
    data, recipe = perturb(root)
    db = root / "perturbed.db"
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(recipe), "--data", str(data), "--db", str(db)], cwd=BACKEND,
                          env={**os.environ, "LOOKOUT_DB": str(db)}, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-600:] + done.stderr[-600:]
    return db


def test_on_changed_data_the_route_is_drafted_to_the_renamed_suppliers_contact_for_the_other_company(changed, tmp_path, monkeypatch):
    db = tmp_path / "p.db"
    shutil.copy(changed, db)
    monkeypatch.setenv("LOOKOUT_DB", str(db))
    c = _client(db, monkeypatch)
    a = _choose(c, "disruption:SUP-0001", "allocation", "Dana Reyes").json()                 # no morning run on this build: drafted in code
    assert a["change"]["how"] == "drafted" and "marlowe" in a["recipient"] and "Yunzhan" not in a["body"] and "Yunzhan" not in a["subject"]
    assert a["body"].rstrip().endswith("Ashgrove Robotics") and "Halden" not in a["body"] and "accepts the notice or waives any of Ashgrove's rights" in a["body"]


def test_a_second_route_to_the_runs_email_gets_its_own_ask_not_the_run_email_as_is(seed, monkeypatch):
    """AI-UI-SYNC Q1: the run's email to a contact is a route's prepared draft only when it already asks that route's question; otherwise the ask is added."""
    c = _client(seed, monkeypatch)
    fire_id, held = _draft_to(seed, "li.wei@yunzhan-motor.example")
    assert _choose(c, "disruption:SUP-0001", "allocation", "Dana Reyes").json()["change"]["how"] == "prepared"           # it asks for allocation already
    air = _choose(c, "disruption:SUP-0001", "air_freight", "Dana Reyes").json()
    assert air["action_id"] == fire_id and air["change"]["how"] == "amended" and "by air" in air["body"] and "by air" not in held
    assert sorted(air["chosen_routes"]) == ["air_freight", "allocation"]


def test_a_roll_up_never_hands_one_buyer_another_buyers_draft(seed, monkeypatch):
    """AI-UI-SYNC Q2: on a case over several suppliers, the chooser gets only requests they sign; another buyer's are theirs to choose."""

    from app.domain.actions import approvers

    c = _client(seed, monkeypatch)
    for key, kind in (("deadline:quotes", "extend"), ("unknown:origin", "ask_origin")):
        for by in sorted(approvers.owners_of(seed, key)):
            r = _choose(c, key, kind, by)
            if r.status_code == 200:
                a = r.json()
                assert by in (approvers.owners_of_action(seed, approvers_action(seed, a["action_id"])) or {by}), (key, by, a["action_id"])
            else:
                assert r.status_code == 409 and "yours to sign" in r.json()["detail"], (key, by, r.text)


def approvers_action(db, action_id):
    from app.domain.actions import ledger

    return ledger.get(db, action_id)
