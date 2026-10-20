"""LOOKOUT_MODE=hybrid (plan-13 live-mode-check): what has a recording replays, what has none runs live, and only with a key; without a key everything replays."""

import pytest

from app.organism import recordings

REC = {"events": []}


@pytest.fixture()
def env(monkeypatch):
    for k in ("LOOKOUT_MODE", "ANTHROPIC_API_KEY", "LOOKOUT_LIVE"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_hybrid_with_a_key_replays_the_recorded_and_runs_the_rest_live(env):
    env.setenv("LOOKOUT_MODE", "hybrid")
    env.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    assert recordings.live_available() is True
    assert recordings.runs_live(REC) is False and recordings.runs_live(None) is True


def test_hybrid_without_a_key_replays_everything_and_says_the_agent_is_not_live(env):
    env.setenv("LOOKOUT_MODE", "hybrid")
    assert recordings.live_available() is False
    assert recordings.runs_live(REC) is False and recordings.runs_live(None) is False


def test_the_other_modes_are_unchanged(env):
    env.setenv("LOOKOUT_MODE", "recorded")
    env.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    assert recordings.runs_live(None) is False
    env.setenv("LOOKOUT_MODE", "live")
    assert recordings.runs_live(REC) is True
    env.setenv("LOOKOUT_MODE", "auto")
    assert recordings.runs_live(REC) is True      # auto with a key: live, as before


def test_in_hybrid_a_recorded_item_run_replays_even_with_a_key(env, tmp_path):
    env.setenv("LOOKOUT_MODE", "hybrid")
    env.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    doc = recordings.find("disruption:SUP-0001")
    assert doc is not None and recordings.runs_live(doc) is False


def test_run_live_is_refused_plainly_when_no_model_is_connected(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app.main import app

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "a.db")
    env.setenv("LOOKOUT_MODE", "hybrid")
    r = TestClient(app).post("/api/action-items/disruption:SUP-0001/runs", json={"asked_by": "Dana Reyes", "live": True})
    assert r.status_code == 503 and "cannot run live" in r.json()["detail"]
