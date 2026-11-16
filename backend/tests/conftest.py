"""Tests skipped until their phase re-points them at the HG build, one reason per file (mirrored in docs/hg/NOTES.md).

They test platform code (the ledger, the agents, the verifier, trust) on Halden fixtures: Halden ids, Halden buyers and the Halden developer
stand-ins in `app/organism/dev`, which were removed with the rest of the Halden code. Nothing here is deleted; each file returns when its phase
rewrites its fixtures on HG data. A test file that is neither collected nor listed here fails the check below, so nothing is skipped silently.
"""

from pathlib import Path

HERE = Path(__file__).parent

SKIPPED: dict[str, str] = {}      # none since Phase 4: the Halden-era organism and count tests were replaced by tests/hg (docs/hg/NOTES.md)

collect_ignore = list(SKIPPED)



import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def built_db(tmp_path_factory):
    """The HG database built once per session from data/ by the committed recipe, exactly as `make build-data` does."""
    from app.domain.imports import build  # noqa: PLC0415

    out = tmp_path_factory.mktemp("hg") / "lookout.db"
    assert build.main(["--recipe", str(_ROOT / "recipes" / "hg"), "--data", str(_ROOT / "data"), "--db", str(out)]) == 0
    return out


@pytest.fixture
def fresh_db(built_db, tmp_path, monkeypatch):
    """A copy of the built database for one test that writes (the ledger, runs, replies), with the app pointed at it."""
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session, sessionmaker  # noqa: PLC0415

    import app.db as appdb  # noqa: PLC0415

    db = tmp_path / "lookout.db"
    shutil.copy(built_db, db)
    eng = create_engine(f"sqlite:///{db}", future=True, connect_args={"check_same_thread": False})
    monkeypatch.setattr(appdb, "DB_PATH", db)
    monkeypatch.setattr(appdb, "engine", eng)
    monkeypatch.setattr(appdb, "SessionLocal", sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, class_=Session))
    yield db
    eng.dispose()
