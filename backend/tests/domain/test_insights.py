"""Insights rules (PLAN 13, MAPPING 10): who sees a Team page (the Head everyone, a lead their team, a buyer themselves), that the Team page follows
the organogram and nothing is ranked, that days waited are the ladders' own days, that a turnaround
leaves out same-day PRs, that ₹ at risk adds up Today's cases, and that the Daily brief carries the person's own cases."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.attention.service import what_needs_attention
from app.domain.insights import service as S
from app.domain.insights.api import router
from app.domain.orders import service as orders
from app.domain.phases.ladder import ladder
from app.domain.projects.model import ProjectAlias
from app.domain.prs import service as prs


@pytest.fixture(scope="module")
def session(db_path):
    engine = create_engine(f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False})
    with Session(engine) as s:
        yield s


@pytest.fixture(scope="module")
def client(db_path):
    engine = create_engine(f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False})

    def _session():
        with Session(engine) as s:
            yield s

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def _buyers(session):
    """Members who see only themselves (nobody reports to them) and whose lead is not the Head, each with PR lines of their own; the first two are
    on different teams."""
    t = lookups.team(session)
    have = {l.buyer_id for l in prs.all_lines(session).values()}
    out = [b for b in t.values() if not b.sees_all and not lookups.under(session, b.id) and b.id in have and not t[b.reports_to].sees_all]
    second = next(b for b in out if b.reports_to != out[0].reports_to)
    return [out[0], second, *[b for b in out[1:] if b is not second]]


def test_a_buyer_sees_only_their_own_page(session, client):
    a, b = _buyers(session)[:2]
    assert S.can_see(session, a.id, a.id) and not S.can_see(session, a.id, b.id)
    assert client.get(f"/api/insights/team/{b.id}", params={"viewer": a.name}).status_code == 403
    assert client.get(f"/api/insights/team/{a.id}", params={"viewer": a.name}).status_code == 200
    r = client.get("/api/insights/team", params={"viewer": a.id}).json()
    assert r["scope"] == "self" and [m["id"] for m in r["members"]] == [a.id]


def test_the_head_sees_everyone_and_a_lead_their_own_team(session, client):
    head = lookups.head(session)
    r = client.get("/api/insights/team", params={"viewer": head.name}).json()
    assert r["scope"] == "all" and len(r["members"]) == len(lookups.team(session))
    a, b = _buyers(session)[:2]
    assert client.get(f"/api/insights/team/{a.id}", params={"viewer": head.id}).status_code == 200
    lead = lookups.lead_of(session, a)
    r = client.get("/api/insights/team", params={"viewer": lead.id}).json()
    assert r["scope"] == "team" and [m["id"] for m in r["members"]] == [lead.id, *lookups.under(session, lead.id)]
    assert client.get(f"/api/insights/team/{a.id}", params={"viewer": lead.name}).status_code == 200
    refused = client.get(f"/api/insights/team/{b.id}", params={"viewer": lead.name})      # another lead's team
    assert refused.status_code == 403 and lookups.lead_of(session, b).name in refused.json()["detail"]


def test_a_stranger_sees_nothing_and_no_viewer_says_so(client):
    assert client.get("/api/insights/team", params={"viewer": "Somebody Else"}).json()["members"] == []
    r = client.get("/api/insights/team").json()
    assert r["scope"] == "all" and "No viewer" in r["note"]


def test_team_follows_the_organogram_never_a_figure(session, client):
    r = client.get("/api/insights/team", params={"viewer": lookups.head(session).id, "sort": "open_prs"}).json()
    ms = r["members"]
    assert r["order"] == "the organogram's order" and ms[0]["id"] == lookups.head(session).id and ms[0]["group"] == "head"
    # each lead heads their own group, followed by everyone who reports up to them, and each group is one run
    for lead in lookups.leads(session):
        run = [m["id"] for m in ms if m["group"] == lead.id]
        assert run[0] == lead.id and set(run[1:]) == set(lookups.under(session, lead.id))
        first = [m["id"] for m in ms].index(lead.id)
        assert [m["id"] for m in ms[first:first + len(run)]] == run
    assert all(m["reports_to"] == lookups.team(session)[m["id"]].reports_to for m in ms)
    # the order would differ if it followed a figure: it does not move when the figures do
    by_open = [m["id"] for m in sorted(r["members"], key=lambda m: -(m["open_prs"]["value"] or 0))]
    assert [m["id"] for m in r["members"]] == S.team_order(session) and (by_open != S.team_order(session) or len(set(by_open)) < 2)
    # no Insights route takes a sort or rank parameter
    for route in router.routes:
        assert not {"sort", "rank", "order"} & {p.name for p in route.dependant.query_params}


def test_days_waited_are_the_ladders_own_days(session):
    for b in _buyers(session):
        page = S.member_page(session, b.id)
        held: dict[str, int] = {}
        for l in prs.all_lines(session).values():
            if l.buyer_id == b.id:
                for f, d in ladder(session, pr_line_id=l.id).held.items():
                    held[f] = held.get(f, 0) + d
        for l in orders.all_lines(session).values():
            if l.buyer_id == b.id and (not l.pr_line_id or l.pr_line_id not in prs.all_lines(session)):
                for f, d in ladder(session, po_line_id=l.id).held.items():
                    held[f] = held.get(f, 0) + d
        assert {w.function: int(w.days.value or 0) for w in page.waits if w.days.value} == {f: d for f, d in held.items() if d}
        assert (page.waited_scm.value or 0) + (page.waited_others.value or 0) == sum(held.values())


def test_turnaround_leaves_out_same_day_prs_and_matches_the_pr_record(session):
    lines = prs.all_lines(session)
    same_day = [l for l in lines.values() if "same_day_po" in (l.flags or "") and l.po_line_id]
    assert same_day and all(S.turnaround(session, l) is None for l in same_day)
    for l in list(lines.values())[:300]:
        assert S.turnaround(session, l) == prs.view(session, l).turnaround_days
    tat_ids = {t[0] for t in S._tats(session)}
    assert not tat_ids & {l.id for l in same_day}


def test_turnaround_is_set_against_the_members_own_vertical_only(session):
    for b in _buyers(session):
        for row in S.member_page(session, b.id).turnaround:
            every = [t for t in S._tats(session) if t[2] == row.vertical]
            assert set(row.vertical_median.refs) == {f"pr_line:{t[0]}" for t in every}
            assert set(row.mine.refs) <= set(row.vertical_median.refs)


def test_savings_compare_with_the_previous_rate_at_the_plant(session):
    b = next(b for b in _buyers(session) if S.member_page(session, b.id).saving_last_detail.lines)
    po = [l for l in orders.all_lines(session).values() if l.buyer_id == b.id]
    want = 0.0
    for l in po:
        earlier = [x for x in orders.all_lines(session).values() if x.material == l.material and x.plant == l.plant and x.doc_date < l.doc_date]
        if l.material and earlier:
            prev = max(earlier, key=lambda x: (x.doc_date, x.id))
            want += (prev.rate_base - l.rate_base) * l.qty_base
    got = S.member_page(session, b.id).saving_last_detail
    assert got.net.value == pytest.approx(want, abs=1)
    assert got.lines == len(got.net.refs) and "previous rate exists" in (got.net.note or "")


def test_effort_on_cancelled_prs_counts_only_deleted_or_short_closed_lines(session):
    for b in _buyers(session):
        c = S.member_page(session, b.id).cancelled_detail
        ids = {r.split(":", 1)[1] for r in c.lines.refs}
        assert all(prs.all_lines(session)[i].status in ("deleted", "closed") for i in ids)
        assert {r.split(":", 1)[1] for r in c.rfq_lines.refs} <= ids


def test_projects_by_vertical_and_risk_adds_up_todays_cases(session):
    rows = S.projects(session).rows
    assert len(rows) == len(lookups.projects(session))
    order = [(lookups.VERTICALS.index(r.vertical), r.name) for r in rows]
    assert order == sorted(order)
    cases = {c.key: c for c in what_needs_attention(session)}
    for r in rows:
        alone = [cases[x.split(":", 1)[1]] for x in r.at_risk.refs]
        assert all([p.id for p in c.projects] == [r.id] for c in alone)
        assert (r.at_risk.value or 0) == pytest.approx(sum(float(c.at_stake.amount) for c in alone), abs=1)
        held = sum(S.ladders(session)[k].held.get("Projects", 0) for k in r.held_by_projects.refs)
        assert (r.held_by_projects.value or 0) == held


def test_estimates_name_the_sheet_names_no_project_resolves_to(session):
    e = S.estimates(session)
    want = {a.alias for a in session.scalars(select(ProjectAlias).where(ProjectAlias.method == "unresolved"))}
    assert {u.name for u in e.unresolved} == want
    for r in e.rows:
        assert r.repeat == (r.over_months > 1)
        assert all(m.received is None for m in r.months if m.month > S.TODAY[:7])  # nothing is received in a month not yet begun


def test_an_over_ask_is_judged_against_the_projects_best_month(session):
    amt, share, _ = S._over_rule()
    for r in S.estimates(session).rows:
        peak = r.peak.value if r.peak else 0
        for m in r.months:
            if m.over is not None and m.requirement:
                diff = (m.requirement.value or 0) - (peak or 0)
                assert m.over == (diff > amt and (not peak or diff / peak > share))


def test_pricing_leaves_out_quotes_from_held_mail_and_spread_is_high_over_low(session):
    from app.domain.inbox.model import Message
    from app.domain.quotes.model import Quote

    held = {m.id for m in session.scalars(select(Message).where(Message.trust == "blocked"))}
    held_quotes = {q.id for q in session.scalars(select(Quote).where(Quote.message_id.in_(held)))} if held else set()
    for r in S.pricing(session).rows:
        if r.latest_quote:
            assert not {x.split(":", 1)[1] for x in r.latest_quote.refs} & held_quotes
        if r.spread:
            assert r.spread.value == pytest.approx((r.high.rate.value or 0) / (r.low.rate.value or 1), abs=0.01)


def test_a_spread_names_the_buyer_of_each_site_above_the_median(session):
    rows = [r for r in S.pricing(session).rows if r.unexplained]
    assert rows
    d = S.pricing_detail(session, rows[0].code)
    assert d.unknowns and all(u.ask in lookups.team(session) for u in d.unknowns if u.ask)
    for u in d.unknowns:
        site = next(s for s in d.by_site if s.project == u.project)
        assert u.ask == site.buyer and u.rate > (d.median or 0)


def test_the_brief_carries_the_persons_own_cases_and_is_never_sent(session, client):
    for b in _buyers(session):
        br = client.get(f"/api/brief/{b.id}").json()
        assert br["sent"] is False and br["person"] == b.id
        mine = [c.key for c in what_needs_attention(session, owner=b.id) if c.waiting_on == "SCM"]
        on_you = next(s for s in br["sections"] if s["key"] == "on_you")
        assert [l["ref"] for l in on_you["lines"]] == [f"item:{k}" for k in mine[:S.BRIEF_LINES]]
        others = {c.key for c in what_needs_attention(session) if b.id not in c.owner_ids}
        assert not {l["ref"].split(":", 1)[1] for s in br["sections"] for l in s["lines"] if (l["ref"] or "").startswith("item:")} & others


def test_the_brief_ages_prs_from_release_and_keeps_to_the_persons_own_purchases(session):
    from app.domain.milestones.model import Milestone

    for b in _buyers(session):
        br = S.brief(session, b.id)
        ageing = next(s for s in br.sections if s.key == "ageing")
        ages = []
        for l in ageing.lines:
            # a PR document can carry lines of several desks: the brief ages the member's own
            open_lines = [x for x in prs.lines_of_pr(session, l.ref.split(":", 1)[1]) if x.status == "open" and x.buyer_id == b.id]
            assert open_lines
            ages.append(max(S.age(x) for x in open_lines))
            assert l.figure == ("1 day" if ages[-1] == 1 else f"{ages[-1]} days")
        assert ages == sorted(ages, reverse=True)
        mine = {l.po_no for l in orders.all_lines(session).values() if l.buyer_id == b.id}
        unexported = {m.po_no for m in session.scalars(select(Milestone)) if not m.po_line_id}
        for l in next(s for s in br.sections if s.key == "milestones").lines:
            assert l.ref.split(":", 1)[1] in mine | unexported
