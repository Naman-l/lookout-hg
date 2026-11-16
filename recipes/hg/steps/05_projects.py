"""Projects from the project directory: vertical, stage, plants, tracking number, project head and planner; their work fronts.

Defect: the directory writes verticals and stages in words ("T&D", "Nearing completion") and a project with two plants as "1131-1132"; a project
won after the last plant was created in SAP has no plant yet.
Rule: a stable id from the printed name; the vertical and stage normalised (raw kept); each plant its own row; the head-office plant belongs to no
project; a project with no plant is kept, and has no SAP records until it gets one. Work fronts and the material groups each consumes are the
vertical leads' answer. The project head and planner become contacts on file.
Consequence if ignored: a PR's plant names no project, a late material reaches no front of work, and a project with no plant reads as one that
buys nothing.
"""
import pandas as pd

from app.domain.imports.helpers import slug

VERTICAL = {"Roads": "roads", "Railway": "railway", "BESS": "bess", "Solar": "solar", "T&D": "td"}
STAGE = {"New": "new", "Running": "running", "Nearing completion": "nearing_completion"}


def run(ctx):
    d = ctx.t["raw_project_directory"]
    bad = d[~d.Vertical.isin(VERTICAL) | ~d.Stage.isin(STAGE)]
    assert bad.empty, f"unmapped vertical or stage: {bad[['Project', 'Vertical', 'Stage']].values.tolist()}"
    p = pd.DataFrame(dict(id=d.Project.map(slug), name=d.Project, vertical=d.Vertical.map(VERTICAL), vertical_raw=d.Vertical, stage=d.Stage.map(STAGE),
                          stage_raw=d.Stage, state=d.State, district=d.District, tracking_no=d["Tracking No."], head_name=d["Project Head"],
                          head_email=d["Head Email"], planner_name=d.Planner, planner_email=d["Planner Email"], sap_plant_name=d["SAP Plant Name"], src_row=d.src_row))
    ctx.t["projects"] = p
    plants = [dict(plant=pl.strip(), project_id=r.id, name=r.sap_plant_name) for r, raw in zip(p.itertuples(), d.Plant) for pl in raw.split("-") if pl.strip()]
    ho = ctx.answers["ho_plant"]
    plants.append(dict(plant=ho["plant"], project_id=None, name=ho["name"]))
    ctx.t["project_plants"] = pd.DataFrame(plants)
    no_plant = p[d.Plant.str.strip() == ""]
    ctx.issue("projects.no_sap_plant", "sheets/Project Directory.csv", "Projects with no SAP plant yet", len(no_plant), "leave",
              "Kept as projects with no plant: their requirement, fund lines, look-ahead items and mail count; no SAP export can carry their PRs, POs or "
              "receipts until a plant is created.", "A new project reads as one that buys nothing, or its purchases are booked at another plant.",
              "; ".join(no_plant.name), "SAP admin")
    fronts = []
    for r in p.itertuples():
        for f in ctx.answers["work_fronts"][r.vertical]:
            fronts.append(dict(id=f"{r.id}:{slug(f['name'])}", project_id=r.id, name=f["name"], material_groups=",".join(f["groups"])))
    ctx.t["work_fronts"] = pd.DataFrame(fronts)
    people = [dict(id=f"project_head:{r.id}", name=r.head_name, function="project_head", title=f"Project Head - {r.name}", project_id=r.id, email=r.head_email)
              for r in p.itertuples()] + [dict(id=f"planner:{r.id}", name=r.planner_name, function="planner", title=f"Planning Engineer - {r.name}", project_id=r.id,
                                               email=r.planner_email) for r in p.itertuples()]
    ctx.t["contacts"] = pd.concat([ctx.t["contacts"], pd.DataFrame(people)], ignore_index=True)
