"""Flag purchase orders raised with no PR (emergency buys).

Defect: 25 PO lines name no purchase requisition: diesel top-ups, crane hire and cement bought in an emergency at site.
Rule: kept as they are, flagged `no_pr`, and left out of PR -> PO turnaround (there is no PR to time); who asked for them is a question.
Consequence if ignored: emergency buys look like planned ones, and the turnaround and the PR ladder have a gap nobody sees.
"""
from app.domain.imports.helpers import add_flag


def run(ctx):
    po = ctx.t["po_lines"]
    mask = po.pr_no.isna()
    add_flag(po, mask, "no_pr")
    ctx.issue("po.no_pr", "sap/ME2N_purchase_orders.csv", "POs with no PR (emergency buys)", int(mask.sum()), "flag",
              "Flagged and left out of PR -> PO turnaround; who asked for each is a question to its buyer.",
              "Emergency buys read as planned ones; the PR ladder has a gap nobody sees.", "; ".join(po[mask].id.head(3)), "@groups:" + ",".join(sorted(set(po[mask].purch_group))))
