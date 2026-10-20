"""Convert each line's quantity to the part's unit; say plainly when that is impossible.

Defect: ten spellings of five units (EA, ea, Each, PC, PCS; KPCS = thousands; FT; M; PK; BOX). 96 KPCS lines are
priced per thousand. 22 FT lines buy parts the master counts in metres. BOX has no pack size anywhere in the data.
Rule: normalise the unit; KPCS x 1000 EA, FT x 0.3048 M; qty_ea = quantity in the part's unit. A BOX line keeps its
money (line_usd is known) but qty_ea is unknown, so it is left out of per-piece comparisons.
Consequence if ignored: a KPCS price read per piece is 1,000 times too high; ft and m added together.
"""

from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag, norm_uom, to_part_unit


def run(ctx):
    df = ctx.t["po_lines"]
    parts = ctx.t["parts"].set_index("part_number")
    df["qty"] = df.qty_raw.astype(float)
    df["qty_received"] = df.qty_received_raw.astype(float)
    df["uom"] = df.uom_raw.map(norm_uom)
    qty_ea = []
    for r in df.itertuples():
        conv = to_part_unit(r.qty, r.uom)
        want = parts.uom.get(r.part_number)
        if conv is None:
            qty_ea.append(None)
        else:
            assert want in (None, conv[1]), f"{r.id}: {r.uom} gives {conv[1]} but part counts in {want}"
            qty_ea.append(conv[0])
    df["qty_ea"] = qty_ea
    df["_factor"] = df.uom.map({"EA": 1.0, "KPCS": 1000.0, "FT": 0.3048, "M": 1.0, "PK": 1.0})  # None for BOX
    spell = df[df.uom_raw != df.uom]
    ctx.issue("po.uom_spellings", "purchase_orders.csv", "Units typed several ways (ea, Each, PC, PCS)", len(spell), "fix",
              "Normalise to EA/KPCS/M/FT/PK/BOX; raw kept in uom_raw.", "Grouping by unit splits one unit into five.",
              examples(spell.uom_raw + " -> " + spell.uom), "ERP admin")
    k = df[df.uom == "KPCS"]
    ctx.issue("po.kpcs_pricing", "purchase_orders.csv", "KPCS lines: quantity in thousands, price per thousand", len(k), "fix",
              "qty_ea = qty x 1000; the price per piece = price / 1000; the line value is unchanged.",
              "Read as pieces, a KPCS line has a thousandth of its parts and a price 1,000 times too high.",
              examples(k.id + ": " + k.qty_raw + " KPCS @ " + k.unit_price_raw), "@parts:" + ",".join(k.part_number.unique()))
    ft = df[df.uom == "FT"]
    ctx.issue("po.feet_for_metre_parts", "purchase_orders.csv", "Lines bought in feet for parts the master counts in metres", len(ft), "fix",
              "Convert feet to metres (x 0.3048); raw kept.", "Wire quantities off by 3.3x against the BOM.",
              examples(ft.id + ": " + ft.qty_raw + " FT"), "@parts:" + ",".join(ft.part_number.unique()))
    box = df[df.uom == "BOX"]
    add_flag(df, df.uom == "BOX", "box_size_unknown")
    ctx.issue("po.box_size_unknown", "purchase_orders.csv", "Lines bought by the BOX with no pack size in the data", len(box), "leave",
              "qty_ea stays unknown; the line's money (line_usd) is kept; the line is excluded from per-piece price comparisons.",
              "The number of pieces bought cannot be stated; a per-piece price would be a guess.",
              examples(box.id + ": " + box.qty_raw + " BOX"), "@parts:" + ",".join(box.part_number.unique()))
