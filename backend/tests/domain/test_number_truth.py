"""Number truth: every figure the screens show is recomputed from the raw files in data/ (never from the database) and must agree. See evals/number_sweep.py;
`make numbers` prints the full report. A wrong number is the one thing a founder stops a demo on."""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evals.number_sweep import Sweep  # noqa: E402


def test_every_figure_the_screens_show_agrees_with_the_raw_files(db_path):
    rows = Sweep(db_path, ROOT / "data").run()
    bad = [r for r in rows if not r.ok]
    assert not bad, "\n".join(f"[{r.group}] {r.name}: shown {r.shown}, raw files give {r.recomputed} ({r.source})" for r in bad)
    groups = {r.group for r in rows}
    assert len(rows) >= 1500 and {"counts", "suppliers", "today", "tariff", "readiness", "inbox", "dates", "orders", "trust", "risk", "parts", "forecast"} <= groups      # the sweep is wide, not a few spot checks


def test_the_sweep_goes_red_when_a_number_is_wrong(db_path, tmp_path):
    """A sweep that cannot fail proves nothing: corrupt an open value, an offer price and a forecast, and it must say so."""
    copy = tmp_path / "wrong.db"
    shutil.copy(db_path, copy)
    con = sqlite3.connect(copy)
    con.execute("update po_lines set open_usd = open_usd + 1000 where id = 'HPO-26-00450/10'")
    con.execute("update offers set unit_price_each = unit_price_each * 2 where id = 5")
    con.execute("update demand_forecast set units = units + 1 where month = '2026-10' and product_part = 'HR-90020'")
    con.commit()
    con.close()
    bad = [r for r in Sweep(copy, ROOT / "data").run() if not r.ok]
    names = " | ".join(r.name for r in bad)
    assert len(bad) >= 8 and "open value" in names and "tariff: owed" in names and "robots planned" in names and "offer 5" in names
