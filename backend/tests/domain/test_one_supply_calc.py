"""Shortage and build readiness are one supply-against-need calculation (demand.month_gaps), so they cannot disagree.
Checked on every part of the two suppliers whose notices move supply (the burned motor plant and the lead-time cut), for every product and month."""

from __future__ import annotations

import pytest

from app.domain.demand import service as demand
from app.domain.orders import service as orders
from app.domain.phases import service as phases

NOT_COVERED = {"disrupted", "after_build", "short", "short_after_stock"}


def _parts(session, *suppliers):
    return sorted({s.part.id for s in orders.open_supply(session) if s.supplier.id in suppliers and not s.stale})


@pytest.mark.parametrize("supplier", ["SUP-0001", "SUP-0013"])
def test_readiness_and_shortage_agree_on_every_part_of_both_notices(session, supplier):
    parts = _parts(session, supplier)
    assert parts
    seen = 0
    for product in ("HR-90020", "HR-90050", "HR-90110"):
        for month in ("2026-10", "2026-11", "2026-12", "2027-01"):
            br = phases.build_readiness(session, product, month)
            state = {p.part.id: p.state for g in br.groups for p in g.parts}
            for part in parts:
                if part not in state:
                    continue
                gap = demand.month_gaps(session, part).get(month)
                bucket = next(b for b in demand.shortage(session, part).buckets if b.month == month)
                if gap is None:      # past the last month any open order lands: need not yet ordered, which neither view calls a gap in dated supply
                    assert not bucket.short, (month, part)
                    continue
                not_covered = gap.gap_now > 0.5
                assert (state[part] in NOT_COVERED) == not_covered, (product, month, part, state[part], gap)
                # the shortage view says the same thing: a month is short exactly when the cumulative gap at the dates now in force is open
                assert bool(bucket.short) == not_covered, (month, part, bucket.short, gap)
                seen += 1
    assert seen >= 12


def test_a_months_shortage_is_never_more_than_it_needs_and_backlog_is_the_gap_now(session):
    for part in _parts(session, "SUP-0001", "SUP-0013"):
        gaps = demand.month_gaps(session, part)
        for b in demand.shortage(session, part).buckets:
            if b.short:
                g = gaps[b.month]
                assert float(b.short.value) <= float(b.requirements.value) and float(b.backlog.value) == pytest.approx(g.gap_now, abs=0.01)


def test_the_fire_and_the_slip_keep_their_numbers(session):
    fire = {b.month: float(b.short.value) for b in demand.shortage(session, "HR-40110").buckets if b.short}
    assert fire == {"2026-10": 364.0, "2026-11": 376.0}                              # the motors: October and November (restart by Nov 17), then they land
    slip = {b.month: (float(b.short.value), float(b.backlog.value)) for b in demand.shortage(session, "HR-51310").buckets if b.short}
    assert slip == {"2026-10": (22.0, 22.0), "2026-11": (24.0, 46.0), "2026-12": (22.0, 68.0), "2027-01": (3.0, 3.0)}     # October is raised: it is short, and 46 is exactly October plus November
    assert demand.shortage(session, "HR-51310").buckets[0].uncovered_before.value == 22        # October was uncovered at the promised dates too: no notice caused it


def test_backlog_accumulates_exactly_the_months_raised_and_the_end_of_the_horizon_is_flagged(session):
    for part in _parts(session, "SUP-0001", "SUP-0013"):
        tp = demand.shortage(session, part)
        raised = 0.0
        for b in tp.buckets:
            if b.short:
                raised += float(b.short.value)
                assert float(b.backlog.value) <= raised + 0.01, (part, b.month)       # never carries a month that was not raised
        last = demand.month_gaps(session, part)
        end = last[max(last)].gap_now if last else 0.0
        assert (tp.unmet_after_all_open_orders is not None) == (end > 0.5), part
    heron = demand.shortage(session, "HR-51310")
    assert float(heron.unmet_after_all_open_orders.value) == 3.0                      # January's remaining 3 is flagged: all the open orders together still fall short
    assert demand.shortage(session, "HR-40110").unmet_after_all_open_orders is None

