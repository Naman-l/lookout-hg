"""The fire on the real wiring and the real model. Skipped unless LOOKOUT_LIVE=1 (it costs about 0.06 USD)."""

import os

import pytest

from app.domain.actions import ledger
from app.organism.workflows.work_item import run_workflow

pytestmark = pytest.mark.skipif(os.environ.get("LOOKOUT_LIVE") != "1", reason="set LOOKOUT_LIVE=1 to call the model")


async def test_the_fire_is_verified_staged_and_sends_nothing(db):
    result = await run_workflow("disruption:SUP-0001", db_path=db)
    assert result.status == "ok"
    ctx = result.ctx
    lookout_denied = [e for e in ctx.recorder.events if e.type == "tool.called" and e.agent == "lookout" and e.payload.get("gate") == "denied"]
    assert lookout_denied == []  # Lookout only reads the item and delegates
    drafts = ledger.list_actions(db)
    assert len(drafts) == 1 and drafts[0].state == "proposed" and drafts[0].recipient == "li.wei@yunzhan-motor.example"
    assert ledger.outbox(db) == []
    assert result.first_step_ms < 2000 and result.wall_ms < 30000
