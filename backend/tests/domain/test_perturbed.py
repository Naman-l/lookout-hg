"""A learning set, not a fixture: the same recipe on data with the facts changed.

The supplier whose plant burns is renamed, the fraud mail asks for a different amount from a different look-alike, a sixth buyer owns
some orders, and the data date moves. The build must pass, every detector must fire on the new values, and nothing of the old month
may leak into what comes out. This is the test that a grep for names cannot replace."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from tests.domain.perturb import BACKEND, FRAUD_AMOUNT, perturb


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """(db path, environment) of a build over perturbed data, a perturbed recipe and a later data date."""
    root = tmp_path_factory.mktemp("perturbed")
    data, recipe = perturb(root)
    # 4. a later data date (the files are the same: only the clock moved)
    db = root / "perturbed.db"
    env = {**os.environ, "LOOKOUT_AS_OF": "2026-10-05", "LOOKOUT_DB": str(db)}
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(recipe), "--data", str(data), "--db", str(db)], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    return db, env


def _keys_and_titles(env):
    code = ("import json; from app.db import engine; from sqlalchemy.orm import Session; from app.domain.attention import service as a; s = Session(engine); "
            "print(json.dumps([[i.key, i.title, i.owner, i.next_action] for i in a.all_items(s)]))")
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_build_passes_and_the_renamed_supplier_is_one_company_under_its_new_name(world):
    db, _ = world
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from supplier_identities").fetchone()[0] == 60
    names = [r[0] for r in con.execute("select name from supplier_records where name like '%arlowe%'")]
    assert len(names) == 3 and not con.execute("select count(*) from supplier_records where lower(name) like '%yunzhan%'").fetchone()[0]


def test_the_fire_is_found_under_the_new_name(world):
    _, env = world
    rows = _keys_and_titles(env)
    fire = next(r for r in rows if r[0].startswith("disruption:") and "fire" in r[1].lower())
    assert fire[1].startswith("Marlowe fire") and "Yunzhan" not in " ".join(sum(rows, []))        # the old name appears nowhere in what the system says


def test_the_fraud_is_blocked_with_the_new_amount_and_the_right_imitation(world):
    db, env = world
    rows = _keys_and_titles(env)
    fraud = next(r for r in rows if r[0].startswith("trust:") and "URGENT" in r[0])
    assert "look-alike Marlowe domain" in fraud[1]
    con = sqlite3.connect(db)
    assert con.execute("select qty from message_events where kind = 'remittance_change'").fetchone()[0] == float(FRAUD_AMOUNT.replace(",", ""))
    assert "187" not in " ".join(r[1] for r in rows)


def test_a_sixth_buyer_owns_orders_and_is_a_person_like_the_rest(world):
    db, _ = world
    con = sqlite3.connect(db)
    assert ("Ravi", "Ravi Okafor") in con.execute("select id, name from buyers").fetchall()
    assert con.execute("select count(*) from po_lines where buyer_id = 'Ravi'").fetchone()[0] > 0
    assert con.execute("select count(*) from parts where buyer_id = 'Ravi'").fetchone()[0] > 0


def test_a_later_data_date_changes_the_clock_and_nothing_else_is_pinned(world):
    db, env = world
    con = sqlite3.connect(db)
    assert con.execute("select value from build_meta where key = 'as_of'").fetchone()[0] == "2026-10-05"
    rows = _keys_and_titles(env)
    revised = next(r for r in rows if "promised revised delivery dates" in r[1])
    assert "Oct 10" in revised[1]                                                          # five days left, not fifteen: the arithmetic follows the date
    code = ("from app.db import engine; from sqlalchemy.orm import Session; from app.domain.attention import service as a; s = Session(engine); "
            "print([i.days_left for i in a.all_items(s) if 'revised delivery dates' in i.title][0])")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True).stdout.strip().splitlines()[-1]
    assert out == "5"


def test_quotes_with_no_record_are_named_not_silently_dropped(world):
    db, _ = world
    con = sqlite3.connect(db)
    row = con.execute("select count, example from data_issues where key = 'quotes.not_extracted'").fetchone()
    assert row is not None and row[0] == 1 and "NEW-QUOTE-1" in row[1]                          # a quote nobody read in is named, not silently dropped
    assert con.execute("select count(*) from offers where message_id like '%NEW-QUOTE-1%'").fetchone()[0] == 0


def test_the_morning_run_follows_the_action_list_of_changed_data(world):
    """No item key is written in the code: on data where the supplier is renamed the morning run takes whatever the list ranks first, trust items left out."""
    db, env = world
    code = ("import json; from app.organism import prepare; "
            "print(json.dumps(prepare.morning_items(None, n=5)))")
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env={**env, "LOOKOUT_FAKE_SERVICES": "0"}, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    picked = json.loads(done.stdout.strip().splitlines()[-1])
    ranked = [k for k, *_ in _keys_and_titles(env) if not k.startswith("trust:")]
    assert picked == ranked[:5] and len(picked) == 5


def test_the_sentences_that_say_the_company_say_the_configured_one(world):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.common.company import company_name
    from app.domain.tariffs import service as tariffs

    db, _ = world
    with Session(create_engine(f"sqlite:///{db}")) as s:
        assert (company_name(s), company_name(s, full=True)) == ("Ashgrove", "Ashgrove Robotics")
        says = {l.incoterm_says for e in tariffs.all_exposures(s) for l in e.open_lines if l.incoterm_says}
    assert any("Ashgrove arranges the shipping" in t for t in says) and not any("Halden" in t for t in says)

