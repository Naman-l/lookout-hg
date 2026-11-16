"""Read prices typed per 1,000 as prices per unit.

Defect: 16 PO lines carry a price unit of 1,000 (AAC blocks priced per thousand pieces): the net price is for 1,000, not for one.
Rule: rate per unit = net price / price unit; the line's value = quantity x rate. The net price and price unit are kept as SAP has them.
Consequence if ignored: a block read at the per-thousand price is 1,000 times too dear, in the rate history and in every saving.
"""


def run(ctx):
    po = ctx.t["po_lines"]
    per = po.price_unit != 1
    po.loc[per, "rate_base"] = po.loc[per, "net_price"] / po.loc[per, "price_unit"]
    po["value"] = po.qty * po.net_price / po.price_unit
    po["open_value"] = po.value
    ctx.issue("po.price_per_1000", "sap/ME2N_purchase_orders.csv", "Prices typed per 1,000 (price unit 1,000)", int(per.sum()), "fix",
              "Rate per unit = net price / price unit; the value follows; SAP's own fields are kept.",
              "The rate reads 1,000 times too high in the rate history and in savings.",
              "; ".join(f"{r.id}: {r.net_price_raw} per {r.price_unit_raw} {r.uom}" for r in po[per].head(3).itertuples()), "@groups:" + ",".join(sorted(set(po[per].purch_group))))
