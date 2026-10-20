import re

from evals import readme_block
from evals.run import ROOT


def test_the_readme_says_what_the_committed_reports_say():
    """If a report changes and the README block is not regenerated (python -m evals.readme_block --write), this fails."""
    assert readme_block.main(["--check"]) == 0


def test_the_prose_around_the_block_states_no_result_number():
    text = (ROOT / "README.md").read_text()
    start = text.index(readme_block.BEGIN)
    a = text.rindex("\n## ", 0, start) + 1                     # the section that holds the generated block, whatever its number
    b = text.index("\n## ", text.index(readme_block.END)) + 1
    prose = re.sub(re.escape(readme_block.BEGIN) + r".*?" + re.escape(readme_block.END), "", text[a:b], flags=re.S)
    assert not re.search(r"\b\d+ of \d+\b|\bUSD\b|\$\d", prose), prose


def test_a_running_round_is_one_generated_line_until_its_result_is_in(tmp_path, monkeypatch):
    import yaml
    status = tmp_path / "round_status.yaml"
    status.write_text(yaml.safe_dump({"running": 10, "fixes": ["one thread per contact", "carry-through"], }))
    monkeypatch.setattr(readme_block, "EV", tmp_path)
    for name in ("report.json", "report_gate29.json", "report_heldout.json", "rounds.yaml", "changes.yaml"):
        (tmp_path / name).write_text((readme_block.ROOT / "evals" / name).read_text())
    (tmp_path / "judge").mkdir()
    for f in (readme_block.ROOT / "evals" / "judge").glob("calibration*.json"):
        (tmp_path / "judge" / f.name).write_text(f.read_text())
    (tmp_path / "report_judge_regrade.json").write_text((readme_block.ROOT / "evals" / "report_judge_regrade.json").read_text())
    text = readme_block.block()
    assert "Round 10 is running on the final agent;" in text and "one thread per contact, carry-through" in text and "were verified live on the running app" in text and "feedback log" not in text
    status.unlink()
    assert "is running on the final agent" not in readme_block.block()


def test_the_block_sets_the_bench_beside_the_held_out_sheets():
    text = readme_block.block()
    assert "Bench versus held-out" in text and "Held-out (" in text and "Prose met in every trial" in text


def test_the_report_opens_with_a_quality_summary_that_counts_what_the_agent_did_and_said():
    from evals import report
    r = {"status": "FAIL", "trials": [{"status": "FAIL", "detail": "prose (judge): buyer's words: jargon", "prose": "failed"}]}
    lines = report.quality_summary({"c": r}, {"c": {"expected": {}}}, None)
    assert lines[0].startswith("QUALITY SUMMARY")
    assert "0 of 1" in lines[1] and "held in 1 of 1; what it SAID" in lines[2] and "held in 0 of 1" in lines[2].split("SAID")[1]


def test_the_readme_block_says_what_it_counts_and_points_to_the_notes():
    text = readme_block.block()
    assert "passed every check in every trial" in text and "could not run" in text
    assert "more held every check that could be made" not in text
    assert "evals/README.md" in text and "calibrated against a model's labels" not in text
    assert "Reading the README table" in readme_block.history()
