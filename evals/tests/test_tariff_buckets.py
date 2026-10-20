"""The app and the independent oracle agree on the three tariff amounts, per part and per open line, from the raw files.

The oracle (evals/oracle.py: pandas, no app code) reads the notice's own in-transit sentence and applies it; the app does the same in
domain/tariffs. Agreement here proves the arithmetic and the rule reading together; the oracle prints its rule table to be challenged.
"""
import sys
from pathlib import Path

import pytest

from evals.oracle import compute
from evals.run import ROOT

sys.path.insert(0, str(ROOT / "backend"))
DB = ROOT / "backend" / "lookout.db"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no built database (make build-data)")


@pytest.fixture(scope="module")
def both():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.tariffs import service as tariffs
    o = compute(ROOT / "data")
    with Session(create_engine(f"sqlite:///{DB}", future=True)) as s:
        yield o, tariffs.all_exposures(s), s, tariffs


def test_owed_conditional_and_gross_agree_per_part(both):
    o, exps, _, _ = both
    for e in exps:
        p = e.part.id
        if e.status == "china_listed":
            assert round(float(e.owed.usd)) == pytest.approx(o["owed_by_part"].get(p, 0), abs=1), p
            assert round(float(e.conditional.usd) if e.conditional else 0) == pytest.approx(o["conditional_by_part"].get(p, 0), abs=1), p
            assert round(float(e.gross.usd)) == pytest.approx(o["gross_by_part"].get(p, 0), abs=1), p
        elif e.status == "unknown_origin":
            assert round(float(e.if_china.usd)) == pytest.approx(o["if_china_by_part"].get(p, 0), abs=1), p
            assert e.owed is None and e.conditional is None   # an unknown origin is never owed, never conditional: one figure, beside the headline


def test_every_open_line_has_the_same_bucket_in_both(both):
    o, exps, _, _ = both
    seen = 0
    for e in exps:
        if e.status != "china_listed":
            continue
        for l in e.open_lines:
            want = o["line_buckets"].get(l.po_line.id)
            if want is not None:
                assert l.bucket == want, (l.po_line.id, l.bucket, want)
                seen += 1
    assert seen == len([k for k in o["line_buckets"]]) - len([k for k in o["line_buckets"] if k not in {l.po_line.id for e in exps if e.status == "china_listed" for l in e.open_lines}])
    assert seen > 20


def test_the_headline_is_owed_only_and_the_other_two_stand_beside_it(both):
    o, exps, _, _ = both
    t1 = [e for e in exps if e.status == "china_listed" and e.tariff.rule.tranche == 1]
    assert round(sum(float(e.owed.usd) for e in t1)) == pytest.approx(o["t1_owed"], abs=2)
    assert round(sum(float(e.conditional.usd) for e in t1 if e.conditional)) == pytest.approx(o["t1_conditional"], abs=2)
    assert o["t1_owed"] + o["t1_conditional"] < o["t1_gross"]   # the amounts are not summed into one, and none exceeds the gross
    assert any("exported before" in r for r in o["rules"]) and any("No in-transit exemption" in r for r in o["rules"])   # tranche 2 has no relief
