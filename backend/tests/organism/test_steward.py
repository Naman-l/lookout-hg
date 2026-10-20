"""The Data steward's code side, with no model: the drift report, the sandbox run, the load-gate-style checks.

The drifted fixture is Halden's own purchase_orders.csv re-exported by a different ERP release, so a correct normaliser must reproduce the original rows
exactly: the original file is the oracle."""

import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from app.domain.imports.steward import checks, drift, tools as steward_tools
from app.organism.workflows import import_file

FIXTURE = Path(__file__).resolve().parents[2] / "app/domain/imports/steward/fixtures/purchase_orders_export_2026-10.csv"
ORIGINAL = Path(__file__).resolve().parents[3] / "data" / "purchase_orders.csv"

ORACLE = '''
import pandas as pd

def run(ctx):
    df = ctx.read_csv("purchase_orders_export_2026-10.csv")
    def d(x):
        return x[5:7] + "/" + x[8:10] + "/" + x[0:4] if x else x
    out = pd.DataFrame({
        "po_number": df["PO No."], "line": df["Ln"], "part_number": df["Item"], "supplier_id": df["Vendor"],
        "qty": df["Order Qty"].str.replace(" ", "", regex=False), "uom": df["UoM"],
        "unit_price": df["Unit Price"].str.replace(",", ".", regex=False), "currency": df["Curr"],
        "order_date": df["Order Date"].map(d), "promised_date": df["Promise Date"].map(d), "received_date": df["Received"].map(d),
        "qty_received": df["Qty Rcvd"], "status": df["Status"], "buyer": df["Buyer Code"]})
    ctx.t["normalised"] = out
'''

LAZY = '''
import pandas as pd

def run(ctx):
    df = ctx.read_csv("purchase_orders_export_2026-10.csv")
    ctx.t["normalised"] = df.rename(columns={"PO No.": "po_number", "Ln": "line", "Item": "part_number", "Vendor": "supplier_id", "Order Qty": "qty", "UoM": "uom",
        "Unit Price": "unit_price", "Curr": "currency", "Order Date": "order_date", "Promise Date": "promised_date", "Received": "received_date",
        "Qty Rcvd": "qty_received", "Status": "status", "Buyer Code": "buyer"})[["po_number", "line", "part_number", "supplier_id", "qty", "uom", "unit_price", "currency",
        "order_date", "promised_date", "received_date", "qty_received", "status", "buyer"]]
'''

pytestmark = pytest.mark.skipif(not ORIGINAL.exists(), reason="needs data/")


def call(tool, **args):
    out = asyncio.run(tool.handler(args))
    return json.loads(out["content"][0]["text"])


@pytest.fixture
def steward(ctx):
    steward_tools.start(ctx, FIXTURE)
    return {t.name: t for t in steward_tools.make_tools(ctx)}


def test_the_drift_report_finds_what_changed_and_leaves_the_ambiguous_to_the_steward():
    r = drift.drift_report(FIXTURE)
    assert r["looks_like"] == "purchase_orders" and r["drifted"] and r["rows"] == 300
    assert len(r["missing"]) == 14 and "Cost Centre" in r["new"] and len(r["new"]) == 15
    hints = {g["expected"]: g["probably"] for g in r["likely_renames"]}
    assert hints["po_number"] == "PO No." and hints["buyer"] == "Buyer Code" and hints["currency"] == "Curr"


def test_a_file_that_already_matches_the_known_export_is_not_drift():
    assert not drift.drift_report(ORIGINAL)["drifted"]


def test_the_oracle_step_runs_in_the_sandbox_and_reproduces_the_original_rows(steward, ctx):
    body = call(steward["try_step"], name="restore", code=ORACLE)
    assert body["data"]["ok"], body
    assert [c["name"] for c in body["data"]["checks"]] == ["columns", "rows", "values", "shapes", "dates"] and all(c["passed"] for c in body["data"]["checks"])
    assert ctx.evidence["import:purchase_orders_export_2026-10.csv:rows_out"].value == 300
    assert ctx.steward["best"]["rows_out"] == 300 and import_file.import_checks(ctx) == []


def test_a_step_that_only_renames_fails_the_gate_checks_and_says_why(steward, ctx):
    body = call(steward["try_step"], name="lazy", code=LAZY)
    failed = {c["name"]: c["detail"] for c in body["data"]["checks"] if not c["passed"]}
    assert not body["data"]["ok"] and "shapes" in failed and "9999-99-99" in failed["shapes"]
    assert ctx.steward["best"] is None and import_file.import_checks(ctx)  # nothing to propose yet


def test_a_hostile_step_is_refused_before_it_runs(steward):
    body = call(steward["try_step"], name="evil", code="import os\n\ndef run(ctx):\n    os.system('echo hi')\n")
    assert not body["data"]["ok"] and "not allowed" in body["data"]["error"]


def test_a_step_that_stores_nothing_is_told_where_to_put_the_result(steward):
    body = call(steward["try_step"], name="empty", code="def run(ctx):\n    pass\n")
    assert not body["data"]["ok"] and "normalised" in body["data"]["error"]


def test_a_findings_count_must_be_a_number_a_tool_returned(steward, ctx):
    out = asyncio.run(steward["add_finding"].handler({"issue": "dates are ISO", "count": 777, "consequence": "x", "example": "2024-10-01"}))
    assert out.get("is_error")
    call(steward["column_facts"], column="Order Date")
    ctx.seen_numerals.add(__import__("decimal").Decimal(300))
    ok = asyncio.run(steward["add_finding"].handler({"issue": "dates are ISO", "count": 300, "consequence": "x", "example": "2024-10-01"}))
    assert not ok.get("is_error") and len(ctx.steward["findings"]) == 1


def test_a_question_becomes_a_flashcard_with_an_owner(steward, ctx):
    call(steward["add_question"], question="What is the new Cost Centre column?", why_it_blocks="It has no place in the known export", proposed_answer="Ignore it", covers=300)
    assert ctx.unknowns[-1].owner == "unassigned" and "ask planning" in ctx.unknowns[-1].question and "Proposed: Ignore it" in ctx.unknowns[-1].question


def test_the_gate_checks_catch_a_lost_value():
    src = pd.DataFrame({"a": ["1", "2", ""], "b": ["x", "y", "z"]})
    exp = pd.DataFrame({"A": ["1"], "B": ["x"]})
    assert all(c["passed"] for c in checks.gate(src, src.rename(columns={"a": "A", "b": "B"}), exp))
    lossy = src.rename(columns={"a": "A", "b": "B"}).assign(B=["x", "", "z"])
    assert not next(c for c in checks.gate(src, lossy, exp) if c["name"] == "values")["passed"]


async def test_a_file_with_no_drift_is_answered_by_code_without_a_model(db, tmp_path, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no drift: no model")

    monkeypatch.setattr(import_file, "run_agent", boom)
    sample = pd.read_csv(ORIGINAL, dtype=str, keep_default_na=False).head(50)
    sample.to_csv(tmp_path / "purchase_orders.csv", index=False)
    result = await import_file.run_import("purchase_orders.csv", db_path=db, incoming_dir=tmp_path)
    assert result.status == "ok" and result.cost_usd == 0.0
    from app.organism.runs import store

    assert "untouched" in store.read_run(db, result.run_id)["recommendation_json"]


SWAPPED = ORACLE.replace('x[5:7] + "/" + x[8:10] + "/" + x[0:4]', 'x[8:10] + "/" + x[5:7] + "/" + x[0:4]')


def test_a_step_that_swaps_day_and_month_is_caught_even_though_the_shapes_look_right(steward, ctx):
    body = call(steward["try_step"], name="swapped", code=SWAPPED)
    failed = {c["name"]: c["detail"] for c in body["data"]["checks"] if not c["passed"]}
    assert not body["data"]["ok"] and "dates" in failed and "MM/DD/YYYY" in failed["dates"] and "shapes" not in failed
    assert ctx.steward["best"] is None


def test_the_stewards_findings_are_attached_to_the_recommendation_by_code(steward, ctx, db, services):
    from app.organism.verifier import verify

    call(steward["try_step"], name="restore", code=ORACLE)
    ctx.seen_numerals.add(__import__("decimal").Decimal(300))
    asyncio.run(steward["add_finding"].handler({"issue": "Dates arrive as ISO", "count": 300, "consequence": "They would not match the pipeline's dates", "example": "2024-10-01", "handling": "fix"}))
    ctx.plan, ctx.groups = [], []
    rec, _ = verify(ctx, {"finding": "The file maps onto the known export.", "numbers": []}, services=services)
    assert [(f.issue, f.count) for f in rec.findings] == [("Dates arrive as ISO", 300)]


def test_every_steward_name_the_import_workflow_reads_exists():
    """The workflow reads module attributes by name (the try_step cap among them); a cleanup that removes one must fail here, not in a live run."""
    import ast
    import inspect

    from app.domain.imports.steward import tools as steward_tools
    from app.organism.workflows import import_file

    read = {n.attr for n in ast.walk(ast.parse(inspect.getsource(import_file))) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "steward_tools"}
    assert "MAX_ATTEMPTS" in read
    assert [a for a in sorted(read) if not hasattr(steward_tools, a)] == []
    assert steward_tools.MAX_ATTEMPTS == 4


def test_a_justified_refusal_with_a_question_for_a_person_is_a_finished_run():
    """FEEDBACK: the steward correctly declined (four required columns missing) and the run was labelled did_not_pass."""
    from types import SimpleNamespace as NS

    from app.organism.workflows.import_file import import_checks

    assert import_checks(NS(steward={"best": None, "questions": []})) and not import_checks(NS(steward={"best": None, "questions": [object()]})) and not import_checks(NS(steward={"best": {"ok": True}}))
