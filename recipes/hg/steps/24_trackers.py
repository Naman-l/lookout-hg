"""The RFQ/CS, expediting and LC/BG trackers (Excel kept by SCM): quotes, comparative statements, milestones after the PO, LCs and guarantees.

Defect: on 20 PR lines the RFQ went out and the CS was approved weeks before the PR was raised (the BESS desk negotiates first and keys the PR in
afterwards), so the ladder's rungs are out of order.
Rule: each tracker row is kept as written (dates to ISO, rates as numbers, raw kept), tied to its project by name, its vendor by code (a vendor not in
the master has none), its PR line and its PO line by number. A comparative statement is built per CS number from its quotes: vendors asked, quotes
in, the first quote's date, the L1 and its rate, who approved it and when. A CS whose RFQ predates its PR is flagged `rfq_before_pr` on the PR line
(kept, shown as the negotiation that came first). A milestone's warranty end is computed from the date its warranty runs from.
Consequence if ignored: the ladder shows an RFQ answered before it was asked, and the BESS desk's turnaround is read as fast work rather than a
PR written after the fact.
"""
from datetime import date

import pandas as pd

from app.domain.imports.helpers import add_flag, iso, parse_dmy, parse_number


def _d(s):
    return iso(parse_dmy(s))


def _add_months(d: str | None, n: int | None) -> str | None:
    if not d or not n or n != n:
        return None
    x = date.fromisoformat(d)
    y, m = divmod(x.month - 1 + int(n), 12)
    return date(x.year + y, m + 1, min(x.day, 28)).isoformat()


def run(ctx):
    projects = dict(zip(ctx.t["projects"].name, ctx.t["projects"].id))
    rec = ctx.t["supplier_records"]
    ident = dict(zip(rec.record_id, rec.identity_id))
    buyers = dict(zip(ctx.t["buyers"].name, ctx.t["buyers"].id))
    pr = ctx.t["pr_lines"]
    pr_ids = set(pr.id)
    cs = ctx.t["raw_cs_tracker"]
    q = pd.DataFrame(dict(id="T" + cs.src_row.astype(str), source="tracker", cs_no=cs["CS No."], project_id=cs.Project.map(projects),
                          pr_no=cs["PR No."].replace("", None), pr_item=cs["PR Item"].map(lambda s: int(s) if s.strip() else None),
                          pr_line_id=[f"{p}/{i}" if p and f"{p}/{i}" in pr_ids else None for p, i in zip(cs["PR No."], cs["PR Item"])],
                          material=cs.Material, record_id=cs["Vendor Code"].replace("", None), identity_id=cs["Vendor Code"].map(ident),
                          vendor_name=cs["Vendor Name"], rfq_sent=cs["RFQ Sent"].map(_d), quote_date=cs["Quote Date"].map(_d), qty=cs.Qty.map(parse_number),
                          uom=cs.Unit, rate=cs["Quoted Rate (INR)"].map(parse_number), rate_raw=cs["Quoted Rate (INR)"].replace("", None), validity=cs["Valid Till"].map(_d),
                          price_basis=cs["Price Basis"], pv_formula=None, l1=(cs.L1 == "Y").astype(int), last_po_rate_printed=cs["Last PO Rate"].map(parse_number),
                          budget_rate_printed=cs["Budget Rate"].map(parse_number), cs_status=cs["CS Status"], approved_by=cs["Approved By"].replace("", None),
                          approved_on=cs["Approved On"].map(_d), buyer_id=cs.Buyer.map(buyers), remarks=cs.Remarks.replace("", None), message_id=None, line_ref=None,
                          src_row=cs.src_row))
    ctx.t["quotes"] = q
    st = []
    for no, g in q.groupby("cs_no"):
        l1 = g[g.l1 == 1]
        st.append(dict(cs_no=no, kind="item" if g.pr_line_id.notna().any() else "rate", project_id=g.project_id.iloc[0], material=g.material.iloc[0],
                       pr_line_ids=",".join(sorted(set(g.pr_line_id.dropna()))) or None, rfq_sent=g.rfq_sent.min(), first_quote=g.quote_date.dropna().min() if g.quote_date.notna().any() else None,
                       vendors_asked=int(g.vendor_name.nunique()), quotes_in=int(g.rate.notna().sum()), status=g.cs_status.iloc[0], approved_on=g.approved_on.dropna().max() if g.approved_on.notna().any() else None,
                       approved_by=g.approved_by.dropna().iloc[0] if g.approved_by.notna().any() else None, l1_record=l1.record_id.iloc[0] if len(l1) else None,
                       l1_rate=float(l1.rate.iloc[0]) if len(l1) and l1.rate.notna().iloc[0] else None))
    ctx.t["comparative_statements"] = pd.DataFrame(st)
    created = dict(zip(pr.id, pr.created))
    early = q[q.pr_line_id.notna() & (q.rfq_sent < q.pr_line_id.map(created))]
    lines = sorted(set(early.pr_line_id))
    add_flag(pr, pr.id.isin(lines), "rfq_before_pr")
    ctx.issue("cs.rfq_before_pr", "sheets/RFQ CS Tracker", "RFQ sent and CS approved before the PR was raised", len(lines), "flag",
              "Kept; the PR line is flagged `rfq_before_pr` and its ladder shows the negotiation first.",
              "The ladder shows an RFQ answered before it was asked, and a desk's turnaround reads as fast work rather than a PR written after the fact.",
              "; ".join(f"{l}: RFQ {early[early.pr_line_id == l].rfq_sent.min()}, PR {created[l]}" for l in lines[:3]), "Sambhav")

    ex = ctx.t["raw_expediting"]
    po_ids = set(ctx.t["po_lines"].id)
    po_vendor = dict(zip(ctx.t["po_lines"].id, ctx.t["po_lines"].record_id))
    ms = pd.DataFrame(dict(id=ex["PO No."] + "/" + ex["PO Item"], po_no=ex["PO No."], po_item=ex["PO Item"].astype(int),
                           po_line_id=[f"{p}/{i}" if f"{p}/{i}" in po_ids else None for p, i in zip(ex["PO No."], ex["PO Item"])], project_id=ex.Project.map(projects),
                           item_text=ex.Item, vendor_name=ex.Vendor, record_id=[po_vendor.get(f"{p}/{i}") for p, i in zip(ex["PO No."], ex["PO Item"])],
                           mfc_requested=ex["MFC Requested"].map(_d), mfc_issued=ex["MFC Issued"].map(_d), mfg_days=ex["Mfg Period (days)"].map(lambda s: int(s) if s.strip() else None),
                           inspection_call=ex["Inspection Call"].map(_d), inspection_planned=ex["Inspection Planned"].map(_d), inspection_done=ex["Inspection Done"].map(_d), dispatch_clearance=ex["Dispatch Clearance"].map(_d),
                           delivered=ex.Delivered.map(_d), site_ready_planned=ex["Site Ready (Planned)"].map(_d), commissioned=ex.Commissioned.map(_d),
                           warranty_months=ex["Warranty (months)"].map(lambda s: int(s) if s.strip() else None), warranty_from=ex["Warranty From"].replace("", None),
                           warranty_end=None, remarks=ex.Remarks.replace("", None), src_row=ex.src_row))
    ms["warranty_end"] = [_add_months(c if w == "Commissioning" else d, m) for d, c, w, m in zip(ms.delivered, ms.commissioned, ms.warranty_from, ms.warranty_months)]
    ctx.t["milestones"] = ms
    outside = ms[ms.po_line_id.isna()]
    ctx.issue("expediting.po_not_in_export", "sheets/Expediting Tracker", "Tracker rows for POs older than the ME2N export", len(outside), "leave",
              "Kept with the PO number as the tracker writes it; the PO line itself is not in the export.", "A milestone with no order behind it in the records.",
              "; ".join(f"{r.id} {r.item_text}" for r in outside.itertuples()), "ShreeDutt")

    lc = ctx.t["raw_lc_bg"]
    ctx.t["lc_bg"] = pd.DataFrame(dict(id=range(1, len(lc) + 1), kind=lc.Type, number=lc.Number.replace("", None), po_no=lc["PO No."], record_id=lc["Vendor Code"],
                                       vendor_name=lc.Vendor, amount=lc["Amount (INR)"].map(parse_number), amount_raw=lc["Amount (INR)"], to_open_by=lc["To Open By"].map(_d),
                                       issued_on=lc["Issued On"].map(_d), expiry=lc.Expiry.map(_d), bank=lc.Bank.replace("", None), status=lc.Status,
                                       remarks=lc.Remarks.replace("", None), src_row=lc.src_row))
