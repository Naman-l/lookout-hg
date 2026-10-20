from evals import factcheck


def test_figures_are_read_with_commas_and_k_m_suffixes():
    assert factcheck.numbers_in("$1.35M owed, $189K more, 1,432,969 exactly, 25%, 3,656 EA, 2026-10-15") [:6] == [1_350_000.0, 189_000.0, 1432969.0, 25.0, 3656.0, 2026.0]


def test_a_value_is_found_within_the_sheets_tolerance_or_not_at_all():
    f = {"name": "owed", "value": 183187, "tolerance": 0.02}
    assert factcheck.found_in_text(f, "HR-40110 owes about $183K in duty.")
    assert not factcheck.found_in_text(f, "HR-40110 owes about $150K in duty.")
    assert factcheck.found_in_text({"name": "d", "value": "2026-12-15"}, "Goods are honoured for delivery by 15 December.")
    assert not factcheck.found_in_text({"name": "d", "value": "2026-12-15"}, "Nothing about December.")
    assert not factcheck.found_in_text({"name": "z", "value": 0}, "0 robots")      # zero is never 'found': it would match anything


def test_right_wrong_and_not_measured_are_told_apart_and_absence_is_not_wrong():
    facts = [{"name": "by_id_ok", "id": "x:ok", "value": 100, "tolerance": 0.01}, {"name": "by_id_off", "id": "x:off", "value": 100},
             {"name": "by_id_absent", "id": "x:gone", "value": 100}, {"name": "in_text", "value": 5000, "tolerance": 0.01}, {"name": "never_said", "value": 777}]
    rec = {"finding": "The price is 5,000 USD.", "numbers": [{"id": "x:ok", "value": 100.5}, {"id": "x:off", "value": 120}]}
    rows = {r["fact"]: r for r in factcheck.check_facts(facts, rec)}
    assert rows["by_id_ok"]["status"] == "right" and rows["by_id_ok"]["via"] == "id"
    assert rows["by_id_off"]["status"] == "wrong"
    assert rows["by_id_absent"]["status"] == "wrong" and rows["by_id_absent"]["got"] == "not in the answer"   # a number the tool gave and the answer does not state
    assert rows["in_text"]["status"] == "right" and rows["in_text"]["via"] == "found in the answer"
    assert rows["never_said"]["status"] == "not measured"            # absent from the words: unknown, not wrong
    assert factcheck.tally(list(rows.values())) == {"right": 2, "wrong": 2, "not measured": 1}
