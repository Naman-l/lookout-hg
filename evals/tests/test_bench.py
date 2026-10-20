import json

import yaml

from evals import report, run
from evals.run import ROOT

SPEC = yaml.safe_load((ROOT / "evals" / "bench.yaml").read_text())
CASES = run.load_cases()


def test_the_answer_sheet_is_within_the_briefs_five_to_fifteen_and_every_sheet_exists():
    ids = report.bench_ids(SPEC)
    answer = ids["controls"] + ids["agent"]
    assert 5 <= len(answer) <= 15 and len(set(answer + ids["system"])) == len(answer) + len(ids["system"])
    assert all(i in CASES for i in answer + ids["system"] + ids["live"])
    assert not set(ids["live"]) & set(answer)   # the live findings are a separate set, not part of the 15


def test_controls_are_tagged_with_what_they_test_and_the_bench_agrees():
    for kind, names in SPEC["controls"].items():
        for i in names:
            assert CASES[i]["category"] == "control" and CASES[i]["tests"] == kind, i
    assert all(CASES[i]["category"] != "control" for i in SPEC["agent"])
    assert {CASES[i]["category"] for i in SPEC["agent"]} == {"ordinary", "hard"}  # reported apart


def test_system_checks_are_code_not_agent_cases():
    assert all(CASES[i]["kind"] not in ("agent", "import") or CASES[i]["id"] == "import-deck" for i in SPEC["system_checks"])


def test_the_bench_view_of_the_committed_report_has_the_three_blocks_and_every_case():
    saved = json.loads((ROOT / "evals" / "report.json").read_text())
    text = report.render_bench(saved["config"], saved["results"], CASES, SPEC, "test")
    for i in report.bench_ids(SPEC)["controls"] + report.bench_ids(SPEC)["agent"]:
        if i in saved["results"]:   # a case added since the committed run (written before the next round) has no result yet and appears when it is run
            assert i in text
    assert not [i for i in saved["results"] if not i.startswith("_") and i not in CASES]
    assert "CONTROLS (guardrails graded on behaviour" in text and "THE AGENT'S CASES" in text and "SYSTEM CHECKS" in text
    assert "controls" in text and "agent cases" in text
