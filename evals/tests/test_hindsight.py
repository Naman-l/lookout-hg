import tempfile
from pathlib import Path

import pytest

from evals import hindsight
from evals.run import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "data").exists(), reason="no data")


def test_the_list_flags_things_the_day_they_arrive_and_never_before_and_the_check_can_fail():
    """The early cuts assert that the fire and the slip items are ABSENT (not that the disruption group is empty): a sole source's insolvency report of 09-10 is a
    legitimate earlier item (risk:SUP-0002), and it must show on the day it can be read."""
    with tempfile.TemporaryDirectory() as w:
        w = Path(w)
        ok = hindsight.run_cut({"as_of": "2026-09-17", "why": "t", "show": ["trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today"], "hide_groups": ["tariff"], "hide": ["disruption:SUP-0001", "disruption:SUP-0013"]}, w)
        assert ok["ok"], ok["problems"]
        # the same cut with the expectations reversed must fail: the grader can go red
        bad = hindsight.run_cut({"as_of": "2026-09-17", "why": "t", "show": ["disruption:SUP-0001"], "hide": ["trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today"]}, w)
        assert not bad["ok"] and any("missing on" in p for p in bad["problems"]) and any("shows before" in p for p in bad["problems"])


def test_a_database_carrying_the_future_is_caught(tmp_path):
    full = ROOT / "backend" / "lookout.db"
    if not full.exists():
        pytest.skip("no built database")
    assert hindsight.leaks(full, "2026-09-17"), "the full month's records must read as leaking when judged as of 09-17"
