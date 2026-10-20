from evals import behaviour


def _t(*owners):
    return {"all_actions": [{"action_id": f"A{i}", "type": "supplier_request", "recipient": "li@x", "state": "proposed", "change": {"owner": o}} for i, o in enumerate(owners)], "runs": []}


SPEC = {"type": "supplier_request", "recipient": "li@x", "count": 1, "per": "owner"}


def test_two_buyers_may_each_hold_a_request_to_one_contact_but_not_two_for_one_owner():
    assert behaviour.grade_sequence(SPEC, _t("Dana Reyes", "Tom Albrecht"))["passed"]
    assert behaviour.grade_sequence(SPEC, _t("Dana Reyes"))["passed"]
    bad = behaviour.grade_sequence(SPEC, _t("Dana Reyes", "Dana Reyes"))
    assert not bad["passed"] and "same owner" in bad["detail"]
    assert not behaviour.grade_sequence(SPEC, _t())["passed"]                      # nothing staged is not a pass


def test_without_the_per_owner_rule_two_requests_still_fail():
    assert not behaviour.grade_sequence({**SPEC, "per": None}, _t("Dana Reyes", "Tom Albrecht"))["passed"]
