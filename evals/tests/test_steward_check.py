"""The steward grader: a correct step passes, a lazy or day/month-swapped one fails, and each case starts the right run."""
import pytest

from evals import agent_runner, steward_check
from evals.fixtures import make_export

NAME, TEXT = make_export.build()
WANT = make_export.original()

RIGHT = '''
import pandas as pd
def run(ctx):
    d = ctx.read_csv("po_export_erp9.csv")
    dt = lambda x: x[5:7] + "/" + x[8:10] + "/" + x[0:4] if x else x
    ctx.t["normalised"] = pd.DataFrame({
        "po_number": d["Document"], "line": d["Pos"], "part_number": d["Material"], "supplier_id": d["Vendor No"],
        "qty": d["Quantity"].str.replace(" ", "", regex=False), "uom": d["Unit"], "unit_price": d["Net Price"].str.replace(",", ".", regex=False),
        "currency": d["Doc Curr"], "order_date": d["Doc Date"].map(dt), "promised_date": d["Delivery Date"].map(dt), "received_date": d["GR Date"].map(dt),
        "qty_received": d["GR Qty"], "status": d["State"], "buyer": d["Purchaser"]})
'''
SWAPPED = RIGHT.replace('x[5:7] + "/" + x[8:10]', 'x[8:10] + "/" + x[5:7]')


def events(script):
    return [{"type": "tool.result", "payload": {"name": "try_step", "ok": True, "script": script}}]


def sandbox_ok():
    try:
        return isinstance(steward_check.replay(RIGHT, NAME, TEXT), object)
    except ModuleNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not sandbox_ok(), reason="needs the app on the path")


def test_the_export_is_drifted_and_the_oracle_is_the_raw_rows():
    assert len(WANT) == 300 and "Cost Centre" in TEXT.splitlines()[0] and "63,45" in TEXT


def test_a_correct_step_reproduces_the_original_rows():
    d = steward_check.grade(events(RIGHT), NAME, TEXT, WANT)
    assert d["passed"], d


def test_a_day_month_swap_is_caught_even_though_every_row_is_kept():
    d = steward_check.grade(events(SWAPPED), NAME, TEXT, WANT)
    assert not d["passed"] and "order_date" in d["detail"]


def test_no_passing_step_means_nothing_to_compare():
    assert not steward_check.grade([], NAME, TEXT, WANT)["passed"]


def test_cases_start_the_right_run():
    path, body, sent = agent_runner.start_request(None, {"post": "/api/imports/steward-runs", "file": "x"})
    assert path == "/api/imports/steward-runs" and body["filename"] == NAME and sent["text"] == TEXT
    path, body, _ = agent_runner.start_request(None, {"post": "/api/messages/{message}/triage-runs", "message": "a b"})
    assert path == "/api/messages/a%20b/triage-runs"
    assert agent_runner.start_request("fire:x", None)[0] == "/api/action-items/fire:x/runs"
    assert agent_runner.start_request(None, None) is None
