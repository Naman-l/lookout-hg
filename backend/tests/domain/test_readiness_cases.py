"""A build page names the cases that stand in the way of each part (Robots FINAL §8B): the readiness route gives every part the keys of Today's rows that hold it
(the part named in the row, or one of its PO lines); duty rows and the origin / HTS unknowns are left out, since they change a part's cost, not whether it arrives."""

import pytest
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app


@pytest.fixture(scope="module")
def client(db_path):
    mp = pytest.MonkeyPatch()
    mp.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    mp.setattr(app_db, "DB_PATH", db_path)
    yield TestClient(app)
    mp.undo()


def test_each_readiness_part_names_the_cases_that_hold_it(client):
    body = client.get("/api/builds/HR-90020/2026-10/readiness").json()
    cases = {p["part"]["id"]: p["cases"] for g in body["groups"] for p in g["parts"]}
    assert cases["HR-40110"] == ["disruption:SUP-0001"]                                # the fire; the duty row is left out
    assert cases["HR-51110"] == ["disruption:SUP-0013"]                                # the Jadepeak notice
    assert cases["HR-60110"] == ["risk:SUP-0029", "deadline:chase", "unknown:undated"]  # Today's order
    assert cases["HR-73112"] == ["deadline:SUP-0042:2026-09-28"]
    assert cases["HR-60430"] == []                                                     # late, and no case covers it
    assert not {k for v in cases.values() for k in v} & {"tariff:all", "unknown:origin", "unknown:hts"}
    keys = {i["key"] for i in client.get("/api/action-items").json()}
    assert {k for v in cases.values() for k in v} <= keys                              # every key opens a row on Today
