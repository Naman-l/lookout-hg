"""Purchase requisitions from ME5A: dates, status, owner and project; PRs with no project left with their requisitioner.

Defect: 14 PR lines were raised at the head-office stores plant with no requirement tracking number: nothing says which project they are for.
Rule: the project is the one whose tracking number the line carries, else the one its plant belongs to; a line at the head-office plant with no
tracking number has no project (left unknown, owner the requisitioner, never guessed). Status: deleted, closed, converted (a PO is named) or open.
The owner is the member of SCM whose purchasing group the line carries. Dates are SAP's dd.mm.yyyy, read to ISO (raw kept).
Consequence if ignored: a head-office PR is counted against no project, or against a project chosen by guess.
"""
import pandas as pd

from app.domain.imports.helpers import iso, parse_dmy


def run(ctx):
    r = ctx.t["raw_me5a"]
    projects = ctx.t["projects"]
    by_tracking = dict(zip(projects.tracking_no, projects.id))
    by_plant = {p.plant: p.project_id for p in ctx.t["project_plants"].itertuples()}
    owner = dict(zip(ctx.t["purchasing_groups"].code, ctx.t["purchasing_groups"].person_id))
    d = lambda col: r[col].map(lambda s: iso(parse_dmy(s)))  # noqa: E731
    project = [by_tracking.get(t) or (by_plant.get(pl) if pl in by_plant else None) for t, pl in zip(r["Requirement Tracking Number"], r.Plant)]
    deleted, closed = r["Deletion Indicator"].str.strip() != "", r.Closed.str.strip() != ""
    status = ["deleted" if dl else "closed" if cl else "converted" if po else "open" for dl, cl, po in zip(deleted, closed, r["Purchase Order"])]
    pr = pd.DataFrame(dict(id=r["Purchase Requisition"] + "/" + r["Item of Requisition"], pr_no=r["Purchase Requisition"], item=r["Item of Requisition"].astype(int),
                           material=r.Material, short_text=r["Short Text"], qty=r["Quantity Requested"].astype(float), qty_raw=r["Quantity Requested"],
                           uom=r["Unit of Measure"], qty_base=r["Quantity Requested"].astype(float), plant=r.Plant, project_id=project,
                           purch_group=r["Purchasing Group"], buyer_id=r["Purchasing Group"].map(owner), requisitioner=r["Name of Requisitioner/Requester"],
                           created=d("Requisition Date"), created_raw=r["Requisition Date"], released=d("Release Date"), released_raw=r["Release Date"],
                           needed_by=d("Delivery Date"), needed_by_raw=r["Delivery Date"], po_no=r["Purchase Order"].replace("", None),
                           po_item=r["Purchase Order Item"].map(lambda s: int(s) if s.strip() else None), po_line_id=None,
                           tracking_no=r["Requirement Tracking Number"].replace("", None), deletion=deleted.astype(int), closed=closed.astype(int),
                           changed_on=d("Changed On"), changed_on_raw=r["Changed On"], status=status, flags="", src_row=r.src_row))
    none = pr[pr.project_id.isna()]
    pr.loc[pr.project_id.isna(), "flags"] = "no_project"
    ctx.t["pr_lines"] = pr
    ho = ctx.answers["ho_plant"]
    people = sorted(set(none.requisitioner))
    ctx.t["contacts"] = pd.concat([ctx.t["contacts"], pd.DataFrame([dict(id=f"{ho['requisitioner_function']}:{k}", name=n, function=ho["requisitioner_function"],
                                                                          title=f"Requisitioner, {ho['name']}", project_id=None, email=None) for k, n in enumerate(people, 1)])],
                                  ignore_index=True)
    ctx.issue("prs.no_project", "sap/ME5A_purchase_requisitions.csv", "PR lines with no project (head-office plant, no tracking number)", len(none), "leave",
              "Left with no project and kept out of project totals; each is a question to its requisitioner.",
              "Spend counted against no project, or against a project chosen by guess.", "; ".join(none.id.head(3)), ", ".join(people) or "SAP admin")
