"""The Reviewer's grade, the one revision round and the grade strip, with the Reviewer itself replaced (no model)."""

from types import SimpleNamespace

import pytest

from app.organism import review as rv
from app.organism.workflows import judging as jd

from .test_verifier import good, seed


def graded(*passes, critical_fail=False):
    """A Review with one check per flag; a failed check gets a critique."""
    return rv.Review(checks=[rv.CheckResult(name=f"c{i}", passed=ok, critique="" if ok else "gap", critical=(critical_fail and not ok)) for i, ok in enumerate(passes)], summary="ok")


def test_the_score_is_the_share_of_checks_passed():
    assert graded(True, True, True, True, True).score == 100 and graded(True, True, True, False, False).score == 60 and graded(False, False).score == 0


def test_one_revision_round_only_for_a_failed_code_check_or_a_failed_critical_check():
    assert rv.needs_revision(False, graded(True, True), revised=False)  # a code check failed
    assert rv.needs_revision(True, graded(True, False, critical_fail=True), revised=False)  # 'nothing in it commits Halden' failed
    assert not rv.needs_revision(True, graded(False, False, False), revised=False)  # soft fails are shown, not acted on
    assert not rv.needs_revision(False, graded(False, critical_fail=True), revised=True)  # already revised: shown as it is
    assert not rv.needs_revision(True, None, revised=False)  # ungraded is not a failure


def test_the_revision_prompt_carries_the_failed_checks_and_their_critiques():
    p = rv.revision_prompt({"failures": ["prose: numbers in the text that no tool returned: 40"]}, graded(True, False))
    assert "no tool returned: 40" in p and "c1: gap" in p and "once" in p


def test_every_kind_has_a_binary_sheet_with_the_common_checks_and_one_critical_check():
    for kind in ("disruption", "risk", "incident", "tariff", "unknown", "deadline", "compare", "ask", "import"):
        sheet = rv.sheet_for(kind)
        names = [c["name"] for c in sheet]
        assert "answers the buyer's question" in names and "nothing in it commits Halden" in names and len(names) == len(set(names))
        assert [c["name"] for c in sheet if c.get("critical")] == ["nothing in it commits Halden"]
        assert all(("PASS" in c["asks"] and "FAIL" in c["asks"]) or "FAIL" in c["asks"] for c in sheet)
    assert any("what is owed, the most it could be" in c["name"] for c in rv.sheet_for("tariff"))   # F6/F108: never "net beside gross" in a buyer's words


def test_the_buyers_words_check_lists_the_terms_that_fail():
    asks = next(c["asks"] for c in rv.sheet_for("common") if c["name"] == "buyer's words")
    for term in ("alias", "analyst", "normaliser", "qty_received", "purchase_orders export", "the tool", "run id"):
        assert term in asks
    assert "Part numbers, PO numbers and quote numbers are fine" in asks


def test_the_assumptions_check_defines_an_assumption_and_names_what_fails():
    asks = next(c["asks"] for c in rv.sheet_for("common") if c["name"] == "assumptions are really assumptions")
    assert "NOT known" in asks and "importer of record" in asks and "stock is zero" in asks and "origin is China" in asks


def test_the_reviewers_one_turn_reply_is_parsed_into_pass_fail_and_anything_malformed_is_ungraded():
    n = len(rv.sheet_for("disruption"))
    flags = ["true"] * (n - 1) + ["false"]
    ok = '{"pass": [' + ",".join(flags) + f'], "critique": {{"{n}": "no month named"}}, "summary": "Good."}}'
    r = rv.parse("Here you go:\n" + ok, "disruption")
    assert r and r.score == round(100 * (n - 1) / n) and r.failed[0].critique == "no month named" and r.checks[2].critical
    assert rv.parse("not json", "disruption") is None
    assert rv.parse('{"pass": [true, true], "summary": "x"}', "disruption") is None  # wrong number of answers
    assert rv.parse('{"pass": [' + ",".join(["1"] * n) + '], "summary": "x"}', "disruption") is None  # 1 is not a verdict: pass or fail only


async def run_judge(ctx, db, services, monkeypatch, reviews, mode="inline"):
    seed(ctx, db)
    queue = list(reviews)

    async def fake_review(kind, title, rec, verifier, drafts=None, only_critical=False):
        return queue.pop(0), 0.01

    monkeypatch.setattr(jd, "review", fake_review)
    monkeypatch.setattr(jd, "MODE", mode)
    j = jd.Judging(kind="disruption", title="Fire", services=services, max_cost=1.0)
    result = SimpleNamespace(ctx=ctx, structured_output=good(ctx_action(ctx)), cost_usd=0.05, status="ok")
    return j, result


def ctx_action(ctx):
    from app.domain.actions import ledger

    return ledger.get(ctx.db_path, ctx.action_ids[0])


async def test_a_low_score_revises_once_and_the_final_answer_carries_the_grade(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [graded(True, False, True, False, True, critical_fail=True)])
    again = await j(result)
    assert again and "gap" in again and j.revised
    assert await j(result) is None  # second answer: judged, never revised again
    status, rec_json, ver_json = j.finish(result)
    assert status == "ok" and '"revised":true' in rec_json.replace(" ", "") and '"reviewer_score":60' in rec_json.replace(" ", "")
    types = [e.type for e in ctx.recorder.events]
    assert types.count("review.result") == 1 and types.count("revision.started") == 1 and types.count("verifier.result") == 2  # one review, one revision
    assert result.cost_usd == pytest.approx(0.06)  # the reviewer's cost is part of the run's


async def test_a_good_score_is_not_revised_and_an_unrunnable_reviewer_is_shown_as_ungraded(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [graded(True, True, True, True, True)])
    assert await j(result) is None and not j.revised
    j2, result2 = await run_judge(ctx, db, services, monkeypatch, [None])
    assert await j2(result2) is None
    _, rec_json, _ = j2.finish(result2)
    assert '"reviewer_score":null' in rec_json.replace(" ", "") and "Not graded" in rec_json


async def test_a_revision_that_breaks_a_code_check_is_discarded(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [graded(False, False, False, False, False, critical_fail=True)])
    assert await j(result)  # first answer is fine by code but poor: revise
    result.structured_output = dict(result.structured_output, finding="It is 77 days late.")  # the revision invents a figure
    assert await j(result) is None
    status, rec_json, _ = j.finish(result)
    assert status == "ok" and j.revision_rejected and "first answer kept" in rec_json and "77 days" not in rec_json



async def test_by_default_the_grade_follows_delivery_and_never_changes_the_run(ctx, db, services, monkeypatch):
    from app.organism.runs import store

    j, result = await run_judge(ctx, db, services, monkeypatch, [graded(True), graded(True, True, True, False, False)], mode="after")  # the first is the draft check
    assert await j(result) is None and j.graded is None  # delivery is not held up by the full grade
    status, rec_json, ver_json = j.finish(result)
    store.insert_run(db, run_id=ctx.run_id, item_key=ctx.item_key, workflow="w", status=status, started_at="now", recommendation_json=rec_json, verifier_json=ver_json, cost_usd=0.05)
    await j.grade_after(result)
    row = store.read_run(db, ctx.run_id)
    assert row["status"] == "ok" and '"reviewer_score": 60' in row["recommendation_json"] and row["cost_usd"] == pytest.approx(0.06)
    assert [e.type for e in ctx.recorder.events].count("review.result") == 1


async def test_a_failed_code_check_still_revises_once_even_when_grading_is_after(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [], mode="after")
    result.structured_output = dict(result.structured_output, finding="It is 77 days late.")
    again = await j(result)
    assert again and "77" in again and j.revised


def test_the_common_sheet_is_not_added_to_itself():
    names = [c["name"] for c in rv.sheet_for("common")]
    assert len(names) == len(set(names)) and names == [c["name"] for c in rv._SHEETS["common"]]


async def test_a_staged_request_that_commits_halden_sends_lookout_back_once_before_delivery(ctx, db, services, monkeypatch):
    seen = {}

    async def fake_review(kind, title, rec, verifier, drafts=None, only_critical=False):
        seen.update(drafts=drafts, only_critical=only_critical)
        return graded(False, critical_fail=True), 0.01

    j, result = await run_judge(ctx, db, services, monkeypatch, [], mode="after")
    monkeypatch.setattr(jd, "review", fake_review)
    again = await j(result)
    assert again and "gap" in again and j.revised
    assert seen["only_critical"] and seen["drafts"][0]["to"] == "li.wei@yunzhan-motor.example" and "revised dates" in seen["drafts"][0]["body"].lower()
    assert any("to something" in e.summary and e.summary.startswith("The Reviewer read the drafted request: it commits") for e in ctx.recorder.events if e.type == "step.text")
    assert await j(result) is None  # one revision only


async def test_with_nothing_staged_delivery_waits_for_no_reviewer(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [], mode="after")
    ctx.action_ids.clear()
    result.structured_output = dict(result.structured_output, action_ids=[])
    assert await j(result) is None  # no review was queued: asking for one would have raised


def test_the_draft_check_reads_the_critical_check_and_the_request():
    sheet = rv.sheet_for("disruption", only_critical=True)
    assert [c["name"] for c in sheet] == ["nothing in it commits Halden"]
    p = rv.build_prompt("disruption", "Fire", {"finding": "f", "numbers": []}, {"passed": True}, drafts=[{"to": "a@b.example", "subject": "s", "body": "We award you the order."}], only_critical=True)
    assert "We award you the order." in p and "answers the buyer's question" not in p
    assert rv.parse('{"pass": [false], "critique": {"1": "awards"}, "summary": "x"}', "disruption", only_critical=True).failed[0].critical


async def test_a_failed_check_is_named_in_the_grade_in_plain_words(ctx, db, services, monkeypatch):
    j, result = await run_judge(ctx, db, services, monkeypatch, [graded(True), graded(True, False, True, False, True)], mode="after")
    assert await j(result) is None
    j.graded = graded(True, False, True, False, True)
    _, rec_json, _ = j.finish(result)
    import json as _json

    assert [c["name"] for c in _json.loads(rec_json)["grade"]["failed_checks"]] == ["c1", "c3"] and _json.loads(rec_json)["grade"]["failed_checks"][0]["reason"] == "gap"


def test_the_reviewer_reads_the_recommendation_in_words_never_our_field_names():
    rec = {"finding": "Yunzhan stops ten lines.", "assumptions": ["Stock is unknown."], "would_change": ["Dana's stock count."],
           "open_questions": [{"what": "on-hand stock", "why_it_blocks": "cover cannot be shown", "owner": "Dana", "question": "How many are on the shelf?"}],
           "numbers": [{"id": "shortage:HR-40110:2026-10:short", "name": "Units short in October", "value": "364", "unit": "EA"}]}
    p = rv.build_prompt("disruption", "Fire", rec, {"passed": True}, drafts=[{"to": "a@b.example", "subject": "Dates", "body": "Please confirm."}])
    for field_name in ("why_it_blocks", "would_change", "open_questions", "assumptions\"", "{\n", "\"finding\""):
        assert field_name not in p, field_name
    assert "Finding: Yunzhan stops ten lines." in p and "Why it blocks: cover cannot be shown. Owner: Dana." in p and "Units short in October: 364 EA" in p and "Please confirm." in p


def test_the_reviewer_reads_the_next_step_and_the_picks_of_a_case_run():
    """F108 preview: both live fire runs failed 'answers the buyer's question' only because the Reviewer never saw the next step, where a case's action lives (F74)."""
    from app.organism import review

    text = review.render({"finding": "Yunzhan's fire stops 10 PO lines; Terns short in October.", "next_step": {"who": "Dana Reyes", "what": "Approve the request to Li Wei", "by": "Oct 10"},
                          "recommended": {"kind": "allocation", "reason": "10 lines, one email"}, "case_findings": [{"key": "no_alt_quote", "meaning": "Three parts have no second source"}],
                          "numbers": [], "open_questions": []})
    assert "Next step: Dana Reyes · Approve the request to Li Wei · Oct 10" in text and "Recommended way through: allocation" in text and "- Three parts have no second source" in text and "no_alt_quote" not in text
    assert "next step carries the action" in (review.Path(review.__file__).parent / "grades.yaml").read_text()


def test_risk_and_incident_runs_are_graded_on_their_own_sheet_and_the_header_has_no_field_label():
    """F108 preview: risk and Ruilian were graded on the fire's 'asks for allocation'; the deadline runs failed 'buyer's words' on 'kind: deadline' in the header."""
    from types import SimpleNamespace

    from app.organism import review
    from app.organism.workflows.work_item import review_kind

    assert review_kind(SimpleNamespace(key="risk:SUP-0002", group="disruption")) == "risk" and review_kind(SimpleNamespace(key="incident:SUP-0018", group="disruption")) == "incident"
    assert review_kind(SimpleNamespace(key="disruption:SUP-0001", group="disruption")) == "disruption"
    assert any("never advises paying ahead" in c["asks"] for c in review.sheet_for("risk")) and any("nothing burned" in c["asks"] for c in review.sheet_for("incident"))
    assert not any("gross beside" in c["asks"] for c in review.sheet_for("tariff"))
    assert "(kind:" not in review.build_prompt("deadline", "Great Plains price rise", {"finding": "x", "numbers": [], "open_questions": []}, {})


def test_the_changed_checks_still_ask_for_what_they_guard_and_an_empty_next_step_shows_nothing():
    """Integrity rule (SIDEQ, AGENT-EXPERT): a grader change only removes the design conflict; each check still fails an answer that lacks the thing."""
    from app.organism import review

    text = review.render({"finding": "Yunzhan's fire stops 10 PO lines.", "next_step": {"who": "", "what": "", "by": ""}, "numbers": [], "open_questions": []})
    assert "Next step:" not in text                                                          # no action anywhere: nothing for check 1 to credit
    first = next(c for c in review.sheet_for("disruption") if c["name"] == "answers the buyer's question")["asks"]
    assert "missing from both" in first
    tariff = review.sheet_for("tariff")[-1]["asks"]
    assert "importer of record and which lines enter in time" in tariff and "where the records give them" not in tariff
    assert "names the robot builds" in review.sheet_for("incident")[-1]["asks"] and "never advises paying ahead" in review.sheet_for("risk")[-1]["asks"]


def test_the_reviewer_reads_the_recommended_option_in_words_not_its_kind_id():
    """R2: 'broker_exclusion' / 'ask_receiving' in the Reviewer packet failed 'buyer's words'; the id is the page's, never the buyer's."""
    from app.organism import review

    text = review.render({"finding": "x", "recommended": {"kind": "broker_exclusion", "reason": "only way to cut it before Nov 1"}, "numbers": [], "open_questions": []})
    assert "broker exclusion" in text and "broker_exclusion" not in text
