"""The duty in three buckets: owed, conditional (in transit), if China. One test per branch of the rule that puts a line in a bucket."""

from __future__ import annotations

import pytest

from app.domain.tariffs import service as tariffs


def _line(session, part: str, po_line: str):
    return next(l for l in tariffs.exposure_for_part(session, part).open_lines if l.po_line.id == po_line)


def test_a_line_promised_before_the_duty_date_owes_nothing(session):
    assert _line(session, "HR-50110", "HPO-26-00429/20").bucket == "not_owed"


def test_a_line_inside_the_in_transit_window_is_conditional(session):
    line = _line(session, "HR-50110", "HPO-26-00609/10")           # due Nov 19: owed only if it was exported before Nov 1
    assert line.bucket == "conditional" and "ship date is unknown" in line.why and line.exposed


@pytest.mark.parametrize("part,po_line,words", [
    ("HR-51220", "HPO-26-00683/10", "no promise date"),             # no date at all
])
def test_a_line_with_no_usable_date_is_conditional(session, part, po_line, words):
    line = _line(session, part, po_line)
    assert line.bucket == "conditional" and words in line.why


def test_a_line_under_force_majeure_is_owed_when_the_notice_puts_the_restart_after_the_duty_date(session):
    line = _line(session, "HR-40110", "HPO-26-00450/10")
    assert line.bucket == "owed" and line.exposed
    assert "the supplier cannot ship before Nov 1 (force majeure notice, Sep 22)" in line.why and "earliest restart is Nov 3" in line.why      # read from the notice's event record
    assert line.under_force_majeure.id.startswith("2026-09-22_NOTICE_OF_FORCE_MAJEURE")
    fire = [l for part in ("HR-40110", "HR-40120", "HR-40210") for l in tariffs.exposure_for_part(session, part).open_lines if l.under_force_majeure]
    assert len(fire) == 7 and {l.bucket for l in fire} == {"owed"}                       # every listed line of the burned plant; its brakes are on no tariff code
    assert tariffs.restart_window(session, "SUP-0001") == ("2026-11-03", "2026-11-17", "2026-09-22", line.under_force_majeure.id)


def test_the_same_line_is_conditional_when_the_restart_could_come_before_the_duty_date(db_path, tmp_path):
    """The rule reads the notice, not a constant: a notice that says 2 to 3 weeks leaves the lines' ship date unknown, so they stay conditional."""
    import shutil
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    copy = tmp_path / "early.db"
    shutil.copy(db_path, copy)
    con = sqlite3.connect(copy)
    con.execute("update message_events set detail = replace(detail, '6 to 8 weeks', '2 to 3 weeks') where kind = 'force_majeure' and ref_type = 'supplier'")
    con.commit()
    con.close()
    with Session(create_engine(f"sqlite:///{copy}", future=True)) as s:
        line = _line(s, "HR-40110", "HPO-26-00450/10")
        assert tariffs.restart_window(s, "SUP-0001")[0] == "2026-10-06"
    assert line.bucket == "conditional" and "force majeure" in line.why and line.under_force_majeure is None


def test_a_stale_line_is_out_and_a_ddp_line_is_the_suppliers(session):
    assert _line(session, "HR-40010", next(l.po_line.id for l in tariffs.exposure_for_part(session, "HR-40010").open_lines if "probably not open" in l.why)).bucket == "out"
    ddp = tariffs.exposure_for_part(session, "HR-20137")
    assert {l.bucket for l in ddp.open_lines if l.importer == "supplier"} == {"pass_through"}


def test_the_headline_is_the_need_not_yet_on_order_and_excludes_conditional(session):
    e = tariffs.exposure_for_part(session, "HR-50110")
    assert e.net.usd == e.owed.usd and e.conditional is not None
    assert float(e.owed.usd) == pytest.approx(0.25 * e.uncovered_qty * float(e.reference_price.usd), rel=0.001)   # no open line is owed; the need is
    assert float(e.conditional.usd) == pytest.approx(0.25 * 203_544, rel=0.001)                                   # the one line due Nov 19, at 25%


def test_the_second_tranche_has_no_in_transit_relief_and_counts_only_months_from_the_date(session):
    e = next(x for x in tariffs.all_exposures(session) if x.status == "china_listed" and x.tariff.rule.tranche == 2)
    assert e.tariff.rule.entered_before is None and "ship date" not in e.rule_sentences["conditional"]
    assert "Jan 1" in e.rule_sentences["owed"] and e.uncovered_qty >= 0


def test_an_unknown_origin_gives_only_the_figure_if_china(session):
    e = tariffs.exposure_for_part(session, "HR-40220")
    assert e.status == "unknown_origin" and e.owed is None and e.conditional is None
    assert e.if_china is not None and e.net.usd == e.if_china.usd and "origin is unknown" in e.rule_sentences["if_china"]


def test_the_rule_sentences_are_stable(session):
    s = tariffs.exposure_for_part(session, "HR-50110").rule_sentences
    assert s["owed"] == ("25% of the price of China-origin parts that will enter on or after Nov 1: the need not yet on order, "
                         "open orders due after Nov 30, and open orders of a supplier whose force majeure notice puts its restart after Nov 1.")
    assert s["conditional"] == ("Open orders that owe nothing if the supplier ships them before Nov 1 and they enter before Dec 1; "
                                "the ship date is unknown, ask the supplier.")
    assert s["if_china"] == "Parts whose origin is unknown: what they would owe if they are made in China; ask the supplier for the origin."


def test_the_notice_s_in_transit_window_is_read_from_the_notice(session):
    r = tariffs.tariff_rule_for(session, "HR-50110").rule
    assert (r.exported_before, r.entered_before) == ("2026-11-01", "2026-12-01")
