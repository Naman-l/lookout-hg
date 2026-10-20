"""The Import conversation on data it was not written for: the renamed supplier, a sixth buyer, a quote nobody read in.

Questions come from the recipe's own decisions, answers wait for a person, the dry run shows every check, approval rebuilds, and what the
cards say is generated from the data: the old month's names must not reappear anywhere in them."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.domain.imports import flow
from app.domain.imports.schema import ImportAnswer, ImportAnswers, ImportApproval
from tests.domain.perturb import ROOT, perturb


@pytest.fixture()
def space(tmp_path, monkeypatch):
    data, recipe = perturb(tmp_path / "world")
    decisions = recipe / "decisions.yaml"
    decisions.unlink(missing_ok=True)
    db = tmp_path / "lookout.db"
    import app.db

    monkeypatch.setattr(app.db, "DB_PATH", db)
    monkeypatch.setattr(flow, "RECIPE_DIR", recipe)
    monkeypatch.setattr(flow, "DATA_DIR", data)
    monkeypatch.setattr("app.domain.common.AS_OF", date(2026, 9, 25))
    flow._baseline.cache_clear()
    yield recipe, db
    flow._baseline.cache_clear()


def test_the_cards_are_written_from_the_changed_data(space):
    d = flow.deck()
    text = d.model_dump_json()
    assert "Marlowe" in text and "Yunzhan" not in text and "yunzhan" not in text         # the company with the most records is named as the data now names it
    cards = {q.id: q for q in d.questions}
    assert cards["alias:legacy-ids"].covers == 10 and "Marlowe" in cards["alias:legacy-ids"].proposed.effect
    assert cards["alias:rename"].covers == 1 and "BCX" in cards["alias:rename"].examples[0].from_


def test_an_answer_dry_run_and_approval_rebuild_the_database_on_changed_data(space):
    recipe, db = space
    flow.answer(ImportAnswers(answered_by="Ravi", answers=[ImportAnswer(question_id="origin:unknown-on-listed-codes", action="change", value="HR-40220=CN"),
                                                         ImportAnswer(question_id="currency:blank", action="accept")]))
    run = flow.dry_run()
    assert run.hash and len(run.checks) >= 30 and all(c.passed for c in run.checks)
    out = flow.approve(ImportApproval(hash=run.hash, approved_by="Khalid"))
    assert out.loaded and db.exists()
    c = sqlite3.connect(db)
    assert c.execute("select coo, coo_method from parts where part_number = 'HR-40220'").fetchone() == ("CN", "answered")
    assert c.execute("select count(*) from po_lines where buyer_id = 'Ravi'").fetchone()[0] > 0 and c.execute("select count(*) from load_gate where passed = 0").fetchone()[0] == 0
    assert c.execute("select count(*) from supplier_records where lower(name) like '%yunzhan%'").fetchone()[0] == 0


def test_an_approval_after_the_answers_moved_is_refused_on_changed_data_too(space):
    h = flow.dry_run().hash
    flow.answer(ImportAnswers(answered_by="Ravi", answers=[ImportAnswer(question_id="currency:blank", action="skip")]))
    with pytest.raises(flow.AnswersChanged):
        flow.approve(ImportApproval(hash=h, approved_by="Khalid"))


def test_the_flow_wrote_only_inside_the_copy(space):
    recipe, db = space
    flow.answer(ImportAnswers(answered_by="Ravi", answers=[ImportAnswer(question_id="currency:blank", action="skip")]))
    flow.approve(ImportApproval(hash=flow.dry_run().hash, approved_by="Khalid"))
    assert db.with_name("decisions.yaml").exists() and not (recipe / "decisions.yaml").exists() and not (ROOT / "recipes" / "halden" / "decisions.yaml").exists()       # the answers went beside the database, never into any recipe
