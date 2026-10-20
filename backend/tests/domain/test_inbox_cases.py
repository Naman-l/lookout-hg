"""Inbox (FINAL 04 §6): each message carries the case it moves, its robots and owner, and each change its quantity and ship date."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(db_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app import db as _db
    from app.db import get_session
    from app.domain.inbox.api import router

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def session():
        with Session(eng) as s:
            yield s

    monkeypatch.setattr(_db, "DB_PATH", db_path)
    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    eng.dispose()


def by_date(rows, day):
    return next(r for r in rows if r["date"] == day)


def test_every_message_links_to_the_case_it_moves(client):
    rows = client.get("/api/messages").json()
    want = {"2026-09-18": ("disruption:SUP-0013", "supplier"), "2026-09-21": ("risk:SUP-0011", "supplier"), "2026-09-17": ("incident:SUP-0018", "part"),
            "2026-09-24": ("disruption:SUP-0001", "part"), "2026-08-14": ("disruption:SUP-0001", "supplier"), "2026-09-22": ("disruption:SUP-0001", "message")}
    assert {d: (by_date(rows, d)["related_item"], by_date(rows, d)["link"]) for d in want} == want
    assert all(r["related_item"] for r in rows)      # every message moves a case
    assert client.get("/api/messages/2026-09-18_Jadepeak_Customer_Notice_CN-2026-09").json()["related_item"] == "disruption:SUP-0013"


def test_a_row_carries_its_owner_short_name_robots_and_the_cases_stage(client):
    rows = client.get("/api/messages").json()
    fire = by_date(rows, "2026-09-22")
    assert fire["supplier_short"] == "Yunzhan" and fire["owner"] == "Dana Reyes" and [r["id"] for r in fire["robots"]] == ["HR-90020", "HR-90050"]
    assert fire["related_stage"]["key"] in ("found", "drafted", "decision_ready")
    held = [r for r in rows if r["trust"] == "suspicious"]
    assert len(held) == 2 and all(r["robots"] == [] for r in held)      # a held message never lights a robot
    assert [r["label"].split()[-1] for r in by_date(rows, "2026-09-09")["robots"]] == ["P5", "H1"]      # names no part: its supplier's open lines


def test_each_change_says_the_quantity_and_ship_date_of_its_delivery(client):
    rl = client.get("/api/messages/2026-09-19_RE_RE_PO_HPO-26-00623_confirmation").json()["changes"]
    got = [(c["ref"]["id"], c["qty"], c["ship"], c["after"]) for c in rl if c["ref"]["type"] == "po_line"]
    assert ("HPO-26-00623/10", 890, "2026-10-09", "2026-10-30") in got
    assert [g for g in got if g[0] == "HPO-26-00623/20"] == [("HPO-26-00623/20", 57, "2026-10-09", "2026-10-30"), ("HPO-26-00623/20", 58, "2026-10-30", "2026-11-20")]      # a split delivery is two rows
    fire = client.get("/api/messages/2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd").json()["changes"]
    assert next(c for c in fire if c["ref"]["id"] == "HPO-26-00450/20")["qty"] == 445


def test_a_look_alike_names_the_domain_it_imitates(client):
    d = client.get("/api/messages/2026-09-23_URGENT_Updated_remittance_details_following_plant_incident").json()
    assert d["summary"]["from_email"].endswith("@yunzhan-rnotor.example") and d["imitates"] == "yunzhan-motor.example"
    assert client.get("/api/messages/2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd").json()["imitates"] is None
