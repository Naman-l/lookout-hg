"""Materials from the SAP material master, with the category a buyer reads and the index a price-variation clause moves with.

Defect: none in the master; the category is not a SAP field.
Rule: the master as SAP has it (group, base unit, alternate unit and its conversion, planned delivery time, PV index); the category of each
group is MIS's answer.
Consequence if ignored: materials cannot be read by category, and a price index cannot be tied to what it prices.
"""
import pandas as pd


def run(ctx):
    m = ctx.t["raw_material_master"]
    cats = ctx.answers["material_categories"]
    missing = sorted(set(m["Material Group"]) - set(cats))
    assert not missing, f"material groups with no category: {missing}"
    num = lambda s: float(s) if s.strip() else None  # noqa: E731
    ctx.t["materials"] = pd.DataFrame(dict(code=m.Material, description=m["Material Description"], group=m["Material Group"], category=m["Material Group"].map(cats),
                                           base_uom=m["Base Unit of Measure"], alt_uom=m["Alternative Unit"].replace("", None),
                                           alt_per_base=m["Alt. Units per Base Unit"].map(num), lead_days=m["Planned Deliv. Time (days)"].map(lambda s: int(s) if s.strip() else None),
                                           pv_index=m["PV Index"].replace("", None), src_row=m.src_row))
