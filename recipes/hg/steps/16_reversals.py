"""Net receipts per PO line: reversals (102) and returns (122) take back what was received.

Defect: 70 receipts were reversed (movement 102: a receipt posted in error, posted back the same or the next day) and 18 returned to the vendor
(122). MB51 lists them as their own rows with negative quantities; added naively as receipts they inflate what was received.
Rule: received = the sum of the signed quantities of 101, 102 and 122 per PO line (in base units); open = ordered - received (never below 0);
the line is received when less than 0.5% is open. The signed rows are kept as exported.
Consequence if ignored: reversed receipts count as delivered, a vendor's on-time record and a project's received value are overstated.
"""


def run(ctx):
    rec, po = ctx.t["receipts"], ctx.t["po_lines"]
    net = rec[rec.po_line_id.notna()].groupby("po_line_id").qty_base.sum()
    po["received_base"] = po.id.map(net).fillna(0.0)
    po["open_base"] = (po.qty_base - po.received_base).clip(lower=0)
    po["open_value"] = po.open_base * po.rate_base
    po["status"] = ["received" if (o <= 0.005 * q) else "open" for o, q in zip(po.open_base, po.qty_base)]
    rev = rec[rec.movement.isin(["102", "122"])]
    ctx.issue("mb51.reversals", "sap/MB51_goods_receipts.csv", "102 reversals and 122 returns listed as rows of their own", len(rev), "fix",
              "Netted: received = the sum of signed 101, 102 and 122 quantities per PO line; the rows are kept as exported.",
              "Reversed receipts count as delivered; on-time and received value are overstated.",
              f"{(rev.movement == '102').sum()} reversals, {(rev.movement == '122').sum()} returns; e.g. " + "; ".join(rev.id.head(2)), "SAP admin")
