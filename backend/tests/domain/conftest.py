"""Build the database once per test session from the committed HG recipe, exactly as `make build-data` does."""

import sqlite3
from pathlib import Path

import pytest

from app.domain.imports import build

ROOT = Path(__file__).resolve().parents[3]
RECIPE = ROOT / "recipes" / "hg"
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    out = tmp_path_factory.mktemp("lookout") / "lookout.db"
    assert build.main(["--recipe", str(RECIPE), "--data", str(DATA), "--db", str(out)]) == 0
    return out


@pytest.fixture(scope="session")
def con(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture(scope="session")
def one(con):
    """The first value of a query: one("select count(*) from po_lines")."""
    return lambda sql, *args: con.execute(sql, args).fetchone()[0]


@pytest.fixture(scope="session")
def issues(con):
    return {r["key"]: dict(r) for r in con.execute("select * from data_issues")}
