"""Goods receipts from MB51; drop the rows the export repeated.

Defect: 18 rows of the MB51 export are exact repeats of the row above them (the same material document and item, every value equal): the
download was appended to.
Rule: keep the first, drop the repeat, and record each drop with the row it repeats (row_drops). A row that shares a document but differs in any
value is kept. The project is the plant's; a receipt in the material's alternate unit is converted to the base unit (as step 12 does for orders).
Consequence if ignored: the repeated receipts count twice, and a PO line looks received when it is not.
"""
import pandas as pd

from app.domain.imports.helpers import iso, parse_dmy


def run(ctx):
    raw = ctx.t["raw_mb51"]
    cols = [c for c in raw.columns if c != "src_row"]
    dup = raw.duplicated(subset=cols, keep="first")
    first = raw[~dup].drop_duplicates(subset=cols).set_index(cols).src_row
    for src, key in zip(raw[dup].src_row, raw[dup][cols].itertuples(index=False, name=None)):
        ctx.drop("raw_mb51", int(src), "exact repeat of another MB51 row (the export was appended to)", f"raw_mb51 row {first[key]}")
    r = raw[~dup]
    m = ctx.t["materials"].set_index("code")
    by_plant = {p.plant: p.project_id for p in ctx.t["project_plants"].itertuples()}
    qty = r.Quantity.astype(float)
    factor = [m.at[c, "alt_per_base"] if c in m.index and m.at[c, "alt_uom"] == u else 1.0 for c, u in zip(r.Material, r["Unit of Entry"])]
    rec = pd.DataFrame(dict(id=r["Material Document"] + "/" + r["Material Doc.Item"], mat_doc=r["Material Document"], item=r["Material Doc.Item"].astype(int),
                            movement=r["Movement Type"], posting_date=r["Posting Date"].map(lambda s: iso(parse_dmy(s))), posting_date_raw=r["Posting Date"],
                            material=r.Material, plant=r.Plant, plant_name=r["Name 1"], project_id=r.Plant.map(by_plant), qty=qty, qty_raw=r.Quantity,
                            uom=r["Unit of Entry"], qty_base=qty / pd.Series(factor, index=r.index), amount=r["Amount in LC"].astype(float), amount_raw=r["Amount in LC"],
                            po_no=r["Purchase Order"].replace("", None), po_item=r.Item.map(lambda s: int(s) if s.strip() else None),
                            po_line_id=(r["Purchase Order"] + "/" + r.Item).where(r["Purchase Order"] != "", None), record_id=r.Supplier.replace("", None),
                            reference=r.Reference, flags="", src_row=r.src_row))
    ctx.t["receipts"] = rec
    ctx.issue("mb51.duplicate_rows", "sap/MB51_goods_receipts.csv", "MB51 rows repeated exactly (an appended download)", int(dup.sum()), "drop",
              "Drop the repeat; each drop is recorded with the row it repeats.", "The receipt counts twice and the PO line looks received when it is not.",
              "; ".join((raw[dup]["Material Document"] + "/" + raw[dup]["Material Doc.Item"]).head(3)), "SAP admin")
