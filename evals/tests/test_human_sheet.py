import json

import yaml

from evals import human_sheet
from evals.human_sheet import OUT

PACKETS = yaml.safe_load((OUT / "packets.yaml").read_text())
KEY = json.loads((OUT / "key.json").read_text())


def test_forty_items_every_planted_defect_in_a_common_check_and_no_leak_of_which():
    items = human_sheet.pick(PACKETS, KEY)
    assert len(items) == 40 and len({(i["packet"], i["check"]) for i in items}) == 40
    assert sum(i["planted"] for i in items) == 19
    assert {i["check"] for i in items} == set(human_sheet.COMMON)
    page = human_sheet.PAGE.replace("__ITEMS__", json.dumps([{"n": 1, "title": "t", "asks": "a", "parts": []}]))
    assert "planted" not in page and "corrupt" not in page.lower()
    assert [i["n"] for i in items] == list(range(1, 41))


def test_answers_parse_and_score_against_the_reviewers_stored_scores():
    items = [{"packet": "P01", "check": "nothing is committed", "planted": False, "n": 1},
             {"packet": "P02", "check": "buyer's words", "planted": True, "n": 2}]
    key = {"P01": {"reviewer": {"nothing is committed": 2}}, "P02": {"reviewer": {"buyer's words": 0}}}
    got = human_sheet.parse("P01 | nothing is committed | yes\nP02 | buyer's words | no\nnoise")
    res = human_sheet.score(got, items, key)
    assert res["agreement"]["rate"] == 1.0 and res["person_rejected_planted_defects"]["rate"] == 1.0
    res = human_sheet.score({("P01", "nothing is committed"): "no", ("P02", "buyer's words"): "yes"}, items, key)
    assert res["agreement"]["rate"] == 0.0 and res["person_rejected_planted_defects"]["rate"] == 0.0
