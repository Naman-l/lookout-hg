from evals import report_html


def test_the_one_screen_report_builds_from_the_committed_reports():
    page = report_html.build()
    for needle in ("Controls: guardrails graded on behaviour", "The agent", "How far to trust the graders", "Not in the answer sheet", "control-unknown-origin", "tariff-hr40110", "Spend so far"):
        assert needle in page, needle
    assert "<script" not in page   # a static page: nothing to fetch, nothing to run


def test_a_case_opens_to_the_question_the_expected_facts_against_the_actual_the_judge_and_the_answer():
    case = {"category": "hard", "reason": "why it matters", "source": "data/x.csv", "start": {"post": "/api/messages/{message}/reply-runs", "message": "M1"},
            "expected": {"facts": [{"name": "owed", "id": "tariff:P:net", "value": 100, "source_table": "purchase_orders"}, {"name": "price", "value": 5000, "tolerance": 0.01},
                                   {"name": "never_said", "value": 777}]}}
    trial = {"status": "FAIL", "detail": "must_mention: missing: ['EXW']; facts: never_said: no number id agreed yet", "prose": "failed",
             "recommendation": {"finding": "The price is 5,000 USD and the duty 100.", "assumptions": ["a"], "would_change": ["b"], "open_questions": [], "numbers": [{"id": "tariff:P:net", "value": 100, "name": "duty"}]},
             "judge": [{"name": "buyer's words", "ok": False, "why": "an id stands in for a name", "quote": "the duty 100"}],
             "facts": [{"fact": "owed", "expected": 100, "via": "id", "got": 100, "status": "right"}, {"fact": "price", "expected": 5000, "via": "found in the answer", "got": 5000, "status": "right"},
                       {"fact": "never_said", "expected": 777, "via": None, "got": None, "status": "not measured"}]}
    card = report_html.case_card("c1", case, {"status": "FAIL", "trials": [trial]}, "Round 9: x. Agent: keep the EXW term beside the price. More.")
    for needle in ("Reply run on the message M1", "why it matters", "data/x.csv", "Expected against actual", "found in the answer", "not measured", "an id stands in for a name",
                   "the duty 100", "The price is 5,000 USD", "What we would change", "keep the EXW term beside the price"):
        assert needle in card, needle
    assert "More." not in card          # one line of what we would change, not the paragraph


def test_the_commercial_facts_headline_counts_right_wrong_and_not_measured_apart():
    from evals import report
    res = {"a": {"trials": [{"status": "FAIL", "facts": [{"status": "right", "via": "id"}, {"status": "right", "via": "found in the answer"}, {"status": "wrong", "via": "id"}, {"status": "not measured", "via": None}]}]}}
    h = report.facts_headline(res, {"a": {}})
    assert "2 right (1 of them only found in the answer's words" in h and "1 wrong" in h and "1 not measured" in h
    assert "not recorded" in report.facts_headline({"a": {"trials": [{"status": "FAIL"}]}}, {"a": {}})
    assert report.change_line("Round 9: lots of history. Agent/DOMAIN: names before ids. Also more.") == "names before ids"
