"""A month's shortage is that month's own, never more than the month needs; the unmet need carried in from earlier months is a separate cumulative `backlog`.
Checked against the S&OP forecast file itself."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.attention import service as attention
from app.domain.demand import service as demand
from app.domain.parts.model import Part

DATA = Path(__file__).resolve().parents[3] / "data"


def _planned() -> dict[tuple[str, str], int]:
    """{(product name, month): robots}, straight from the forecast file."""
    out = defaultdict(int)
    with open(DATA / "demand_forecast.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[(r["product"].strip(), r["month"][:7])] += int(float(r["units"]))
    return out


def test_heron_misses_its_november_builds_not_a_running_total(session):
    planned = _planned()
    heron = next(k for k in planned if k[0].lower().startswith("heron") and k[1] == "2026-11")
    assert planned[heron] == 24                                                   # the S&OP plans 24 Herons in November
    nov = next(b for b in demand.shortage(session, "HR-51310").buckets if b.month == "2026-11")
    assert float(nov.short.value) == 24 and float(nov.backlog.value) == 46        # short is November's own; 46 is the cumulative need through November, a separate field
    dec = next(b for b in demand.shortage(session, "HR-51310").buckets if b.month == "2026-12")
    assert float(dec.short.value) == 22 and float(dec.backlog.value) == 68        # December needs 22; 68 is the backlog
    hit = [r for it in attention.what_needs_attention(session) if it.key == "disruption:SUP-0013" for r in it.robots_short if r.product.label == "Heron H1"]
    assert [(r.month, r.robots) for r in hit] == [("2026-11", 24), ("2026-12", 22)]      # robots short never exceeds the robots planned that month


def test_no_month_is_short_by_more_than_it_needs_and_backlog_is_cumulative(session):
    checked = 0
    for part in session.scalars(select(Part.part_number)):
        tp = demand.shortage(session, part)
        for b in tp.buckets:
            if b.short is None:
                continue
            assert 0 < float(b.short.value) <= float(b.requirements.value), (part, b.month)
            assert b.backlog is not None and float(b.backlog.value) >= float(b.short.value), (part, b.month)
            checked += 1
    assert checked > 10


def test_robots_short_is_scaled_by_the_share_of_the_month_that_is_short(session):
    # a partial shortage stops a share of the month's robots, never more than were planned
    hit = attention._robots_hit(session, ["HR-51310"], "2026-11")
    assert hit == {"Heron H1": 24}
    planned = _planned()
    for it in attention.what_needs_attention(session):
        for r in it.robots_short:
            assert 0 < r.robots <= planned[(r.product.label, r.month)], (it.key, r.product.label, r.month)


@pytest.mark.parametrize("part", ["HR-40110", "HR-51110"])
def test_the_first_short_month_is_unchanged(session, part):
    tp = demand.shortage(session, part)
    first = next(b for b in tp.buckets if b.short is not None)
    assert tp.first_short_month == first.month == "2026-10" and float(first.backlog.value) == float(first.short.value)
