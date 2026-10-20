"""Halden's own purchase_orders.csv (first 300 rows) as a different ERP release exports it. Written for the evals, apart from the app's own example.

The change: columns renamed and reordered; a new "Cost Centre" column nobody has explained; dates as ISO instead of month/day/year; prices with a
decimal comma; whole quantities from 1,000 up with a space for thousands. Nothing else changes, so the original 300 rows are the oracle."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
NAME = "po_export_erp9.csv"
RENAME = {"po_number": "Document", "line": "Pos", "part_number": "Material", "supplier_id": "Vendor No", "qty": "Quantity", "uom": "Unit", "unit_price": "Net Price",
          "currency": "Doc Curr", "order_date": "Doc Date", "promised_date": "Delivery Date", "received_date": "GR Date", "qty_received": "GR Qty", "status": "State", "buyer": "Purchaser"}
ORDER = ["Document", "Pos", "Doc Date", "Vendor No", "Material", "Quantity", "Unit", "Net Price", "Doc Curr", "Delivery Date", "GR Date", "GR Qty", "State", "Purchaser", "Cost Centre"]


def original(root: Path = ROOT) -> pd.DataFrame:
    """The oracle: the first 300 rows of the raw file, every value as written."""
    return pd.read_csv(root / "data" / "purchase_orders.csv", dtype=str, keep_default_na=False).head(300)


def _iso(d: str) -> str:
    return f"{d[6:]}-{d[:2]}-{d[3:5]}" if len(d) == 10 and d[2] == "/" else d


def build(root: Path = ROOT) -> tuple[str, str]:
    """(file name, csv text) of the re-exported file."""
    df = original(root)
    out = df.copy()
    for c in ("order_date", "promised_date", "received_date"):
        out[c] = out[c].map(_iso)
    out["unit_price"] = out["unit_price"].str.replace(".", ",", regex=False)
    out["qty"] = out["qty"].map(lambda q: f"{int(q):,}".replace(",", " ") if q.isdigit() and int(q) >= 1000 else q)
    out = out.rename(columns=RENAME)
    out["Cost Centre"] = ["K" + str(310 + i % 9) for i in range(len(out))]
    return NAME, out[ORDER].to_csv(index=False)
