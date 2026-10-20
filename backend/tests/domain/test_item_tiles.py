"""Every kind of item carries the numbers its tiles show, each a Money, Quantity or date with provenance."""

from __future__ import annotations

from app.domain.attention import service as attention


def tiles(session, key):
    d = attention.item_detail(session, key)
    assert d is not None, key
    return {n.id: n for n in d.numbers if n.id.startswith("tile:")}


def test_the_tariff_has_owed_if_late_if_china_and_act_by(session):
    t = tiles(session, "tariff:all")
    assert list(t)[:4] == ["tile:owed", "tile:if_late", "tile:if_china", "tile:act_by"]
    assert round(float(t["tile:owed"].value.usd)) == 1_432_969 and round(float(t["tile:if_late"].value.usd)) == 104_142 and round(float(t["tile:if_china"].value.usd)) == 114_575
    assert t["tile:act_by"].value.date == "2026-10-15" and all(n.value.provenance for n in t.values())


def test_the_consignment_has_robots_slip_days_and_the_date_the_board_is_due(session):
    t = tiles(session, "consignment:HR-30110")
    assert float(t["tile:slip_days"].value.value) == 21 and t["tile:pcb_due"].value.date == "2026-10-16"
    robots = {k: float(v.value.value) for k, v in t.items() if k.startswith("tile:robots:")}
    assert robots == {"tile:robots:HR-90020:2026-10": 182.0, "tile:robots:HR-90050:2026-10": 40.0, "tile:robots:HR-90110:2026-10": 22.0}      # per product, in the month the board is due


def test_the_risk_item_has_late_lines_and_the_prepayment_term(session):
    t = tiles(session, "risk:SUP-0002")
    assert float(t["tile:lines_late"].value.value) == 1 and float(t["tile:prepayment"].value.value) == 30 and t["tile:prepayment"].value.uom == "%"
    ids = {n.id for n in attention.item_detail(session, "risk:SUP-0002").numbers}
    assert {"risk_open_value:SUP-0002", "risk_need:HR-12210"} <= ids                       # the open dollars and the sole-source volume


def test_the_unknown_origin_row_has_how_many_what_if_china_and_act_by(session):
    t = tiles(session, "unknown:origin")
    assert float(t["tile:count"].value.value) == 5 and round(float(t["tile:if_china"].value.usd)) > 0
    assert "tile:count" in tiles(session, "unknown:undated") and "tile:if_china" not in tiles(session, "unknown:undated")


def test_the_chase_row_has_lines_dollars_and_the_largest(session):
    ids = {n.id for n in attention.item_detail(session, "deadline:chase").numbers}
    assert {"chase:count", "chase:open_total", "chase:largest"} <= ids
