"""Choose one USD price per part to value demand that has no order yet.

Defect: there is no price list. The only prices are PO lines, some of them broker buys, returns or decimal slips.
Rule: the part's most recent PO line that is not cancelled, not a return, not a price outlier or decimal slip, not on a
non-active supplier record and counted in pieces (BOX excluded); ties on the same order date go to the line that comes last in the file. A part with no such
line has no reference price: its forecast demand is unknown in money, not zero.
Consequence if ignored: exposure valued at 11.74 USD for a battery pack, or at a broker's 4x.
"""
import pandas as pd


def run(ctx):
    df = ctx.t["po_lines"]
    bad = df["flags"].str.contains("price_outlier|decimal_slip|return|non_active_supplier|box_size_unknown")
    ok = df[(df.status != "CANCELLED") & ~bad & df.unit_usd_each.notna()].sort_values(["order_date", "src_row"])
    last = ok.groupby("part_number").tail(1).set_index("part_number")
    n_ok = ok.groupby("part_number").size()
    n_all = df.groupby("part_number").size()
    ctx.t["reference_prices"] = pd.DataFrame({
        "part_number": last.index, "usd_each": last.unit_usd_each.values, "po_line_id": last.id.values,
        "n_lines": n_ok.reindex(last.index).values, "n_excluded": (n_all.reindex(last.index) - n_ok.reindex(last.index)).values})
