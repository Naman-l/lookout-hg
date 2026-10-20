"""GET /api/health says who the customer is, from the build's configuration, so the screens never hard-code the brand."""
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app


def test_health_carries_the_company_from_the_build(db_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", db_path)
    body = TestClient(app).get("/api/health").json()
    assert body["ok"] is True and body["company"] == "Halden Robotics" and body["company_short"] == "Halden"


def test_health_gives_the_id_patterns_from_the_recipe(db_path, monkeypatch):
    import re

    monkeypatch.setattr(app_db, "DB_PATH", db_path)
    p = TestClient(app).get("/api/health").json()["id_patterns"]
    assert re.fullmatch(p["part"], "HR-51110") and re.fullmatch(p["supplier"], "SUP-0001") and re.fullmatch(p["po_line"], "HPO-26-00450/10") and re.fullmatch(p["po_number"], "PO-10531")
    assert p["legacy_supplier"] and not re.fullmatch(p["part"], "HPO-26-00450")
