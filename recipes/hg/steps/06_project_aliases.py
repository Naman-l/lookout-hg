"""Link the names other sheets write for a project to the project, by a person's answer; leave the rest unresolved.

Defect: every sheet writes project names its own way. The fund sheets say Ahmedabad for Narol, NDRS for NDLS, Thane Metro for Thane, Arurangabad
for Aurangabad, and one KD-1&2 column for KD-01 and KD-02; the look-ahead says "UPPTCL - Mizapur/ Chunar - SS"; the payment projection says
Chouraniya. Some fund columns name jobs that are on no other sheet (Prakasha, DV-10, OD CRR, DMRC-DC-01A, "OD-05, 06"), and "Mirzapur" in the
railway band could be a railway job or the UPPTCL Mirzapur-Chunar line.
Rule: a name equal to a project's name (any case) is that project; any other name is linked only by a person's answer in answers.yaml (with who
and why), which may name two projects for one column; everything else stays unresolved, with MIS as its owner. Nothing is matched by likeness.
Consequence if ignored: the fund sheet and the requirement sheet are compared for the wrong project, or not at all, and a typing error splits a
project in two.
"""
import pandas as pd

SUBTOTAL = ("sub total", "total", "description")


def _names(ctx) -> list[tuple[str, str]]:
    out = []
    for f in ctx.t["_files"].itertuples():
        df = ctx.t.get(f.raw_table)
        if df is None:
            continue
        if f.key == "fund":
            head = df[df.c0 == "Description"].iloc[0]
            out += [(str(v).strip(), "fund") for c, v in head.items() if c not in ("src_row", "c0") and str(v).strip() and not str(v).strip().lower().startswith(SUBTOTAL)]
        elif f.key == "lookahead":
            out += [(v, "lookahead") for v in df.Project]
        elif f.key == "tat_report":
            out += [((g or p), "tat_report") for g, p in zip(df.Group, df.Project)]
        elif f.key == "payment_projection":
            out += [(v, "payment_projection") for v in df["Project Name"]]
        elif f.key in ("roads_req", "railway_req"):
            h = df.index[df.c0 == "Material"][0]
            names = df.loc[h + 1]
            out += [(str(v).strip(), f.key) for c, v in names.items() if c not in ("src_row",) and str(v).strip() and not str(v).strip().lower().startswith(SUBTOTAL)]
    return list(dict.fromkeys(out))


def run(ctx):
    projects = ctx.t["projects"]
    by_name = {n.lower(): i for n, i in zip(projects.name, projects.id)}
    answers = {(a["alias"], a["source"]): a for a in ctx.answers.get("project_aliases") or []}
    rows, linked, unresolved = [], [], []
    for name, source in _names(ctx):
        if name.lower() in by_name:
            rows.append(dict(alias=name, source=source, project_ids=by_name[name.lower()], method="same_name", answered_by=None, evidence=None))
        elif (name, source) in answers:
            a = answers[(name, source)]
            ids = [by_name[n.lower()] for n in a["projects"]]
            rows.append(dict(alias=name, source=source, project_ids=",".join(ids), method="answer", answered_by=a["answered_by"], evidence=a["evidence"]))
            linked.append(f"{name} = {' + '.join(a['projects'])}")
        else:
            rows.append(dict(alias=name, source=source, project_ids=None, method="unresolved", answered_by=None, evidence=None))
            unresolved.append(f"{name} ({source.replace('_', ' ')})")
    for pl in ctx.t["project_plants"].itertuples():      # MB51 prints the plant's long name: the plant ties it to its project
        if pl.project_id and pl.name:
            rows.append(dict(alias=pl.name, source="mb51", project_ids=pl.project_id, method="plant", answered_by=None, evidence=f"plant {pl.plant}"))
    df = pd.DataFrame(rows)
    df.insert(0, "id", range(1, len(df) + 1))
    ctx.t["project_aliases"] = df
    ctx.issue("projects.name_variants", "sheets", "Project names written differently across sheets (Ahmedabad / Narol, NDRS / NDLS, Arurangabad, KD-1&2)", len(linked),
              "link", "Linked by a person's answer (who and why in answers.yaml); one column may stand for two projects.",
              "The fund and requirement sheets are compared for the wrong project, or a typing error splits a project in two.", "; ".join(linked[:4]), "Sudeep")
    ctx.issue("projects.unresolved_names", "sheets", "Names on a sheet that resolve to no project", len(unresolved), "leave",
              "Left unresolved, with MIS as the owner; their figures are shown under the name as printed and kept out of project totals.",
              "A fund line counted against the wrong job, or a real job missing from the project list.", "; ".join(unresolved[:4]), "Sudeep")
