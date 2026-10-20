"""F100 / Rev 4.2: an Ask answer's tables are built by code from the run's own tool results; every cell is a tool figure with its evidence id."""

import json
from pathlib import Path

from app.organism.runs import tables
from app.organism.schemas import RunEvent

REC = Path(__file__).resolve().parents[2] / "app" / "organism" / "recordings"


def _events(name):
    return [RunEvent.model_validate(e) for e in json.loads((REC / name).read_text())["events"]]


def _ids_returned(events):
    return {n["id"] for e in events if e.type == "tool.result" for n in (e.payload or {}).get("numbers") or []}


def test_the_fire_question_comes_back_as_shortfall_po_lines_and_quotes_every_cell_a_tool_figure():
    ev = _events("ask_cec66163.json")
    out = {t.kind: t for t in tables.build(ev)}
    assert set(out) == {"shortfall", "po_lines", "quotes"}
    short = out["shortfall"]
    assert short.columns == ["Oct", "Nov"] and short.by == "Supply planner"
    assert [(r.label, [c.say for c in r.cells]) for r in short.rows][:2] == [("HR-40110", ["364", "376"]), ("HR-40120", ["182", "188"])]
    q = {(r.part, r.label): [c.say if c else None for c in r.cells] for r in out["quotes"].rows}
    assert q[("HR-40110", "Q-YZ-26-0831")] == ["$151.19", "$37.80", "$188.99", None]  # one part's quote never takes another part's figures
    assert q[("HR-40120", "Q-YZ-26-0831")][0] == "$74.12"
    assert len(out["po_lines"].rows) == tables.MAX_ROWS and out["po_lines"].more == 4
    cited = {c.id for t in out.values() for r in t.rows for c in r.cells if c}
    assert cited and cited <= _ids_returned(ev)  # cited, and nothing a tool did not return


def test_exposure_is_largest_duty_first_and_a_run_that_read_nothing_has_no_table():
    t = tables.build(_events("ask_f97dc146.json"))
    assert t[0].kind == "exposure" and [r.label for r in t[0].rows][:2] == ["HR-50110", "HR-50210"] and t[0].columns == ["Duty owed", "Only if late"]
    assert tables.build([]) == []
    failed = [RunEvent.model_validate({"run_id": "r", "seq": 1, "t_ms": 0, "type": "tool.result", "agent": "supply_planner", "agent_label": "Supply planner", "summary": "x", "ts": "now",
                                       "payload": {"ok": False, "numbers": [{"id": "shortage:HR-1:2026-10:short", "value": "5", "unit": "EA"}]}})]
    assert tables.build(failed) == []


def test_get_run_carries_tables_on_an_ask_run_only(tmp_path, monkeypatch):
    from app import db as app_db
    from app.organism import api as organism_api
    from app.organism.runs import store
    from app.organism.runs.events import Recorder

    monkeypatch.setattr(app_db, "DB_PATH", tmp_path / "t.db")
    db = str(app_db.DB_PATH)
    for rid, wf in (("run-ask", "ask"), ("run-item", "work_item")):
        store.insert_run(db, run_id=rid, item_key="k", workflow=wf, status="ok", started_at="now")
        rec = Recorder(rid, db)
        rec.emit("run.started", "x", question="q")
        rec.emit("tool.result", "Shortage", agent="supply_planner", tool="shortage_for_parts", ok=True, numbers=[{"id": "shortage:HR-40110:2026-10:short", "name": "short", "value": "364", "unit": "EA"}], unknowns=[])
    ask = organism_api.get_run("run-ask")
    assert [(t.kind, t.rows[0].cells[0].say, t.rows[0].cells[0].id) for t in ask.tables] == [("shortfall", "364", "shortage:HR-40110:2026-10:short")]
    assert organism_api.get_run("run-item").tables == []


def test_my_late_lines_come_back_as_a_table_of_the_askers_own_lines_with_codes_words():
    """BUYER Q8 'Which of my late lines stops a build first?': a table of her late lines (days late, buyer, the robot it feeds) from the chase case's
    own figures; never a judgement the model makes alone."""
    def ev(numbers):
        return RunEvent.model_validate({"run_id": "r", "seq": 1, "t_ms": 0, "ts": "now", "summary": "x", "type": "tool.result", "agent": "lookout", "agent_label": "Lookout",
                                        "payload": {"ok": True, "tool": "get_item", "numbers": numbers}})
    nums = [{"id": "item:deadline:chase:chase:HPO-26-00415/10", "name": "HPO-26-00415/10 HR-1: Xinda, 30 days past due, Dana, feeds Heron H1, no message mentions it", "value": "5975.2", "unit": "USD", "say": "$5,975.20"},
            {"id": "item:deadline:chase:chase:HPO-26-00404/10", "name": "HPO-26-00404/10 HR-2: Hallerbeck, 1 day past due, Dana, feeds Porter P5, no message mentions it", "value": "1000", "unit": "USD"},
            {"id": "item:deadline:chase:chase:HPO-26-00505/10", "name": "HPO-26-00505/10 HR-3: Vistaray, 2 days past due, Marcus, no message mentions it", "value": "50", "unit": "USD"}]
    mine = tables.build([ev(nums)], asked_by="Dana Reyes")
    t = next(x for x in mine if x.kind == "late_lines")
    assert [r.label for r in t.rows] == ["HPO-26-00415/10", "HPO-26-00404/10"] and t.columns == ["Open value"]
    assert t.rows[0].note == "Xinda, 30 days past due, Dana, feeds Heron H1" and t.rows[0].cells[0].say == "$5,975.20"  # no repeat of the line, part or table title
    assert len(next(x for x in tables.build([ev(nums)]) if x.kind == "late_lines").rows) == 3  # no asker: every line


def test_when_the_answer_names_some_of_the_lines_the_table_shows_those():
    """LOOKOUT live on :8000 (via BUILD-4-13): 'Which of the 10 lines were already past due before the fire?' answered three lines, while the table
    listed every line the planner read (6 + 6 more), so it never named them. The table keeps the lines the answer names."""
    ev = _events("ask_cec66163.json")
    all_rows = next(t for t in tables.build(ev) if t.kind == "po_lines")
    assert all_rows.more > 0
    some = next(t for t in tables.build(ev, answer_text="Three lines were late: HPO-26-00450/10, 00614/10 and HPO-26-00614/20.") if t.kind == "po_lines")
    assert sorted(r.label for r in some.rows) == ["HPO-26-00450/10", "HPO-26-00614/10", "HPO-26-00614/20"]
    assert some.more == all_rows.more + len(all_rows.rows) - 3 and some.more_what == "other lines read"  # the rest counted, never hidden
    assert len(next(t for t in tables.build(ev, answer_text="No line is named here.") if t.kind == "po_lines").rows) == tables.MAX_ROWS  # none named: unchanged


def test_each_late_line_carries_its_own_robots_on_order_bound_to_its_part_and_robot():
    """BUYER Q8 (1 run in 3 failed the verifier: '26 is said of the Porter'): each late line's robots on order come from its own part's cover figure,
    with the robot named in the cell, so the count cannot drift to another line."""
    def ev(numbers, tool):
        return RunEvent.model_validate({"run_id": "r", "seq": 1, "t_ms": 0, "ts": "now", "summary": "x", "type": "tool.result", "agent": "lookout", "agent_label": "Lookout",
                                        "payload": {"ok": True, "tool": tool, "numbers": numbers}})
    late = [{"id": "item:deadline:chase:chase:L-1/10", "name": "Motor order (L-1 line 10) Motor (P-1): Xinda, 30 days past due, Dana, feeds Heron H1 October, no message mentions it", "value": "5975.2", "unit": "USD"},
            {"id": "item:deadline:chase:chase:L-2/10", "name": "Gearbox order (L-2 line 10) Gearbox (P-2): Hallerbeck, 1 day past due, Dana, feeds Porter P5 October, no message mentions it", "value": "75000", "unit": "USD"}]
    cover = [{"id": "cover:P-1:R1:robots_on_order", "name": "Heron H1 robots that the open orders of P-1 cover if all of it goes to the Heron H1", "value": "26", "unit": "robots"},
             {"id": "cover:P-2:R2:robots_on_order", "name": "Porter P5 robots that the open orders of P-2 cover if all of it goes to the Porter P5", "value": "169", "unit": "robots"}]
    t = next(x for x in tables.build([ev(late, "get_item"), ev(cover, "where_used_for_parts")], asked_by="Dana Reyes") if x.kind == "late_lines")
    assert t.columns == ["Open value", "Robots on order"]
    got = {r.label: (r.cells[1].say, r.cells[1].id) for r in t.rows}
    assert got == {"L-1/10": ("26 Heron H1", "cover:P-1:R1:robots_on_order"), "L-2/10": ("169 Porter P5", "cover:P-2:R2:robots_on_order")}


def test_a_part_on_two_robots_shows_the_count_of_the_robot_the_line_feeds():
    """AGENT-EXPERT should-fix on 315e6f3: the cover was bound by part only (the first robot found); a part on two robots must show the count of the
    robot its line feeds, and none when its label names no robot."""
    def ev(numbers, tool):
        return RunEvent.model_validate({"run_id": "r", "seq": 1, "t_ms": 0, "ts": "now", "summary": "x", "type": "tool.result", "agent": "lookout", "agent_label": "Lookout",
                                        "payload": {"ok": True, "tool": tool, "numbers": numbers}})
    late = [{"id": "item:deadline:chase:chase:L-1/10", "name": "Lidar order (L-1 line 10) Lidar (P-1): Vistaray, 2 days past due, Marcus, feeds Porter P5 October, no message mentions it", "value": "50", "unit": "USD"},
            {"id": "item:deadline:chase:chase:L-2/10", "name": "Lidar order (L-2 line 10) Lidar (P-1): Vistaray, 9 days past due, Marcus, no message mentions it", "value": "60", "unit": "USD"}]
    cover = [{"id": "cover:P-1:R1:robots_on_order", "name": "Tern T2 robots that the open orders of P-1 cover if all of it goes to the Tern T2", "value": "1520", "unit": "robots"},
             {"id": "cover:P-1:R2:robots_on_order", "name": "Porter P5 robots that the open orders of P-1 cover if all of it goes to the Porter P5", "value": "760", "unit": "robots"}]
    t = next(x for x in tables.build([ev(late, "get_item"), ev(cover, "where_used_for_parts")]) if x.kind == "late_lines")
    cells = {r.label: r.cells[1] for r in t.rows}
    assert cells["L-1/10"].say == "760 Porter P5" and cells["L-1/10"].id == "cover:P-1:R2:robots_on_order"  # the robot it feeds, not the first found
    assert cells["L-2/10"] is None  # no robot named: no count
