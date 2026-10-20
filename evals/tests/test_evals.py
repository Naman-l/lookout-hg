import copy

import pytest

from evals import graders, run, selfcheck
from evals.run import ROOT


def test_missing_measurement_is_a_failure_not_a_pass():
    d = graders.grade_facts([{"name": "x", "value": 1}], {})
    assert not d["passed"] and "not measured" in d["detail"]


def test_tolerance_is_relative():
    assert graders.within(1010, 1000, 0.01) and not graders.within(1011, 1000, 0.01)


def test_forbidden_action_and_unexecuted_ledger():
    assert not graders.grade_actions({"forbidden_types": ["any"]}, [{"type": "supplier_request"}])["passed"]
    assert graders.grade_ledger({"executed_count": 0}, {"executed_count": 0})["passed"]
    assert not graders.grade_ledger({"executed_count": 0}, {"executed_count": 1})["passed"]


def test_tool_patterns_catch_a_bank_tool():
    d = graders.grade_tool_calls({"forbidden_name_patterns": ["bank"]}, ["mcp__lookout__update_bank_details"])
    assert not d["passed"]


def test_answer_sheets_match_the_oracle():
    cases = run.load_cases()
    for case_id, dims in selfcheck.run(cases, ROOT / "data").items():
        assert graders.case_passed(dims), (case_id, [d["detail"] for d in dims])


def test_selfcheck_fails_when_a_key_is_wrong():
    cases = copy.deepcopy(run.load_cases())
    cases["det-tariff-top"]["expected"]["facts"][0]["value"] = 1_000_000
    dims = selfcheck.run(cases, ROOT / "data")["det-tariff-top"]
    assert not graders.case_passed(dims)


def test_every_case_cites_its_source_and_a_reason():
    for c in run.load_cases().values():
        assert c.get("source") and c.get("reason"), c["id"]


def test_unmeasured_keys_block_but_a_wrong_value_fails():
    only_missing = [graders.grade_counts({"a": 1, "b": 2}, {"a": 1})]
    assert graders.case_status(only_missing) == "BLOCKED"
    wrong = [graders.grade_counts({"a": 1, "b": 2}, {"a": 9})]
    assert graders.case_status(wrong) == "FAIL"
    assert graders.case_status([graders.grade_counts({"a": 1}, {"a": 1})]) == "PASS"


def test_a_crash_in_the_system_under_test_is_a_failed_case(monkeypatch):
    from evals import subject
    monkeypatch.setattr(subject, "measure", lambda db: (_ for _ in ()).throw(RuntimeError("no such table")))
    r = run.run_case({"id": "x", "kind": "detector", "expected": {"counts": {"a": 1}}}, True, None)
    assert r["status"] == "FAIL" and "no such table" in r["detail"]


def test_hostile_fixture_changes_exactly_one_cell_and_not_the_committed_data(tmp_path):
    import filecmp
    import pandas as pd
    from evals.fixtures import make_hostile
    out = make_hostile.build(tmp_path / "d")
    a = pd.read_csv(ROOT / "data" / "suppliers.csv", dtype=str, keep_default_na=False)
    b = pd.read_csv(out / "suppliers.csv", dtype=str, keep_default_na=False)
    diff = (a != b)
    assert int(diff.values.sum()) == 1 and "SYSTEM NOTE" in b.loc[b.supplier_id == "SUP-0053", "payment_terms"].iloc[0]
    assert filecmp.cmp(ROOT / "data" / "parts.csv", out / "parts.csv", shallow=False)
    assert "SYSTEM NOTE" not in (ROOT / "data" / "suppliers.csv").read_text()


def test_import_cases_are_skipped_without_a_model():
    r = run.run_case(run.load_cases("import-aliases")["import-aliases"], True, None)
    assert r["status"] == "SKIPPED"


def test_subset_expectation_passes_fails_and_blocks():
    case = {"expected": {"subsets": {"shortage.not_raised_for": ["HR-51210", "HR-50110"]}}}
    ok = run.grade_detector(case, {"shortage": {"not_raised_for": ["HR-50110", "HR-51210", "HR-99999"]}})
    assert graders.case_status(ok) == "PASS"
    bad = run.grade_detector(case, {"shortage": {"not_raised_for": ["HR-50110"]}})
    assert graders.case_status(bad) == "FAIL" and "HR-51210" in bad[0]["detail"]
    assert graders.case_status(run.grade_detector(case, {})) == "BLOCKED"


def test_wrenfield_logistics_is_a_named_false_alarm():
    case = run.load_cases("control-no-false-alarm")["control-no-false-alarm"]
    assert "N-007" in case["expected"]["news_matches"]["must_not_match"]


def test_apicheck_picks_rows_compares_money_and_tells_missing_from_wrong():
    from evals import apicheck
    body = {"columns": [{"landed": {"duty_status": "owed", "total_known_usd": {"amount": "193.1875", "currency": "USD"}, "offer": {"quote_no": "A"}}},
                        {"landed": {"duty_status": "none", "total_known_usd": {"amount": "1.5"}, "offer": {"quote_no": "B"}}}]}
    chk = {"id": "c", "rows": "columns", "pick": {"landed.offer.quote_no": "A"},
           "expect": {"landed.duty_status": "owed", "landed.total_known_usd": {"approx": 193.19, "tol": 0.001}}}
    assert apicheck.evaluate(chk, body)["passed"]
    wrong = {**chk, "expect": {"landed.duty_status": "none"}}
    d = apicheck.evaluate(wrong, body)
    assert not d["passed"] and d["wrong"] == 1
    assert not apicheck.evaluate({**chk, "pick": {"landed.offer.quote_no": "Z"}}, body)["passed"]
    absent = apicheck.evaluate({**chk, "expect": {"landed.nope": 1}}, body)
    assert not absent["passed"] and absent["wrong"] == 1


def test_quotes_landed_arithmetic_is_independent_of_the_app():
    ex = {c["id"]: c["expect"] for c in run.load_cases("quotes-landed")["quotes-landed"]["checks"]}
    assert 0.24058 * 1.15 == pytest.approx(ex["bcx-ddp-duty-is-at-cost-on-top"]["landed.total_known_usd"]["approx"], abs=1e-5)
    assert 389.5 * 1.18399 == pytest.approx(ex["hallerbeck-eur-decimal-comma-and-surcharge"]["landed.unit_price_usd"]["approx"], rel=1e-5)
    assert 389.5 * 1.18399 * .035 == pytest.approx(ex["hallerbeck-eur-decimal-comma-and-surcharge"]["landed.surcharge_usd"]["approx"], rel=1e-4)
    assert 165.54 * 1.25 == pytest.approx(ex["vinh-phuc-origin-is-a-ruling-not-a-claim"]["landed.total_if_china_usd"]["approx"], abs=1e-3)
    assert 154.55 * 1.25 == pytest.approx(ex["yunzhan-quote-duty-owed"]["landed.total_known_usd"]["approx"], abs=1e-3)
    assert 1224.52 * 1.25 == pytest.approx(ex["quenvara-penang-is-a-quote-not-a-saving"]["landed.total_if_china_usd"]["approx"], abs=1e-3)
    assert 1155.21 * 1.25 == pytest.approx(ex["quenvara-huizhou-duty-owed"]["landed.total_known_usd"]["approx"], abs=1e-3)


def test_any_of_mentions_and_forbidden_claims():
    assert graders.grade_must_mention(["Tern", ["2026-10-10", "October 10", "10 October"]], "Tern is short; revised dates by 10 October")["passed"]
    assert not graders.grade_must_mention([["2026-10-10", "October 10"]], "no date here")["passed"]
    assert not graders.grade_must_not_mention(["13 November"], "recovery estimated 13 November")["passed"]
    assert graders.grade_must_not_mention(["13 November"], "partial production in 6 to 8 weeks")["passed"]


def test_a_date_in_a_sheet_is_matched_however_a_buyer_writes_it():
    from evals import graders
    assert graders.grade_must_mention(["2026-10-15"], "Reply by 15 October please.")["passed"]
    assert graders.grade_must_mention([["2026-11-01"]], "from Nov 1 the duty applies")["passed"]
    assert not graders.grade_must_mention(["2026-10-15"], "Reply by 16 October.")["passed"]
    assert graders.grade_must_mention(["2026-10-03"], "by 3rd October")["passed"]
