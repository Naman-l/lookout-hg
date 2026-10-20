import importlib
from pathlib import Path

from app import db


def test_a_relative_database_path_is_relative_to_the_repository_not_to_where_the_command_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOKOUT_DB", "backend/lookout.db")
    monkeypatch.chdir(tmp_path)
    assert db._db_path() == db._ROOT / "backend" / "lookout.db" and db._db_path().is_absolute()
    monkeypatch.setenv("LOOKOUT_DB", str(tmp_path / "x.db"))
    assert db._db_path() == tmp_path / "x.db"
    monkeypatch.setenv("LOOKOUT_DB", "")
    assert db._db_path() == db._ROOT / "backend" / "lookout.db"
