"""HG behaviour tests: a session bound to the built database, and an API client pointed at a fresh copy for tests that write."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def session(built_db):
    eng = create_engine(f"sqlite:///{built_db}", future=True)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture
def client(fresh_db, monkeypatch):
    monkeypatch.setenv("LOOKOUT_MORNING", "0")
    monkeypatch.setenv("LOOKOUT_PACE", "0")
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.organism import coderun

    monkeypatch.setattr(coderun, "PACE", 0)
    import app.db as appdb

    def _session():
        with appdb.SessionLocal() as s:
            yield s
    app.dependency_overrides[get_session] = _session
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
