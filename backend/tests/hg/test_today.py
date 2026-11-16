"""Today on the 20 Oct data: one case per cause, the tabs the plan expects, every story's figure computed by its rule, the folds, and each member's share."""

from decimal import Decimal

from app.domain.attention import service

TABS = {"requirement": 3, "after_po": 4, "price": 6, "payments": 3, "vendor_risk": 5, "trust": 3, "unknown": 3}


def amount(i) -> float:
    return float(i.at_stake.amount) if i.at_stake is not None and hasattr(i.at_stake, "amount") else None


def test_one_case_per_cause_in_the_tabs_the_plan_expects(session):
    items = service.what_needs_attention(session)
    assert len(items) == 27
    got = {}
    for i in items:
        got[i.tab] = got.get(i.tab, 0) + 1
    assert got == TABS


def test_each_story_fires_with_the_figure_its_rule_gives(session):
    by = {i.key: i for i in service.what_needs_attention(session)}
    assert amount(by["mfc-validity:4500120768"]) == 14_000_000          # the vendor's stated claim if the MFC comes after the validity
    assert round(amount(by["pr-cancelled:gaya:2026-10-15"]) / 1e5) == 343   # the enquiry at the lowest quotes: ₹3.43 Cr
    assert abs(amount(by["pv-claim:4500121087"]) - (5_294_689 - 4_356_293)) < 1   # claimed less the PV on the PO's own base month
    assert amount(by["inspection-ready:4500121346"]) == 33 * 18_000      # storage from the end of free storage to the plinth date
    assert amount(by["commissioning:4500087611"]) == 1_500_000
    assert amount(by["abg:ABG/UTPL/2025/118"]) == 26_400_000
    assert round(amount(by["lc:4500123578"]) / 1e7) == 320
    assert amount(by["l1-above-last:tumkur:11000020"]) == (720 - 650) * 128_000
    assert by["pr-stuck:1000203689"].waiting_on == "Projects"
    assert by["pr-late:1000204034"].act_by == "2026-11-03"
    assert {i.key for i in by.values() if i.tab == "trust"} == {k for k in by if k.startswith("trust:")}


def test_folds_keep_one_row_per_cause_and_every_child_resolves(session):
    by = {i.key: i for i in service.what_needs_attention(session)}
    assert "schedule-slip:100601" in {d.key for d in by["late-streak:100601"].dated}
    assert any(d.key.startswith("quote-lapse:") for d in by["pv-longlead:bess-chorniya"].dated)
    assert {d.key for d in by["fund-mismatch:2026-11"].dated} == {"fund-mismatch:2026-10", "fund-mismatch:2026-12"}
    assert by["rate-spread:11000020"].dated
    for i in by.values():
        for d in i.dated:
            assert service.item_detail(session, d.key) is not None
            assert d.key not in by


def test_yours_is_each_members_share_of_a_team_case(session):
    team = {i.key: i for i in service.what_needs_attention(session)}
    jitender = {i.key: i for i in service.what_needs_attention(session, "Jitender")}
    assert "rate-spread:11000020" in jitender and amount(jitender["rate-spread:11000020"]) < amount(team["rate-spread:11000020"])
    assert jitender["rate-spread:11000020"].team_total is not None
    sudeep = {i.key for i in service.what_needs_attention(session, "Sudeep")}
    assert "fund-mismatch:2026-11" in sudeep and any(k.startswith("trust:") and "fund_transfer" in k for k in sudeep)
    from app.domain import lookups
    for who in lookups.team(session):
        for i in service.what_needs_attention(session, who):
            assert who in i.owner_ids


def test_a_figure_that_cannot_be_computed_is_an_unknown_with_an_owner(session):
    d = service.item_detail(session, "unknown:no-budget-rate")
    assert d.unknowns and all(u.owner for u in d.unknowns)
    assert Decimal(1)  # every money case carries its rule
    for i in service.what_needs_attention(session):
        if i.at_stake is not None and hasattr(i.at_stake, "amount"):
            assert i.at_stake_rule, i.key
