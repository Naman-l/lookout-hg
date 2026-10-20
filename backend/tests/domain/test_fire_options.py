"""The ways through the Yunzhan-shaped disruption as data: four options, each with fields, none with prose, every number from a record."""

from __future__ import annotations

import pytest

from app.domain.attention import options, service as attention
from app.domain.orders.model import ReferencePrice
from app.domain.quotes import service as quotes

KEY = "disruption:SUP-0001"


@pytest.fixture()
def opts(session):
    return {o.kind: o for o in options.fire_options(session, KEY)}


def test_four_options_each_with_the_unknown_that_decides_it(opts):
    assert list(opts) == ["allocation", "air_freight", "resequence", "second_source"]
    for o in opts.values():
        assert o.decided_by.owner and o.decided_by.question and o.label


def test_allocation_starts_at_the_suppliers_own_promise(opts):
    o = opts["allocation"]
    assert o.earliest.date == "2026-10-10" and "promise" in o.earliest_basis and o.earliest.provenance.inputs and o.cost_unknowns


def test_air_freight_prices_the_duty_that_shipping_in_time_avoids_and_leaves_freight_unknown(session, opts):
    o = opts["air_freight"]
    assert o.earliest is None and "no stock or shipping date" in o.earliest_basis
    assert float(o.duty_effect.usd) == pytest.approx(85_350, rel=0.001)                    # 25% of the seven tariff-listed lines under the notice
    assert "unless goods that survived ship before" in o.duty_effect.provenance.rule and "2026-11-01" in o.duty_effect.provenance.rule
    assert [u.what for u in o.cost_unknowns] == ["air freight"]


def test_resequence_lays_out_every_product_with_its_short_parts_and_picks_none(opts):
    o = opts["resequence"]
    shown = [(p.product.id, p.product.label, len(p.short_parts)) for p in o.products]
    assert shown == sorted(shown) and sorted(x[1:] for x in shown) == sorted([("Heron H1", 0), ("Porter P5", 2), ("Tern T2", 3)])      # part-number order, not exposure order
    assert all(p.robots > 0 for p in o.products) and o.earliest.date == "2026-10-01"
    assert not any(k in o.model_dump() for k in ("rank", "recommended", "preferred", "score"))             # "lay them out, name what decides each; no pick"


def test_second_source_is_the_other_suppliers_quote_with_its_condition_and_cost(session, opts):
    o = opts["second_source"]
    assert "Vinh Phuc" in o.label and o.moq == 200
    assert o.earliest is None and "PPAP" in o.earliest_basis and o.not_before.date == "2026-11-24"          # the floor: the data date plus 60 days; the real date waits on PPAP
    offer = next(v for v in quotes.offers_for_part(session, "HR-40110") if "Vinh Phuc" in v.supplier_name and v.qty_break == 500)
    landed = quotes.landed_cost(session, offer.offer_id)
    ref = session.get(ReferencePrice, "HR-40110").usd_each
    assert float(o.cost_delta.usd) == pytest.approx((float(landed.total_known_usd.usd) - ref) * 364, abs=1)         # price now against price paid, on the October shortage
    assert o.cost_unknowns and any("origin" in u.why_it_blocks or "China" in u.what for u in o.cost_unknowns)      # duty is unknown until the broker rules the origin


def test_fire_rows_carry_structured_numbers_for_the_tiles(session):
    row = next(i for i in attention.what_needs_attention(session) if i.key == KEY)
    assert (row.lines_in_scope, row.lines_already_late) == (10, 4)
    assert {(r.product.label, r.month, r.robots) for r in row.robots_short} == {("Tern T2", "2026-10", 182), ("Porter P5", "2026-10", 40), ("Tern T2", "2026-11", 188), ("Porter P5", "2026-11", 42)}
    assert next(r for r in row.robots_short if r.product.label == "Tern T2").short_parts


def test_only_a_disruption_has_options(session):
    assert options.fire_options(session, "tariff:all") is None and options.fire_options(session, "no-such-item") is None


def test_a_slip_has_no_stock_that_survived(session):
    """plan-13 item 4: the Jadepeak notice is a slip, not a fire: its options are worded from the notice kind (nothing burned)."""
    opts = {o.kind: o for o in options.fire_options(session, "disruption:SUP-0013")}
    assert opts["allocation"].label == "Ask Jadepeak to keep the original dates or allocate" and opts["air_freight"].label == "Air-ship the delayed lines"
    text = " ".join(f"{o.label} {' '.join(n.what for n in o.needs)} {o.earliest_basis or ''} {o.decided_by.what} {o.decided_by.question} {o.duty_effect.provenance.rule if o.duty_effect else ''}" for o in opts.values())
    assert "surviv" not in text and "undamaged" not in text
    fire = {o.kind: o for o in options.fire_options(session, KEY)}
    assert fire["air_freight"].label == "Air-freight what survived"                            # the fire keeps its own words
