"""The reference tables: the delegation of authority, the commodity indices, and the long-lead look-ahead with each item's order-by date.

Defect: none planted. The DoA writes limits in Indian grouping ("5,00,00,000"); the look-ahead writes lead times as text ("10-12 Months"), need-by
as MM/YYYY and names projects its own way (resolved in step 06).
Rule: DoA limits to numbers; index values to numbers by month; for each look-ahead item, the lead time's bounds, the need-by month, the order-by
date (need-by minus the longest lead time), the material it is (answers.yaml) and that material's PV index; amount = qty x rate, checked against
the printed amount by the gate.
Consequence if ignored: a draft's countersign cannot be decided, a PV claim cannot be checked, and a long-lead item's last safe order date is not known.
"""
import re
from datetime import date

import pandas as pd

from app.domain.imports.helpers import parse_number


def run(ctx):
    d = ctx.t["raw_doa"]
    ctx.t["doa_rules"] = pd.DataFrame(dict(id=range(1, len(d) + 1), document=d.Document, from_inr=d["From (INR)"].map(parse_number).fillna(0.0),
                                           to_inr=d["To (INR)"].map(parse_number), approver=d.Approver, countersign=d.Countersign.replace("", None), src_row=d.src_row))
    ci = ctx.t["raw_commodity_index"]
    ctx.t["commodity_index"] = pd.DataFrame(dict(id=ci.Index + ":" + ci.Month, month=ci.Month, index=ci.Index, value=ci.Value.astype(float), unit=ci.Unit,
                                                 source=ci.Source, src_row=ci.src_row))
    if "raw_lookahead" not in ctx.t:      # built after the data date (step 02): not read
        return
    la = ctx.t["raw_lookahead"]
    alias = {a.alias: a.project_ids for a in ctx.t["project_aliases"].itertuples() if a.source == "lookahead"}
    mats = ctx.answers["lookahead_materials"]
    pv = dict(zip(ctx.t["materials"].code, ctx.t["materials"].pv_index))
    rows, totals = [], []
    for _, x in la.iterrows():
        lead = re.findall(r"\d+", x["Lead Time"])
        lo, hi = int(lead[0]), int(lead[-1])
        mm, yy = x["Need By (MM/YYYY)"].split("/")
        need = f"{yy}-{int(mm):02d}"
        y, m = divmod(int(yy) * 12 + int(mm) - 1 - hi, 12)
        qty, rate = float(x.Qty), parse_number(x["Tentative Rate (INR)"])
        code = mats.get(x.Item)
        rows.append(dict(id=int(x.src_row), block="immediate" if x.Block.startswith("Need") else "q4", project_as_printed=x.Project, project_id=alias.get(x.Project),
                         scope=(re.search(r" - (SS|TL)$", x.Project) or [None, None])[1], item=x.Item, uom=x.UOM, qty=qty, rate=rate, rate_raw=x["Tentative Rate (INR)"],
                         amount=qty * rate, price_basis=x["Price Basis"], lead_min_months=lo, lead_max_months=hi, lead_raw=x["Lead Time"], need_by=need,
                         order_by=date(y, m + 1, 1).isoformat(), material=code, pv_index=pv.get(code) if x["Price Basis"] == "PV" else None, status=x.Status,
                         src_row=int(x.src_row)))
        totals.append(dict(id=f"lookahead:{x.src_row}", file="sheets/Look Ahead Long Lead Items", what=f"{x.Project} {x.Item} amount", printed=parse_number(x["Amount (INR)"]),
                           computed=qty * rate, tolerance=1.0, note=None))
    ctx.t["lookahead_items"] = pd.DataFrame(rows)
    ctx.t["sheet_totals"] = pd.concat([ctx.t["sheet_totals"], pd.DataFrame(totals)], ignore_index=True)
    unknown = [r["item"] for r in rows if not r["material"]]
    assert not unknown, f"look-ahead items with no material: {unknown}"
