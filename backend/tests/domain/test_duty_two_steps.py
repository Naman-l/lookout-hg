"""BUYER 02: the duty roll-up recommends the broker exclusion with a reason that names the $85K owed on lines that cannot ship; the case's next
step is two steps (budget it, ask the broker), so the reason says both."""
from app.domain.attention.api import two_step_duty


def _answer(kind="broker_exclusion", ids=("item:tariff:all:duty_owed_fire:SUP-0001",), reason="$85K owed on fire lines that cannot ship"):
    return {"finding": "x", "recommended": {"kind": kind, "reason": reason, "number_ids": list(ids)}}


def test_the_broker_exclusion_for_the_fire_lines_names_both_steps():
    out = two_step_duty("tariff:all", _answer())
    assert out["recommended"]["reason"] == "$85K owed on fire lines that cannot ship: budget it, and ask the broker for an exclusion"
    assert out["recommended"]["kind"] == "broker_exclusion" and out["recommended"]["number_ids"] == ["item:tariff:all:duty_owed_fire:SUP-0001"]


def test_anything_else_is_left_as_the_agent_said_it():
    for key, a in [("disruption:SUP-0001", _answer()), ("tariff:all", _answer(kind="accept")), ("tariff:all", _answer(ids=("item:tariff:all:at_stake",))),
                   ("tariff:all", _answer(reason="budget the $85K")), ("tariff:all", None), ("tariff:all", {"finding": "x"})]:
        assert two_step_duty(key, a) == a
