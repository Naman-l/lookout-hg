"""Build the database once per test session from the committed recipe, exactly as `make build-data` does."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.imports import build

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    out = tmp_path_factory.mktemp("lookout") / "lookout.db"
    assert build.main(["--recipe", str(ROOT / "recipes" / "halden"), "--data", str(ROOT / "data"), "--db", str(out)]) == 0
    return out


@pytest.fixture()
def session(db_path):
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture(scope="session")
def con(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()
