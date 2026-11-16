"""The load gate: checks that run in code before anything is written to the database.

A build whose gate fails writes no database. Each check returns (name, passed, detail). What is checked is the recipe's (`gate.yaml` beside
`answers.yaml`), never a table named here: every raw row reconciled (kept once, or dropped once with a reason), no raw value lost, every inferred
value labelled, aliases linked not merged, joins resolve or the gap is a counted issue, keys unique, every sheet cell read once and kept as
written, every total a sheet prints recomputed from the cells read, and nets that cannot be negative are not.
"""

from __future__ import annotations

import pandas as pd

from app.domain.imports.context import Ctx


def reconciled(ctx: Ctx) -> dict[str, dict]:
    """{clean table: {"raw": raw table, "where": an optional pandas query selecting the clean rows that come from it}}."""
    out = {}
    for clean, spec in ((ctx.gate or {}).get("reconciled") or {}).items():
        out[clean] = spec if isinstance(spec, dict) else {"raw": spec}
    return out


def _rows(t: dict, name: str) -> pd.DataFrame:
    return t.get(name, pd.DataFrame())


def run_gate(ctx: Ctx) -> list[tuple[str, bool, str]]:
    t, out, cfg = ctx.t, [], ctx.gate or {}
    drops = pd.DataFrame(ctx.drops, columns=["raw_table", "src_row", "reason", "kept_as", "step"])

    # 1. every raw row is in the clean table once, or dropped once with a reason
    for clean, spec in reconciled(ctx).items():
        raw = spec["raw"]
        if raw not in t:      # a sheet built after the data date is not read (step 02): nothing to reconcile, unless a clean table was made anyway
            made = clean in t and len(t[clean]) and (not spec.get("where") or len(t[clean].query(spec["where"])))
            out.append((f"rows reconciled: {raw} -> {clean}", not made, "not read: built after the data date" if not made else f"{raw} was not loaded"))
            continue
        c = _rows(t, clean)
        if spec.get("where") and len(c):
            c = c.query(spec["where"])
        raw_rows = set(t[raw]["src_row"])
        kept = list(c["src_row"]) if len(c) else []
        dropped = list(drops.loc[drops.raw_table == raw, "src_row"])
        dup = len(kept) + len(dropped) - len(set(kept) | set(dropped))
        missing = raw_rows - set(kept) - set(dropped)
        extra = (set(kept) | set(dropped)) - raw_rows
        ok = not dup and not missing and not extra
        out.append((f"rows reconciled: {raw} -> {clean}", ok,
                    f"{len(raw_rows)} raw rows = {len(kept)} kept + {len(dropped)} dropped with a reason"
                    + ("" if ok else f"; missing {len(missing)}, twice {dup}, unknown {len(extra)}")))

    # 2. no raw value lost: *_raw columns equal the source at the same row
    for clean, cols in (cfg.get("raw_kept") or {}).items():
        spec = reconciled(ctx).get(clean)
        if not spec or clean not in t or not len(t[clean]) or spec["raw"] not in t:
            continue
        c = t[clean].query(spec["where"]) if spec.get("where") else t[clean]
        merged = c.merge(t[spec["raw"]], on="src_row", suffixes=("", "__src"))
        for ccol, rcol in cols.items():
            src = merged[rcol + "__src"] if rcol + "__src" in merged else merged[rcol]
            bad = int((merged[ccol].fillna("").astype(str) != src.fillna("").astype(str)).sum())
            out.append((f"raw kept: {clean}.{ccol}", bad == 0, f"{len(merged)} rows compared with {spec['raw']}.{rcol}; {bad} differ"))

    # 3. every inferred value is labelled
    for clean, ccol, rcol, mcol in cfg.get("inferred") or []:
        spec = reconciled(ctx)[clean]
        merged = t[clean].merge(t[spec["raw"]][["src_row", rcol]].rename(columns={rcol: "__raw"}), on="src_row")
        filled = merged[(merged["__raw"].str.strip() == "") & merged[ccol].notna() & (merged[ccol] != "")]
        bad = int((filled[mcol] != "inferred").sum())
        out.append((f"inferred labelled: {clean}.{ccol}", bad == 0, f"{len(filled)} blanks filled by a rule; {bad} unlabelled"))

    # 4. aliases linked, not merged
    for spec in cfg.get("linked_not_merged") or []:
        rec, ident, raw = _rows(t, spec["records"]), _rows(t, spec["identities"]), spec["raw"]
        ok = len(rec) == len(t[raw]) - int((drops.raw_table == raw).sum()) and rec[spec["identity_col"]].isin(ident["id"]).all() and len(ident) <= len(rec)
        out.append((f"aliases linked, not merged: {spec['records']}", bool(ok), f"{len(rec)} records kept under {len(ident)} companies"))

    # 5. joins resolve, or the gap is a counted issue
    keys = {i["key"]: i["count"] for i in ctx.issues}
    for name, (ct, cc, pt, pc, ikey) in (cfg.get("joins") or {}).items():
        child = _rows(t, ct)[cc].dropna() if cc in _rows(t, ct) else pd.Series(dtype=str)
        child = child[child.astype(str) != ""]
        gap = int((~child.isin(_rows(t, pt)[pc])).sum())
        ok = gap == 0 or keys.get(ikey) == gap
        out.append((f"join resolves: {name}", ok, f"{len(child)} references, {gap} unresolved" + (f", counted in issue {ikey}" if gap and ok else "")))

    # 6. primary keys are unique where the model says so
    for tbl, col in cfg.get("unique") or []:
        dups = int(_rows(t, tbl)[col].duplicated().sum()) if col in _rows(t, tbl) else 0
        out.append((f"unique: {tbl}.{col}", dups == 0, f"{dups} duplicates"))

    # 7. every sheet cell read once, and kept exactly as written
    for spec in cfg.get("cells") or []:
        c, raw = _rows(t, spec["clean"]), spec["raw"]
        rows = c.query(spec["where"]) if spec.get("where") and len(c) else c
        if not len(rows):
            out.append((f"cells kept: {spec['clean']} <- {raw}", raw not in t or not len(t[raw]), "no cells read"))
            continue
        dup = int(rows.duplicated(subset=["src_row", "src_col"]).sum())
        grid = t[raw].set_index("src_row")
        bad = sum(1 for r in rows.itertuples() if str(grid.at[r.src_row, f"c{r.src_col}"]) != str(getattr(r, spec["raw_col"])))
        out.append((f"cells kept: {spec['clean']} <- {raw}", dup == 0 and bad == 0, f"{len(rows)} cells read; {dup} read twice; {bad} differ from the sheet"))

    # 8. every total a sheet prints equals the same total recomputed from the cells read
    if cfg.get("sheet_totals"):
        st = _rows(t, "sheet_totals")
        checked = st[st.printed.notna()] if len(st) else st
        bad = checked[(checked.printed - checked.computed).abs() > checked.tolerance] if len(checked) else checked
        out.append(("sheet totals recompute", len(bad) == 0, f"{len(checked)} printed totals recomputed from the cells read; {len(bad)} disagree"
                    + ("" if not len(bad) else ": " + "; ".join(f"{r.what} {r.printed:g} vs {r.computed:g}" for r in bad.head(3).itertuples()))))

    # 9. nets that cannot be negative are not (a reversal or a return never takes back more than was received)
    for spec in cfg.get("nonnegative") or []:
        c = _rows(t, spec["table"])
        if not len(c):
            continue
        net = c.groupby(spec["group_by"])[spec["column"]].sum()
        neg = int((net < -1e-6).sum())
        out.append((f"not negative: {spec['table']}.{spec['column']} per {spec['group_by']}", neg == 0, f"{len(net)} groups; {neg} net negative"))
    return out
