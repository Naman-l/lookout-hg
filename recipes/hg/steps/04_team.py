"""The SCM team: who they are and whom they report to (the organogram), their SAP purchasing groups, and the people outside SCM on file by function.

Defect: the organogram is a drawing, not a table. One column block per GM (a desk label beside the people, merged down the rows it covers), each
person as "N. Name (Designation)" with their work on the lines below, designations written four ways ("GM- SCM", "(GM SCM)", "-AM", "Sr.Exc."),
posts still to be filled marked "(TBF)" in place of a name, and a "Total Employee" cell at the foot. SAP's purchasing groups say which desk raised
or ordered a line, not who sits at it, and nothing in the exports says who in Finance opens an LC or who in QA calls an inspection.
Rule: the organogram is read cell by cell: the head from the row under the title, one lead per block of the leads' row, then each numbered cell
under a lead (its desk label carried down the merged rows); "(TBF)" is an open post, never a person. Its own total is checked against the people it
names. The team answers (purchasing groups, verticals, SAP user, DoA limit, who countersigns, the duties each member holds) are joined to it by
name; the purchasing-group export is joined to the team by its code.
Consequence if ignored: no line has an owner, nobody may sign, a note to Finance has no recipient on file, and an open post reads as a person.
"""
import re

import pandas as pd

_MR = re.compile(r"^\s*Mr\.?\s+", re.I)
_MEMBER = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")


def _designation(text: str) -> str:
    """'GM- SCM' / 'GM SCM' -> 'GM - SCM'; 'Sr.Exc.' -> 'Sr. Exc.'; 'MT.' -> 'MT'. The sheet's own words, spaced one way."""
    t = re.sub(r"\s+", " ", text.strip())
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    t = re.sub(r"\s*-\s*SCM$", " - SCM", t)
    t = re.sub(r"^(GM|AGM|Manager) SCM$", r"\1 - SCM", t)
    t = re.sub(r"\.(?=[A-Za-z])", ". ", t)
    return t[:-1] if re.fullmatch(r"[A-Z]{2,3}\.", t) else t


def _person_line(first: str) -> tuple[str, str]:
    """'Mohan Bahadur-(Manager)' / 'Neeraj (Sr.Exc.)' / 'Jagdish Vyas -AM' -> (name, designation)."""
    m = re.match(r"^(.+?)\s*-?\s*\(([^()]+)\)\s*$", first)
    if m:
        return m.group(1).strip(" -"), _designation(m.group(2))
    m = re.match(r"^(.+?)\s+-\s*([A-Za-z.]+)\s*$", first)
    if m:
        return m.group(1).strip(), _designation(m.group(2))
    return first.strip(), ""


def _text(lines: list[str]) -> str | None:
    t = "\n".join(x.strip() for x in lines if x.strip())
    return t or None


def read_organogram(grid: pd.DataFrame) -> tuple[list[dict], int | None, list[str]]:
    """The people the organogram draws, in its order: dicts of key, name, designation, reports_to (a key), category, portfolio,
    responsibilities, vacancy, src_row, src_col. Also the sheet's own total and what could not be read."""
    cols = [c for c in grid.columns if c.startswith("c")]
    rows = grid.to_dict("records")
    cell = lambda r, c: (r.get(c) or "").strip()      # noqa: E731
    lines = lambda r, c: [x for x in (r.get(c) or "").replace("\r", "").split("\n")]      # noqa: E731
    people, problems, total = [], [], None
    # the head: the first filled row under the title whose cell names a person
    head_i = next(i for i, r in enumerate(rows) if any(_MR.match(cell(r, c)) for c in cols))
    hc = next(c for c in cols if _MR.match(cell(rows[head_i], c)))
    hl = [x for x in lines(rows[head_i], hc) if x.strip()]
    people.append(dict(key="head", name=_MR.sub("", hl[0]).strip(), designation=_designation(hl[1]) if len(hl) > 1 else "", reports_to=None,
                       category=None, portfolio=None, responsibilities=_text(hl[2:]), vacancy=0, src_row=rows[head_i]["src_row"], src_col=hc))
    # the leads: the next row, one per filled cell; a lead's block runs to the next lead's column
    lead_row = rows[head_i + 1]
    starts = [c for c in cols if cell(lead_row, c)]
    blocks = []
    for n, c in enumerate(starts):
        span = cols[cols.index(c): cols.index(starts[n + 1]) if n + 1 < len(starts) else len(cols)]
        ll = [x for x in lines(lead_row, c) if x.strip()]
        key = f"lead{n + 1}"
        people.append(dict(key=key, name=_MR.sub("", ll[0]).strip(), designation=_designation(ll[1]) if len(ll) > 1 else "", reports_to="head",
                           category=None, portfolio=_text(ll[2:]), responsibilities=None, vacancy=0, src_row=lead_row["src_row"], src_col=c))
        blocks.append(dict(key=key, label=span[0] if len(span) > 1 else None, people=span[-1], current=None))
    # the people under each lead, row by row, until the total
    for r in rows[head_i + 2:]:
        if any(cell(r, c).lower() == "total employee" for c in cols):
            vals = [cell(r, c) for c in cols if cell(r, c)]
            total = int(vals[vals.index("Total Employee") + 1]) if "Total Employee" in vals and vals[-1].isdigit() else None
            break
        for b in blocks:
            if b["label"] and cell(r, b["label"]):
                b["current"] = re.sub(r"\s+", " ", cell(r, b["label"]))
            text = cell(r, b["people"])
            if not text:
                continue
            ls = [x for x in lines(r, b["people"]) if x.strip()]
            m = _MEMBER.match(ls[0])
            if not m:      # words in a lead's own column with no number: the lead's own work (the Manager SCM's block has no team)
                lead = next(p for p in people if p["key"] == b["key"])
                lead["responsibilities"] = _text([lead["responsibilities"] or "", *ls])
                continue
            first = m.group(2)
            if re.search(r"\(TBF\)\s*$", first, re.I):
                post = re.sub(r"\s*\(TBF\)\s*$", "", first, flags=re.I)
                desig, _, desk = post.rpartition(" - ")
                people.append(dict(key=f"tbf-{r['src_row']}-{b['people']}", name=None, designation=_designation(desig or post), reports_to=b["key"],
                                   category=b["current"], portfolio=desk.strip() or None, responsibilities=_text(ls[1:]), vacancy=1,
                                   src_row=r["src_row"], src_col=b["people"]))
                continue
            name, desig = _person_line(first)
            if not desig:
                problems.append(f"row {r['src_row']}: no designation for {name}")
            people.append(dict(key=f"p-{r['src_row']}-{b['people']}", name=name, designation=desig, reports_to=b["key"], category=b["current"],
                               portfolio=None, responsibilities=_text(ls[1:]), vacancy=0, src_row=r["src_row"], src_col=b["people"]))
    return people, total, problems


def run(ctx):
    domain = ctx.answers["internal_domain"]
    team = ctx.answers["team"]
    people, total, problems = read_organogram(ctx.t["raw_organogram"])
    by_name = {re.sub(r"\s+", " ", m["name"]).lower(): m for m in team}
    key_to_id = {p["key"]: by_name[p["name"].lower()]["id"] for p in people if p["name"] and p["name"].lower() in by_name}
    on_sheet = {p["name"].lower() for p in people if p["name"]}

    rows = []
    for m in team:
        words = m["name"].lower().split()
        org = next((p for p in people if p["name"] and p["name"].lower() == m["name"].lower()), None)
        rows.append(dict(id=m["id"], name=m["name"], initials=m["initials"], role=m["role"], purchasing_groups=",".join(m["groups"]),
                         verticals=",".join(m["verticals"]), sap_user=m["sap_user"],
                         email=f"{words[0]}.{words[-1]}@{domain}" if len(words) > 1 else f"{words[0]}@{domain}",
                         signs_upto=m["signs_upto"], countersigns=int(bool(m["countersigns"])), sees_all=int(bool(m["sees_all"])),
                         designation=org["designation"] if org else None, reports_to=key_to_id.get(org["reports_to"]) if org and org["reports_to"] else None,
                         duties=",".join(m.get("duties") or [])))
    ctx.t["buyers"] = pd.DataFrame(rows)

    order: dict[str, int] = {}
    org_rows = []
    for p in people:
        parent = p["reports_to"]
        order[parent] = order.get(parent, 0) + 1
        org_rows.append(dict(id=key_to_id.get(p["key"], p["key"]), name=p["name"], designation=p["designation"],
                             reports_to=key_to_id.get(parent, parent) if parent else None, category=p["category"], portfolio=p["portfolio"],
                             responsibilities=p["responsibilities"], position=order[parent], vacancy=p["vacancy"], member_id=key_to_id.get(p["key"]),
                             src_row=p["src_row"], src_col=p["src_col"]))
    ctx.t["org_people"] = pd.DataFrame(org_rows)

    named = [p for p in people if p["name"] and p["key"] != "head"]
    vacant = [p for p in people if p["vacancy"]]
    if total is not None and total != len(named):
        ctx.issue("team.total_disagrees", "sheets/SCM Material Organogram.csv", "The organogram's own total disagrees with the people it names", 1, "flag",
                  "The people are counted from the cells; the sheet's total is shown beside them.", "A head count nobody can trace.",
                  f"Total Employee {total}; {len(named)} named under the head", "Satish")
    ctx.issue("team.open_posts", "sheets/SCM Material Organogram.csv", "Posts the organogram marks TBF (to be filled)", len(vacant), "leave",
              "Shown on the organisation chart as open posts under their lead; never a person, never an owner of lines.",
              "An open post reads as a person who owns a desk.",
              "; ".join(f"{p['designation']} - {p['portfolio']}" if p["portfolio"] else p["designation"] for p in vacant), "Satish")
    missing = [p["name"] for p in named if p["name"].lower() not in by_name]
    ctx.issue("team.not_in_answers", "sheets/SCM Material Organogram.csv", "People on the organogram with no team entry", len(missing), "leave",
              "On the organisation chart, but they own no purchasing group and may not sign until the team answers name them.",
              "Their lines have no owner.", ", ".join(missing), "Satish")
    extra = [m["name"] for m in team if m["name"].lower() not in on_sheet]
    ctx.issue("team.not_on_organogram", "recipe answers (team)", "Team members the organogram does not show", len(extra), "leave",
              "They keep their purchasing groups; the organisation chart lists them under nobody.", "A member reports to nobody.", ", ".join(extra), "Satish")
    if problems:
        ctx.issue("team.unread_cells", "sheets/SCM Material Organogram.csv", "Organogram cells read without a designation", len(problems), "flag",
                  "The person is kept with no designation.", "A person shows with no designation.", "; ".join(problems[:3]), "Satish")

    owner = {g: m["id"] for m in team for g in m["groups"]}
    pg = ctx.t["raw_purchasing_groups"].copy()
    ctx.t["purchasing_groups"] = pd.DataFrame(dict(code=pg["Purch. Group"], description=pg["Description"], person_id=pg["Purch. Group"].map(owner),
                                                   email=pg["E-Mail Address"], src_row=pg.src_row))
    unknown = pg[~pg["Purch. Group"].isin(owner)]
    ctx.issue("team.unowned_groups", "sap/purchasing_groups.csv", "Purchasing groups no team member owns", len(unknown), "leave",
              "Lines on these groups have no owner until a person says whose they are.", "Nobody signs for their lines.",
              ", ".join(unknown["Purch. Group"]), "Satish")
    ctx.t["contacts"] = pd.DataFrame([dict(id=k, name=v["name"], function=k, title=v["title"], project_id=None, email=v["email"])
                                      for k, v in ctx.answers["functions"].items()])
