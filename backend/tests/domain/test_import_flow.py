"""The Import conversation: questions from the recipe's own decisions, answers, a dry run, an approval that loads."""
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from app.domain.imports import flow
from app.domain.imports.schema import ImportAnswer, ImportAnswers, ImportApproval

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def space(tmp_path, monkeypatch):
    recipe = tmp_path / "halden"
    shutil.copytree(ROOT / "recipes" / "halden", recipe, ignore=shutil.ignore_patterns("__pycache__", "decisions.yaml"))
    db = tmp_path / "lookout.db"
    import app.db

    monkeypatch.setattr(app.db, "DB_PATH", db)
    monkeypatch.setattr(flow, "RECIPE_DIR", recipe)
    flow._baseline.cache_clear()
    yield recipe, db
    flow._baseline.cache_clear()


def say(by, **answers):
    return ImportAnswers(answered_by=by, answers=[ImportAnswer(question_id=k.replace("__", ":").replace("_", "-"), action=a if isinstance(a, str) else a[0], value=None if isinstance(a, str) else a[1]) for k, a in answers.items()])


def test_the_deck_is_short_and_code_driven(space):
    d = flow.deck()
    assert [(q.id, q.covers) for q in d.questions] == [("alias:legacy-ids", 10), ("alias:rename", 1), ("currency:blank", 9), ("origin:unknown-on-listed-codes", 5),
                                                      ("duplicate-row:po", 6), ("possible-duplicate:parts", 3), ("stock:count", 335)]
    assert all(q.state == "open" and 1 <= len(q.examples) <= 3 and q.proposed.answer and q.proposed.effect and len(q.entries) == q.covers for q in d.questions)
    assert {q.kind for q in d.questions} == {"alias", "currency", "origin", "duplicate_row", "possible_duplicate", "stock_count"}
    ex = next(q for q in d.questions if q.id == "alias:legacy-ids").examples[0]
    assert ex.from_.startswith("V1") and ex.to.startswith("SUP-")


def test_answers_are_kept_with_who_and_when(space):
    d = flow.answer(ImportAnswers(answered_by="Khalid", answers=[ImportAnswer(question_id="currency:blank", action="accept"),
                                                                ImportAnswer(question_id="duplicate-row:po", action="skip"),
                                                                ImportAnswer(question_id="origin:unknown-on-listed-codes", action="change", value="HR-40220=CN")]))
    s = {q.id: q for q in d.questions}
    assert (s["currency:blank"].state, s["duplicate-row:po"].state, s["origin:unknown-on-listed-codes"].state) == ("accepted", "skipped", "changed")
    assert s["origin:unknown-on-listed-codes"].answer == "HR-40220=CN" and s["currency:blank"].answered_by == "Khalid" and s["currency:blank"].answered_at
    assert s["alias:rename"].state == "open"
    with pytest.raises(KeyError):
        flow.answer(ImportAnswers(answered_by="K", answers=[ImportAnswer(question_id="nope", action="accept")]))
    with pytest.raises(ValueError):
        flow.answer(ImportAnswers(answered_by="K", answers=[ImportAnswer(question_id="alias:rename", action="change")]))


def test_dry_run_shows_before_after_and_every_check(space):
    run = flow.dry_run()
    f = {x.file: x for x in run.files}
    assert (f["purchase_orders.csv"].rows_in, f["purchase_orders.csv"].rows_out) == (2622, 2616) and (f["suppliers.csv"].rows_in, f["suppliers.csv"].rows_out) == (71, 71)
    assert any("repeated exactly" in c for c in f["purchase_orders.csv"].changes)
    assert len(run.checks) >= 30 and all(c.passed for c in run.checks) and run.recipe_steps == 26 and run.answers.total == 7
    h = run.hash
    flow.answer(say("Khalid", duplicate_row__po="skip"))
    run2 = flow.dry_run()
    assert run2.hash != h and run2.answers.skipped == 1 and {x.file: x for x in run2.files}["purchase_orders.csv"].rows_out == 2622       # the repeats stay
    assert all(c.passed for c in run2.checks)


def test_approve_is_refused_when_the_answers_changed_since_the_dry_run(space):
    h = flow.dry_run().hash
    flow.answer(say("Khalid", currency__blank="skip"))
    with pytest.raises(flow.AnswersChanged):
        flow.approve(ImportApproval(hash=h, approved_by="Khalid"))


def test_approve_writes_the_answers_into_the_recipe_and_loads(space):
    recipe, db = space
    flow.answer(ImportAnswers(answered_by="Dana", answers=[ImportAnswer(question_id="origin:unknown-on-listed-codes", action="change", value="HR-40220=CN,HR-13103=TW"),
                                                         ImportAnswer(question_id="currency:blank", action="skip")]))
    out = flow.approve(ImportApproval(hash=flow.dry_run().hash, approved_by="Khalid"))
    assert out.loaded and db.exists() and not db.with_name(db.name + ".pending").exists()
    assert not (recipe / "decisions.yaml").exists()                  # the recipe stays as committed
    saved = yaml.safe_load(db.with_name("decisions.yaml").read_text())["decisions"]      # the approved answers live beside the database
    assert saved["origin:unknown-on-listed-codes"]["by"] == "Dana" and saved["origin:unknown-on-listed-codes"]["approved_by"] == "Khalid" and saved["currency:blank"]["at"]
    c = sqlite3.connect(db)
    assert c.execute("select coo, coo_method from parts where part_number='HR-40220'").fetchone() == ("CN", "answered")
    assert c.execute("select coo, coo_method from parts where part_number='HR-13103'").fetchone() == ("TW", "answered")
    assert c.execute("select count(*) from po_lines where currency_method='unknown'").fetchone()[0] == 9
    assert c.execute("select count(*) from po_lines where currency_method='inferred'").fetchone()[0] == 0
    assert c.execute('select count(*) from load_gate where passed=0').fetchone()[0] == 0
    d = flow.deck()
    assert {q.id: q.state for q in d.questions}["currency:blank"] == "skipped"           # the recipe now carries the answer: a rebuild gives the same database


def test_each_answer_changes_the_data_it_names(space):
    recipe, db = space
    flow.answer(say("K", alias__legacy_ids="skip", alias__rename="skip", possible_duplicate__parts="skip"))
    flow.approve(ImportApproval(hash=flow.dry_run().hash, approved_by="K"))
    c = sqlite3.connect(db)
    assert c.execute("select count(*) from supplier_identities").fetchone()[0] == 71            # nothing linked: every record is its own company
    assert c.execute("select count(*) from supplier_records").fetchone()[0] == 71               # and no record was lost
    assert c.execute("select count(*) from part_links").fetchone()[0] == 0
    assert c.execute("select count(*) from data_issues where key='parts.duplicate_parts'").fetchone()[0] == 1       # the defect is still reported


# --- the routes ---
@pytest.fixture()
def client(space):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.domain.imports.api import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_import_routes_walk_the_whole_conversation(client, space):
    recipe, db = space
    deck = client.get("/api/imports/questions").json()
    assert deck["import_id"].startswith("halden-") and len(deck["questions"]) == 7 and "from" in deck["questions"][0]["examples"][0]
    r = client.post("/api/imports/answers", json={"answered_by": "Khalid", "answers": [{"question_id": q["id"], "action": "accept"} for q in deck["questions"]]})
    assert r.status_code == 200 and {q["state"] for q in r.json()["questions"]} == {"accepted"}
    assert client.post("/api/imports/answers", json={"answered_by": "K", "answers": [{"question_id": "nope", "action": "accept"}]}).status_code == 404
    assert client.post("/api/imports/answers", json={"answered_by": "K", "answers": [{"question_id": "alias:rename", "action": "change"}]}).status_code == 422
    run = client.get("/api/imports/dry-run").json()
    assert run["answers"] == {"total": 7, "changed": 0, "skipped": 0} and all(c["passed"] for c in run["checks"]) and run["hash"]
    client.post("/api/imports/answers", json={"answered_by": "Khalid", "answers": [{"question_id": "currency:blank", "action": "skip"}]})
    assert client.post("/api/imports/approve", json={"hash": run["hash"], "approved_by": "Khalid"}).status_code == 409        # the answers changed since that dry run
    run = client.get("/api/imports/dry-run").json()
    ok = client.post("/api/imports/approve", json={"hash": run["hash"], "approved_by": "Khalid"})
    assert ok.status_code == 200 and ok.json()["loaded"] and db.exists()


def test_a_stock_count_turns_unknown_into_covered_or_short(space):
    recipe, db = space
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.phases import service

    def readiness():
        eng = create_engine(f"sqlite:///{db}", future=True)
        with Session(eng) as s:
            b = service.build_readiness(s, "HR-90020", "2026-10")
        eng.dispose()
        return b

    flow.answer(say("Khalid", stock__count=("change", "HR-11103=40000\nHR-71110=1; HR-99999=5; HR-71113=lots; nonsense")))
    run = flow.dry_run()
    assert all(c.passed for c in run.checks)
    flow.approve(ImportApproval(hash=run.hash, approved_by="Khalid"))
    b = readiness()
    st = {p.part.id: p for g in b.groups for p in g.parts}
    assert st["HR-11103"].state == "in_stock" and st["HR-71110"].state == "short_after_stock" and st["HR-71110"].on_hand.value == 1
    assert st["HR-71113"].state == "no_order"                                            # a count that did not read leaves the part unknown, not zero
    assert b.counts["no_order"] == 78 and b.counts["in_stock"] == 1 and b.counts["short_after_stock"] == 1 and b.stock_counted == 2
    c = sqlite3.connect(db)
    assert c.execute("select counted_by from stock_counts where part_number='HR-11103'").fetchone() == ("Khalid",)
    issues = dict(c.execute("select key, count from data_issues where key like 'stock.%'").fetchall())
    assert issues == {"stock.part_unknown": 1, "stock.pair_not_read": 2}


def test_what_a_person_approved_survives_a_rebuild_but_never_enters_the_committed_recipe(space, tmp_path):
    """The Import screen writes beside the database: the committed recipe is unchanged (so the eval gate, which reads the recipe only, is unaffected), and a rebuild next to that database applies the answers."""
    recipe, db = space
    flow.answer(ImportAnswers(answered_by="Dana", answers=[ImportAnswer(question_id="origin:unknown-on-listed-codes", action="change", value="HR-40220=CN,HR-13103=TW")]))
    flow.approve(ImportApproval(hash=flow.dry_run().hash, approved_by="Khalid"))
    assert not (ROOT / "recipes" / "halden" / "decisions.yaml").exists() and not (recipe / "decisions.yaml").exists()
    kept = db.with_name("decisions.yaml")
    assert kept.exists()
    rebuilt_here = tmp_path / "elsewhere"
    rebuilt_here.mkdir()
    from app.domain.imports import build

    assert build.main(["--recipe", str(recipe), "--data", str(flow.DATA_DIR), "--db", str(rebuilt_here / "lookout.db")]) == 0        # another directory: only the committed recipe
    assert sqlite3.connect(rebuilt_here / "lookout.db").execute("select coo_method from parts where part_number='HR-40220'").fetchone()[0] != "answered"
    assert build.main(["--recipe", str(recipe), "--data", str(flow.DATA_DIR), "--db", str(db)]) == 0                                # beside the database: the answers apply
    assert sqlite3.connect(db).execute("select coo, coo_method from parts where part_number='HR-40220'").fetchone() == ("CN", "answered")
