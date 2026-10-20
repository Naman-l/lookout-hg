"""The case frame (plan-13 agent spec): each case kind has fixed Summary row labels, and the run's prompt gives them to Lookout."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.attention import options
from app.organism.workflows.work_item import build_prompt


@pytest.mark.parametrize("key,kind", [
    ("disruption:SUP-0001", "fire"), ("disruption:SUP-0013", "slip"), ("incident:SUP-0018", "incident"), ("risk:SUP-0002", "risk"),
    ("deadline:SUP-0041:2026-10-15", "price_lock"), ("deadline:SUP-0042:2026-09-28", "closure"), ("deadline:quotes", None), ("tariff:all", None),
])
def test_case_kind_comes_from_the_detectors_own_context(session, key, kind):
    assert options.case_kind(session, key) == kind


def test_a_case_gets_the_situation_line_and_no_points():
    """F74 P1: the case page has no points slot; the finding is the Situation. A message is not a case."""
    from app.organism.workflows.work_item import is_case

    fire = SimpleNamespace(key="disruption:SUP-0001", group="disruption", title="Fire", owner="Dana", refs=[], numbers=[])
    p = build_prompt(fire)
    assert is_case(fire) and "write no `points`" in p and "no instruction" in p
    msg = SimpleNamespace(key="triage:m", group="triage", title="Triage: x", owner="", refs=[])
    assert not is_case(msg) and "write no `points`" not in build_prompt(msg)
    assert not is_case(SimpleNamespace(key="trust:x", group="trust", numbers=[]))      # trust is answered by code, with its own rows


def test_the_planner_works_only_the_case_on_a_disruption():
    """plan-13 1d: on the fire, build_readiness added 14 open questions about other parts of the build; the planner names every short part instead."""
    from pathlib import Path

    import app.organism.specialists as sp

    text = (Path(sp.__file__).parent / "supply_planner" / "instructions.md").read_text()
    assert "do not call `build_readiness`" in text and "Name every part that runs short" in text


def test_the_past_due_count_on_a_fire_says_what_it_counts(session):
    """plan-13 1e (LOOKOUT fire-past-due-check): the 4 lines are past their promise date at the data date, not 'late before the notice'."""
    from app.domain.attention import service
    from app.domain.attention.tools import read_item

    numbers, _, _ = read_item(service.item_detail(session, "disruption:SUP-0001"))
    late = next(n for n in numbers if n.id.endswith(":lines_already_late"))
    assert late.value == 4 and late.name == "Of those, lines already past their promise date at the data date" and "notice" not in late.name


def test_the_packet_lists_the_cases_options_from_the_code_table(db_path, monkeypatch):
    """plan-13 item 2: the fire's packet carries the table's five kinds (wait included) in the table's words; a risk case never sees 'what survived'."""
    from app.organism import services as default_services
    from app.organism.context_packet import build

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)   # the real records, not the organism's test stand-ins
    svc = default_services.get(str(db_path))
    try:
        fire = build(svc.attention.get_item("disruption:SUP-0001"), svc, str(db_path))
        assert fire.option_kinds == ["allocation", "alternate_on_file", "second_source", "air_freight", "resequence", "wait"]
        assert "1. Allocation request · Yunzhan (kind allocation). Needs:" in fire.text and "6. Wait for revised dates (kind wait): the buyer's decision" in fire.text
        assert "$85K [option:disruption:SUP-0001:air_freight:duty_effect]" in fire.text
        assert "- [no_alt_quote] No second source on any PO line or quote for 3 of 5 parts" in fire.text and "restart_window" in fire.finding_facts
        risk = build(svc.attention.get_item("risk:SUP-0002"), svc, str(db_path))
        assert risk.option_kinds[0] == "open_terms" and "survived" not in risk.text and "(kind air_freight)" not in risk.text
        quotes = build(svc.attention.get_item("deadline:quotes"), svc, str(db_path))
        assert "Let the quote lapse (kind lapse): the buyer's decision" in quotes.text            # a kind with no option builder still lists the table's ways
    finally:
        svc.close()


def test_the_prompt_lines_for_stale_orders_linked_documents_small_money_and_a_message_that_moves_a_case():
    """plan-13 item 5: each prompt line is where the agent will read it."""
    from pathlib import Path

    import app.organism as org

    here = Path(org.__file__).parent
    clerk = (here / "specialists" / "buyers_clerk" / "instructions.md").read_text()
    assert "never an email to the supplier: log one question per owning buyer, asking Receiving" in clerk
    assert "add one line for it to this email" in clerk and "a note to enter in the ERP" in clerk
    assert 'Say small money plainly ("small: $2.4K")' in (here / "constitution.md").read_text()
    triage = SimpleNamespace(key="triage:m", group="triage", title="Triage: new dates", owner="", refs=[])
    assert "say which item it moves" in build_prompt(triage, plan=["inbox_analyst", "buyers_clerk"])
    assert "say which item it moves" not in build_prompt(triage, plan=["inbox_analyst"])        # an unvetted sender: the line about the clerk does not apply


def test_missing_origin_owes_one_letter_per_supplier_of_the_parts(db_path):
    """plan-13 item 7: unknown:origin is no longer a roll-up with no clerk; code lists the supplier of each part (its latest order line) and who owns them."""
    from app.organism.workflows.work_item import ROLL_UPS, suppliers_owed

    item = SimpleNamespace(key="unknown:origin", refs=[SimpleNamespace(type="part", id=p) for p in ("HR-13103", "HR-21106", "HR-40220", "HR-40320", "HR-51130")])
    assert "unknown:origin" not in ROLL_UPS and "unknown:hts" in ROLL_UPS
    assert suppliers_owed(item, None, str(db_path)) == {"SUP-0009": "Dana Reyes", "SUP-0010": "Dana Reyes", "SUP-0013": "Priya Nair", "SUP-0018": "Priya Nair"}


def test_the_duty_owed_on_the_fires_lines_is_a_number_the_duty_case_can_cite(session):
    """plan-13 item 8: 'budget $85K on the fire's 7 lines' needs a tariff number: the same figure as the fire's air-freight duty effect."""
    from app.domain.attention import service
    from app.domain.attention.tools import read_item

    numbers, _, _ = read_item(service.item_detail(session, "tariff:all"))
    fire = next(n for n in numbers if n.id == "item:tariff:all:duty_owed_fire:SUP-0001")
    air = {o.kind: o for o in options.fire_options(session, "disruption:SUP-0001")}["air_freight"]
    assert fire.value == air.duty_effect.usd and "Yunzhan's 7 open orders under force majeure" in fire.name and "Nov 1" in fire.name


def test_only_an_insolvent_supplier_has_a_court_appointed_monitor(session):
    """AGENT-EXPERT F79: Vistaray and Quenvara deliver late; they are not in insolvency, so their open question names no monitor."""
    from app.domain.attention import service

    def asks(key):
        return " ".join(f"{u.question} {u.why_it_blocks}" for u in service.item_detail(session, key).unknowns)

    assert "court-appointed monitor" in asks("risk:SUP-0002")
    assert "monitor" not in asks("risk:SUP-0029") and "monitor" not in asks("risk:SUP-0011")


def test_every_specialist_has_a_label_in_the_run_events():
    """AGENTS-UI-13: /api/runs showed 'sourcing_analyst' and 'tariff_analyst' raw."""
    from app.organism.runs.events import LABELS
    from app.organism.specialists.registry import SPECIALISTS

    assert all(LABELS[n] == s.label for n, s in SPECIALISTS.items()) and LABELS["sourcing_analyst"] == "Sourcing analyst"
    assert {"lookout", "verifier", "reviewer"} <= set(LABELS)


def test_the_clerk_marks_past_due_lines_and_greets_by_name():
    from pathlib import Path

    import app.organism as org

    clerk = (Path(org.__file__).parent / "specialists" / "buyers_clerk" / "instructions.md").read_text()
    assert '"(past due)" after each such line' in clerk and 'Open with "Dear <the contact\'s name exactly as on file>,"' in clerk


def test_code_finds_the_facts_on_the_fire_and_the_past_due_case(session):
    """findings.md Rev 2: every figure is code's; the page falls back to the template meaning."""
    from app.domain.attention import findings

    fire = {c.key: c for c in findings.candidates(session, "disruption:SUP-0001")}
    assert list(fire) == ["no_alt_quote", "alt_on_file", "alt_quote_coverage", "supplier_otd", "past_due", "restart_window", "supplier_streak"]
    assert fire["no_alt_quote"].fact == "No second source on any PO line or quote for 3 of 5 parts (HR-40130, HR-40210, HR-40230)"     # Siam (PO line) and Vinh Phuc (quote) count
    assert "Siam Motion has supplied HR-40120" in fire["alt_on_file"].fact and fire["restart_window"].template_meaning.startswith("Nothing from the burned plant")
    assert fire["supplier_streak"].fact == "Yunzhan's last 9 receipts were late (May 6 → Aug 19, +8 to +26 days); late on 65% of 2026 receipts against 12% in 2025"
    assert fire["alt_quote_coverage"].fact == "Vinh Phuc quotes HR-40110 only (1 of 5 parts)"      # UX SL-6: the name a buyer says, not the legal name
    assert "70% of its 53 closed lines (37 of 53)" in fire["supplier_otd"].fact
    assert fire["past_due"].fact == "4 of 10 lines past their promise on Sep 25; 3 were already late before the notice of Sep 22"
    assert fire["restart_window"].fact.startswith("Restart estimated Nov 3 – Nov 17") and all(c.template_meaning for c in fire.values())
    chase = {c.key: c for c in findings.candidates(session, "deadline:chase")}
    assert set(chase) == {"no_word", "feeds_robot", "no_origin", "other_case"} and chase["no_word"].fact.startswith("16 lines")
    assert "HR-40320" in chase["no_origin"].fact and "Hallerbeck" in chase["other_case"].fact
    duty = findings.candidates(session, "tariff:all")
    assert [c.key for c in duty] == ["fire_lines_duty"] and duty[0].fact.startswith("$85K of the duty owed is on Yunzhan's 7 open orders under force majeure")
    assert {c.key: c.fact for c in findings.candidates(session, "disruption:SUP-0013")}["supplier_streak"].startswith("Jadepeak's last 5 receipts were late (Jul 17")   # every supplier case gets its record
    risk = {c.key: c for c in findings.candidates(session, "risk:SUP-0002")}
    assert {"risk_insolvency", "risk_prepayment", "risk_price_jump"} <= set(risk) and "+20.2% at 250 pcs ($445.30), against $370.52" in risk["risk_price_jump"].fact   # "don't prepay" has its reason
    assert [(c.key, c.fact) for c in findings.candidates(session, "unknown:hts")] == [("no_hts", "No HTS code for HR-12120, HR-50310 (China origin): the duty on them cannot be computed")]   # BUYER R2b: an empty block read as nothing found
    aged = {c.key: c.fact for c in findings.candidates(session, "unknown:stale-orders")}
    assert aged["aged_PO-10711"] == "Motor, brushed DC order (PO-10711 line 1): open since Feb 2025, 553 days past due" and len(aged) <= 4


def test_linked_cases_carry_their_own_at_stake_as_a_citable_number_and_the_same_build_links_ranked_last(db_path, monkeypatch):
    """F103 R5/R6: Lookout may connect cases only through the other case's own figure, by id; the fire and Jadepeak stop the same robots in October."""
    from app.organism import services as default_services
    from app.organism.context_packet import build, linked_items

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = default_services.get(str(db_path))
    try:
        fire = svc.attention.get_item("disruption:SUP-0001")
        links = {o.key: why for o, why in linked_items(fire, svc)}
        assert links["disruption:SUP-0013"].startswith("the same build: Porter P5 October")
        assert not links.get("incident:SUP-0018", "").startswith("the same build")   # no month on record for Ruilian's lines: not claimed
        p = build(fire, svc, str(db_path))
        ids = {n.id: n for n in p.numbers if n.id.startswith("linked:")}
        assert "linked:disruption:SUP-0013:at_stake" in ids and f"[linked:disruption:SUP-0013:at_stake]" in p.text and ids["linked:disruption:SUP-0013:at_stake"].say
    finally:
        svc.close()


def test_each_buyers_duty_share_is_split_into_what_cannot_be_avoided_and_what_still_depends(session):
    """BUYER Q6 'How much of my duty share can I still avoid?': the share per buyer, the part on the burned supplier's lines (cannot ship before the duty
    date; the same figure as duty_owed_fire), and the rest, which depends on ship dates or origin proof. All code figures."""
    from decimal import Decimal

    from app.domain.attention import service
    from app.domain.attention.tools import read_item

    numbers, _, _ = read_item(service.item_detail(session, "tariff:all"))
    n = {x.id.removeprefix("item:tariff:all:"): Decimal(x.value) for x in numbers}
    shares = {k: v for k, v in n.items() if k.startswith("duty_share:")}
    assert abs(sum(shares.values()) - n["tile:owed"]) < Decimal("0.05")  # the shares add up to the owed
    assert n["duty_share_fixed:Dana"] == n["duty_owed_fire:SUP-0001"]  # the fire's lines are Dana's
    assert abs(n["duty_share_fixed:Dana"] + n["duty_share_open:Dana"] - n["duty_share:Dana"]) < Decimal("0.05")


def test_every_demo_case_has_code_facts_with_figures(session):
    """R1 (BUYER #12, UX R1-12): Ruilian's findings were empty and others lacked figures; code counts, sums and divides, never the agent."""
    from app.domain.attention import findings, option_kinds

    f = lambda key: {c.key: c.fact for c in findings.candidates(session, key)}  # noqa: E731
    rui = f("incident:SUP-0018")
    assert rui["redated"].startswith("3 lines re-dated to Oct 30 – Nov 20") and rui["late_before"] == "3 of 5 lines were already past their promise on Sep 25; 2 of them have no new date"
    jade = f("disruption:SUP-0013")
    assert jade["moved"].startswith("5 PO lines move out 42 to 49 days") and jade["late_duty"].startswith("$6,422.85 duty on HPO-26-00517/10")
    assert "lead time 8 → 16 weeks" in jade["lead_time"]
    assert f("risk:SUP-0002")["cover"] == "338 HR-12210 on order covers about 4 months at 80 a month"
    assert len(f("deadline:quotes")) == 3 and "expires Oct 16" in f("deadline:quotes")["quote_SUP-0022"]
    gp = f("deadline:SUP-0041:2026-10-15")
    assert "+8.5% on extruded profiles" in gp["rise"] and "$2,392.39" in gp["saving"] and "before stock on hand" in gp["saving"]
    slip_rows = {o.kind: o for o in option_kinds.option_kinds(session, "disruption:SUP-0013")}
    assert "8 → 16 weeks" in slip_rows["order_before"].changes                              # cited from the supplier's own notice


def test_an_incident_run_is_told_it_is_not_a_fire():
    item = SimpleNamespace(key="incident:SUP-0018", group="disruption", title="Ruilian cyberattack", owner="Priya", refs=[], numbers=[])
    p = build_prompt(item)
    assert "incident, not a fire" in p and "no allocation" in p
    assert "incident, not a fire" not in build_prompt(SimpleNamespace(key="disruption:SUP-0001", group="disruption", title="Fire", owner="Dana", refs=[], numbers=[]))
