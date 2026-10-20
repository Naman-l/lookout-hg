"""The load gate: checks that run in code before anything is written to the database.

A build whose gate fails writes no database. Each check returns (name, passed, detail). The checks are the
ones design/IMPORT.md names: every raw row reconciled, no raw value lost, every inferred value labelled,
aliases linked not merged, joins resolve or the gap is a counted issue.
"""

from __future__ import annotations

import pandas as pd

from app.domain.imports.context import Ctx

# clean table -> (raw table, one raw row per clean row, or rows may be dropped with a reason)
RECONCILED = {
    "supplier_records": "raw_suppliers",
    "parts": "raw_parts",
    "bom_lines": "raw_bom",
    "po_lines": "raw_purchase_orders",
    "demand_forecast": "raw_demand_forecast",
}

# clean column -> raw column: the clean row keeps the source value exactly as it was
RAW_KEPT = {
    "supplier_records": {"country_raw": "country", "payment_terms_raw": "payment_terms", "incoterms_raw": "incoterms"},
    "parts": {"coo_raw": "country_of_origin", "hts_raw": "hts_code", "category_raw": "category"},
    "bom_lines": {"qty_per_raw": "qty_per", "uom_raw": "uom"},
    "po_lines": {"part_raw": "part_number", "qty_raw": "qty", "uom_raw": "uom", "unit_price_raw": "unit_price",
                 "currency_raw": "currency", "qty_received_raw": "qty_received", "buyer_raw": "buyer", "order_date_raw": "order_date",
                 "promised_date_raw": "promised_date", "received_date_raw": "received_date"},
    "demand_forecast": {"product_raw": "product"},
}

# (clean table, clean column, raw column, method column): a blank in the source filled by a rule must say so
INFERRED = [("po_lines", "currency", "currency", "currency_method")]

# join name -> (child table, child column, parent table, parent column, issue key that counts the gap)
JOINS = {
    "po_lines.part": ("po_lines", "part_number", "parts", "part_number", "po.part_unresolved"),
    "po_lines.record": ("po_lines", "record_id", "supplier_records", "record_id", "po.supplier_unresolved"),
    "bom.parent": ("bom_lines", "parent_part", "parts", "part_number", "bom.parent_unresolved"),
    "bom.child": ("bom_lines", "child_part", "parts", "part_number", "bom.orphan_child"),
    "parts.preferred": ("parts", "preferred_record_id", "supplier_records", "record_id", "parts.preferred_unresolved"),
    "forecast.product": ("demand_forecast", "product_part", "parts", "part_number", "forecast.product_unresolved"),
}


def run_gate(ctx: Ctx) -> list[tuple[str, bool, str]]:
    t, out = ctx.t, []
    drops = pd.DataFrame(ctx.drops, columns=["raw_table", "src_row", "reason", "kept_as", "step"])

    # 1. every raw row is in the clean table once, or dropped once with a reason
    for clean, raw in RECONCILED.items():
        raw_rows = set(t[raw]["src_row"])
        kept = list(t[clean]["src_row"])
        dropped = list(drops.loc[drops.raw_table == raw, "src_row"])
        dup = len(kept) + len(dropped) - len(set(kept) | set(dropped))
        missing = raw_rows - set(kept) - set(dropped)
        extra = (set(kept) | set(dropped)) - raw_rows
        ok = not dup and not missing and not extra
        out.append((f"rows reconciled: {raw} -> {clean}", ok,
                    f"{len(raw_rows)} raw rows = {len(kept)} kept + {len(dropped)} dropped with a reason"
                    + ("" if ok else f"; missing {len(missing)}, twice {dup}, unknown {len(extra)}")))

    # 2. no raw value lost: *_raw columns equal the source at the same row
    for clean, cols in RAW_KEPT.items():
        raw = RECONCILED[clean]
        merged = t[clean].merge(t[raw], on="src_row", suffixes=("", "__src"))
        for ccol, rcol in cols.items():
            src = merged[rcol + "__src"] if rcol + "__src" in merged else merged[rcol]
            bad = int((merged[ccol].fillna("") != src.fillna("")).sum())
            out.append((f"raw kept: {clean}.{ccol}", bad == 0, f"{len(merged)} rows compared with {raw}.{rcol}; {bad} differ"))

    # 3. every inferred value is labelled
    for clean, ccol, rcol, mcol in INFERRED:
        merged = t[clean].merge(t[RECONCILED[clean]][["src_row", rcol]].rename(columns={rcol: "__raw"}), on="src_row")
        filled = merged[(merged["__raw"].str.strip() == "") & merged[ccol].notna() & (merged[ccol] != "")]
        bad = int((filled[mcol] != "inferred").sum())
        out.append((f"inferred labelled: {clean}.{ccol}", bad == 0, f"{len(filled)} blanks filled by a rule; {bad} unlabelled"))

    # 4. aliases linked, not merged
    rec, ident = t["supplier_records"], t["supplier_identities"]
    ok = len(rec) == len(t["raw_suppliers"]) and rec["identity_id"].isin(ident["id"]).all() and len(ident) <= len(rec)
    out.append(("aliases linked, not merged: supplier_records", bool(ok),
                f"{len(rec)} ERP records kept under {len(ident)} companies"))

    # 5. joins resolve, or the gap is a counted issue
    keys = {i["key"]: i["count"] for i in ctx.issues}
    for name, (ct, cc, pt, pc, ikey) in JOINS.items():
        child = t[ct][cc].dropna()
        gap = int((~child.isin(t[pt][pc])).sum())
        ok = gap == 0 or keys.get(ikey) == gap
        out.append((f"join resolves: {name}", ok, f"{len(child)} references, {gap} unresolved"
                    + (f", counted in issue {ikey}" if gap and ok else "")))

    # 6. primary keys are unique where the model says so
    for tbl, col in [("po_lines", "id"), ("parts", "part_number"), ("supplier_records", "record_id")]:
        dups = int(t[tbl][col].duplicated().sum())
        out.append((f"unique: {tbl}.{col}", dups == 0, f"{dups} duplicates"))
    return out
