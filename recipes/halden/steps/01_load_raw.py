"""Load every source file as text, one row per record, untouched.

Defect: none yet; this is the baseline every later check reconciles against.
Rule: strings only (no type guessing), a 1-based `src_row`, files read-only. The `raw_*` tables are never changed
by any later step and are written to the database, so any clean value can be traced to its source row.
"""
FILES = {
    "raw_suppliers": "suppliers.csv",
    "raw_parts": "parts.csv",
    "raw_bom": "bom.csv",
    "raw_purchase_orders": "purchase_orders.csv",
    "raw_demand_forecast": "demand_forecast.csv",
    "raw_fx_rates": "external/fx_rates.csv",
}


def run(ctx):
    for table, rel in FILES.items():
        ctx.t[table] = ctx.read_csv(rel)
