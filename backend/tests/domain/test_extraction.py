"""Quote extraction: records that cite their line, checked in code on every build; a model proposes records, a person releases them."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

from app.domain.imports import extraction

BACKEND = Path(__file__).resolve().parents[2]
RECIPE = BACKEND.parent / "recipes" / "halden"
DATA = BACKEND.parent / "data"
SPOT = "2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today"
GREAT_PLAINS = "2026-09-09_Price_adjustment_notice_-_aluminum_extrusions_effective_November_1_2026"


def _build(recipe: Path, db: Path):
    return subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(recipe), "--db", str(db)], cwd=BACKEND, capture_output=True, text=True)


def _recipe_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "halden"
    shutil.copytree(RECIPE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def test_verify_accepts_a_price_on_its_line_next_to_its_part():
    lines = ["Item Part Price", "HR-1 widget", "9.99"]
    assert extraction.verify({"line": "9.99", "price_raw": "9.99", "part_number": "HR-1"}, lines) is None
    assert extraction.verify({"line": "9.99", "price_raw": "9.99", "part_number": "HR-1"}, lines, "") is None


def test_verify_names_what_is_wrong():
    lines = ["HR-1 widget", "9.99"]
    assert "not in the document" in extraction.verify({"line": "8.88", "price_raw": "8.88"}, lines)
    assert "not on its cited line" in extraction.verify({"line": "9.99", "price_raw": "8.88"}, lines)
    assert "HR-2" in extraction.verify({"line": "9.99", "price_raw": "9.99", "part_number": "HR-2"}, lines)
    assert extraction.verify({"line": "9.99", "price_raw": "9.99", "part_number": "HR-2"}, lines, "Quote for HR-2") is None      # the subject counts for an email


def test_the_build_replays_the_records_and_reproduces_the_offers(tmp_path):
    db = tmp_path / "a.db"
    done = _build(RECIPE, db)
    assert done.returncode == 0, done.stdout[-300:] + done.stderr[-300:]
    con = sqlite3.connect(db)
    assert con.execute("select count(*), count(distinct message_id) from offers").fetchone() == (51, 9)
    assert con.execute("select price_raw, (select price_raw from offers o2 where o2.id = o.superseded_by) from offers o where superseded_by is not null").fetchall() == [("138.36", "183.36")]
    assert abs(con.execute("select unit_price_each from offers where price_raw = 'per 1,000 240.58'").fetchone()[0] - 0.24058) < 1e-9         # per 1,000, divided in code


def test_a_changed_price_stops_the_build_and_names_the_line(tmp_path):
    recipe = _recipe_copy(tmp_path)
    f = recipe / "extractions" / f"{SPOT}.yaml"
    f.write_text(f.read_text().replace("price_raw: '38.50'", "price_raw: '3.85'"))
    done = _build(recipe, tmp_path / "b.db")
    assert done.returncode != 0 and f"{SPOT}.yaml" in done.stderr and "not on its cited line" in done.stderr


def test_the_extractor_writes_what_passes_and_lists_what_does_not_and_the_build_waits_for_a_person(tmp_path):
    recipe = _recipe_copy(tmp_path)
    db = tmp_path / "c.db"
    assert _build(recipe, db).returncode == 0
    subject, body = sqlite3.connect(db).execute("select subject, body from messages where id = ?", (GREAT_PLAINS,)).fetchone()
    figure_line = next(l.strip() for l in body.splitlines() if "+8.5%" in l)
    reply = "```json\n" + json.dumps([
        {"line": figure_line, "price_raw": "8.5%", "price": 8.5, "conditions": "from the notice", "validity_date": "2026-11-01"},
        {"line": figure_line, "price_raw": "8.5%", "price": 8.5, "supplier_name": "A Supplier Nobody Wrote"},
        {"line": "a line the model made up", "price_raw": "1.00", "price": 1.0},
    ]) + "\n```"
    path = extraction.extract(GREAT_PLAINS, subject, body, DATA, recipe / "extractions", ask=lambda _: reply, model="test-model")
    doc = yaml.safe_load(path.read_text())
    assert doc["by"] == "model" and doc["reviewed"] is False and len(doc["offers"]) == 1 and len(doc["rejected"]) == 2
    assert "not in the document" in doc["rejected"][0]["reason"] or "not in the document" in doc["rejected"][1]["reason"]
    assert any("supplier name" in r["reason"] for r in doc["rejected"])      # a name the model typed that the document does not hold
    try:
        extraction.extract(GREAT_PLAINS, subject, body, DATA, recipe / "extractions", ask=lambda _: reply)
        raise AssertionError("an existing record must not be overwritten")
    except FileExistsError:
        pass
    assert _build(recipe, db).returncode == 0
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from offers").fetchone()[0] == 51                                       # not loaded until reviewed
    assert con.execute("select count from data_issues where key = 'quotes.extraction_awaiting_review'").fetchone()[0] == 1
    path.write_text(path.read_text().replace("reviewed: false", "reviewed: true"))
    assert _build(recipe, db).returncode == 0
    assert sqlite3.connect(db).execute("select count(*) from offers").fetchone()[0] == 52                       # a person released it


def test_an_alternative_site_that_cites_a_line_not_in_the_email_stops_the_build(tmp_path):
    recipe = _recipe_copy(tmp_path)
    f = next((recipe / "extractions").glob("2026-09-02_Baycrest*.yaml"))
    f.write_text(f.read_text().replace("production for the charging contacts", "production for the charging pins"))      # the cited line no longer matches the mail
    done = _build(recipe, tmp_path / "c.db")
    assert done.returncode != 0 and "the alternative site is not on the lines it cites" in done.stderr
