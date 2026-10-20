"""Name the buyers and products, and map the forecast's product names to part numbers.

Defect: the forecast says "Tern T2"; every other file says HR-90020. Buyers appear as full names and as initials
(TA, PN, MC, DR, SM) depending on which ERP wrote the line.
Rule: the mapping is a recorded answer (answers.yaml) checked against the item master's descriptions; a forecast row
whose name matches no product stops the build. Buyers map by name or initials to one id.
Consequence if ignored: the forecast cannot be exploded through the BOM, so demand is zero for every part.
"""
import pandas as pd

from app.domain.imports.context import examples


def run(ctx):
    ctx.t["buyers"] = pd.DataFrame(ctx.answers["buyers"])
    parts = ctx.t["parts"].set_index("part_number")
    prod = ctx.answers["products"]
    for name, p in prod.items():
        desc = parts.loc[p["part"], "description"]
        assert name.lower() in desc.lower(), f"{name} does not match {p['part']} ({desc})"
        assert parts.loc[p["part"], "kind"] == "finished"
    ctx.t["products"] = pd.DataFrame([dict(part_number=p["part"], name=n, family=p["family"]) for n, p in prod.items()])

    raw = ctx.t["raw_demand_forecast"]
    df = pd.DataFrame({"src_row": raw.src_row, "product_raw": raw["product"],
                       "product_part": raw["product"].map(lambda n: prod.get(n, {}).get("part")),
                       "month": raw.month, "units": raw.units.astype(int)})
    ctx.t["demand_forecast"] = df.assign(id=range(1, len(df) + 1))
    unmapped = df[df.product_part.isna()]
    ctx.issue("forecast.product_unresolved", "demand_forecast.csv", "Forecast product name matches no product", len(unmapped), "flag",
              "Row kept unmapped.", "Its demand is missing from every part.", examples(unmapped.product_raw), "ERP admin")
    ctx.issue("forecast.product_names", "demand_forecast.csv",
              "The forecast names robots, not part numbers", len(df), "fix",
              "Map each name to its finished-good part (answers.yaml), verified against the item master description.",
              "Without the mapping, forecast x BOM cannot give demand per part.",
              examples(f"{n} -> {p['part']}" for n, p in prod.items()), "ERP admin")
