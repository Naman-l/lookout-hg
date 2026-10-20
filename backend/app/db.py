"""SQLite session factory. The file is built by `make build-data` (app.data.build)."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_ROOT = Path(__file__).resolve().parents[2]
def _db_path() -> Path:
    """LOOKOUT_DB, or backend/lookout.db. A relative path is relative to the repository root (the .env sits there), not to the folder a command happens to run in."""
    p = Path(os.environ.get("LOOKOUT_DB") or _ROOT / "backend" / "lookout.db")
    return p if p.is_absolute() else _ROOT / p


DB_PATH = _db_path()

engine = create_engine(f"sqlite:///{DB_PATH}", future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_session():
    """FastAPI dependency."""
    with SessionLocal() as session:
        yield session
