"""The stage ladder and build readiness: only what the records show is done or expected; the rest is unknown with someone to ask."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.phases import service
from app.domain.phases.api import router

SHOWN = {"need", "quote", "ordered", "promised", "received", "closed"}   # the rungs the data can honestly show
NEVER = {"acknowledged", "at_supplier", "shipped", "in_transit", "customs", "inspected", "stocked", "kitted"}


@pytest.fixture()
def client(db_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def session():
        with Session(eng) as s:
            yield s

    from app.db import get_session

    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    eng.dispose()


def test_tern_october_counts(session):
    b = service.build_readiness(session, "HR-90020", "2026-10")
    assert b.units == 182
    assert b.counts == {"covered": 35, "after_build": 13, "past_due": 3, "disrupted": 3, "no_order": 80, "in_house": 7}
    assert sum(b.counts.values()) == 141
    # the figures an earlier cut gave: 45 with dated supply that covers the quantity, 87 with nothing open (80 bought parts and 7 assemblies)
    assert b.counts["covered"] + b.counts["after_build"] + b.counts["past_due"] == 51
    assert b.counts["no_order"] + b.counts["in_house"] == 87


def test_the_fire_is_disrupted(session):
    b = service.build_readiness(session, "HR-90020", "2026-10")
    parts = {p.part.id: p for g in b.groups for p in g.parts}
    for pn in ("HR-40110", "HR-40120", "HR-40130"):
        assert parts[pn].state == "disrupted" and parts[pn].cause is not None and parts[pn].cause.type == "message"


def test_no_order_is_unknown_not_covered(session):
    b = service.build_readiness(session, "tern t2", "2026-10")
    none = [p for g in b.groups for p in g.parts if p.state == "no_order"]
    assert none and all(p.ask and p.ask.owner and p.ask.question for p in none)
    assert "unknown without stock data" in b.verdict and "%" not in b.verdict


def test_rolled_up_by_sub_assembly(session):
    b = service.build_readiness(session, "HR-90020", "2026-10")
    ids = [g.assembly.id for g in b.groups]
    assert ids[0] == "HR-90020" and "HR-80110" in ids
    drive = next(g for g in b.groups if g.assembly.id == "HR-80110")
    assert "HR-40110" in {p.part.id for p in drive.parts}


def test_unknown_month_or_product(session):
    assert service.build_readiness(session, "HR-90020", "2030-01") is None
    assert service.build_readiness(session, "nope", "2026-10") is None


def test_open_line_ladder(session):
    lad = service.part_phases(session, "HR-40110")
    line = lad.lines[0]
    by = {r.key: r for r in line.rungs}
    assert [r.key for r in line.rungs] == list(service.KEYS)
    assert by["ordered"].state == "done" and by["promised"].state == "disrupted" and by["promised"].flag == "disrupted"
    for k in NEVER:
        assert by[k].state in ("unknown", "na"), k
        if by[k].state == "unknown":
            assert by[k].unknown.owner and by[k].unknown.question and by[k].unknown.why_it_blocks
    assert by["at_supplier"].flag == "disrupted" and by["at_supplier"].source.type == "message"
    assert "%" not in line.verdict


def test_closed_line_never_infers_transit_or_customs(session):
    lad = service.line_phases(session, "PO-10412/1")
    by = {r.key: r for r in lad.rungs}
    assert by["received"].state == "done" and by["closed"].state == "done"
    assert all(by[k].state in ("unknown", "na") for k in NEVER)
    assert "does not tell us" in by["customs"].detail or by["customs"].state == "na"


def test_done_and_expected_rungs_cite_a_record(session):
    for pn in ("HR-40110", "HR-51110", "HR-12110"):
        lad = service.part_phases(session, pn)
        for l in [lad] + lad.lines:
            for r in l.rungs:
                if r.state in ("done", "expected"):
                    assert r.source is not None, (pn, r.key)


def test_undated_and_stale_lines_are_unknown(session):
    from app.domain.orders import service as orders

    stale = next(s for s in orders.open_supply(session) if s.stale)
    lad = service.line_phases(session, stale.po_line.id)
    assert {r.key: r for r in lad.rungs}["promised"].state == "unknown"


def test_phases_api(client):
    r = client.get("/api/phases", params={"part": "HR-40110"})
    assert r.status_code == 200 and r.json()["kind"] == "part" and r.json()["lines"]
    r = client.get("/api/phases", params={"po_line": "PO-10412/1"})
    assert r.status_code == 200 and r.json()["kind"] == "po_line"
    assert client.get("/api/phases").status_code == 422
    assert client.get("/api/phases", params={"part": "HR-40110", "po_line": "PO-10412/1"}).status_code == 422
    assert client.get("/api/phases", params={"part": "NOPE"}).status_code == 404


def test_readiness_api(client):
    r = client.get("/api/builds/HR-90020/2026-10/readiness")
    assert r.status_code == 200
    j = r.json()
    assert j["counts"]["disrupted"] == 3 and j["units"] == 182 and j["verdict"]
    assert client.get("/api/builds/Tern%20T2/2026-10/readiness").status_code == 200
    assert client.get("/api/builds/HR-90020/2030-01/readiness").status_code == 404


def test_a_past_date_is_never_expected(session):
    """An expected rung carries a date that has not passed; a promise that has passed is late or disrupted, on lines and on parts."""
    from app.domain.common import AS_OF

    for pn in ("HR-40110", "HR-51110", "HR-51130", "HR-60110", "HR-12110", "HR-21103"):
        lad = service.part_phases(session, pn)
        for l in [lad] + lad.lines:
            for r in l.rungs:
                if r.state == "expected" and r.date:
                    assert r.date >= AS_OF.isoformat(), (pn, r.key, r.date)


def test_the_part_ladder_and_readiness_agree(session):
    b = service.build_readiness(session, "HR-90020", "2026-10")
    for g in b.groups:
        for p in g.parts:
            if p.state in ("disrupted", "past_due"):
                lad = service.part_phases(session, p.part.id)
                by = {r.key: r for r in lad.rungs}
                assert by["promised"].state == ("disrupted" if p.state == "disrupted" else by["promised"].state) and by["promised"].state in ("disrupted", "late"), p.part.id
                if p.state == "disrupted":
                    assert by["promised"].source.type == "message"


def test_part_rungs_describe_current_supply_not_old_orders(session):
    lad = service.part_phases(session, "HR-40110")
    by = {r.key: r for r in lad.rungs}
    assert by["received"].state != "done"                      # the old delivery is history, not progress
    assert "last time" in by["received"].detail and "HPO-26-00321" in by["received"].detail
    assert by["promised"].state == "disrupted" and "3 of 3 open lines" in by["promised"].detail
    idle = service.part_phases(session, "HR-11103")           # nothing open: nothing to receive, history in the detail
    assert {r.key: r for r in idle.rungs}["received"].state == "na" and {r.key: r for r in idle.rungs}["promised"].state == "na"


def test_a_revision_announced_before_the_line_fell_due_is_its_current_date(session):
    """Jadepeak's notice of Sep 18 moved HPO-26-00486/10 (due Sep 21) and HPO-26-00517/20 (due Sep 23) to Nov 9 and Nov 4: after the build, with the PO date shown beside it."""
    b = service.build_readiness(session, "HR-90020", "2026-10")
    parts = {p.part.id: p for g in b.groups for p in g.parts}
    for pn, new in (("HR-51110", "2026-11-09"), ("HR-51130", "2026-11-04")):
        p = parts[pn]
        assert p.state == "after_build" and p.arrives == new
        assert "notice of Sep 18" in p.detail and "PO date" in p.detail and "passed" in p.detail
    for pn, (line, rev) in {"HR-51110": ("HPO-26-00486/10", "Nov 9"), "HR-51130": ("HPO-26-00517/20", "Nov 4")}.items():
        r = {x.key: x for x in service.line_phases(session, line).rungs}["promised"]
        assert r.state == "late" and r.flag == "slipped" and rev in r.detail and "PO date" in r.detail and "notice of Sep 18" in r.detail


def test_part_page_carries_the_shortage_and_the_supply_state(session):
    from app.domain.parts.service import part_detail

    d = part_detail(session, "HR-40110")
    assert d.shortage.month == "2026-10" and float(d.shortage.requirement.value) == 364 and float(d.shortage.short.value) == 364 and float(d.shortage.covered.value) == 0
    assert d.supply_state.state == "disrupted" and d.supply_state.source.type == "message" and "3 of 3 open lines" in d.supply_state.detail
    ladder = {r.key: r for r in service.part_phases(session, "HR-40110").rungs}["promised"]
    assert (d.supply_state.state, d.supply_state.date) == (ladder.state, ladder.date)            # the page and the ladder read the same rule
    fine = part_detail(session, "HR-12110")
    assert fine.shortage is None and fine.supply_state.state == "expected" and fine.supply_state.date >= "2026-09-25"
    idle = part_detail(session, "HR-11103")
    assert idle.shortage is None and idle.supply_state is None


def test_every_number_on_the_part_page_has_a_buyer_phrase_for_its_source(session):
    """Provenance rules are read by buyers: no function names, versions or column names; a computed number always says how."""
    import re

    from app.domain.parts.service import part_detail

    seen = []

    def walk(o):
        if isinstance(o, dict):
            if "method" in o and "source" in o:
                seen.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for pn in ("HR-40110", "HR-12110", "HR-50110", "HR-10001", "HR-31110", "HR-90020", "HR-21130"):
        walk(part_detail(session, pn).model_dump(mode="json", exclude_none=True))
    assert len(seen) > 30
    for p in seen:
        rule = p.get("rule") or ""
        assert not re.search(r"\b[a-z_]+\.[a-z_]+\b v\d|\bv\d\b|qty_per|_id\b", rule), rule
        if p["method"] == "computed":
            assert rule, p


def test_each_open_line_carries_its_quantity_and_date(session):
    lad = service.part_phases(session, "HR-51110")
    assert lad.lines and all(l.qty is not None and l.qty.value > 0 and l.promised for l in lad.lines)
    moved = next(l for l in lad.lines if l.subject.id == "HPO-26-00486/10")
    assert moved.promised.date == "2026-11-09" and moved.promised.erp_date == "2026-09-21"      # the supplier's date, the ERP date beside it
    same = service.part_phases(session, "HR-12110").lines[0]
    assert same.promised.erp_date is None and same.qty.uom
    undated = next((s for s in __import__("app.domain.orders.service", fromlist=["x"]).open_supply(session) if not s.promise and not s.stale), None)
    if undated:
        assert service.line_phases(session, undated.po_line.id).promised is None
    assert service.line_phases(session, "PO-10412/1").qty is None                                 # a closed line has nothing still to arrive


def test_builds_summary_is_one_small_row_per_product(client):
    r = client.get("/api/builds")
    assert r.status_code == 200
    rows = {x["product"]["id"]: x for x in r.json()}
    assert set(rows) == {"HR-90020", "HR-90050", "HR-90110"} and len(r.content) < 6000
    t = rows["HR-90020"]
    assert t["month"] == "2026-10" and t["units"] == 182 and t["verdict"]
    assert t["counts"] == {"covered": 35, "after_build": 13, "past_due": 3, "disrupted": 3, "no_order": 80, "in_house": 7}
    assert all(set(("covered", "after_build", "past_due", "disrupted", "no_order", "in_house")) <= set(x["counts"]) for x in rows.values())


def test_readiness_is_lean_and_keeps_its_sources(client):
    r = client.get("/api/builds/HR-90020/2026-10/readiness")
    assert len(r.content) < 70_000
    j = r.json()
    assert j["need_source"]["rule"] and j["need_source"]["method"] == "computed"
    row = next(p for g in j["groups"] for p in g["parts"] if p["part"]["id"] == "HR-40110")
    assert row["po_lines"] and "provenance" not in row["need"] and row["cause"]["type"] == "message"        # the tap-through is the ladder and the notice
