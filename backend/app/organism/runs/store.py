"""Run and run_event persistence. Plain sqlite3 on the run's DB file; the tables are created on first use."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..schemas import RunEvent

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, parent_run_id TEXT, item_key TEXT NOT NULL, workflow TEXT NOT NULL,
  status TEXT NOT NULL, started_at TEXT NOT NULL, model TEXT, prompt_hash TEXT, toolset_hash TEXT,
  sdk_version TEXT, cost_usd REAL, wall_ms INTEGER, first_step_ms INTEGER, turns INTEGER,
  tool_calls INTEGER DEFAULT 0, denied_calls INTEGER DEFAULT 0, asked_by TEXT,
  recommendation_json TEXT, verifier_json TEXT, recorded INTEGER DEFAULT 0, recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY (run_id, seq)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    return con


def insert_run(db_path, **row) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with connect(db_path) as con:
        con.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", list(row.values()))


def update_run(db_path, run_id: str, **row) -> None:
    sets = ", ".join(f"{k} = ?" for k in row)
    with connect(db_path) as con:
        con.execute(f"UPDATE runs SET {sets} WHERE run_id = ?", [*row.values(), run_id])


def last_seq(db_path, run_id: str) -> int:
    """The highest event number a run has stored (0 when none): a recorder that writes more events for an existing run continues from it."""
    with connect(db_path) as con:
        return con.execute("SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id = ?", (run_id,)).fetchone()[0]


def append_event(db_path, event: RunEvent) -> int:
    """Store one event and return its row id: the SSE id, so a client can resume with Last-Event-ID."""
    with connect(db_path) as con:
        cur = con.execute(
            "INSERT INTO run_events (run_id, seq, event_json) VALUES (?, ?, ?)",
            (event.run_id, event.seq, event.model_dump_json()),
        )
        return cur.lastrowid


def read_events(db_path, run_id: str, after_seq: int = 0) -> list[RunEvent]:
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT event_json FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after_seq)
        ).fetchall()
    return [RunEvent.model_validate(json.loads(r[0])) for r in rows]


def read_run(db_path, run_id: str) -> dict | None:
    with connect(db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def read_tree_events(db_path, run_id: str, after_id: int = 0) -> list[tuple[int, RunEvent]]:
    """(row id, event) for the run and its child runs (ids run_id.1, run_id.2 ...), in the order they happened."""
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT rowid, event_json FROM run_events WHERE (run_id = ? OR run_id LIKE ?) AND rowid > ? ORDER BY rowid",
            (run_id, run_id + ".%", after_id),
        ).fetchall()
    return [(r[0], RunEvent.model_validate(json.loads(r[1]))) for r in rows]


def scratch_copy(prefix: str = "lookout-") -> str:
    """A throwaway copy of the built the company database (data plus empty run tables), so a script's runs and drafts never touch the real file."""
    import shutil
    import tempfile
    from pathlib import Path

    from ... import db as app_db

    dest = Path(tempfile.mkdtemp(prefix=prefix)) / "scratch.db"
    if Path(app_db.DB_PATH).exists():
        shutil.copy(app_db.DB_PATH, dest)
    return str(dest)
