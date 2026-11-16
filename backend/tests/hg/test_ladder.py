"""The PR-to-payment ladder: each rung's date from a record, and whose move each wait was, by the rule in PLAN 6.2."""

from app.domain.phases.ladder import ladder


def test_the_ips_pr_waits_on_projects_since_the_spec_query(session):
    L = ladder(session, pr_line_id="1000203689/10")
    assert L.waiting_on == "Projects" and L.waiting_since == "2026-09-27" and L.days_waiting == 23


def test_an_mfc_held_for_site_readiness_is_projects_wait(session):
    L = ladder(session, po_line_id="4500120768/10")
    now = next(r for r in L.rungs if r.state == "now")
    assert now.key == "mfc_issued" and now.held_by == "Projects"


def test_quotes_in_means_the_cs_is_scms_to_approve(session):
    L = ladder(session, pr_line_id="1000204034/10")
    assert next(r for r in L.rungs if r.state == "now").key == "cs_approved" and L.waiting_on == "SCM"


def test_every_done_rung_cites_its_source(session):
    for kw in ({"pr_line_id": "1000204034/10"}, {"po_line_id": "4500121087/10"}, {"po_line_id": "4500120768/10"}):
        L = ladder(session, **kw)
        assert all(r.source for r in L.rungs if r.state == "done" and r.key != "closed"), kw
