"""Records (FINAL 06): each part names the robots it goes into, and a message held for imitating a supplier is filed under that supplier (#17)."""

from app.domain.attention import service as attention
from app.domain.parts import service as parts


def test_each_part_names_the_robots_whose_bom_uses_it(session):
    by = {p.ref.id: p for p in parts.list_parts(session)}
    assert by["HR-40110"].robots == ["HR-90020"]      # the Tern drive motor
    assert by["HR-30110"].robots == ["HR-90020", "HR-90050", "HR-90110"]      # the safety controller, in every robot
    assert by["HR-12210"].robots == ["HR-90050"]      # the Porter gearbox
    assert sum(1 for p in by.values() if p.robots) == 288 and len(by) == 502      # the rest are in no robot's BOM


def test_a_look_alike_sender_is_filed_under_the_supplier_it_imitates(session):
    trust = {i.key: i for i in attention.what_needs_attention(session) if i.group == "trust"}
    fraud = next(i for k, i in trust.items() if k.startswith("trust:2026-09-23"))
    assert [(r.type, r.id) for r in fraud.refs if r.type == "supplier"] == [("supplier", "SUP-0001")]
    spot = next(i for k, i in trust.items() if k.startswith("trust:2026-09-12"))
    assert [(r.type, r.id) for r in spot.refs if r.type == "supplier"] == [("supplier", "SUP-0027")]      # a sender on file keeps its own record
    assert all(not i.robots for i in trust.values())      # filing it under the supplier lights no robot


def test_measured_lead_time_beside_the_planned_one(session):
    from app.domain.parts.service import lead_time_actual, lead_time_bias

    bias = lead_time_bias(session)      # the planning-parameter finding (LOOKOUT pain-patterns/stats2.py)
    assert (bias["lines"], bias["later"], bias["median_overrun_days"], bias["median_actual_days"]) == (2340, 2303, 32, 69)
    a = lead_time_actual(session, "HR-40110")
    assert (a.planned_days, a.median_days, a.receipts, a.later) == (35, 84, 18, 18) and len(a.lines) == 18
