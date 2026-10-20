"""The headline numbers, recomputed blind from data/ and the advisory (docs/design/domain.md), as fixtures."""
import pytest

from app.domain.bom import service as bom
from app.domain.demand import service as demand
from app.domain.orders import service as orders
from app.domain.tariffs import service as tariffs
from dev.probe import measure


def near(got, want, pct=0.5):
    assert got == pytest.approx(want, rel=pct / 100), f"{got:,.0f} is not within {pct}% of {want:,.0f}"


def test_past_due_open_lines(session):
    assert len(orders.past_due(session, include_stale=True)) == 29        # open and promise < 2026-09-25
    assert len(orders.past_due(session)) == 26                            # three stale legacy lines are unknowns, not delays
    assert sorted(l.po_line.id for l in orders.past_due(session, include_stale=True) if l.stale) == ["PO-10710/1", "PO-10711/1", "PO-10788/1"]


def test_hr40110_demand_against_stuck_supply(session):
    reqs = {r.month: float(r.qty.value) for r in demand.requirements(session, "HR-40110")}
    assert (reqs["2026-10"], reqs["2026-11"], reqs["2026-12"]) == (364, 376, 352)
    assert sum(reqs.values()) == 4796                                      # Tern T2 2,398 robots x 2 motors
    supply = orders.open_supply(session, "HR-40110")
    assert [float(s.qty.value) for s in supply] == [355, 435, 350]
    assert all(s.supplier.id == "SUP-0001" and s.disrupted_by for s in supply)
    sh = demand.shortage(session, "HR-40110")
    assert sh.first_short_month == "2026-10" and sh.disrupted
    assert sh.on_hand.owner and "inventory" in sh.on_hand.why_it_blocks


def test_bom_explosion_and_where_used(session):
    q = {r.part.id: float(r.qty_per_robot.value) for r in bom.explode_bom(session, "HR-90020")}
    assert q["HR-40110"] == 2 and q["HR-12110"] == 2 and q["HR-50110"] == 1
    assert {w.product.id for w in bom.where_used(session, "HR-80300")} == {"HR-90020", "HR-90050", "HR-90110"}


def test_tariff_headline_net_first_gross_beside(db_path):
    f = measure(db_path)["facts"]
    near(f["tariff_t1_gross_usd"], 2_135_681)            # open POs + 12-month forecast, every line
    near(f["tariff_t1_net_usd"], 1_432_969)             # OWED: the need not yet on order from the duty date on, plus the burned plant's lines (85,350) that cannot ship before Nov 1
    near(f["tariff_t1_conditional_usd"], 104_142)        # CONDITIONAL: open orders that owe nothing if shipped before Nov 1 and entered before Dec 1 (189,493 before the fire's lines moved to owed)
    near(f["tariff_t1_net_usd:HR-50110"], 501_186)       # 552,072 before the in-transit rule moved 50,886 of it to conditional
    near(f["tariff_t1_net_usd:HR-50210"], 480_373)
    near(f["tariff_t1_net_usd:HR-40110"], 183_187, pct=1)  # the three force-majeure lines (43,473) are owed: the notice puts the restart after Nov 1
    near(f["tariff_t2_gross_usd"], 137_524)            # 147,458 before the DDP (BCX) duty, paid by the supplier, is taken out
    near(f["tariff_t2_net_usd"], 91_593)                # no in-transit relief; only the months from Jan 1 count
    near(f["tariff_t2_conditional_usd"], 2_383)
    near(f["unknown_origin_gross_usd"], 156_561, pct=0.1)
    near(f["unknown_origin_if_china_usd"], 114_575, pct=0.1)   # IF CHINA: shown beside the headline, never in it
    near(f["open_po_duty_usd:HR-40110"], 43_473, pct=0.1)


def test_part_level_exposure_names_every_line(session):
    e = tariffs.exposure_for_part(session, "HR-50110")
    near(float(e.gross.usd), 862_388)
    assert e.rate == 0.25 and e.effective_date == "2026-11-01"
    assert e.net.provenance.method == "computed" and "China-origin" in e.net.provenance.rule and "not yet on order" in e.net.provenance.rule
    assert all(l.why for l in e.open_lines)
    assert any("probably not open" in l.why for l in tariffs.exposure_for_part(session, "HR-40010").open_lines)


def test_unknowns_and_excluded_codes(session):
    assert tariffs.exposure_for_part(session, "HR-40220").status == "unknown_origin"
    assert tariffs.exposure_for_part(session, "HR-40220").unknown.owner
    assert tariffs.tariff_rule_for(session, "HR-20140").status == "excluded"        # coax connectors
    assert tariffs.tariff_rule_for(session, "HR-50310").status == "unknown_hts"      # China origin, no code
    assert tariffs.tariff_rule_for(session, "HR-51120").status == "listed"           # the letter-O code, repaired
    assert tariffs.coo_status(session, "HR-40220").status == "unknown"


def test_probe_counts(db_path):
    c = measure(db_path)["counts"]
    assert (c["po_rows_raw"], c["po_exact_duplicate_rows_dropped"], c["po_lines_open_or_partial"]) == (2622, 6, 185)
    assert (c["po_lines_past_due_raw"], c["po_lines_past_due"]) == (29, 26)
    assert c["force_majeure_open_qty"] == 4892 and c["force_majeure_hr40110_open_qty"] == 1140
    assert c["unknown_origin_on_listed_codes"] == ["HR-13103", "HR-21106", "HR-40220", "HR-40320", "HR-51130"]


def test_ddp_duty_is_a_pass_through_not_halden_s(session):
    for line in ("HPO-26-00591/40", "HPO-26-00490/50"):
        d = tariffs.duty_for_line(session, line)
        assert d.status == "pass_through" and d.importer == "supplier"
    e = tariffs.exposure_for_part(session, "HR-20137")
    assert e.pass_through is not None and float(e.pass_through.usd) > 0
    assert e.net is None or float(e.net.usd) == 0


def test_duty_for_line_cases(session):
    assert tariffs.duty_for_line(session, "HPO-26-00442/10").status == "unknown"        # HR-40220: origin blank
    assert tariffs.duty_for_line(session, "HPO-26-00450/10").status == "owed"           # HR-40110 under force majeure, 08-26
    assert tariffs.duty_for_line(session, "HPO-26-00450/10").importer == "company"
