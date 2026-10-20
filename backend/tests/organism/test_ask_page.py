"""h10: Ask knows the page the buyer asked from and what it can do there; it never claims a screen action it cannot do."""
from app.organism.workflows.ask import build_prompt, page_lines


def test_the_prompt_names_the_page_and_what_lookout_can_do_there():
    p = build_prompt("what page am I on?", None, "Dana Reyes", None, {"kind": "today", "label": "Today · Yours · Disruption"})
    assert "The buyer is on Today · Yours · Disruption in Lookout: the buyer's list of cases that need a decision" in p
    assert "You cannot click, filter, sort or change what is on the screen" in p
    case = page_lines({"kind": "case", "label": "Yunzhan fire"})
    assert "stage a decision or a note on this case" in case[1] and "amend its waiting draft" in case[1]


def test_no_page_changes_nothing_and_layout_words_stay_banned():
    p = build_prompt("what page am I on?", None, "Dana Reyes")
    assert "The buyer is on" not in p and "never point to the layout" in p
    assert page_lines(None) == [] and page_lines({"kind": ""}) == []
