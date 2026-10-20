"""Clean the bill of materials: a repeated row, a unit mismatch, an orphan child, an obsolete child.

Defect: HR-15109 appears twice under HR-80240 with identical rows (an export duplicate); HR-10033 appears twice under
HR-80140 with different quantity and find number (two placements: both are real); HR-75107 is 2,000 MM in the BOM
and M in the item master; HR-77190 is not in the item master; obsolete HR-52010 is still in two power modules.
Rule: drop only exact duplicates (counted, with the surviving row named); keep second placements and flag them;
convert the BOM unit to the part's unit when the conversion is exact (MM -> M) and keep the raw; keep orphans and
flag them (the explosion shows the part, the master does not know it); flag obsolete children.
Consequence if ignored: HR-15109 is counted twice in every robot; 2,000 metres of tubing in one robot; a demand
line for a part nobody can price or order; builds planned around an obsolete converter.
"""
import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import norm_part_number, norm_uom, to_part_unit

KEY = ["parent_part", "child_part", "qty_per", "uom", "level", "find_no"]


def run(ctx):
    raw = ctx.t["raw_bom"]
    parts = ctx.t["parts"].set_index("part_number")
    dup = raw.duplicated(subset=KEY, keep="first")
    first = raw[~dup].set_index(KEY).src_row
    for src, key in zip(raw[dup].src_row, raw[dup][KEY].itertuples(index=False, name=None)):
        ctx.drop("raw_bom", src, "exact duplicate of another BOM row (export glitch)", f"raw_bom row {first[key]}")
    ctx.issue("bom.exact_duplicate_rows", "bom.csv", "A BOM row repeated exactly", int(dup.sum()), "drop",
              "Drop the second copy; the drop is recorded in row_drops with the row it duplicates.",
              "The part is counted twice in every robot's explosion.",
              examples(raw[dup].parent_part + " > " + raw[dup].child_part), "ERP admin")
    r = raw[~dup].copy()
    df = pd.DataFrame({"src_row": r.src_row, "parent_part": r.parent_part.map(norm_part_number),
                       "child_part": r.child_part.map(norm_part_number), "qty_per_raw": r.qty_per, "uom_raw": r.uom,
                       "level": r.level.astype(int), "find_no": r.find_no.replace("", None)})
    qty, uom, flags = [], [], []
    for row, raw_row in zip(df.itertuples(), r.itertuples()):
        f, q, u = [], float(raw_row.qty_per), norm_uom(raw_row.uom)
        pu = parts.uom.get(row.child_part)
        if pu and u != pu:
            conv = to_part_unit(q, u)
            assert conv and conv[1] == pu, f"BOM unit {u} cannot become {pu} for {row.child_part}"
            q, u = conv[0], pu
            f.append("unit_converted")
        qty.append(q); uom.append(u); flags.append(f)
    df["qty_per"], df["uom"] = qty, uom
    placements = df.groupby(["parent_part", "child_part"]).size()
    multi = {k for k, v in placements.items() if v > 1}
    obsolete = set(parts.index[parts.status == "Obsolete"])
    for i, row in enumerate(df.itertuples()):
        if (row.parent_part, row.child_part) in multi:
            flags[i].append("second_placement")
        if row.child_part not in parts.index:
            flags[i].append("orphan_child")
        if row.child_part in obsolete:
            flags[i].append("obsolete_child")
    df["flags"] = [",".join(f) or None for f in flags]
    ctx.t["bom_lines"] = df.reset_index(drop=True).assign(id=lambda d: range(1, len(d) + 1))

    def has(flag):
        return df[df["flags"].fillna("").str.contains(flag)]

    s = has("second_placement")
    ctx.issue("bom.second_placement", "bom.csv", "The same child twice under one parent with a different quantity or find number",
              len(s), "flag", "Both rows kept: they are two placements on the drawing, not an error.",
              "Collapsing them would understate the part's quantity per robot.", examples(s.parent_part + " > " + s.child_part + " pos " + s.find_no.fillna("?")), "ERP admin")
    c = has("unit_converted")
    ctx.issue("bom.unit_mismatch", "bom.csv", "BOM quantity in a different unit from the item master", len(c), "fix",
              "Convert exactly (MM -> M); the raw quantity and unit stay in qty_per_raw and uom_raw.",
              "A length in millimetres read as metres is a thousand-fold demand.",
              examples(c.child_part + ": " + c.qty_per_raw + " " + c.uom_raw + " -> " + c.qty_per.astype(str) + " " + c.uom), "@parts:" + ",".join(c.child_part))
    o = has("orphan_child")
    ctx.issue("bom.orphan_child", "bom.csv", "BOM child is not in the item master", len(o), "flag",
              "Row kept and flagged; the explosion lists the part, the part master cannot describe or price it.",
              "Demand for this part can never be matched to a supplier, price or PO.",
              examples(o.parent_part + " > " + o.child_part), "ERP admin")
    ob = has("obsolete_child")
    ctx.issue("bom.obsolete_child", "bom.csv", "An obsolete part is still in a BOM", len(ob), "flag",
              "Kept and flagged; demand for it is shown with the obsolete status.",
              "Builds are planned around a part marked no longer used: either the BOM or the status is wrong.",
              examples(ob.parent_part + " > " + ob.child_part), "@parts:" + ",".join(ob.child_part))
    # declared depth must match the structure
    kids = df.groupby("parent_part").child_part.apply(list).to_dict()
    depth = {}

    def walk(p, d):
        for ch in kids.get(p, []):
            depth.setdefault((p, ch), d)
            walk(ch, d + 1)

    for root in parts.index[parts.kind == "finished"]:
        walk(root, 1)
    bad = df[[depth.get((a, b), -1) != lv for a, b, lv in zip(df.parent_part, df.child_part, df.level)]]
    ctx.issue("bom.level_mismatch", "bom.csv", "Declared level differs from the structure", len(bad), "flag",
              "Level is not used; depth comes from the structure.", "Indented BOM views would mis-indent.", examples(bad.parent_part + " > " + bad.child_part), "ERP admin")
