"""The steward's drift report compares an incoming file with the CLOSEST known export, mapping each found column to at most one expected column; or with the one it names."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.domain.imports.steward import drift

DATA = Path(__file__).resolve().parents[3] / "data"


def _orders_renamed(tmp_path, rows=25):
    po = pd.read_csv(DATA / "purchase_orders.csv", dtype=str, keep_default_na=False)
    keep = ["po_number", "line", "part_number", "supplier_id", "qty", "uom", "unit_price", "currency", "order_date", "status"]
    v = po[keep].head(rows).rename(columns={"po_number": "Order No", "line": "Pos", "part_number": "Item", "supplier_id": "Vendor", "qty": "Qty", "uom": "Unit", "unit_price": "Price",
                                            "currency": "Curr", "order_date": "Date", "status": "State"})
    v["Date"] = pd.to_datetime(v["Date"], format="mixed").dt.strftime("%d/%m/%Y")      # day first
    p = tmp_path / "legacy_orders.csv"
    v.to_csv(p, index=False)
    return p


def test_renamed_order_lines_are_read_as_the_order_export_not_the_bom(tmp_path):
    r = drift.drift_report(_orders_renamed(tmp_path), DATA)
    assert r["looks_like"] == "purchase_orders" and r["known_export"] == "purchase_orders.csv"
    assert {g["probably"] for g in r["likely_renames"]} >= {"Order No", "Item", "Vendor"}      # a mapping can now be tried


def test_a_renamed_bom_is_still_the_bom(tmp_path):
    bom = pd.read_csv(DATA / "bom.csv", dtype=str, keep_default_na=False).head(40)
    bom.columns = [f"{c}_x" for c in bom.columns]
    p = tmp_path / "b.csv"
    bom.to_csv(p, index=False)
    assert drift.drift_report(p, DATA)["looks_like"] == "bom"


def test_the_steward_can_name_the_export_and_a_wrong_name_is_refused(tmp_path):
    p = _orders_renamed(tmp_path)
    assert drift.drift_report(p, DATA, table="bom")["looks_like"] == "bom"
    with pytest.raises(ValueError):
        drift.drift_report(p, DATA, table="nonsense")


def test_a_column_is_not_credited_twice(tmp_path):
    df = pd.read_csv(DATA / "purchase_orders.csv", dtype=str, keep_default_na=False).head(25)[["part_number"]]
    one_column = drift.fit(df, drift.known_export("purchase_orders", DATA))
    assert one_column < 0.15      # one matching column of fourteen is not a 14-column match
