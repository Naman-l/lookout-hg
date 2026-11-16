"""Load every source file as text, one row per record, untouched.

Defect: none yet; this is the baseline every later check reconciles against.
Rule: strings only (no type guessing), a 1-based `src_row`, files read-only. A SAP list export's stamp line is read apart from its header; a
hand-built sheet with a layout of its own (title rows, multi-row headers) is read as a grid of cells (c0, c1, ...) so no cell is lost to a
header guess. The `raw_*` tables are never changed by a later step (except the date cut in step 02) and are written to the database, so any
clean value can be traced to its source row and cell.
"""
import pandas as pd

from app.domain.imports.helpers import month_label


def run(ctx):
    files = []
    for key, spec in ctx.answers["sources"].items():
        if spec["kind"] == "inbox":
            continue      # step 27 reads the mail
        rels = [spec["file"]] if "file" in spec else ctx.find(spec["glob"])
        for rel in rels:
            if spec.get("layout") == "grid":
                df = ctx.read_grid(rel)
            else:
                df = ctx.read_csv(rel, skip=spec.get("skip", 1 if spec.get("stamp") == "header" else 0))
            name = f"raw_{key}"
            if spec.get("many"):      # one raw table per file, named by the month the file is for ("November-26" -> raw_fund_2026_11)
                name += "_" + month_label(rel.split("/")[-1].split(" ")[-2]).replace("-", "_")
            ctx.t[name] = df
            files.append(dict(key=key, file=rel, raw_table=name, kind=spec["kind"], stamp=spec.get("stamp", "none"), title=spec.get("title", key),
                              first_line=ctx.first_line(rel), rows=len(df)))
    ctx.t["_files"] = pd.DataFrame(files)
