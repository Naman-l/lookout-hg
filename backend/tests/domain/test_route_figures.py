"""The Decision table's figures for every kind of case (FINAL-SPEC §2): one row per route of the case's code table, in its order, with Covers, Earliest and
Cost from the records or the case's own figures, empty with its reason where the records hold none. Proved on the seed build and on a perturbed build."""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.attention import option_kinds, route_figures, service
from tests.domain.perturb import BACKEND, perturb


def _rows(session, key, owner=None):
    from app.domain.attention.api import action_item_options

    return action_item_options(key, owner, session)


def _every_case(session):
    return [i.key for i in service.what_needs_attention(session) if i.group != "trust"]


def _check_every_case(session):
    for key in _every_case(session):
        rows, table = _rows(session, key), option_kinds.option_kinds(session, key)
        assert [r.kind for r in rows] == [t.kind for t in table], key                         # the same routes, the same order, as the Decision table
        for r in rows:
            assert r.cost_basis or r.cost is not None or r.cost_delta is not None or r.kind in ("allocation", "air_freight", "resequence", "second_source", "order_before"), (key, r.kind)
            for m in (r.cost, r.cost_delta, getattr(r, "duty_effect", None)):
                assert m is None or m.provenance is not None                                   # every figure carries where it came from


def test_every_case_gets_one_row_per_route_with_figures_or_the_reason_there_are_none(session):
    _check_every_case(session)


def test_the_figures_are_the_cases_own(session):
    duty = {r.kind: r for r in _rows(session, "tariff:all", "Dana Reyes")}
    owed = next(n for n in service.item_detail(session, "tariff:all").numbers if n.id == "tile:owed")
    team = {r.kind: r for r in _rows(session, "tariff:all")}
    assert team["accept"].cost.usd == owed.value.usd and "[tile:owed]" in team["accept"].cost_basis
    assert duty["switch_origin"].covers.startswith("HR-40110") and round(float(duty["switch_origin"].cost_delta.usd), 2) == round(160.87 - 188.99, 2)
    gp = {r.kind: r for r in _rows(session, "deadline:SUP-0041:2026-10-15")}
    assert float(gp["buy_ahead"].cost_delta.usd) == -float(service.item_detail(session, "deadline:SUP-0041:2026-10-15").at_stake.usd) and gp["buy_ahead"].earliest.date == "2026-10-15"
    fire = {r.kind: r for r in _rows(session, "disruption:SUP-0001")}
    assert fire["alternate_on_file"].covers == "HR-40120 only" and fire["allocation"].covers == "10 PO lines" and fire["resequence"].covers == "3 products"
    risk = {r.kind: r for r in _rows(session, "risk:SUP-0002")}
    assert risk["recheck"].earliest.date == "2026-10-31" and risk["open_terms"].earliest.date < "2026-10-31"     # the reply comes before the act-by, never on it
    assert [r.kind for r in _rows(session, "consignment:HR-30110")] == ["earlier_date", "cm_partial", "direct_air", "cm_stock"]


@pytest.fixture(scope="module")
def changed(tmp_path_factory):
    root = tmp_path_factory.mktemp("figures-perturbed")
    data, recipe = perturb(root)
    db = root / "perturbed.db"
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(recipe), "--data", str(data), "--db", str(db)], cwd=BACKEND,
                          env={**os.environ, "LOOKOUT_DB": str(db)}, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-600:] + done.stderr[-600:]
    return db


def test_on_changed_data_every_case_still_gets_its_rows_from_its_own_records(changed):
    eng = create_engine(f"sqlite:///{changed}", future=True)
    with Session(eng) as s:
        _check_every_case(s)
        assert {r.kind for r in _rows(s, "disruption:SUP-0001")} >= {"allocation", "resequence"}
        assert not any("Yunzhan" in (r.label + (r.covers or "") + (r.cost_basis or "")) for k in _every_case(s) for r in _rows(s, k))
    eng.dispose()


def test_g1_the_viewers_duty_budget_is_her_fixed_share_and_the_team_total_only_for_everyone(session):
    dana = {r.kind: r for r in _rows(session, "tariff:all", "Dana Reyes")}["accept"]
    team = {r.kind: r for r in _rows(session, "tariff:all")}["accept"]
    fixed = next(n for n in service.item_detail(session, "tariff:all").numbers if n.id == "duty_share_fixed:Dana")
    assert dana.cost.usd == fixed.value.usd and "[duty_share_fixed:Dana]" in dana.cost_basis and dana.covers == "your fixed share"
    assert team.cost.usd != dana.cost.usd and "[tile:owed]" in team.cost_basis


def test_buy_ahead_says_the_saving_comes_from_ordering_the_uncovered_need(session):
    gp = {r.kind: r for r in _rows(session, "deadline:SUP-0041:2026-10-15")}["buy_ahead"]
    assert gp.cost_basis == "kept by ordering the need open orders don't cover by Oct 15, at today's price"


def test_g2_g3_an_email_routes_earliest_and_covers_are_its_prepared_drafts(tmp_path, monkeypatch):
    """With the morning run's drafts: Earliest is the reply-by the prepared email asks (the earliest one, D7), Covers the lines it names."""
    import shutil

    seed = BACKEND / "demo-seed.db"
    if not seed.exists():
        pytest.skip("no demo seed in this checkout")
    db = tmp_path / "seed.db"
    shutil.copy(seed, db)
    from app import db as _db

    monkeypatch.setattr(_db, "DB_PATH", db)
    eng = create_engine(f"sqlite:///{db}", future=True)
    with Session(eng) as s:
        ruilian = {r.kind: r for r in _rows(s, "incident:SUP-0018")}["confirm_dates_hold"]
        assert ruilian.earliest.date == "2026-10-09" and ruilian.earliest.provenance.method == "extracted"     # "Please reply as soon as you can, and by 9 October"
        chase = {r.kind: r for r in _rows(s, "deadline:chase")}
        lines = {l.ref.id for l in service.item_detail(s, "deadline:chase").po_lines}
        bodies = " ".join(a.body or "" for a in route_figures._route_drafts(s, "deadline:chase", "ship_date"))
        named = {x for x in lines if x in bodies or re.search(rf"{re.escape(x.split('/')[0])},? lines? (?:\d+(?:, | and | & ))*{int(x.split('/')[1])}\b", bodies)}
        assert chase["ship_date"].covers == f"{len(named)} PO lines" and 0 < len(named) < len(lines)             # the case's lines the emails carrying its ask name, never another case's
        assert not any(x.startswith("HPO-26-00675") for x in named) and chase["reorder"].covers == f"{len(lines)} PO lines"
        assert {r.kind: r for r in _rows(s, "risk:SUP-0002")}["bridge"].covers is None
    eng.dispose()


def test_t1_under_a_viewer_the_budget_is_never_the_team_total(session):
    team = {r.kind: r for r in _rows(session, "tariff:all")}["accept"].cost.usd
    for who in ("Priya Nair", "Dana Reyes", "Tom Albrecht", "Marcus Chen"):
        a = {r.kind: r for r in _rows(session, "tariff:all", who)}["accept"]
        assert (a.cost is None and a.cost_basis == "your share of the duty is not in the records") or (a.cost.usd != team and f":{who.split()[0]}]" in a.cost_basis), who


def test_13_the_second_sources_cost_says_it_is_before_duty(session):
    o = {r.kind: r for r in _rows(session, "disruption:SUP-0001")}["second_source"]
    assert "before any duty" in o.cost_basis


def test_r1_a_roll_up_under_a_viewer_counts_and_costs_only_her_lines(session):
    mine = next(i for i in service.what_needs_attention(session, "Dana Reyes") if i.key == "deadline:chase")
    dana = {r.kind: r for r in _rows(session, "deadline:chase", "Dana Reyes")}
    team = {r.kind: r for r in _rows(session, "deadline:chase")}
    her_lines = [l for l in service.item_detail(session, "deadline:chase").po_lines if l.buyer == "Dana Reyes"]
    assert dana["reorder"].covers == f"{len(her_lines)} PO lines" != team["reorder"].covers
    assert dana["ship_date"].cost.usd == mine.at_stake.usd != team["ship_date"].cost.usd
    hit = service.item_context(session, "unknown:stale-orders")[1]
    hers = [m for m, _ in hit["members"] if m.owner == "Dana Reyes"]
    assert {r.covers for r in _rows(session, "unknown:stale-orders", "Dana Reyes")} == {f"{len(hers)} orders"} != {r.covers for r in _rows(session, "unknown:stale-orders")}


def test_r2_buy_ahead_covers_what_its_cost_is_on(session):
    gp = {r.kind: r for r in _rows(session, "deadline:SUP-0041:2026-10-15")}["buy_ahead"]
    assert gp.covers == "the need open orders don't cover" and "the need open orders don't cover" in gp.cost_basis
