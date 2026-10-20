"""Read the sources as they stood on the data date: nothing dated after it exists yet.

Defect: none in the files. The step exists so the same recipe can rebuild the database as it would have stood on an earlier day
(`LOOKOUT_AS_OF=2026-09-17 make build-data`), which is how "would we have seen it coming" is asked of the system. On the data's own
date it changes nothing and records nothing.
Rule: a PO line ordered after the data date is not read; a receipt dated after it is undone (the line goes back to OPEN with nothing
received: the export keeps only the last receipt, so an earlier partial receipt cannot be recovered); an FX month after the data
date's month is not read. Messages, news and the tariff advisory are cut where they are read (steps 19, 20, 21) by the same date.
Consequence if ignored: a replay would know next week's orders, receipts and prices.
"""
from app.domain.imports.helpers import parse_date_any

TABLE = "purchase_orders.csv (after the data date)"


def run(ctx):
    po = ctx.t["raw_purchase_orders"]
    ordered = po.order_date.map(parse_date_any)
    late = ordered > ctx.as_of
    for src in po[late].src_row:
        ctx.drop(TABLE, int(src), f"ordered after the data date {ctx.as_of}", "not read")
    received = po.received_date.map(parse_date_any)
    undo = ~late & (received > ctx.as_of)
    po = po[~late].copy()
    undo = undo[~late]
    po.loc[undo, ["received_date", "qty_received", "status"]] = ["", "0", "OPEN"]
    ctx.t["raw_purchase_orders"] = po
    ctx.issue("horizon.po_lines", "purchase_orders.csv", "PO lines ordered after the data date", int(late.sum()), "drop",
              f"Not read: the data stands as of {ctx.as_of}.", "A replay would know orders placed after the day it replays.",
              f"{int(late.sum())} lines", "ERP admin")
    ctx.issue("horizon.receipts", "purchase_orders.csv", "Receipts dated after the data date", int(undo.sum()), "fix",
              "Undone: the line is OPEN with nothing received (the export keeps only the last receipt).",
              "A replay would show goods as received before they arrived.", f"{int(undo.sum())} lines", "ERP admin")
    fx = ctx.t["raw_fx_rates"]
    ctx.t["raw_fx_rates"] = fx[fx.month <= ctx.as_of.strftime("%Y-%m")].copy()
