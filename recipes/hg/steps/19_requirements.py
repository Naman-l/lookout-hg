"""The 3-month material requirement (roads and railway sheets) as one line per project, row and month; every printed total recomputed.

Defect: the sheets are laid out for reading, not for reading by machine: a title row, then a header over three rows (the bands "Nearly
Completion Projects" / "Newly Started Projects" or the months, the project names, then the plant codes or the months), each material as a
Qty. / Rate / Amount triplet, quantities in an accounting format ("  51,485 ", "  -   ") and amounts in Cr. Cells hold spreadsheet errors
(#DIV/0! in the weighted rate of an empty row, #REF! under the totals).
Rule: the header is read by position (the "Material" row, the names below it, the months or plants below that); a quantity cell with a number
above zero becomes a line (project, row, month, qty, rate, amount = qty x rate), keeping the cell's row and column and its text. Error cells are
counted and left. Every total the sheet prints (a row's quarter total, a column's amount) is recomputed from the cells read; the gate fails the build
if one disagrees.
Consequence if ignored: a misread header puts a quantity under the wrong project or month; a lost cell disappears from every total.
"""
import pandas as pd

from app.domain.imports.helpers import month_label, parse_number, stamp_in_name


def _parse(ctx, key: str, sheet: str, lines: list, totals: list) -> int:
    files = ctx.t["_files"]
    hit = files[files.key == key]
    if hit.empty:
        return 0
    f = hit.iloc[0]
    g = ctx.t[f.raw_table]
    built = stamp_in_name(f.file.split("/")[-1]).isoformat()
    alias = {a.alias: a.project_ids for a in ctx.t["project_aliases"].itertuples() if a.source == key}
    codes = ctx.answers["sheet_materials"]
    h = g.index[g.c0 == "Material"][0]
    band, names, third = g.loc[h], g.loc[h + 1], g.loc[h + 2]
    cols, month_totals, quarter_col, b, name = [], {}, None, "", ""
    ncol = g.shape[1] - 1
    for c in range(3, ncol):
        bt, nm, th = str(band[f"c{c}"]).strip(), str(names[f"c{c}"]).strip(), str(third[f"c{c}"]).strip()
        if bt:
            b = bt
        if nm:
            name = nm
        if b.lower().startswith(("total", "weighted")):
            if sheet == "railway" and b.lower().startswith("total") and quarter_col is None:
                quarter_col = c
            break
        month = month_label(th) or month_label(b)
        if name.lower().startswith("total"):
            if sheet == "railway" and month and nm:      # the railway sheet's own total for each month
                month_totals[c] = month
            continue
        if not month:
            continue
        cols.append((c, name, month))
    errors = 0
    rows = g.index[g.c1 == "Qty."]
    for r in rows:
        row = str(g.at[r, "c0"]).strip().replace("\n", " ")
        unit = str(g.at[r, "c2"]).strip() or None
        sum_qty, by_month = 0.0, {}
        for c, nm, month in cols:
            raw_q, raw_r, raw_a = str(g.at[r, f"c{c}"]), str(g.at[r + 1, f"c{c}"]), str(g.at[r + 2, f"c{c}"])
            try:
                q = parse_number(raw_q)
            except ValueError:
                errors += 1
                continue
            if not q:
                continue
            try:
                rate = parse_number(raw_r)
            except ValueError:
                errors += 1
                rate = None
            amt_p = parse_number(raw_a) if raw_a.strip() and not raw_a.strip().startswith("#") else None
            sum_qty += q
            by_month[month] = by_month.get(month, 0.0) + q
            lines.append(dict(id=f"{sheet}:{g.at[r, 'src_row']}:{c}", sheet=sheet, file=f.file, built_on=built, project_id=alias.get(nm), column_as_printed=nm,
                              row_as_printed=row, material_codes=",".join(codes.get(row, [])), unit=unit, month=month, qty=q, qty_raw=raw_q, rate=rate,
                              rate_raw=raw_r if raw_r.strip() else None, amount=q * rate if rate else None, amount_printed=amt_p * 1e7 if amt_p is not None else None,
                              src_row=int(g.at[r, "src_row"]), src_col=c))
        for c, month in month_totals.items():      # each month's total column (railway)
            t = parse_number(str(g.at[r, f"c{c}"]))
            if t is not None:
                totals.append(dict(id=f"{sheet}:qty:{g.at[r, 'src_row']}:{month}", file=f.file, what=f"{row} quantity, {month} total", printed=t,
                                   computed=by_month.get(month, 0.0), tolerance=max(2.0, abs(t) * 0.0001), note=None))
        start = quarter_col if quarter_col is not None else (max(c for c, _, _ in cols) + 1 if cols else 3)
        for c in range(start, ncol):      # the row's quarter total: the "Total Q3" column, else the first number after the last month column
            v = str(g.at[r, f"c{c}"])
            try:
                t = parse_number(v)
            except ValueError:
                errors += 1
                continue
            if t is not None:
                totals.append(dict(id=f"{sheet}:qty:{g.at[r, 'src_row']}", file=f.file, what=f"{row} quantity, quarter total", printed=t, computed=sum_qty,
                                   tolerance=max(2.0, abs(t) * 0.0001), note=None))
                break
    for r in g.index:      # the spreadsheet errors elsewhere on the sheet (weighted rates of empty rows, #REF! under the totals)
        errors += sum(1 for c in range(ncol) if str(g.at[r, f"c{c}"]).strip().startswith("#")) if g.at[r, "c1"] not in ("Qty.",) else 0
    return errors


def run(ctx):
    lines, totals = [], []
    errors = _parse(ctx, "roads_req", "roads", lines, totals) + _parse(ctx, "railway_req", "railway", lines, totals)
    df = pd.DataFrame(lines)
    ctx.t["requirement_lines"] = df
    ctx.t["sheet_totals"] = pd.DataFrame(totals)
    nameless = df[df.project_id.isna()] if len(df) else df
    assert nameless.empty, f"requirement columns with no project: {sorted(set(nameless.column_as_printed))}"
    ctx.issue("requirements.sheet_errors", "sheets/Roads and Railway requirement", "Spreadsheet errors in the requirement sheets (#DIV/0!, #REF!)", errors, "leave",
              "Counted and left as they are; no figure is read from an error cell.", "An error read as a number, or a row silently dropped.",
              "#DIV/0! in the weighted rate of empty rows; #REF! under the totals", "Sudeep")
