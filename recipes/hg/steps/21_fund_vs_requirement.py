"""Set the fund sheet beside the material requirement, project by project, head by head, month by month; flag where they disagree.

Defect: the fund requirement Finance receives and the material requirement SCM plans from are built apart and do not agree for some projects and
months (Gaya's aggregate head in November is a third above what the requirement prices; Aurangabad's is a quarter below; Narol's cement and
JH-13's petroleum products are above), and Pune-Shirur carries a fund line but has no column on the requirement sheet.
Rule: for every fund column, head and month the requirement sheets cover, the requirement is qty x rate summed over the rows the head pays for
(answers.yaml: fund heads, as Finance and MIS answered) for the column's projects; the TMT heads are taken together. They disagree when they
differ by more than both ₹25 L and 10%, or when the fund asks more than ₹25 L for a project the requirement sheets do not carry. Unresolved columns
are compared with nothing.
Consequence if ignored: Finance funds a requirement SCM never planned, or SCM plans a month Finance never funds.
"""
import pandas as pd


def run(ctx):
    fl, rq = ctx.t["fund_lines"], ctx.t["requirement_lines"]
    if not len(fl) or not len(rq):
        ctx.t["fund_checks"] = pd.DataFrame()
        return
    heads = ctx.answers["fund_heads"]
    group = ctx.answers.get("fund_head_groups") or {}
    rule = ctx.answers["fund_check"]
    months = set(rq.month)
    on_sheet = {p for ids in rq.project_id.dropna() for p in ids.split(",")}
    fl = fl.assign(head_group=fl["head"].map(lambda h: group.get(h, h)))
    rows = []
    for (month, col, hg), part in fl[fl.month.isin(months) & fl.project_ids.notna() & fl.head_group.isin(heads)].groupby(["month", "column_as_printed", "head_group"]):
        pids = part.project_ids.iloc[0].split(",")
        fund = float(part.amount.sum())
        req_lines = rq[(rq.month == month) & rq.row_as_printed.isin(heads[hg]) & rq.project_id.map(lambda p: bool(p) and bool(set(p.split(",")) & set(pids)))]
        carried = bool(set(pids) & on_sheet)
        req = float(req_lines.amount.fillna(0).sum()) if carried else None
        diff = fund - (req or 0.0)
        disagrees = (req is None and fund > rule["min_difference_inr"]) or (req is not None and abs(diff) > rule["min_difference_inr"] and abs(diff) > rule["min_share"] * max(req, 1.0))
        rows.append(dict(id=f"{month}:{col}:{hg}", month=month, column_as_printed=col, project_ids=",".join(pids), head=hg, requirement=req, fund=fund,
                         difference=diff if req is not None else None, disagrees=int(disagrees), fund_line_ids=",".join(map(str, part.id)),
                         requirement_line_ids=",".join(req_lines.id) if req is not None else None))
    df = pd.DataFrame(rows)
    ctx.t["fund_checks"] = df
    bad = df[df.disagrees == 1]
    ctx.issue("fund.disagrees_with_requirement", "sheets/SCM Fund Requirement", "Requirement and fund sheets disagree for some projects and months", len(bad), "flag",
              "Each project, head and month set side by side; a difference above both ₹25 L and 10% (or a fund line for a project the requirement does not carry) is flagged for MIS to reconcile.",
              "Finance funds a requirement SCM never planned, or SCM plans a month Finance never funds.",
              "; ".join(f"{r.month} {r.column_as_printed} {r.head}: fund ₹{r.fund / 1e7:.2f} Cr vs requirement " + (f"₹{r.requirement / 1e7:.2f} Cr" if pd.notna(r.requirement) else "none on the requirement sheets")
                        for r in bad.sort_values("month").head(3).itertuples()), "Sudeep")
