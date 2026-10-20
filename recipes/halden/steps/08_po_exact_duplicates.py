"""Drop PO lines repeated exactly by an export glitch.

Defect: 6 rows are identical to another row in every column, including PO number and line.
Rule: keep the first, drop the rest, and record each drop with the row it duplicates (row_drops). Rows that share a PO
and line but differ in any value are NOT dropped.
Consequence if ignored: the line's quantity and value are counted twice in open supply and spend.
"""
from app.domain.imports.context import examples

COLS = ["po_number", "line", "part_number", "supplier_id", "qty", "uom", "unit_price", "currency", "order_date",
        "promised_date", "received_date", "qty_received", "status", "buyer"]


def run(ctx):
    raw = ctx.t["raw_purchase_orders"]
    dup = raw.duplicated(subset=COLS, keep="first")
    if ctx.decision("duplicate-row:po")[0] == "skip":   # the person keeps the repeats: they stay, flagged, with their own id
        ctx.issue("po.exact_duplicate_rows", "purchase_orders.csv", "A PO line repeated exactly (export glitch)", int(dup.sum()), "flag",
                  "Kept at the person's request; each repeat is flagged export_duplicate and gets its own id (#2).",
                  "Quantity and value of the line are counted twice in open supply and spend.", examples(raw[dup].po_number + "/" + raw[dup].line), "ERP admin")
        ctx.t["po_lines"] = raw.reset_index(drop=True).copy()
        return
    first = raw[~dup].set_index(COLS).src_row
    for src, key in zip(raw[dup].src_row, raw[dup][COLS].itertuples(index=False, name=None)):
        ctx.drop("raw_purchase_orders", src, "exact duplicate of another PO line (export glitch)", f"raw_purchase_orders row {first[key]}")
    ctx.issue("po.exact_duplicate_rows", "purchase_orders.csv", "A PO line repeated exactly (export glitch)", int(dup.sum()), "drop",
              "Drop the later copy; each drop is recorded with the row it duplicates.",
              "Quantity and value of the line are counted twice in open supply and spend.",
              examples(raw[dup].po_number + "/" + raw[dup].line), "ERP admin")
    ctx.t["po_lines"] = raw[~dup].reset_index(drop=True).copy()
