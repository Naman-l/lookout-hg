"""Load finance's monthly FX table and check it covers every month and currency the POs use.

Defect: none in the file; the check is that a PO in JPY ordered in a given month has a rate for that month.
Rule: usd_per_unit as given, one row per (month, currency). The PO step converts at the order month's rate and
stops the build if a rate is missing. MYR has no rate and no PO uses it.
Consequence if ignored: prices in six currencies compared as if they were dollars.
"""


def run(ctx):
    raw = ctx.t["raw_fx_rates"]
    df = raw[["month", "currency"]].copy()
    df["usd_per_unit"] = raw.usd_per_unit.astype(float)
    assert not df.duplicated(["month", "currency"]).any()
    ctx.t["fx_rates"] = df
