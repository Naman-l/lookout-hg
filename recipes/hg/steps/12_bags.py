"""Count cement bought by the bag in tonnes.

Defect: cement is bought in tonnes from plants and in 50 kg bags from dealers: 30 PO lines and the 29 PR lines behind them (one is an emergency
buy with no PR; 59 counted) are in BAG, the rest in MT. The material master holds the conversion (20 bags to the tonne).
Rule: a line in the material's alternate unit gets a quantity in the base unit (bags / 20) and a rate per tonne (price per bag x 20); the
quantity and unit as entered are kept. Receipts are converted the same way when they are read (step 15).
Consequence if ignored: bags and tonnes are added together, and a bag price compared with a tonne price looks 20 times cheaper.
"""


def run(ctx):
    m = ctx.t["materials"].set_index("code")
    po, pr = ctx.t["po_lines"], ctx.t["pr_lines"]
    n = 0
    for df in (po, pr):
        alt = df.apply(lambda r: m.at[r.material, "alt_uom"] == r.uom if r.material in m.index else False, axis=1)
        factor = df.material.map(lambda c: m.at[c, "alt_per_base"] if c in m.index else None)
        df.loc[alt, "qty_base"] = df.loc[alt, "qty"] / factor[alt]
        if "rate_base" in df:
            df.loc[alt, "rate_base"] = df.loc[alt, "net_price"] / df.loc[alt, "price_unit"] * factor[alt]
            df.loc[alt, "open_base"] = df.loc[alt, "qty_base"]
        n += int(alt.sum())
    po["base_uom"] = po.material.map(lambda c: m.at[c, "base_uom"] if c in m.index else None)
    bags = po[po.uom != po.base_uom]
    ctx.issue("po.cement_bags_and_tonnes", "sap/ME2N_purchase_orders.csv", "Cement in both MT and bags", n, "fix",
              "Quantity in tonnes = bags / 20 (the material master's conversion), rate per tonne = price per bag x 20; the entry is kept.",
              "Bags and tonnes added together; a bag price looks 20 times cheaper than a tonne price.",
              "; ".join(f"{r.id}: {r.qty_raw} BAG = {r.qty_base:g} MT" for r in bags.head(3).itertuples()), "Govind")
