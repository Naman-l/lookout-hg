import os

os.environ.setdefault("LOOKOUT_FAKE_SERVICES", "1")  # unit tests never need the Halden database

import pytest  # noqa: E402

from app.organism.dev import fakes  # noqa: E402
from app.organism.context import RunContext  # noqa: E402
from app.organism.runner import allow_map  # noqa: E402
from app.organism.runs.events import Recorder  # noqa: E402

PLAN = ["supply_planner", "buyers_clerk"]


def _main_db_counts():
    import sqlite3  # noqa: PLC0415

    from app import db as app_db  # noqa: PLC0415

    if not app_db.DB_PATH.exists():
        return {"runs": 0, "actions": 0}
    con = sqlite3.connect(f"file:{app_db.DB_PATH}?mode=ro", uri=True)
    try:
        return {t: (con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (t,)).fetchone() else 0) for t in ("runs", "actions")}  # no table is no rows
    finally:
        con.close()


@pytest.fixture(scope="session", autouse=True)
def the_main_database_is_left_as_it_was():
    """No test may leave runs or actions in the real database: a test that does changes what every later run, gate and screenshot sees."""
    before = _main_db_counts()
    yield
    assert _main_db_counts() == before, "a test wrote runs or actions to the main database; give it a temporary one (monkeypatch app.db.DB_PATH)"


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def ctx(db):
    return RunContext(run_id="run-t", item_key="disruption:SUP-0001", db_path=db, recorder=Recorder("run-t", db), plan=list(PLAN), allow=allow_map(PLAN))


@pytest.fixture
def services():
    return fakes


def seed_buyers(db_path) -> None:
    """The buyers table the approval check reads; a test database has none until this runs."""
    import sqlite3  # noqa: PLC0415

    with sqlite3.connect(str(db_path)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS buyers (id TEXT PRIMARY KEY, name TEXT, initials TEXT)")
        con.execute("INSERT OR IGNORE INTO buyers VALUES ('Dana', 'Dana Reyes', 'DR'), ('Marcus', 'Marcus Chen', 'MC')")


@pytest.fixture(autouse=True)
def the_recipes_id_shapes(monkeypatch):
    """The id shapes are the recipe's (`id_shapes` in recipes/halden/answers.yaml), read from the build in the app; a unit test has no build, so it reads the recipe itself."""
    from pathlib import Path

    import yaml

    from app.organism import id_shapes

    shapes = yaml.safe_load((Path(__file__).resolve().parents[3] / "recipes" / "halden" / "answers.yaml").read_text())["id_shapes"]
    monkeypatch.setattr(id_shapes, "_read", lambda db_path: shapes)
