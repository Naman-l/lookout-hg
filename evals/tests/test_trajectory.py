"""The trajectory grader reads the path from stored events: specialists, order, tools with arguments, loops."""
import json
from pathlib import Path

import yaml

from evals import trajectory

ROOT = Path(__file__).resolve().parents[2]


def ev(type, agent="x", **payload):
    return {"type": type, "agent": agent, "payload": payload}


def started(s):
    return ev("child.started", s, specialist=s)


def call(by, tool, **args):
    return ev("tool.called", by, name=tool, args=args)


def test_a_right_path_passes():
    events = [started("supply_planner"), call("supply_planner", "disrupted_supply", supplier_id="SUP-0001"), started("buyers_clerk")]
    spec = {"specialists": ["supply_planner", "buyers_clerk"], "order": ["supply_planner", "buyers_clerk"], "tools": [{"tool": "disrupted_supply", "by": "supply_planner", "args_any": {"supplier_id": ["SUP-0001"]}}]}
    assert trajectory.grade(spec, events)["passed"]


def test_wrong_order_wrong_argument_and_forbidden_specialist_each_fail():
    events = [started("buyers_clerk"), started("supply_planner"), call("supply_planner", "disrupted_supply", supplier_id="SUP-0099")]
    d = trajectory.grade({"order": ["supply_planner", "buyers_clerk"], "tools": [{"tool": "disrupted_supply", "args_any": {"supplier_id": ["SUP-0001"]}}], "specialists_forbidden": ["buyers_clerk"]}, events)
    assert not d["passed"] and "out of order" in d["detail"] and "never asked about" in d["detail"] and "buyers_clerk started" in d["detail"]


def test_a_missing_tool_a_loop_and_errors_fail():
    events = [call("a", "t", q=1)] * 4 + [ev("tool.result", "a", name="t", ok=False)] * 3
    d = trajectory.grade({"tools": [{"tool": "other"}], "max_repeat": 3, "max_tool_errors": 2, "max_tool_calls": 3}, events)
    assert not d["passed"] and "other not called" in d["detail"] and "repeated 4 times" in d["detail"] and "3 tool calls failed" in d["detail"] and "budget 3" in d["detail"]


def test_a_tool_a_specialist_must_never_call():
    d = trajectory.grade({"tools_forbidden_by": {"inbox_analyst": ["draft_supplier_request"]}}, [call("inbox_analyst", "mcp__lookout__draft_supplier_request")])
    assert not d["passed"]


def test_the_shipped_fire_recording_fits_the_fire_sheet():
    """A compatibility check of the sheet against a path the product produced, not a way to tune the sheet."""
    rec = json.loads((ROOT / "backend/app/organism/recordings/disruption_SUP-0001.json").read_text())
    spec = yaml.safe_load((ROOT / "evals/cases/disruption-fm.yaml").read_text())["expected"]["trajectory"]
    assert trajectory.grade(spec, rec["events"])["passed"]
