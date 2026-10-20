"""The outside sources a case rests on are served as received and read only: a notice with its full text, a news item with its publisher; a wrong id is a clean 404."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app


@pytest.fixture(scope="module")
def client(db_path):
    mp = pytest.MonkeyPatch()
    mp.setattr(app_db, "DB_PATH", db_path)
    yield TestClient(app, raise_server_exceptions=False)
    mp.undo()


def test_every_source_on_file_answers_by_its_own_id_with_its_text(client):
    rows = client.get("/api/sources").json()
    assert rows and {r["type"] for r in rows} <= {"news", "notice"}
    for r in rows:
        one = client.get(f"/api/sources/{r['type']}/{r['id']}")
        assert one.status_code == 200 and one.json()["id"] == r["id"]
        assert one.json()["text"], f"{r['type']} {r['id']} has no text as received"


def test_a_notice_carries_its_full_text_not_only_the_recipe_summary(client):
    notices = client.get("/api/sources?type=notice").json()
    assert notices
    n = notices[0]
    assert len(n["text"]) > len(n["summary"] or "") and n["summary"] != n["text"]


def test_a_wrong_type_or_id_is_a_clean_4xx_and_nothing_writes(client):
    assert client.get("/api/sources/news/zz-not-an-id").status_code == 404
    assert client.get("/api/sources/zz/zz-not-an-id").status_code == 404
    assert client.get("/api/sources?type=zz").status_code == 422
    assert client.post("/api/sources", json={}).status_code == 405
