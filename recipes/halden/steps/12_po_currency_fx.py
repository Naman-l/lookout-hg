"""Fix the currency labels, fill blanks from the supplier record (labelled), and convert to USD at the order month's rate.

Defect: RMB used for CNY on 13 lines; 9 lines have no currency; six non-USD currencies priced in their own units, so
2,427.54 CNY and 346.79 USD cannot be compared by eye.
Rule: RMB -> CNY. A blank currency takes the invoicing currency of the supplier record, marked currency_method
'inferred' (the supplier's usual currency, not a certainty). USD = price x finance's rate for the order month; the
rate and month are stored on the line. A missing rate stops the build.
Consequence if ignored: JPY prices look cheap and EUR prices look dear; blank-currency lines get priced at zero.
"""
import pandas as pd

from app.domain.imports.context import examples


def run(ctx):
    df = ctx.t["po_lines"]
    rec = ctx.t["supplier_records"].set_index("record_id")
    fx = {(r.month, r.currency): r.usd_per_unit for r in ctx.t["fx_rates"].itertuples()}
    cur = df.currency_raw.str.strip().str.upper().replace({"RMB": "CNY"})
    blank = cur == ""
    unknown_cur = blank & (ctx.decision("currency:blank")[0] == "skip")   # the person would rather leave the 9 unknown than fill them from the supplier
    cur = cur.where(~blank | unknown_cur, df.record_id.map(rec.currency))
    assert (cur.notna() & ((cur != "") | unknown_cur)).all(), "a blank currency whose supplier record has no currency"
    df["currency"] = cur
    df["currency_method"] = ["unknown" if u else "inferred" if b else "stated" for b, u in zip(blank, unknown_cur)]
    df["unit_price"] = df.unit_price_raw.astype(float)
    df["fx_month"] = df.order_date.str[:7]
    df["fx_rate"] = pd.to_numeric(pd.Series([None if u else 1.0 if c == "USD" else fx[(m, c)] for c, m, u in zip(df.currency, df.fx_month, unknown_cur)], index=df.index))
    df["line_usd"] = df.qty * df.unit_price * df.fx_rate
    df["unit_usd_each"] = [None if f is None or f != f else p * r / f for p, r, f in zip(df.unit_price, df.fx_rate, df._factor)]

    rmb = df[df.currency_raw.str.upper() == "RMB"]
    ctx.issue("po.currency_rmb", "purchase_orders.csv", "RMB written for CNY", len(rmb), "fix", "RMB -> CNY; raw kept in currency_raw.",
              "Chinese lines split across two currency codes and one is missing from a naive rate lookup.", examples(rmb.id), "ERP admin")
    b = df[blank]
    ctx.issue("po.currency_blank", "purchase_orders.csv", "PO line with no currency", len(b), "infer",
              "Use the supplier record's invoicing currency and label it inferred (currency_method). None of the nine is open.",
              "A blank would price the line at zero or in the wrong money; the label tells the buyer it was filled by a rule.",
              examples(b.id + " -> " + b.currency), "@suppliers:" + ",".join(sorted(set(b.identity_id))))
    non = df[df.currency != "USD"]
    ctx.issue("po.non_usd_prices", "purchase_orders.csv", "Prices in six currencies (EUR, JPY, CNY, MXN, TWD, CHF) in their own units", len(non), "fix",
              "Convert at finance's rate for the order month (rate and month stored on the line); the original price and currency stay.",
              "Comparing 2,427.54 CNY to a 346.79 USD quote by eye; averages across currencies.",
              examples(non.id + ": " + non.unit_price_raw + " " + non.currency + " x " + non.fx_rate.round(4).astype(str)), "@suppliers:" + ",".join(sorted(set(non.identity_id))[:6]))
    # one company billed in more than one currency across its records: the lines outside its usual currency are named
    by_cur = df.groupby(["identity_id", "currency"]).size().rename("n").reset_index()
    mixed = by_cur.groupby("identity_id").filter(lambda g: len(g) > 1)
    usual = mixed.sort_values("n").groupby("identity_id").tail(1).set_index("identity_id").currency
    odd = df[df.identity_id.isin(usual.index) & (df.currency != df.identity_id.map(usual))]
    ctx.issue("po.same_supplier_two_currencies", "purchase_orders.csv", "One company priced in more than one currency across its records", len(odd), "flag",
              "Kept; converted at the order month's rate.", "A price in one currency read next to the same company's price in another (a 1,000 in yuan beside a 140 in dollars) is read as a tenfold overcharge.",
              examples(odd.id + " " + odd.currency + " (usually " + odd.identity_id.map(usual) + ")"), "@suppliers:" + ",".join(sorted(set(odd.identity_id))))
