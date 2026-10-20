"""Say what each status means for supply: open quantity, returns, short closes, cancellations.

Defect: not every row is an ordinary purchase. 3 lines have negative quantities (returns); 78 CLOSED lines were
received short; 25 are cancelled; 13 are partially received.
Rule: open_qty_ea and open_usd exist only for OPEN and PARTIAL lines (quantity minus received, never negative).
Returns, short closes and cancels are flagged and kept; none counts as supply. Past due is NOT stored: it is computed
from the promise date and the data date (AS_OF) by the orders service.
Consequence if ignored: a return reads as negative supply, a short-closed line as supply that arrived, a cancelled
line as supply still coming.
"""
from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag


def run(ctx):
    df = ctx.t["po_lines"]
    is_open = df.status.isin(["OPEN", "PARTIAL"])
    rem = (df.qty - df.qty_received).clip(lower=0)
    df["open_qty_ea"] = [r * f if (o and f == f) else None for o, r, f in zip(is_open, rem, df._factor)]
    df["open_usd"] = [r * p * fx if o else None for o, r, p, fx in zip(is_open, rem, df.unit_price, df.fx_rate)]

    ret = df.qty < 0
    add_flag(df, ret, "return")
    r = df[ret]
    ctx.issue("po.returns", "purchase_orders.csv", "Negative quantities (returns)", len(r), "flag",
              "Kept and flagged 'return'; never counted as supply or as a purchase price.",
              "A return read as an order shrinks spend and open supply.", examples(r.id + " " + r.qty_raw), "@parts:" + ",".join(r.part_number))
    short = (df.status == "CLOSED") & (df.qty_received < df.qty) & ~ret
    add_flag(df, short, "short_closed")
    s = df[short]
    ctx.issue("po.short_closed", "purchase_orders.csv", "Lines closed with less received than ordered", len(s), "flag",
              "Kept and flagged 'short_closed'; the shortfall is not treated as coming.",
              "Supply the plan expected never arrived; supplier on-time-in-full is overstated if only 'closed' is read.",
              examples(s.id + ": " + s.qty_received_raw + " of " + s.qty_raw), "@parts:" + ",".join(sorted(set(s.part_number))[:8]))
    c = df[df.status == "CANCELLED"]
    ctx.issue("po.cancelled", "purchase_orders.csv", "Cancelled lines", len(c), "flag",
              "Kept; excluded from supply, spend and reference prices.", "Cancelled value counted as spend.",
              examples(c.id), "ERP admin")
