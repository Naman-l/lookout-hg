"""GET /api/health says who the customer is, from the build's configuration, so the screens never hard-code the brand."""
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app


def test_health_without_a_build_says_the_company(tmp_path, monkeypatch):
    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "none.db")
    monkeypatch.delenv("LOOKOUT_COMPANY", raising=False)
    body = TestClient(app).get("/api/health").json()
    assert body["company"] == "the company" and body["company_short"] == "the company"
