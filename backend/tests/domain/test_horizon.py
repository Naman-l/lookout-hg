"""The data horizon: the same recipe rebuilds the database as it stood on an earlier day, and nothing dated after that day is visible."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
RECIPE = BACKEND.parent / "recipes" / "halden"
HORIZON = "2026-09-17"      # the day before the advisory and the fire notice, five days before the fire notice reached the inbox


@pytest.fixture(scope="module")
def early(tmp_path_factory):
    db = tmp_path_factory.mktemp("horizon") / "early.db"
    env = {**os.environ, "LOOKOUT_AS_OF": HORIZON, "LOOKOUT_DB": str(db)}
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(RECIPE), "--db", str(db)], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-600:] + done.stderr[-600:]
    return db, env


def test_nothing_dated_after_the_horizon_is_in_the_database(early):
    db, _ = early
    con = sqlite3.connect(db)
    one = lambda q: con.execute(q).fetchone()[0]       # noqa: E731
    assert one("select value from build_meta where key='as_of'") == HORIZON
    assert one("select max(date) from messages") <= HORIZON and one("select count(*) from messages") == 9
    assert one("select max(order_date) from po_lines") <= HORIZON
    assert one("select count(*) from po_lines where received_date > ?".replace("?", f"'{HORIZON}'")) == 0
    assert one("select max(date) from news_items") <= HORIZON
    assert one("select count(*) from tariff_rules") == 0 and one("select count(*) from tariff_exclusions") == 0     # the advisory is dated Sep 18
    assert one("select max(month) from fx_rates") <= HORIZON[:7]
    assert one("select count(*) from message_events where kind in ('force_majeure','remittance_change')") == 0


def test_the_action_list_at_the_horizon_is_what_a_buyer_could_have_seen(early):
    db, env = early
    code = ("import json; from app.db import engine; from sqlalchemy.orm import Session; from app.domain.attention import service as a; "
            "from app.domain.common import AS_OF; s = Session(engine); "
            "print(json.dumps([str(AS_OF)] + [i.key for i in a.what_needs_attention(s)]))")
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    as_of, *keys = json.loads(done.stdout.strip().splitlines()[-1])
    assert as_of == HORIZON
    assert "tariff:all" not in keys and not any(k.startswith("disruption:") or k.startswith("trust:2026-09-23") for k in keys)
    assert "deadline:chase" in keys and "deadline:quotes" in keys     # the late lines, and the quotes that lapse in October (Yunzhan's Oct 13 among them: no fire yet to split it out)
