"""Link each PR line to the PO line that converted it, and flag PRs keyed in the same day as their PO.

Defect: 39 PR lines were created on the same day as the PO that converted them: the PR was keyed in after the order was agreed (most BESS PRs,
whose RFQ and CS are dated weeks before the PR, and a few urgent buys on roads sites). Their PR -> PO time is 0 by construction.
Rule: the link is the PR and item the PO line names (and the PO the PR names); a pair dated the same day is flagged `same_day_po` on both lines
and left out of turnaround, as the brief asks. Nothing is dropped.
Consequence if ignored: the BESS desk looks like it turns a PR into an order in 0.4 days, and the median turnaround of every vertical is pulled down.
"""
from app.domain.imports.helpers import add_flag


def run(ctx):
    pr, po = ctx.t["pr_lines"], ctx.t["po_lines"]
    po_ids = set(po.id)
    link = {f"{p}/{i}": l for p, i, l in zip(po.pr_no, po.pr_item, po.id) if p and i == i and i is not None}
    pr["po_line_id"] = [f"{p}/{int(i)}" if p and i == i and i is not None and f"{p}/{int(i)}" in po_ids else None for p, i in zip(pr.po_no, pr.po_item)]
    po["pr_line_id"] = po.apply(lambda r: f"{r.pr_no}/{int(r.pr_item)}" if r.pr_no and r.pr_item == r.pr_item and r.pr_item is not None else None, axis=1)
    missing = pr[pr.po_no.notna() & pr.po_line_id.isna()]
    ctx.issue("prs.po_not_in_export", "sap/ME5A_purchase_requisitions.csv", "PR lines naming a PO line the ME2N export does not hold", len(missing), "leave",
              "The link is left empty; the PR keeps the PO number it names.", "A converted PR reads as open.", "; ".join(missing.id.head(3)), "SAP admin")
    created = dict(zip(pr.id, pr.created))
    po_date = dict(zip(po.id, po.doc_date))
    same = pr.po_line_id.map(lambda l: l is not None) & (pr.po_line_id.map(po_date) == pr.created)
    add_flag(pr, same, "same_day_po")
    add_flag(po, po.id.isin(set(pr[same].po_line_id)), "same_day_po")
    ctx.issue("prs.same_day_po", "sap/ME5A_purchase_requisitions.csv", "PRs created the same day as their PO", int(same.sum()), "flag",
              "Flagged on the PR and the PO, and left out of PR -> PO turnaround.",
              "Turnaround reads near zero for a desk that keys PRs in after the negotiation (BESS shows 0.4 days).",
              "; ".join(f"{r.id} = {r.po_line_id} on {r.created}" for r in pr[same].head(3).itertuples()), "@groups:" + ",".join(sorted(set(pr[same].purch_group))))
