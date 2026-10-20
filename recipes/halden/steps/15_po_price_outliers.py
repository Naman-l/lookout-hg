"""Flag prices far from the same part's usual price: broker buys and one decimal slip.

Defect: some twenty lines are priced more than 3x above or below the part's median USD price. Most are broker buys
(Saltmarsh, Kowloon) at 3-4x; two are decimal slips (HR-50110 battery pack at 11.74 against about 1,162; HR-10019 screws
at 16.88 against 0.17).
Rule: flag price_outlier when unit_usd_each is outside [median/3, median x 3] for the part (cancelled, return and BOX
lines excluded from the median), except a low price the part is bought at again (another line within 10%: a second price level, not an error); flag decimal_slip when the ratio is within 10% of 100 or 1/100. Flagged lines are
kept, and are never used as a reference price.
Consequence if ignored: forecast demand valued at a broker's price; a battery pack worth 11.74 USD.
"""
import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag


def run(ctx):
    df = ctx.t["po_lines"]
    ok = df[(df.status != "CANCELLED") & (df.qty > 0) & df.unit_usd_each.notna()]
    med = ok.groupby("part_number").unit_usd_each.median()
    ratio = df.unit_usd_each / df.part_number.map(med)
    live = (df.status != "CANCELLED") & (df.qty > 0)
    high, low = ratio > 3, ratio < 1 / 3
    # A price far BELOW the median is a second price level, not an error, when the same part is bought at that level again (a volume supplier beside small lots): it is flagged
    # only when it stands alone (a sample, a slip). Far ABOVE the median (a broker or urgent buy) is always flagged.
    def has_twin(x):      # another line of the part within 10% of this line's ratio
        v = x.to_numpy(dtype=float)
        return pd.Series([bool(((abs(v - a) / max(abs(a), 1e-9)) < 0.1).sum() > 1) if a == a else False for a in v], index=x.index)

    twin = ratio.groupby(df.part_number, group_keys=False).apply(has_twin)
    out = ratio.notna() & (high | (low & ~twin)) & live
    slip = out & (((ratio - 0.01).abs() < 0.001) | ((ratio - 100).abs() < 10))
    add_flag(df, out, "price_outlier")
    add_flag(df, slip, "decimal_slip")
    o = df[out & ~slip]
    ctx.issue("po.price_outliers", "purchase_orders.csv", "Prices more than 3x away from the part's median (broker and urgent buys)", len(o), "flag",
              "Flag price_outlier; kept in spend, excluded from reference prices.",
              "Valuing forecast demand at a broker's price overstates exposure; comparing a quote to one broker line makes any quote look cheap.",
              examples(o.id + " " + o.part_number + " " + ratio[o.index].round(2).astype(str) + "x"), "@parts:" + ",".join(sorted(set(o.part_number))))
    s = df[slip]
    ctx.issue("po.decimal_slip", "purchase_orders.csv", "A price that looks like a misplaced decimal point (1/100 or 100x the median)", len(s), "flag",
              "Flag decimal_slip; kept as found, never used as a reference price.", "A price one decimal place off makes the spend and the duty on the part wrong by 10x or 100x.",
              examples(s.id + " " + s.part_number + " " + s.unit_usd_each.round(2).astype(str) + " USD"), "@parts:" + ",".join(s.part_number))
