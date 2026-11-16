"""Budget (tender / BOQ) rates per project and material; requirement lines with no budget rate left with their project.

Defect: 7 project-and-material pairs on the requirement sheets have no budget rate: the estimate was never set against them, so what is bought
cannot be compared with what was estimated.
Rule: the budget sheet as written (the project by name, the rate as a number, raw kept). A requirement line whose project has no budget rate for any of
the row's materials is counted and left unknown, owned by the project's planning; nothing is estimated.
Consequence if ignored: "against budget" is silently computed on fewer lines than it claims, or on a guessed estimate.
"""
import pandas as pd


def run(ctx):
    b = ctx.t["raw_budget_rates"]
    projects = dict(zip(ctx.t["projects"].name, ctx.t["projects"].id))
    df = pd.DataFrame(dict(id=range(1, len(b) + 1), project_id=b.Project.map(projects), plant=b.Plant, material=b.Material, unit=b.Unit,
                           rate=b["Budget Rate (INR)"].astype(float), rate_raw=b["Budget Rate (INR)"], basis=b.Basis, src_row=b.src_row))
    assert df.project_id.notna().all(), "a budget row names no project"
    ctx.t["budget_rates"] = df
    have = set(zip(df.project_id, df.material))
    rq = ctx.t["requirement_lines"]
    pairs = sorted({(r.project_id, r.row_as_printed) for r in rq.itertuples() if r.project_id and r.material_codes
                    and not any((p, c) in have for p in r.project_id.split(",") for c in r.material_codes.split(","))})
    names = dict(zip(ctx.t["projects"].id, ctx.t["projects"].name))
    ctx.issue("budget.missing_rates", "sheets/budget_rates.csv", "Requirement lines with no budget rate for their project", len(pairs), "leave",
              "Left unknown and named for the project's planning; 'against budget' is computed only where a rate exists, and says on how many lines.",
              "Against-budget figures silently cover fewer lines than they claim, or rest on a guessed estimate.",
              "; ".join(f"{names.get(p.split(',')[0], p)}: {row}" for p, row in pairs[:4]), "Projects (planning)")
