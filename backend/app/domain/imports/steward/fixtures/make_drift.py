"""Makes `purchase_orders_export_2026-10.csv`: Halden's own purchase_orders.csv (first 300 rows) as a different ERP release exports it.

The drift: columns renamed and reordered, a new "Cost Centre" column, dates as ISO (2024-10-01 instead of 10/01/2024), prices with a decimal comma
(63,45), quantities with a thousands space. The values are otherwise the same, so a correct normaliser reproduces the original rows exactly: the
original is the oracle for the steward's tests. Run: python make_drift.py"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
SRC = HERE.parents[5] / "data" / "purchase_orders.csv"
RENAME = {"po_number": "PO No.", "line": "Ln", "part_number": "Item", "supplier_id": "Vendor", "qty": "Order Qty", "uom": "UoM", "unit_price": "Unit Price",
          "currency": "Curr", "order_date": "Order Date", "promised_date": "Promise Date", "received_date": "Received", "qty_received": "Qty Rcvd",
          "status": "Status", "buyer": "Buyer Code"}


def iso(d: str) -> str:
    return f"{d[6:]}-{d[:2]}-{d[3:5]}" if len(d) == 10 and d[2] == "/" else d


def main() -> Path:
    df = pd.read_csv(SRC, dtype=str, keep_default_na=False).head(300)
    out = df.copy()
    for c in ("order_date", "promised_date", "received_date"):
        out[c] = out[c].map(iso)
    out["unit_price"] = out["unit_price"].str.replace(".", ",", regex=False)
    out["qty"] = out["qty"].map(lambda q: f"{int(q):,}".replace(",", " ") if q.isdigit() and int(q) >= 1000 else q)
    out = out.rename(columns=RENAME)
    out["Cost Centre"] = ["CC-" + str(4400 + (i % 7)) for i in range(len(out))]
    cols = ["PO No.", "Ln", "Order Date", "Vendor", "Item", "Order Qty", "UoM", "Unit Price", "Curr", "Promise Date", "Received", "Qty Rcvd", "Status", "Buyer Code", "Cost Centre"]
    path = HERE / "purchase_orders_export_2026-10.csv"
    out[cols].to_csv(path, index=False)
    return path


if __name__ == "__main__":
    print(main())
