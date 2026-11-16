"""Read the MIS turnaround report, with its 0 days for a project that closed nothing read as no measurement.

Defect: the report prints "0" in the average-TAT column for every project that closed no PR in the period (Dhule P-Way raised 2, closed 0; Bikaner
O&M raised 6, closed 0). That is no measurement, not a PR turned into a PO in zero days.
Rule: where PRs closed is 0, the average is None ("no measurement"), raw kept; elsewhere the printed average stands. The rows are the report's own
statement: Lookout recomputes turnaround from ME5A and ME2N (same-day PRs left out) and shows the two side by side.
Consequence if ignored: the slowest desks read as the fastest, and an average across projects is pulled toward zero.
"""
import pandas as pd


def run(ctx):
    if "raw_tat_report" not in ctx.t:      # built after the data date (step 02): not read
        return
    r = ctx.t["raw_tat_report"]
    alias = {(a.alias, a.source): a.project_ids for a in ctx.t["project_aliases"].itertuples()}
    printed = [(g or p) for g, p in zip(r.Group, r.Project)]
    closed = r["PR Closed"].astype(int)
    avg = [None if c == 0 else float(a) for c, a in zip(closed, r["Avg TAT (Days)"])]
    ctx.t["tat_report"] = pd.DataFrame(dict(id=range(1, len(r) + 1), vertical=r.Vertical, group=r.Group.replace("", None), project_as_printed=r.Project,
                                            project_id=[(alias.get((n, "tat_report")) or "").split(",")[0] or None for n in printed], raised=r["PR Raised"].astype(int),
                                            closed=closed, avg_tat=avg, avg_tat_raw=r["Avg TAT (Days)"], src_row=r.src_row))
    zero = r[closed == 0]
    ctx.issue("tat.zero_means_none", "sheets/PR PO TAT Report", "\"0\" turnaround printed where nothing closed", len(zero), "fix",
              "Read as no measurement (None); the printed 0 is kept beside it.", "The slowest desks read as the fastest; averages are pulled toward zero.",
              "; ".join(f"{(g + ' ' if g else '')}{p}: {a} raised, 0 closed" for g, p, a in zip(zero.Group, zero.Project, zero["PR Raised"])), "Sudeep")
