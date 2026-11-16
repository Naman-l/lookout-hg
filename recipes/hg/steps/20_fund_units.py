"""The fund requirement sheets as lines in rupees; amounts typed in lakh or rupees in a sheet that is in crore read in their own unit.

Defect: the fund sheets are in ₹ Cr, but three cells were typed in other units, as text: "45 L" (Karnal, mechanical dues, November), "23,50,000"
(Ganga, transportation, November, in rupees) and "1.5 L" (Dhule, consumables, October). The sheet's own SUM leaves text out, so its totals do not
include them.
Rule: each cell is read in the unit it names (lakh, crore) or, with Indian grouping, as rupees; a plain number is crore, as the sheet says. Lines are
in rupees with the raw text and its unit kept. Each total the sheet prints is recomputed from its numeric cells, as its SUM did, and checked by the
gate; the cells typed as text are then counted in.
Consequence if ignored: "45 L" read as 45 Cr is a hundred times too much; left out, as the sheet's total leaves it out, the month is understated.
"""
import pandas as pd

from app.domain.imports.helpers import month_label, parse_inr, stamp_in_name

BANDS = ("Sub Total for New Projects", "Sub Total for Nearing Completion Projects", "Sub Total for Railway Projects", "Sub Total for BESS+Solar+T&D")


def run(ctx):
    lines, totals, odd = [], [], []
    files = ctx.t["_files"]
    for f in files[files.key == "fund"].itertuples():
        g = ctx.t[f.raw_table]
        month = month_label(f.file.split("/")[-1].split(" ")[-2])
        built = stamp_in_name(f.file.split("/")[-1]).isoformat()
        alias = {a.alias: a.project_ids for a in ctx.t["project_aliases"].itertuples() if a.source == "fund"}
        h = g.index[g.c0 == "Description"][0]
        header = g.loc[h]
        ncol = g.shape[1] - 1
        cols, band_of, band, k = [], {}, 0, 0
        for c in range(1, ncol):
            name = str(header[f"c{c}"]).strip()
            if not name:
                continue
            if name in BANDS:
                band_of[c] = ("band", BANDS.index(name))
                band += 1
                continue
            if name.startswith("Sub Total in"):
                band_of[c] = ("all", None)
                continue
            cols.append((c, name, ["new", "near", "railway", "ne"][min(band, 3)]))
        r = h + 1
        while r in g.index and str(g.at[r, "c0"]).strip() and str(g.at[r, "c0"]).strip() != "Total Cost in Cr.":
            head = str(g.at[r, "c0"]).strip()
            per_band, numeric_sum = {}, 0.0
            for c, name, bnd in cols:
                raw = str(g.at[r, f"c{c}"]).strip()
                if not raw:
                    continue
                amt, unit = parse_inr(raw, unit="cr")
                flags = ""
                if unit != "cr":
                    odd.append(f"{name}, {head}: '{raw}'")
                    flags = "unit_fixed"
                else:      # what the sheet's SUM saw
                    per_band[bnd] = per_band.get(bnd, 0.0) + amt
                    numeric_sum += amt
                lines.append(dict(file=f.file, month=month, built_on=built, head=head, column_as_printed=name, project_ids=alias.get(name), band=bnd, amount=amt,
                                  amount_raw=raw, unit_raw=unit, src_row=int(g.at[r, "src_row"]), src_col=c, flags=flags))
            for c, (kind, idx) in band_of.items():
                raw = str(g.at[r, f"c{c}"]).strip()
                printed = parse_inr(raw, unit="cr")[0] if raw else 0.0
                computed = numeric_sum if kind == "all" else per_band.get(["new", "near", "railway", "ne"][idx], 0.0)
                totals.append(dict(id=f"fund:{month}:{r}:{c}", file=f.file, what=f"{month} {head}, {str(header[f'c{c}']).strip()}", printed=printed, computed=computed,
                                   tolerance=0.011 * 1e7 * max(1, len(cols)) / 10, note="the sheet's SUM, which leaves out cells typed as text"))
            r += 1
    df = pd.DataFrame(lines)
    df.insert(0, "id", range(1, len(df) + 1))
    ctx.t["fund_lines"] = df
    ctx.t["sheet_totals"] = pd.concat([ctx.t["sheet_totals"], pd.DataFrame(totals)], ignore_index=True)
    ctx.issue("fund.mixed_units", "sheets/SCM Fund Requirement", "Amounts mixed between ₹, Lakh and Cr in a sheet that is in Cr", len(odd), "fix",
              "Each cell read in the unit it names (lakh, crore; Indian grouping = rupees); lines in rupees, raw text and unit kept; the sheet's totals, which left the text out, are recomputed with them.",
              "\"45 L\" read as 45 Cr is a hundred times too much; left out, as the sheet's SUM leaves it out, the month is understated.", "; ".join(odd[:3]), "Sudeep")
