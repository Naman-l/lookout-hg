"""The claim rules on answers (answer_rules), on the shipped recordings and on changed figures: a planned count is never 'short', the rise on the
uncovered need is never 'at stake', no robots are named hit when none is short. Recorded answers are served with the rules applied."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

from app.domain.attention import service
from app.organism.answer_rules import correct_answer, fix_planned_short, fix_robots_hit, fix_stake_scope

REC = Path(__file__).resolve().parents[2] / "app" / "organism" / "recordings"


OLD = {   # what the recordings said before the claim rules and the re-records of 2026-10-14: the safety net still corrects such a sentence, marked
    "consignment:HR-30110": ("Lanxin's PCB slips 21 days; up to 182 Tern T2 robots short in October.", [{"id": "item:consignment:HR-30110:tile:robots:HR-90020:2026-10", "value": "182"}],
                             "Lanxin's PCB slips 21 days; 182 Tern T2 robots planned in October."),
    "deadline:SUP-0041:2026-10-15": ("Great Plains' price rise from November hits 5 open lines; $2,392.39 at stake.", [],
                                     "Great Plains' price rise from November hits 5 open lines; $2,392.39 on the need open orders don't cover."),
    "deadline:chase": ("16 late lines, $496K open, hit Heron H1, Porter P5, Tern T2 October.", [], "16 late lines, $496K open."),
}


def test_a_sentence_that_breaks_a_rule_is_served_corrected_and_marked(session):
    for key, (old, nums, fixed) in OLD.items():
        out = correct_answer({"finding": old, "numbers": nums}, service.item_detail(session, key))
        assert out["finding"] == fixed and out["corrections"] and all(c.startswith("corrected by a rule: ") for c in out["corrections"]), key


def test_after_the_re_records_no_shipped_recording_needs_a_correction(session):
    for path in sorted(REC.glob("*.json")):
        doc = json.loads(path.read_text())
        detail = service.item_detail(session, doc["item_key"]) if doc.get("recommendation") else None
        if detail is not None:
            assert correct_answer(doc["recommendation"], detail) is doc["recommendation"] or correct_answer(doc["recommendation"], detail) == doc["recommendation"], path.name


def test_on_changed_figures_each_rule_follows_the_figures_meaning():
    planned = [(Decimal(240), "Alpha A1 planned in March")]
    assert fix_planned_short("up to 240 Alpha A1 robots short in March", planned) == "240 Alpha A1 robots planned in March"
    both = planned + [(Decimal(240), "Units short in 2027-03")]
    assert fix_planned_short("240 Alpha A1 robots short in March", both) == "240 Alpha A1 robots short in March"     # a real shortfall of that size: kept
    assert fix_stake_scope("$9.10 at stake", "the rise on the need that open orders do not cover") == "$9.10 on the need open orders don't cover"
    assert fix_stake_scope("$9.10 at stake", "open value of the lines on the notice") == "$9.10 at stake"
    assert fix_robots_hit("3 late lines, hit Alpha A1 in March.", [], ["Alpha A1"]) == "3 late lines."
    assert fix_robots_hit("3 late lines, hit Alpha A1 in March.", [NS(product="Alpha A1")], ["Alpha A1"]) == "3 late lines, hit Alpha A1 in March."


def test_the_run_page_gets_the_same_marked_correction(session):
    from app.organism.answer_rules import correct_recommendation
    from app.organism.schemas import Recommendation

    old, nums, fixed = OLD["deadline:chase"]
    rec = correct_recommendation(Recommendation(finding=old, numbers=[]), service.item_detail(session, "deadline:chase"))
    assert rec.finding == fixed and rec.corrections == ["corrected by a rule: the records show no robot short"]
